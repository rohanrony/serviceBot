"""Cached call-session updates report only verified authoritative outcomes."""
import asyncio
from copy import deepcopy
from unittest.mock import Mock

import pytest

from serviceBot.api import telephony
from serviceBot.services import booking


@pytest.fixture(scope='session', autouse=True)
def setup_and_cleanup_test_db():
    yield


@pytest.fixture
def session_update(monkeypatch):
    monkeypatch.setattr(booking, '_IN_FLIGHT_BOOKING_SESSIONS', {})
    booking.track_session_booking('owned-call', 17, '2026-11-20T10:00:00', 90, phone='+14242704893')
    rows = [{'id': 17, 'booking_type': 'appointment', 'appointment_datetime': '2026-11-20T10:00:00',
             'duration_minutes': 90, 'status': 'pending', 'service_type': 'Oil Change, Tire Rotation',
             'make': 'Honda', 'model': 'Civic', 'year': 2021,
             'service_components': [{'name': 'Oil Change', 'duration_minutes': 60}, {'name': 'Tire Rotation', 'duration_minutes': 30}],
             'visit_group_id': None, 'visit_member_ids': []}]
    monkeypatch.setattr(telephony, 'lookup_customer_by_phone', lambda _: {'customer_id': 3, 'name': 'Owned'})
    monkeypatch.setattr(telephony, 'update_customer_name', Mock())
    monkeypatch.setattr(telephony, 'get_customer_appointments', lambda _: deepcopy(rows))
    monkeypatch.setattr(telephony, 'get_service_required_fields', lambda _: {'duration_minutes': 60})
    creates = [Mock(), Mock()]
    monkeypatch.setattr(telephony, 'create_service_request', creates[0])
    monkeypatch.setattr(telephony, 'book_appointment', creates[1])
    def evidence(ids):
        from datetime import timedelta
        return [{'id': row['id'], 'request_staff': 7, 'reservation_id': 100, 'service_request_id': row['id'],
            'staff_agent_id': 7, 'status': 'ACTIVE', 'request_status': 'pending', 'phone': '+14242704893',
            'duration_minutes': row['duration_minutes'], 'booking_time': row['appointment_datetime'],
            'starts_at': row['appointment_datetime'],
            'ends_at': booking.parse_reservation_start(row['appointment_datetime']) + timedelta(minutes=row['duration_minutes']),
            'segments': [{'reservation_id': 100, 'staff_agent_id': 7, 'segment_start': start}
                      for start in booking.reservation_segments(booking.parse_reservation_start(row['appointment_datetime']), row['duration_minutes'])]}
                for row in rows]
    monkeypatch.setattr(telephony, '_session_capacity_evidence', evidence, raising=False)
    def invoke(name, **changes):
        return asyncio.run(telephony.voice_tools({'name': name, 'arguments': {
            'customer_name': 'Owned', 'phone': '+14242704893', 'make': 'Honda', 'model': 'Civic', 'year': 2021,
            'service_type': 'Oil Change', 'booking_type': 'appointment', 'call_sid': 'owned-call',
            'booking_time': '2026-11-20T12:00:00', 'appointment_datetime': '2026-11-20T12:00:00', **changes,
        }}))['result']
    return invoke, rows, creates


@pytest.mark.parametrize('name', ['create_service_request', 'book_appointment'])
@pytest.mark.parametrize('outcome', ['raise', False, None, {'success': False, 'message': 'private-token'}, {'success': True}, 1])
def test_failed_or_unknown_session_update_never_claims_success_or_replaces_cache(session_update, monkeypatch, name, outcome):
    invoke, _, creates = session_update
    before = deepcopy(booking._IN_FLIGHT_BOOKING_SESSIONS)
    effect = Mock(side_effect=RuntimeError('private-token')) if outcome == 'raise' else Mock(return_value=outcome)
    monkeypatch.setattr(telephony, 'reschedule_appointment', effect)
    result = invoke(name)
    assert result['success'] is False
    assert result['error_code'] == 'SESSION_BOOKING_UPDATE_UNVERIFIED'
    assert 'private-token' not in str(result)
    assert booking._IN_FLIGHT_BOOKING_SESSIONS == before
    for create in creates: create.assert_not_called()


