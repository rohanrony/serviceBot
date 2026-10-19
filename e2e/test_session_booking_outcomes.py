"""Real HTTP/PG session updates preserve native state on rejected moves."""
from copy import deepcopy
from datetime import datetime, timedelta

import pytest

from e2e.scenarios import capacity_snapshot, service
from e2e.test_voice_and_reporting import voice
from serviceBot.api import telephony
from serviceBot.services import booking


@pytest.fixture
def session_case(api, db, scenario, freeze_business_clock):
    freeze_business_clock(scenario['start'] - timedelta(days=2))
    service(api, 'Session Oil', [1], 60)
    args = {'phone': '+15550100006', 'customer_name': 'Owned Session', 'make': 'Honda', 'model': 'Civic',
            'year': 2021, 'service_type': 'Session Oil', 'issue_description': 'Session Oil',
            'booking_type': 'appointment', 'booking_time': scenario['start'].isoformat(),
            'appointment_datetime': scenario['start'].isoformat(), 'call_sid': 'owned-session'}
    first = voice(api, 'create_service_request', args)
    assert first['success'] is True, first
    return args, first['service_request_id']


@pytest.mark.parametrize('name', ['create_service_request', 'book_appointment'])
@pytest.mark.parametrize('failure', ['conflict', 'exception', 'false_result'])
def test_native_session_failed_update_keeps_reservation_calendar_outbox_audit_and_cache(api, db, scenario, session_case, monkeypatch, name, failure):
    args, request_id = session_case
    new_time = scenario['start'] + timedelta(hours=1)
    if failure == 'conflict':
        other = dict(args, phone='+15550100002', customer_name='Blair E2E', call_sid='other-session',
                     booking_time=new_time.isoformat(), appointment_datetime=new_time.isoformat())
        assert voice(api, 'create_service_request', other)['success'] is True
    elif failure == 'exception':
        def fail(**kwargs): raise RuntimeError('private-token')
        monkeypatch.setattr(telephony, 'reschedule_appointment', fail)
    else:
        monkeypatch.setattr(telephony, 'reschedule_appointment', lambda **kwargs: {'success': False, 'message': 'private-token'})
    before = capacity_snapshot(db)
    audit = db('SELECT * FROM service_request_audit_log ORDER BY id')
    slots = db('SELECT * FROM mock_calendar_slots ORDER BY id')
    cache = deepcopy(booking._IN_FLIGHT_BOOKING_SESSIONS)
    args.update(booking_time=new_time.isoformat(), appointment_datetime=new_time.isoformat())
    result = voice(api, name, args)
    assert result['success'] is False
    assert result['error_code'] == 'SESSION_BOOKING_UPDATE_UNVERIFIED'
    assert 'private-token' not in str(result)
    assert capacity_snapshot(db) == before
    assert db('SELECT * FROM service_request_audit_log ORDER BY id') == audit
    assert db('SELECT * FROM mock_calendar_slots ORDER BY id') == slots
    assert booking._IN_FLIGHT_BOOKING_SESSIONS == cache
    assert datetime.fromisoformat(db('SELECT booking_time FROM service_requests WHERE id=%s', (request_id,))[0]['booking_time']) == scenario['start']


@pytest.mark.parametrize('name', ['create_service_request', 'book_appointment'])
def test_native_session_success_uses_snapshot_duration_after_catalog_drift(api, db, scenario, session_case, name):
    args, request_id = session_case
    db("UPDATE services SET duration_minutes=30 WHERE name='Session Oil'")
    new_time = scenario['start'] + timedelta(hours=1)
    args.update(booking_time=new_time.isoformat(), appointment_datetime=new_time.isoformat())
    result = voice(api, name, args)
    assert result['success'] is True, result
    assert result['duration_minutes'] == 60
    assert result['notification_delivery_status'] == 'unverified'
    assert booking.get_session_booking('owned-session')['duration_minutes'] == 60
    row = db('SELECT * FROM service_requests WHERE id=%s', (request_id,))[0]
    assert row['duration_minutes'] == 60 and datetime.fromisoformat(row['booking_time']) == new_time
    assert len(db('SELECT id FROM service_requests WHERE customer_id=%s', (row['customer_id'],))) == 1


