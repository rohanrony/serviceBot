"""Historical events retire even when the intermediate upsert is superseded."""
from datetime import timedelta

import pytest

from e2e.test_calendar_projection_ordering import projection
from e2e.test_workflows import PORTAL, book, edit_payload


@pytest.fixture
def captured_calendar(monkeypatch):
    from serviceBot.services import outbox_worker

    events, created, deleted = {}, [], []

    def create(**payload):
        event_id = payload['external_event_id']
        created.append(event_id)
        events[event_id] = payload
        return True

    def delete(**payload):
        event_id = payload['event_id']
        deleted.append(event_id)
        events.pop(event_id, None)
        return True

    monkeypatch.setattr(outbox_worker, 'create_agent_calendar_event', create)
    monkeypatch.setattr(outbox_worker, 'delete_agent_calendar_event_by_id', delete)
    return events, created, deleted, delete


def chained_moves(api, db, scenario):
    from serviceBot.services import outbox_worker

    request_id = book(api, scenario)
    a = projection(db, request_id)
    outbox_worker._dispatch_outbox_event('calendar_projection', request_id, a)
    moves = []
    for hours in (1, 2):
        response = api.put(f'{PORTAL}/service-requests/{request_id}', json=edit_payload(
            scenario, booking_time=(scenario['start'] + timedelta(hours=hours)).isoformat()))
        assert response.status_code == 200, response.text
        moves.append(projection(db, request_id))
    return request_id, a, *moves


def test_latest_then_stale_upsert_retires_every_previous_event(api, db, scenario, captured_calendar):
    from serviceBot.services import outbox_worker

    events, created, deleted, _ = captured_calendar
    request_id, a, b, c = chained_moves(api, db, scenario)
    assert b['old_calendar_event_id'] == a['calendar_event_id']
    assert c['old_booking_time_str'] == b['booking_time_str']
    outbox_worker._dispatch_outbox_event('calendar_projection', request_id, c)
    outbox_worker._dispatch_outbox_event('calendar_projection', request_id, b)
    assert set(events) == {c['calendar_event_id']}
    assert created == [a['calendar_event_id'], c['calendar_event_id']]
    assert a['calendar_event_id'] in deleted
    assert b['calendar_event_id'] in deleted
    assert c['calendar_event_id'] not in deleted
    assert db('SELECT calendar_event_id, calendar_integration_status FROM service_requests WHERE id=%s', (request_id,)) == [
        {'calendar_event_id': c['calendar_event_id'], 'calendar_integration_status': 'CREATED'}]


def test_cancel_then_stale_retirement_cleans_history_without_recreation(api, db, scenario, captured_calendar):
    from serviceBot.services import outbox_worker

    events, created, _, _ = captured_calendar
    request_id, a, b, c = chained_moves(api, db, scenario)
    outbox_worker._dispatch_outbox_event('calendar_projection', request_id, c)
    assert api.patch(f'{PORTAL}/service-requests/{request_id}/status', json={'status': 'cancelled'}).status_code == 200
    cancellation = projection(db, request_id)
    outbox_worker._dispatch_outbox_event('calendar_projection', request_id, cancellation)
    outbox_worker._dispatch_outbox_event('calendar_projection', request_id, b)
    assert events == {}
    assert created == [a['calendar_event_id'], c['calendar_event_id']]
    assert db('SELECT calendar_integration_status FROM service_requests WHERE id=%s', (request_id,)) == [
        {'calendar_integration_status': 'DELETED'}]


@pytest.mark.parametrize('project_current', [False, True])
def test_return_to_a_protects_recorded_and_deterministic_active_identity(api, db, scenario, captured_calendar, project_current):
    from serviceBot.services import outbox_worker

    events, _, deleted, _ = captured_calendar
    request_id, a, b, _ = chained_moves(api, db, scenario)
    response = api.put(f'{PORTAL}/service-requests/{request_id}', json=edit_payload(scenario))
    assert response.status_code == 200, response.text
    latest = projection(db, request_id)
    assert latest['calendar_event_id'] == a['calendar_event_id']
    if project_current:
        outbox_worker._dispatch_outbox_event('calendar_projection', request_id, latest)
    deleted.clear()
    outbox_worker._dispatch_outbox_event('calendar_projection', request_id, b)
    assert a['calendar_event_id'] in events
    assert a['calendar_event_id'] not in deleted


def test_stale_retirement_failure_retries_without_poisoning_current_status(api, db, scenario, captured_calendar, monkeypatch):
    from serviceBot.services import outbox_worker

    events, created, _, delete = captured_calendar
    request_id, a, b, c = chained_moves(api, db, scenario)
    outbox_worker._dispatch_outbox_event('calendar_projection', request_id, c)
    monkeypatch.setattr(outbox_worker, 'delete_agent_calendar_event_by_id', lambda **_kw: False)
    with pytest.raises(RuntimeError, match='previous projection'):
        outbox_worker._dispatch_outbox_event('calendar_projection', request_id, b)
    outbox_worker._mark_calendar_projection_failed(request_id, b)
    assert db('SELECT calendar_event_id, calendar_integration_status FROM service_requests WHERE id=%s', (request_id,)) == [
        {'calendar_event_id': c['calendar_event_id'], 'calendar_integration_status': 'CREATED'}]
    monkeypatch.setattr(outbox_worker, 'delete_agent_calendar_event_by_id', delete)
    outbox_worker._dispatch_outbox_event('calendar_projection', request_id, b)
    assert set(events) == {c['calendar_event_id']}
    assert created == [a['calendar_event_id'], c['calendar_event_id']]