@pytest.mark.parametrize('name', ['create_service_request', 'book_appointment'])
@pytest.mark.parametrize('defect', ['foreign', 'inactive', 'invalid_id', 'missing_id', 'zero_id', 'wrong_cache_phone'])
def test_cached_request_requires_current_phone_ownership_before_domain_update(session_update, monkeypatch, name, defect):
    invoke, rows, creates = session_update
    if defect in ('foreign', 'inactive'): rows.clear()
    elif defect == 'invalid_id': booking._IN_FLIGHT_BOOKING_SESSIONS['owned-call']['service_request_id'] = True
    elif defect == 'missing_id': booking._IN_FLIGHT_BOOKING_SESSIONS['owned-call'].pop('service_request_id')
    elif defect == 'zero_id': booking._IN_FLIGHT_BOOKING_SESSIONS['owned-call']['service_request_id'] = 0
    else: booking._IN_FLIGHT_BOOKING_SESSIONS['owned-call']['phone'] = '+16662704893'
    before = deepcopy(booking._IN_FLIGHT_BOOKING_SESSIONS)
    effect = Mock(return_value=True)
    monkeypatch.setattr(telephony, 'reschedule_appointment', effect)
    result = invoke(name)
    assert result['success'] is False
    assert booking._IN_FLIGHT_BOOKING_SESSIONS == before
    effect.assert_not_called()
    for create in creates: create.assert_not_called()


@pytest.mark.parametrize('name', ['create_service_request', 'book_appointment'])
@pytest.mark.parametrize('readback', ['unchanged', 'missing', 'raise', 'success'])
def test_exact_true_still_requires_authoritative_readback_and_preserves_booked_duration(session_update, monkeypatch, name, readback):
    invoke, rows, _ = session_update
    before = deepcopy(booking._IN_FLIGHT_BOOKING_SESSIONS)
    def update(**kwargs):
        if readback == 'success': rows[0]['appointment_datetime'] = '2026-11-20T12:00:00'
        elif readback == 'missing': rows.clear()
        elif readback == 'raise': monkeypatch.setattr(telephony, 'get_customer_appointments', Mock(side_effect=RuntimeError('private-token')))
        return True
    monkeypatch.setattr(telephony, 'reschedule_appointment', update)
    result = invoke(name)
    assert result['success'] is (readback == 'success')
    if readback == 'success':
        assert result['duration_minutes'] == 90
        assert result['expected_end_time'] == '2026-11-20 13:30:00'
        assert booking.get_session_booking('owned-call')['duration_minutes'] == 90
        assert result['notification_delivery_status'] == 'unverified'
    else:
        assert booking._IN_FLIGHT_BOOKING_SESSIONS == before
        assert 'private-token' not in str(result)


@pytest.mark.parametrize('name', ['create_service_request', 'book_appointment'])
def test_same_current_time_retry_does_not_reschedule_or_create(session_update, monkeypatch, name):
    invoke, rows, creates = session_update
    rows[0]['appointment_datetime'] = '2026-11-20T12:00:00'
    effect = Mock(return_value=True)
    monkeypatch.setattr(telephony, 'reschedule_appointment', effect)
    result = invoke(name)
    assert result['success'] is True and result['is_update'] is False
    assert result['duration_minutes'] == 90
    effect.assert_not_called()
    for create in creates: create.assert_not_called()