@pytest.mark.parametrize('name', ['create_service_request', 'book_appointment'])
def test_native_same_session_same_time_retry_has_zero_booking_or_projection_effects(api, db, session_case, name):
    args, request_id = session_case
    before = capacity_snapshot(db)
    audit = db('SELECT * FROM service_request_audit_log ORDER BY id')
    slots = db('SELECT * FROM mock_calendar_slots ORDER BY id')
    cache = deepcopy(booking._IN_FLIGHT_BOOKING_SESSIONS)
    result = voice(api, name, args)
    assert result['success'] is True and result['is_update'] is False
    assert result.get('service_request_id', result.get('appointment_id')) == request_id
    assert capacity_snapshot(db) == before
    assert db('SELECT * FROM service_request_audit_log ORDER BY id') == audit
    assert db('SELECT * FROM mock_calendar_slots ORDER BY id') == slots
    assert booking._IN_FLIGHT_BOOKING_SESSIONS == cache


@pytest.mark.parametrize('name', ['create_service_request', 'book_appointment'])
@pytest.mark.parametrize('defect', ['foreign', 'cancelled'])
def test_native_stale_or_foreign_cache_cannot_move_or_duplicate_request(api, db, scenario, session_case, name, defect):
    args, request_id = session_case
    if defect == 'foreign':
        db('UPDATE service_requests SET customer_id=2 WHERE id=%s', (request_id,))
    else:
        booking.BookingService().cancel(request_id=request_id, customer_consent_obtained=True,
                                        triggered_by='offline_test')
        assert db('SELECT status FROM service_requests WHERE id=%s', (request_id,)) == [{'status': 'cancelled'}]
    before = capacity_snapshot(db)
    cache = deepcopy(booking._IN_FLIGHT_BOOKING_SESSIONS)
    args.update(booking_time=(scenario['start'] + timedelta(hours=1)).isoformat(),
                appointment_datetime=(scenario['start'] + timedelta(hours=1)).isoformat())
    result = voice(api, name, args)
    assert result['success'] is False and result['error_code'] == 'SESSION_BOOKING_UPDATE_UNVERIFIED'
    assert capacity_snapshot(db) == before
    assert booking._IN_FLIGHT_BOOKING_SESSIONS == cache


@pytest.mark.parametrize('name', ['create_service_request', 'book_appointment'])
def test_native_grouped_session_retains_full_booked_snapshot_after_catalog_drift(api, db, scenario, freeze_business_clock, name):
    freeze_business_clock(scenario['start'] - timedelta(days=2))
    service(api, 'Session Oil', [1], 60)
    service(api, 'Session Tire', [1], 30)
    for offset in range(120, 240, 15):
        db('INSERT INTO mock_calendar_slots(staff_agent_id,slot_datetime) VALUES(1,%s)',
           (scenario['start'] + timedelta(minutes=offset),))
    args = {'phone': '+15550100006', 'customer_name': 'Owned Group', 'make': 'Honda', 'model': 'Civic',
            'year': 2021, 'service_type': 'Session Oil and Session Tire', 'services': ['Session Oil', 'Session Tire'],
            'booking_type': 'appointment', 'appointment_datetime': scenario['start'].isoformat(),
            'booking_time': scenario['start'].isoformat(), 'call_sid': 'owned-group'}
    first = voice(api, 'book_appointment', args)
    assert first['success'] is True, first
    cache = booking.get_session_booking('owned-group')
    request_id = cache['service_request_id']
    before = db('SELECT service_components FROM service_requests WHERE id=%s', (request_id,))[0]
    assert cache['duration_minutes'] == 90
    db("UPDATE services SET duration_minutes=15 WHERE name IN ('Session Oil','Session Tire')")
    new_time = scenario['start'] + timedelta(hours=1)
    args.update(booking_time=new_time.isoformat(), appointment_datetime=new_time.isoformat())
    result = voice(api, name, args)
    assert result['success'] is True and result['duration_minutes'] == 90, result
    row = db('SELECT * FROM service_requests WHERE id=%s', (request_id,))[0]
    assert row['duration_minutes'] == 90 and row['service_components'] == before['service_components']
    assert datetime.fromisoformat(row['booking_time']) == new_time
    assert booking.get_session_booking('owned-group')['duration_minutes'] == 90
    before_retry = capacity_snapshot(db)
    normalized_args = dict(args, service_type=' session oil ', services=['SESSION OIL'],
                           make=' honda ', model='CIVIC', year='2021')
    retried = voice(api, name, normalized_args)
    assert retried['success'] is True and retried['is_update'] is False, retried
    assert retried['duration_minutes'] == 90
    assert capacity_snapshot(db) == before_retry


