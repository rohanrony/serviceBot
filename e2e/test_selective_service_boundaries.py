"""Selective voice/portal removal over real HTTP, domain owner and PostgreSQL."""
import pytest

from e2e.test_voice_and_reporting import voice
from e2e.test_voice_mutation_ownership import snapshot
from e2e.test_workflows import request_by_id
from serviceBot.services.booking import BookingService


@pytest.fixture
def grouped_visit(api, db, scenario):
    db("INSERT INTO services(name,duration_minutes) VALUES ('Tire Rotation',30),('Brake Inspection',30)")
    db("INSERT INTO service_staff_agents(service_id,staff_agent_id) SELECT id,1 FROM services WHERE name IN ('Oil Change','Tire Rotation')")
    db("INSERT INTO service_staff_agents(service_id,staff_agent_id) SELECT id,2 FROM services WHERE name='Brake Inspection'")
    receipts = BookingService().reserve_multi_service_appointment(customer_id=1,
        services=['Oil Change', 'Tire Rotation', 'Brake Inspection'],
        appointment_datetime=scenario['start'], vehicle_details={'make': 'Toyota', 'model': 'Camry', 'year': 2020})
    assert len(receipts) == 2
    return receipts[0]['service_request_id'], receipts[1]['service_request_id']


@pytest.mark.parametrize('boundary', ['voice', 'portal'])
def test_selected_service_removal_readback_keeps_start_and_companion(api, db, grouped_visit, boundary):
    target, companion = grouped_visit
    before = request_by_id(api, target)
    companion_before = request_by_id(api, companion)
    assert before['service_components'] == [
        {'name': 'Oil Change', 'duration_minutes': 60}, {'name': 'Tire Rotation', 'duration_minutes': 30}]
    if boundary == 'voice':
        result = voice(api, 'cancel_appointment', {'phone': '+15550100001',
            'appointment_id': target, 'service_name': 'Oil Change'})
    else:
        response = api.post(f'/api/v1/portal/service-requests/{target}/remove-service',
            json={'service_name': 'Oil Change', 'customer_consent_obtained': True})
        assert response.status_code == 200, response.text
        result = response.json()
    assert result['success'] is True, result
    assert result['cancelled'] is False
    assert result['notification_status'] == 'queued'
    after = request_by_id(api, target)
    assert after['service_components'] == [{'name': 'Tire Rotation', 'duration_minutes': 30}]
    assert after['duration_minutes'] == 30
    assert after['booking_start_time'] == before['booking_start_time']
    assert after['booking_end_time'] != before['booking_end_time']
    assert after['notification_queue_status'] == 'PENDING'
    assert after['calendar_integration_status'] == 'PENDING_CALENDAR'
    companion_after = request_by_id(api, companion)
    for field in ('booking_start_time', 'booking_end_time', 'duration_minutes', 'service_components', 'status'):
        assert companion_after[field] == companion_before[field]
    assert len(db('SELECT seg.* FROM appointment_reservation_segments seg JOIN appointment_reservations r ON r.id=seg.reservation_id WHERE r.service_request_id=%s', (target,))) == 2


@pytest.mark.parametrize('kind', ['foreign', 'invalid_service', 'missing_consent', 'unknown_service'])
def test_rejected_selective_request_preserves_every_effect(api, db, grouped_visit, kind):
    target, _ = grouped_visit
    before = snapshot(db)
    if kind == 'missing_consent':
        response = api.post(f'/api/v1/portal/service-requests/{target}/remove-service', json={'service_name': 'Oil Change'})
        assert response.status_code == 400
    else:
        result = voice(api, 'cancel_appointment', {'phone': '+15550100002' if kind == 'foreign' else '+15550100001',
            'appointment_id': target, 'service_name': None if kind == 'invalid_service' else
                'Unknown Service' if kind == 'unknown_service' else 'Oil Change'})
        assert result['success'] is False
    assert snapshot(db) == before


def test_omitted_voice_service_still_cancels_linked_visit(api, db, grouped_visit):
    target, companion = grouped_visit
    result = voice(api, 'cancel_appointment', {'phone': '+15550100001', 'appointment_id': target})
    assert result['success'] is True
    assert {row['status'] for row in db('SELECT status FROM service_requests WHERE id=ANY(%s)', ([target, companion],))} == {'cancelled'}


@pytest.mark.parametrize('boundary', ['voice', 'portal'])
def test_last_selected_service_cancels_only_selected_appointment(api, grouped_visit, boundary):
    target, companion = grouped_visit
    companion_before = request_by_id(api, companion)
    for name in ('Oil Change', 'Tire Rotation'):
        if boundary == 'voice':
            result = voice(api, 'cancel_appointment', {'phone': '+15550100001',
                'appointment_id': target, 'service_name': name})
        else:
            response = api.post(f'/api/v1/portal/service-requests/{target}/remove-service',
                json={'service_name': name, 'customer_consent_obtained': True})
            assert response.status_code == 200, response.text
            result = response.json()
        assert result['success'] is True
    assert result['cancelled'] is True
    assert request_by_id(api, target)['status'] == 'cancelled'
    companion_after = request_by_id(api, companion)
    for field in ('booking_start_time', 'booking_end_time', 'duration_minutes', 'service_components', 'status'):
        assert companion_after[field] == companion_before[field]
