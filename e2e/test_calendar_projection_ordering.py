"""Out-of-order provider retries must preserve the current reservation projection."""
from datetime import timedelta

import pytest

from e2e.test_workflows import PORTAL, book


def projection(db, request_id):
    return db("SELECT payload FROM outbox_notifications WHERE request_id=%s AND event_type='calendar_projection' ORDER BY id DESC LIMIT 1", (request_id,))[0]['payload']


def test_old_retry_cannot_shrink_newer_consolidated_calendar_event(api, db, scenario, monkeypatch):
    from serviceBot.db.queries import consolidate_appointment_service
    from serviceBot.services import outbox_worker

    request_id = book(api, scenario)
    old = projection(db, request_id)
    native, calls = {}, []
    def create(**payload):
        calls.append(payload)
        native[payload['external_event_id']] = payload['duration_minutes']
        return len(calls) != 1  # The first write applied remotely, but its response was lost.
    monkeypatch.setattr(outbox_worker, 'create_agent_calendar_event', create)
    with pytest.raises(RuntimeError, match='did not confirm'):
        outbox_worker._dispatch_outbox_event('calendar_projection', request_id, old)
    assert consolidate_appointment_service(request_id, 'Inspect brakes', additional_duration_minutes=15)['success']
    latest = projection(db, request_id)
    outbox_worker._dispatch_outbox_event('calendar_projection', request_id, latest)
    outbox_worker._dispatch_outbox_event('calendar_projection', request_id, old)
    assert len(calls) == 2
    assert native[latest['calendar_event_id']] == 75
    assert db('SELECT duration_minutes, calendar_integration_status FROM service_requests WHERE id=%s', (request_id,)) == [{'duration_minutes': 75, 'calendar_integration_status': 'CREATED'}]


def test_obsolete_upsert_cannot_recreate_cancelled_booking(api, db, scenario, monkeypatch):
    from serviceBot.services import outbox_worker

    request_id = book(api, scenario)
    old = projection(db, request_id)
    assert api.patch(f'{PORTAL}/service-requests/{request_id}/status', json={'status': 'cancelled'}).status_code == 200
    writes = []
    monkeypatch.setattr(outbox_worker, 'create_agent_calendar_event', lambda **kw: writes.append(kw) or True)
    outbox_worker._dispatch_outbox_event('calendar_projection', request_id, old)
    assert writes == []
    assert db('SELECT calendar_integration_status FROM service_requests WHERE id=%s', (request_id,))[0]['calendar_integration_status'] != 'CREATED'


def test_obsolete_delete_cannot_remove_reactivated_reservation(api, db, scenario, monkeypatch):
    from serviceBot.services import outbox_worker

    request_id = book(api, scenario)
    assert api.patch(f'{PORTAL}/service-requests/{request_id}/status', json={'status': 'cancelled'}).status_code == 200
    old = projection(db, request_id)
    new_start = scenario['start'] + timedelta(hours=1)
    # Model a subsequent owner restoring the reservation with a different projection.
    db("UPDATE service_requests SET status='pending', booking_time=%s, calendar_event_id='new-owner', calendar_integration_status='CREATED' WHERE id=%s", (str(new_start), request_id))
    db("UPDATE appointment_reservations SET status='ACTIVE', starts_at=%s, ends_at=%s, calendar_event_id='new-owner', calendar_integration_status='CREATED' WHERE service_request_id=%s", (new_start, new_start + timedelta(hours=1), request_id))
    writes = []
    monkeypatch.setattr(outbox_worker, 'delete_agent_calendar_event_by_id', lambda **kw: writes.append(kw) or True)
    outbox_worker._dispatch_outbox_event('calendar_projection', request_id, old)
    assert writes == []
    assert db('SELECT calendar_integration_status, calendar_event_id FROM service_requests WHERE id=%s', (request_id,)) == [{'calendar_integration_status': 'CREATED', 'calendar_event_id': 'new-owner'}]


def test_old_failure_cannot_overwrite_newer_projection_status(api, db, scenario, monkeypatch):
    from serviceBot.db.queries import consolidate_appointment_service
    from serviceBot.services import outbox_worker

    request_id = book(api, scenario)
    old = projection(db, request_id)
    assert consolidate_appointment_service(request_id, 'Inspect brakes', additional_duration_minutes=15)['success']
    latest = projection(db, request_id)
    monkeypatch.setattr(outbox_worker, 'create_agent_calendar_event', lambda **kw: True)
    outbox_worker._dispatch_outbox_event('calendar_projection', request_id, latest)
    outbox_worker._mark_calendar_projection_failed(request_id, old)
    assert db('SELECT calendar_integration_status, calendar_event_id FROM service_requests WHERE id=%s', (request_id,)) == [{'calendar_integration_status': 'CREATED', 'calendar_event_id': latest['calendar_event_id']}]
