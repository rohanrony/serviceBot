"""Every portal reassignment uses the same validated reservation authority."""
from datetime import timedelta

import pytest

from e2e.scenarios import capacity_snapshot
from e2e.test_selective_service_boundaries import (
    grouped_visit as grouped_visit,  # noqa: PLC0414
)


@pytest.mark.parametrize('endpoint', ['assign-agent', 'reassign'])
@pytest.mark.parametrize('failure', ['unknown_calendar', 'busy_calendar', 'qualification'])
def test_reassignment_rejection_preserves_all_booking_and_audit_state(
    api, db, scenario, grouped_visit, monkeypatch, endpoint, failure
):
    from serviceBot.services import google_calendar

    request_id = grouped_visit[0]
    if failure != 'qualification':
        db("INSERT INTO service_staff_agents(service_id,staff_agent_id) SELECT id,2 FROM services WHERE name IN ('Oil Change','Tire Rotation') ON CONFLICT DO NOTHING")
    def events(agent_id, *_):
        if agent_id != 2 or failure == 'qualification':
            return []
        if failure == 'unknown_calendar':
            return None
        return [{'start': {'dateTime': scenario['start'].isoformat()},
                 'end': {'dateTime': (scenario['start'] + timedelta(hours=1)).isoformat()}}]
    monkeypatch.setattr(google_calendar, 'fetch_agent_events', events)
    before = capacity_snapshot(db)
    audit = db('SELECT * FROM service_request_audit_log ORDER BY id')
    if endpoint == 'assign-agent':
        response = api.patch(f'/api/v1/portal/service-requests/{request_id}/assign-agent', json={'staff_agent_id': 2})
    else:
        response = api.post(f'/api/v1/portal/service-requests/{request_id}/reassign', json={'new_agent_id': 2, 'reason': 'Guard regression'})
    assert response.status_code == 409, response.text
    assert capacity_snapshot(db) == before
    assert db('SELECT * FROM service_request_audit_log ORDER BY id') == audit


def test_verified_manual_reassignment_moves_every_segment_and_preserves_reason(
    api, db, grouped_visit, monkeypatch
):
    from serviceBot.services import google_calendar

    request_id = grouped_visit[0]
    db("INSERT INTO service_staff_agents(service_id,staff_agent_id) SELECT id,2 FROM services WHERE name IN ('Oil Change','Tire Rotation') ON CONFLICT DO NOTHING")
    monkeypatch.setattr(google_calendar, 'fetch_agent_events', lambda *_: [])
    reservation = db('SELECT id FROM appointment_reservations WHERE service_request_id=%s', (request_id,))[0]['id']
    outbox_before = db('SELECT COUNT(*) AS count FROM outbox_notifications')[0]['count']
    response = api.post(f'/api/v1/portal/service-requests/{request_id}/reassign',
                        json={'new_agent_id': 2, 'reason': 'Supervisor confirmed replacement'})
    assert response.status_code == 200, response.text
    assert response.json()['confirmation_status'] == 'pending_agent_confirmation'
    assert response.json()['escalation_status'] == 'reassigned'
    assert {row['staff_agent_id'] for row in db('SELECT staff_agent_id FROM appointment_reservation_segments WHERE reservation_id=%s', (reservation,))} == {2}
    assert len(db("SELECT id FROM mock_calendar_slots WHERE service_request_id=%s AND staff_agent_id=2 AND reservation_status='RESERVED'", (request_id,))) == 6
    assert db('SELECT COUNT(*) AS count FROM outbox_notifications')[0]['count'] == outbox_before + 2
    audit = db("SELECT notes,metadata FROM service_request_audit_log WHERE request_id=%s AND event_type='AGENT_REASSIGNED' ORDER BY id DESC LIMIT 1", (request_id,))[0]
    assert audit['metadata']['reason'] == 'Supervisor confirmed replacement'
    assert 'Supervisor confirmed replacement' in audit['notes']


def test_manual_assignment_of_unscheduled_intake_preserves_supervisor_reason(api, db):
    response = api.post('/api/v1/portal/service-requests/1/reassign',
                        json={'new_agent_id': 2, 'reason': 'Supervisor routing intake'})
    assert response.status_code == 200, response.text
    audit = db("SELECT notes,metadata FROM service_request_audit_log WHERE request_id=1 AND event_type='AGENT_ASSIGNED' ORDER BY id DESC LIMIT 1")[0]
    assert audit['metadata']['reason'] == 'Supervisor routing intake'
    assert 'Supervisor routing intake' in audit['notes']