@pytest.mark.parametrize('name', ['create_service_request', 'book_appointment'])
def test_native_committed_move_with_failed_readback_is_unknown_not_unchanged(api, db, scenario, session_case, monkeypatch, name):
    args, request_id = session_case
    original_get = telephony.get_customer_appointments
    original_update = telephony.reschedule_appointment
    fault = {'after_commit': False}
    def get_owned(phone):
        if fault['after_commit']:
            raise RuntimeError('private-readback-token')
        return original_get(phone)
    def update(**kwargs):
        outcome = original_update(**kwargs)
        fault['after_commit'] = True
        return outcome
    monkeypatch.setattr(telephony, 'get_customer_appointments', get_owned)
    monkeypatch.setattr(telephony, 'reschedule_appointment', update)
    cache = deepcopy(booking._IN_FLIGHT_BOOKING_SESSIONS)
    before_outbox = len(db('SELECT id FROM outbox_notifications'))
    new_time = scenario['start'] + timedelta(hours=1)
    args.update(booking_time=new_time.isoformat(), appointment_datetime=new_time.isoformat())
    result = voice(api, name, args)
    assert result['success'] is False and result['error_code'] == 'SESSION_BOOKING_UPDATE_UNVERIFIED'
    assert 'Check the existing appointment before trying again' in result['message']
    assert 'unchanged' not in result['message'] and 'private' not in str(result)
    assert booking._IN_FLIGHT_BOOKING_SESSIONS == cache
    assert datetime.fromisoformat(db('SELECT booking_time FROM service_requests WHERE id=%s', (request_id,))[0]['booking_time']) == new_time
    assert len(db('SELECT id FROM outbox_notifications')) == before_outbox + 2
    assert len(db('SELECT id FROM service_requests WHERE customer_id=(SELECT customer_id FROM service_requests WHERE id=%s)', (request_id,))) == 1


@pytest.mark.parametrize('name', ['create_service_request', 'book_appointment'])
@pytest.mark.parametrize('defect', ['missing', 'cancelled', 'shifted', 'missing_segment', 'wrong_segment_staff'])
@pytest.mark.parametrize('move', [False, True])
def test_native_orphaned_or_inconsistent_capacity_cannot_pass_session_noop(api, db, scenario, session_case, monkeypatch, name, defect, move):
    from unittest.mock import Mock
    args, request_id = session_case
    if move:
        when = scenario["start"] + timedelta(hours=1)
        args.update(booking_time=when.isoformat(), appointment_datetime=when.isoformat())
    rid = db('SELECT id FROM appointment_reservations WHERE service_request_id=%s', (request_id,))[0]['id']
    if defect == 'missing': db('DELETE FROM appointment_reservations WHERE id=%s', (rid,))
    elif defect == 'cancelled': db("UPDATE appointment_reservations SET status='CANCELLED' WHERE id=%s", (rid,))
    elif defect == 'shifted': db("UPDATE appointment_reservations SET starts_at=starts_at+interval '15 minutes',ends_at=ends_at+interval '15 minutes' WHERE id=%s", (rid,))
    elif defect == 'missing_segment': db('DELETE FROM appointment_reservation_segments WHERE reservation_id=%s AND segment_start=(SELECT min(segment_start) FROM appointment_reservation_segments WHERE reservation_id=%s)', (rid,rid))
    else: db('UPDATE appointment_reservation_segments SET staff_agent_id=2 WHERE reservation_id=%s', (rid,))
    before = capacity_snapshot(db)
    cache = deepcopy(booking._IN_FLIGHT_BOOKING_SESSIONS)
    effect = Mock(side_effect=AssertionError('must not reach reschedule'))
    monkeypatch.setattr(telephony, 'reschedule_appointment', effect)
    result = voice(api, name, args)
    assert result['success'] is False and result['error_code'] == 'SESSION_BOOKING_UPDATE_UNVERIFIED'
    effect.assert_not_called()
    assert capacity_snapshot(db) == before and booking._IN_FLIGHT_BOOKING_SESSIONS == cache