@pytest.mark.parametrize('name', ['create_service_request', 'book_appointment'])
def test_equivalent_utc_and_business_time_is_verified_noop(session_update, monkeypatch, name):
    invoke, rows, creates = session_update
    # November New York noon is 17:00Z. Raw strings differ but instants agree.
    rows[0]['appointment_datetime'] = '2026-11-20T17:00:00Z'
    effect = Mock(return_value=True)
    monkeypatch.setattr(telephony, 'reschedule_appointment', effect)
    result = invoke(name)
    assert result['success'] is True and result['is_update'] is False
    assert result['duration_minutes'] == 90
    effect.assert_not_called()
    for create in creates: create.assert_not_called()


@pytest.mark.parametrize('name', ['create_service_request', 'book_appointment'])
@pytest.mark.parametrize('change', [{'service_type': 'Oil Change Extra'}, {'services': ['Brake']}, {'make': 'Ford'}, {'model': 'Accord'}, {'year': True}])
def test_v2_requested_context_change_is_not_reported_as_applied(session_update, monkeypatch, name, change):
    invoke, rows, creates = session_update
    rows[0]['appointment_datetime'] = '2026-11-20T12:00:00'
    effect = Mock(return_value=True)
    monkeypatch.setattr(telephony, 'reschedule_appointment', effect)
    cache = deepcopy(booking._IN_FLIGHT_BOOKING_SESSIONS)
    result = invoke(name, **change)
    assert result['success'] is False and result['error_code'] == 'SESSION_BOOKING_UPDATE_UNVERIFIED'
    assert booking._IN_FLIGHT_BOOKING_SESSIONS == cache
    effect.assert_not_called()
    for create in creates: create.assert_not_called()


@pytest.mark.parametrize('name', ['create_service_request', 'book_appointment'])
@pytest.mark.parametrize('defect', ['missing', 'cancelled', 'shifted', 'missing_segment', 'wrong_segment_staff', 'read_error', 'boolean_staff'])
@pytest.mark.parametrize('move', [False, True])
def test_v2_native_capacity_is_required_before_noop_or_move(session_update, monkeypatch, name, defect, move):
    invoke, rows, creates = session_update
    if not move:
        rows[0]['appointment_datetime'] = '2026-11-20T12:00:00'
    evidence = telephony._session_capacity_evidence
    def corrupt(ids):
        data = evidence(ids)
        if defect == 'missing': return []
        if defect == 'read_error': raise RuntimeError('private-token')
        if defect == 'cancelled': data[0]['status'] = 'CANCELLED'
        elif defect == 'shifted': data[0]['starts_at'] = '2026-11-20T12:15:00'
        elif defect == 'missing_segment': data[0]['segments'].pop()
        elif defect == 'wrong_segment_staff': data[0]['segments'][0]['staff_agent_id'] = 8
        elif defect == 'boolean_staff': data[0]['request_staff'] = True
        return data
    monkeypatch.setattr(telephony, '_session_capacity_evidence', corrupt)
    effect = Mock(return_value=True)
    monkeypatch.setattr(telephony, 'reschedule_appointment', effect)
    cache = deepcopy(booking._IN_FLIGHT_BOOKING_SESSIONS)
    result = invoke(name)
    assert result['success'] is False and 'private-token' not in str(result)
    assert booking._IN_FLIGHT_BOOKING_SESSIONS == cache
    effect.assert_not_called()
    for create in creates: create.assert_not_called()


@pytest.mark.parametrize('name', ['create_service_request', 'book_appointment'])
def test_v2_booked_group_subset_and_normalized_vehicle_are_compatible(session_update, monkeypatch, name):
    invoke, rows, _ = session_update
    rows[0]['appointment_datetime'] = '2026-11-20T12:00:00'
    effect = Mock(return_value=True)
    monkeypatch.setattr(telephony, 'reschedule_appointment', effect)
    result = invoke(name, service_type=' oil change ', services=['TIRE ROTATION'], make=' honda ', model='CIVIC', year='2021')
    assert result['success'] is True and result['duration_minutes'] == 90
    effect.assert_not_called()
