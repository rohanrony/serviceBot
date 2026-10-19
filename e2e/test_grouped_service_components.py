"""Grouped appointment capacity and selected-service removal on real PostgreSQL."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import pytest

from e2e.scenarios import capacity_snapshot, multi_booking, multi_services, service
from serviceBot.db.queries import get_customer_appointments
from serviceBot.services.booking import BookingService, BookingValidationError


def rows(db, group):
    return db('SELECT * FROM service_requests WHERE visit_group_id=%s ORDER BY booking_time,id', (group,))


def remove(request_id, name, **kwargs):
    return BookingService().remove_appointment_service(request_id=request_id, service_name=name,
        customer_consent_obtained=True, triggered_by='portal', **kwargs)


def test_same_technician_one_appointment_reservation_and_projection(api, db, scenario):
    names = multi_services(api, 'single')
    result = multi_booking(api, scenario, names)
    assert result['success'] is True, result
    booked = rows(db, result['visit_group_id'])
    assert len(booked) == 1
    row = booked[0]
    assert row['service_type'] == ', '.join(names)
    assert row['duration_minutes'] == 75
    assert row['service_components'] == [{'name': names[0], 'duration_minutes': 30}, {'name': names[1], 'duration_minutes': 45}]
    assert len(db('SELECT * FROM appointment_reservations WHERE service_request_id=%s', (row['id'],))) == 1
    assert len(db("SELECT * FROM outbox_notifications WHERE request_id=%s AND event_type='calendar_projection'", (row['id'],))) == 1
    lookup = next(item for item in get_customer_appointments('+15550100001') if item['id'] == row['id'])
    assert lookup['service_components'] == row['service_components']


@pytest.fixture
def grouped_visit(api, db, scenario):
    service(api, 'First', [1], 30)
    service(api, 'Second tech', [2], 45)
    service(api, 'Third', [1], 30)
    result = multi_booking(api, scenario, ['First', 'Second tech', 'Third'])
    assert result['success'] is True, result
    booked = rows(db, result['visit_group_id'])
    assert [(row['staff_agent_id'], row['service_type'], row['duration_minutes']) for row in booked] == [(1, 'First, Third', 60), (2, 'Second tech', 45)]
    assert [datetime.fromisoformat(row['booking_time']) for row in booked] == [scenario['start'], scenario['start'] + timedelta(minutes=60)]
    return booked


@pytest.mark.parametrize('name', ['First', 'Third'])
def test_removal_keeps_selected_start_and_companion_unchanged(api, db, scenario, grouped_visit, name):
    selected, companion = grouped_visit
    reservation = db('SELECT * FROM appointment_reservations WHERE service_request_id=%s', (selected['id'],))[0]
    # Catalog duration changes must not change the booked snapshot duration.
    db('UPDATE services SET duration_minutes=120 WHERE name=%s', (name,))
    result = remove(selected['id'], name)
    assert result['success'] and not result['cancelled']
    assert result['notification_status'] == 'queued'
    assert result['duration_minutes'] == 30
    after = db('SELECT * FROM service_requests WHERE id=%s', (selected['id'],))[0]
    assert after['booking_time'] == selected['booking_time']
    assert after['booking_end_at'] == scenario['start'] + timedelta(minutes=30)
    assert after['service_components'] == [{'name': 'Third' if name == 'First' else 'First', 'duration_minutes': 30}]
    assert db('SELECT * FROM service_requests WHERE id=%s', (companion['id'],))[0] == companion
    current = db('SELECT * FROM appointment_reservations WHERE id=%s', (reservation['id'],))[0]
    assert (current['id'], current['starts_at'], current['staff_agent_id']) == (reservation['id'], reservation['starts_at'], reservation['staff_agent_id'])
    assert current['ends_at'] == scenario['start'] + timedelta(minutes=30)
    segments = db('SELECT segment_start FROM appointment_reservation_segments WHERE reservation_id=%s ORDER BY segment_start', (reservation['id'],))
    assert [item['segment_start'] for item in segments] == [scenario['start'], scenario['start'] + timedelta(minutes=15)]
    released = db('SELECT * FROM mock_calendar_slots WHERE staff_agent_id=1 AND slot_datetime >= %s AND slot_datetime < %s', (scenario['start'] + timedelta(minutes=30), scenario['start'] + timedelta(minutes=60)))
    assert len(released) == 2 and all(not item['is_booked'] and item['service_request_id'] is None for item in released)
    projection = db("SELECT payload FROM outbox_notifications WHERE request_id=%s AND event_type='calendar_projection' ORDER BY id DESC LIMIT 1", (selected['id'],))[0]['payload']
    assert projection['duration_minutes'] == 30 and projection['booking_time_str'] == selected['booking_time']
    assert db('SELECT notes FROM service_request_audit_log WHERE request_id=%s', (selected['id'],))


def test_last_service_cancel_selected_only_and_default_cancel_still_whole_visit(db, grouped_visit):
    selected, companion = grouped_visit
    result = remove(companion['id'], 'Second tech')
    assert result['cancelled'] and result['service_components'] == []
    assert db('SELECT status FROM service_requests WHERE id=%s', (selected['id'],))[0]['status'] == 'pending'
    assert db('SELECT * FROM service_requests WHERE id=%s', (companion['id'],))[0]['status'] == 'cancelled'
    assert not db("SELECT * FROM appointment_reservations WHERE service_request_id=%s AND status='ACTIVE'", (companion['id'],))
    payload = db("SELECT payload FROM outbox_notifications WHERE request_id=%s AND event_type='calendar_projection' ORDER BY id DESC LIMIT 1", (companion['id'],))[0]['payload']
    assert payload['action'] == 'delete'
    BookingService().cancel(request_id=selected['id'], customer_consent_obtained=True, triggered_by='portal')
    assert all(row['status'] == 'cancelled' for row in rows(db, selected['visit_group_id']))


@pytest.mark.parametrize('corruption', ['missing', 'duration', 'duplicate', 'callback', 'unknown', 'consent'])
def test_bad_snapshot_or_selection_has_no_effects(db, grouped_visit, corruption):
    selected = grouped_visit[0]
    name = 'First'
    consent = True
    if corruption == 'missing': db('UPDATE service_requests SET service_components=NULL WHERE id=%s', (selected['id'],))
    if corruption == 'duration': db('UPDATE service_requests SET duration_minutes=75 WHERE id=%s', (selected['id'],))
    if corruption == 'duplicate': db("UPDATE service_requests SET service_components='[{\"name\":\"First\",\"duration_minutes\":30},{\"name\":\"First\",\"duration_minutes\":30}]' WHERE id=%s", (selected['id'],))
    if corruption == 'callback': db("UPDATE service_requests SET booking_type='callback' WHERE id=%s", (selected['id'],))
    if corruption == 'unknown': name = 'first'
    if corruption == 'consent': consent = False
    before = capacity_snapshot(db)
    with pytest.raises(BookingValidationError):
        BookingService().remove_appointment_service(request_id=selected['id'], service_name=name,
            customer_consent_obtained=consent, triggered_by='portal')
    assert capacity_snapshot(db) == before


@pytest.mark.parametrize('final', [False, True])
def test_projection_or_final_cancel_failure_rolls_back_whole_selected_transaction(db, grouped_visit, monkeypatch, final):
    selected, companion = grouped_visit
    before = capacity_snapshot(db)
    if final:
        original = BookingService._cancel_locked
        def fail(self, *args, **kwargs):
            original(self, *args, **kwargs)
            raise RuntimeError('after cancellation writes')
        monkeypatch.setattr(BookingService, '_cancel_locked', fail)
    else:
        monkeypatch.setattr(BookingService, '_enqueue_projection_events', lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError('projection failure')))
    with pytest.raises(RuntimeError): remove(companion['id'] if final else selected['id'], 'Second tech' if final else 'First')
    assert capacity_snapshot(db) == before


def test_concurrent_same_component_removal_commits_once(db, grouped_visit):
    selected = grouped_visit[0]
    def attempt():
        try: return remove(selected['id'], 'First')['success']
        except BookingValidationError: return False
    before = len(db('SELECT * FROM outbox_notifications WHERE request_id=%s', (selected['id'],)))
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: attempt(), range(2)))
    assert sorted(outcomes) == [False, True]
    assert len(db('SELECT * FROM outbox_notifications WHERE request_id=%s', (selected['id'],))) == before + 2


def test_inactive_only_mapping_does_not_fall_back_to_any_active_technician(api, db, scenario):
    names = multi_services(api, 'single')
    db('UPDATE staff_agents SET is_active=FALSE WHERE id=1')
    before = capacity_snapshot(db)
    result = multi_booking(api, scenario, names)
    assert result['success'] is False
    assert capacity_snapshot(db) == before


def test_canonical_consolidation_maintains_removable_snapshot(api, db, scenario):
    from serviceBot.db.queries import consolidate_appointment_service
    names = multi_services(api, 'single')
    service(api, 'Added', [1], 15)
    result = multi_booking(api, scenario, names)
    selected = rows(db, result['visit_group_id'])[0]
    added = consolidate_appointment_service(selected['id'], 'Added work', 'Added', 15)
    assert added.get('success', True), added
    after = db('SELECT * FROM service_requests WHERE id=%s', (selected['id'],))[0]
    assert after['service_components'] == [*selected['service_components'], {'name': 'Added', 'duration_minutes': 15}]
    removed = remove(selected['id'], 'Added')
    assert removed['duration_minutes'] == 75
    assert removed['service_components'] == selected['service_components']


def test_legacy_single_canonical_can_cancel_only_selected_row(db, grouped_visit):
    selected, companion = grouped_visit
    db('UPDATE service_requests SET service_components=NULL WHERE id=%s', (companion['id'],))
    assert remove(companion['id'], 'Second tech')['cancelled']
    assert db('SELECT * FROM service_requests WHERE id=%s', (selected['id'],))[0] == selected


def test_final_cancel_uses_one_connection_transaction(db, grouped_visit):
    from serviceBot.db.connection import get_db_connection
    calls = []
    def connection():
        calls.append(True)
        return get_db_connection()
    service_owner = BookingService(connection_factory=connection)
    assert service_owner.remove_appointment_service(request_id=grouped_visit[1]['id'], service_name='Second tech',
        customer_consent_obtained=True, triggered_by='portal')['cancelled']
    assert len(calls) == 1


def test_same_technician_callbacks_stay_separate(db, api, scenario):
    names = multi_services(api, 'single')
    receipts = BookingService().reserve_multi_service_appointment(customer_id=1, services=names,
        appointment_datetime=scenario['start'], booking_type='callback')
    assert len(receipts) == 2
    booked = rows(db, receipts[0]['visit_group_id'])
    assert all(row['booking_type'] == 'callback' and row['service_components'] is None for row in booked)
    assert len(db("SELECT * FROM appointment_reservations WHERE service_request_id=ANY(%s) AND status='ACTIVE'", ([row['id'] for row in booked],))) == 2


def test_grouped_reschedule_preserves_snapshot_and_all_component_qualifications(db, grouped_visit, scenario):
    selected, companion = grouped_visit
    new_start = scenario['start'] + timedelta(days=1)
    receipt = BookingService().reschedule(request_id=selected['id'], new_datetime=new_start,
        customer_consent_obtained=True, triggered_by='portal')
    assert receipt.staff_agent_id == 1
    after = db('SELECT * FROM service_requests WHERE id=%s', (selected['id'],))[0]
    assert after['service_components'] == selected['service_components']
    assert after['duration_minutes'] == 60
    assert db('SELECT booking_time FROM service_requests WHERE id=%s', (companion['id'],))[0]['booking_time'] == (new_start + timedelta(minutes=60)).strftime('%Y-%m-%d %H:%M:%S')


def test_implicit_consolidation_preserves_same_visit_companion(db, grouped_visit):
    from serviceBot.db.queries import consolidate_appointment_service
    selected, companion = grouped_visit
    companion_reservations = db('SELECT * FROM appointment_reservations WHERE service_request_id=%s', (companion['id'],))
    companion_outbox = db('SELECT * FROM outbox_notifications WHERE request_id=%s ORDER BY id', (companion['id'],))
    result = consolidate_appointment_service(selected['id'], 'extra diagnostic work', additional_duration_minutes=15)
    assert result.get('success', True), result
    assert db('SELECT * FROM service_requests WHERE id=%s', (companion['id'],))[0] == companion
    assert db('SELECT * FROM appointment_reservations WHERE service_request_id=%s', (companion['id'],)) == companion_reservations
    assert db('SELECT * FROM outbox_notifications WHERE request_id=%s ORDER BY id', (companion['id'],)) == companion_outbox
    # Unstructured work cannot inherit a false canonical component snapshot.
    assert db('SELECT service_components FROM service_requests WHERE id=%s', (selected['id'],))[0]['service_components'] is None


def test_grouped_reschedule_rejects_staff_unqualified_for_one_component(db, grouped_visit, scenario):
    from serviceBot.services.booking import BookingConflictError
    selected = grouped_visit[0]
    db("DELETE FROM service_staff_agents WHERE service_id=(SELECT id FROM services WHERE name='Third')")
    db("INSERT INTO service_staff_agents(service_id,staff_agent_id) SELECT id,2 FROM services WHERE name='Third'")
    before = capacity_snapshot(db)
    with pytest.raises(BookingConflictError):
        BookingService().reschedule(request_id=selected['id'], new_datetime=scenario['start'] + timedelta(days=1),
            customer_consent_obtained=True, triggered_by='portal')
    assert capacity_snapshot(db) == before


def test_mismatched_segment_staff_is_rejected_without_any_effect(db, grouped_visit):
    selected = grouped_visit[0]
    db('UPDATE appointment_reservation_segments SET staff_agent_id=2 WHERE reservation_id=(SELECT id FROM appointment_reservations WHERE service_request_id=%s)', (selected['id'],))
    before = capacity_snapshot(db)
    with pytest.raises(BookingValidationError): remove(selected['id'], 'First')
    assert capacity_snapshot(db) == before


def test_consolidation_rejects_added_service_for_other_technician_atomically(api, db, scenario):
    from serviceBot.db.queries import consolidate_appointment_service
    names = multi_services(api, 'single')
    service(api, 'Other tech only', [2], 15)
    result = multi_booking(api, scenario, names)
    selected = rows(db, result['visit_group_id'])[0]
    before = capacity_snapshot(db)
    audit = db('SELECT * FROM service_request_audit_log ORDER BY id')
    rejected = consolidate_appointment_service(selected['id'], 'New canonical service', 'Other tech only', 15)
    assert rejected['success'] is False
    assert capacity_snapshot(db) == before
    assert db('SELECT * FROM service_request_audit_log ORDER BY id') == audit


def test_component_migration_can_be_reapplied_without_losing_snapshot_data(grouped_visit):
    from pathlib import Path

    from serviceBot.db.connection import get_db_connection
    forward = Path('serviceBot/db/migrations/0007_service_components.sql').read_text()
    with get_db_connection() as conn, conn.cursor() as cursor:
        cursor.execute('SELECT id,service_components FROM service_requests ORDER BY id')
        before = cursor.fetchall()
        cursor.execute(forward)
        cursor.execute(forward)
        cursor.execute('SELECT id,service_components FROM service_requests ORDER BY id')
        assert cursor.fetchall() == before


@pytest.mark.parametrize('inactive', [False, True])
def test_consolidation_mappingless_accepts_only_active_selected_staff(api, db, scenario, inactive):
    from serviceBot.db.queries import consolidate_appointment_service
    names = multi_services(api, 'single')
    service(api, 'Mappingless added', [], 15)
    result = multi_booking(api, scenario, names)
    selected = rows(db, result['visit_group_id'])[0]
    if inactive: db('UPDATE staff_agents SET is_active=FALSE WHERE id=1')
    before = capacity_snapshot(db)
    result = consolidate_appointment_service(selected['id'], 'More work', 'Mappingless added', 15)
    if inactive:
        assert result['success'] is False
        assert capacity_snapshot(db) == before
    else:
        assert result.get('success', True), result
        assert db('SELECT service_components FROM service_requests WHERE id=%s', (selected['id'],))[0]['service_components'][-1] == {'name': 'Mappingless added', 'duration_minutes': 15}


def test_component_migration_bootstrap_column_then_up_and_backed_up_rollback(grouped_visit):
    import json
    from pathlib import Path

    from serviceBot.db.connection import get_db_connection
    forward = Path('serviceBot/db/migrations/0007_service_components.sql').read_text()
    backward = Path('serviceBot/db/migrations/0007_service_components.down.sql').read_text()
    with get_db_connection() as conn, conn.cursor() as cursor:
        cursor.execute('SELECT id,service_components FROM service_requests ORDER BY id')
        backup = cursor.fetchall()
        try:
            cursor.execute(backward)
            cursor.execute("SELECT 1 FROM information_schema.columns WHERE table_name='service_requests' AND column_name='service_components'")
            assert cursor.fetchall() == []
            # Simulate bootstrap's nullable column existing before tracked up.
            cursor.execute('ALTER TABLE service_requests ADD COLUMN service_components JSONB')
            cursor.execute(forward)
            cursor.execute(forward)
            for request_id, components in backup:
                cursor.execute('UPDATE service_requests SET service_components=%s WHERE id=%s',
                    (json.dumps(components) if components is not None else None, request_id))
            cursor.execute('SELECT id,service_components FROM service_requests ORDER BY id')
            assert cursor.fetchall() == backup
            cursor.execute("SELECT 1 FROM pg_constraint WHERE conrelid='service_requests'::regclass AND conname='service_requests_components_array'")
            assert len(cursor.fetchall()) == 1
        finally:
            conn.rollback()


@pytest.mark.parametrize('names', [['First', 'First'], ['First', 'first']])
def test_duplicate_canonical_components_and_case_alias_reject_atomically(db, grouped_visit, scenario, names):
    before = capacity_snapshot(db)
    with pytest.raises(BookingValidationError):
        BookingService().reserve_multi_service_appointment(customer_id=1, services=names,
            appointment_datetime=scenario['start'] + timedelta(days=1))
    assert capacity_snapshot(db) == before


def test_grouped_request_start_end_metadata_matches_authoritative_reservations(db, grouped_visit):
    for request in grouped_visit:
        reservation = db("SELECT * FROM appointment_reservations WHERE service_request_id=%s AND status='ACTIVE'", (request['id'],))[0]
        assert request['booking_start_at'] == reservation['starts_at']
        assert request['booking_end_at'] == reservation['ends_at']