@pytest.mark.parametrize('name', ['create_service_request', 'book_appointment'])
@pytest.mark.parametrize('move', [False, True])
@pytest.mark.parametrize('change', [{'service_type': 'Session Oil Extra'}, {'services': ['Session Oil', 'Brake']}, {'make': 'Ford'}, {'model': 'Accord'}, {'year': 2022}])
def test_native_changed_context_cannot_be_silently_discarded_or_cached(api, db, scenario, session_case, monkeypatch, name, move, change):
    from unittest.mock import Mock
    args, _ = session_case
    args.update(change)
    if move:
        when = scenario['start'] + timedelta(hours=1)
        args.update(booking_time=when.isoformat(), appointment_datetime=when.isoformat())
    before = capacity_snapshot(db)
    cache = deepcopy(booking._IN_FLIGHT_BOOKING_SESSIONS)
    effect = Mock(side_effect=AssertionError('must not reach reschedule'))
    monkeypatch.setattr(telephony, 'reschedule_appointment', effect)
    result = voice(api, name, args)
    assert result['success'] is False and result['error_code'] == 'SESSION_BOOKING_UPDATE_UNVERIFIED'
    effect.assert_not_called()
    assert capacity_snapshot(db) == before and booking._IN_FLIGHT_BOOKING_SESSIONS == cache


@pytest.mark.parametrize('name', ['create_service_request', 'book_appointment'])
@pytest.mark.parametrize('defect', ['cancelled', 'missing_segment'])
def test_native_postcommit_capacity_inconsistency_is_unknown_and_preserves_cache(api, db, scenario, session_case, monkeypatch, name, defect):
    args, request_id = session_case
    original = telephony.reschedule_appointment
    def update(**kwargs):
        result = original(**kwargs)
        rid = db('SELECT id FROM appointment_reservations WHERE service_request_id=%s', (request_id,))[0]['id']
        if defect == 'cancelled':
            db("UPDATE appointment_reservations SET status='CANCELLED' WHERE id=%s", (rid,))
        else:
            db('DELETE FROM appointment_reservation_segments WHERE reservation_id=%s', (rid,))
        return result
    monkeypatch.setattr(telephony, 'reschedule_appointment', update)
    cache = deepcopy(booking._IN_FLIGHT_BOOKING_SESSIONS)
    when = scenario['start'] + timedelta(hours=1)
    args.update(booking_time=when.isoformat(), appointment_datetime=when.isoformat())
    result = voice(api, name, args)
    assert result['success'] is False and result['error_code'] == 'SESSION_BOOKING_UPDATE_UNVERIFIED'
    assert 'Check the existing appointment before trying again' in result['message']
    assert 'unchanged' not in result['message']
    assert datetime.fromisoformat(db('SELECT booking_time FROM service_requests WHERE id=%s', (request_id,))[0]['booking_time']) == when
    assert booking._IN_FLIGHT_BOOKING_SESSIONS == cache
