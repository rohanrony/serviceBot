"""Calendar cancellation uses owned event identity and durable provider evidence."""

import pytest
from datetime import timedelta

from e2e.test_workflows import PORTAL, book, edit_payload


@pytest.mark.parametrize("stored_id", [None, "owned-cancel-event"])
@pytest.mark.parametrize('entry', ['portal', 'booking_service'])
def test_cancellation_queues_and_dispatches_exact_calendar_deletion(api, db, scenario, monkeypatch, stored_id, entry):
    from serviceBot.services import outbox_worker

    request_id = book(api, scenario)
    reservation = db("SELECT * FROM appointment_reservations WHERE service_request_id=%s", (request_id,))[0]
    event_id = stored_id or f"servicebot{reservation['id']}{reservation['starts_at']:%Y%m%d%H%M}"
    if stored_id:
        db("UPDATE appointment_reservations SET calendar_event_id=%s WHERE id=%s", (stored_id, reservation['id']))
    last_id = db("SELECT MAX(id) AS id FROM outbox_notifications")[0]['id']
    if entry == 'portal':
        response = api.patch(f"{PORTAL}/service-requests/{request_id}/status", json={"status": "cancelled_by_customer"})
        assert response.status_code == 200, response.text
    else:
        from serviceBot.services.booking import BookingService
        assert BookingService().cancel(request_id=request_id, customer_consent_obtained=True, triggered_by='customer')['cancelled'] is True
    events = db("SELECT * FROM outbox_notifications WHERE request_id=%s AND event_type='calendar_projection' AND id>%s", (request_id, last_id))
    assert len(events) == 1
    payload = events[0]['payload']
    assert payload['action'] == 'delete'
    assert payload['calendar_event_id'] == event_id
    deleted = []
    monkeypatch.setattr(outbox_worker, 'delete_agent_calendar_event_by_id', lambda **kw: deleted.append(kw) or True, raising=False)
    outbox_worker._dispatch_outbox_event('calendar_projection', request_id, payload)
    assert deleted == [{'agent_id': reservation['staff_agent_id'], 'event_id': event_id}]
    assert db("SELECT calendar_integration_status FROM appointment_reservations WHERE id=%s", (reservation['id'],)) == [{'calendar_integration_status': 'DELETED'}]


def test_calendar_deletion_migration_rolls_back_and_reapplies(api, db, scenario):
    from serviceBot.db.connection import get_db_connection
    from serviceBot.db.migrations import apply_migrations, rollback_migration

    request_id = book(api, scenario)
    for table, key in [('service_requests', 'id'), ('appointment_reservations', 'service_request_id'), ('mock_calendar_slots', 'service_request_id')]:
        db(f"UPDATE {table} SET calendar_integration_status='DELETED' WHERE {key}=%s", (request_id,))
    version = '0006_calendar_deletion_state'
    try:
        with get_db_connection() as connection:
            rollback_migration(connection, version)
        for table, key in [('service_requests', 'id'), ('appointment_reservations', 'service_request_id'), ('mock_calendar_slots', 'service_request_id')]:
            assert all(row['calendar_integration_status'] == 'FAILED' for row in db(f"SELECT calendar_integration_status FROM {table} WHERE {key}=%s", (request_id,)))
        constraints = db("SELECT pg_get_constraintdef(oid) AS definition FROM pg_constraint WHERE conname IN ('appointment_reservations_calendar_integration_status_check', 'mock_calendar_slots_calendar_integration_status_check')")
        assert len(constraints) == 2
        assert all('DELETED' not in row['definition'] for row in constraints)
    finally:
        with get_db_connection() as connection:
            apply_migrations(connection)
    db("UPDATE appointment_reservations SET calendar_integration_status='DELETED' WHERE service_request_id=%s", (request_id,))


@pytest.mark.parametrize('status', ['in_progress', 'completed'])
def test_non_cancellation_status_change_does_not_queue_calendar_deletion(api, db, scenario, status):
    request_id = book(api, scenario)
    if status == 'completed':
        assert api.patch(f"{PORTAL}/service-requests/{request_id}/status", json={'status': 'in_progress'}).status_code == 200
    last_id = db("SELECT MAX(id) AS id FROM outbox_notifications")[0]['id']
    response = api.patch(f"{PORTAL}/service-requests/{request_id}/status", json={'status': status})
    assert response.status_code == 200, response.text
    assert not db("SELECT id FROM outbox_notifications WHERE request_id=%s AND event_type='calendar_projection' AND id>%s", (request_id, last_id))


def test_reschedule_retains_recorded_old_calendar_identity(api, db, scenario, monkeypatch):
    from serviceBot.services import outbox_worker

    request_id = book(api, scenario)
    db("UPDATE appointment_reservations SET calendar_event_id='abc123old' WHERE service_request_id=%s", (request_id,))
    last_id = db("SELECT MAX(id) AS id FROM outbox_notifications")[0]['id']
    response = api.put(f"{PORTAL}/service-requests/{request_id}", json=edit_payload(scenario, booking_time=(scenario['start'] + timedelta(hours=1)).isoformat()))
    assert response.status_code == 200, response.text
    payload = db("SELECT payload FROM outbox_notifications WHERE request_id=%s AND event_type='calendar_projection' AND id>%s", (request_id, last_id))[0]['payload']
    assert payload['old_calendar_event_id'] == 'abc123old'
    deleted = []
    monkeypatch.setattr(outbox_worker, 'delete_agent_calendar_event_by_id', lambda **kw: deleted.append(kw) or True)
    monkeypatch.setattr(outbox_worker, 'create_agent_calendar_event', lambda **kw: True)
    outbox_worker._dispatch_outbox_event('calendar_projection', request_id, payload)
    assert deleted == [{'agent_id': payload['old_agent_id'], 'event_id': 'abc123old'}]
