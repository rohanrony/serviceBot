"""Unknown calendars and prepared summaries never become fabricated success."""
from datetime import datetime
from unittest.mock import MagicMock, Mock

import pytest
from fastapi.testclient import TestClient

from serviceBot.api import telephony
from serviceBot.db import queries
from serviceBot.main import app
from serviceBot.services import booking


@pytest.fixture
def availability(monkeypatch):
    cursor = MagicMock()
    cursor.__enter__.return_value = cursor
    cursor.fetchall.side_effect = [[{'id': 1}, {'id': 2}], [], []]
    connection = MagicMock()
    connection.__enter__.return_value = connection
    monkeypatch.setattr(queries, 'get_db_connection', lambda: connection)
    monkeypatch.setattr(queries, 'dict_cursor', lambda _: cursor)
    monkeypatch.setattr(queries, '_generate_dynamic_slots', lambda *a, **kw: ['2026-11-11 10:00:00'])
    monkeypatch.setattr(queries, 'parse_preferred_date_and_time', lambda _: ('2026-11-11', None, None))
    monkeypatch.setattr(queries, 'get_service_required_fields', lambda name, **kwargs: {'name': name, 'duration_minutes': 30})
    monkeypatch.setattr(queries, 'get_qualified_agent_ids', lambda name, **kwargs: [1, 2])
    monkeypatch.setattr('serviceBot.services.calendar_sync.get_configured_business_hours', lambda: list(range(7, 18)))
    monkeypatch.setattr('serviceBot.services.calendar_sync.get_configured_business_days', lambda: list(range(7)))
    states = {1: None, 2: None}
    def fetch(agent, *args):
        state = states[agent]
        if isinstance(state, Exception): raise state
        return state
    monkeypatch.setattr(queries, 'fetch_agent_events', fetch)
    # check_availability reimports this dependency at call time.
    monkeypatch.setattr('serviceBot.services.google_calendar.fetch_agent_events', fetch)
    return states


def busy():
    return [{'start': {'dateTime': '2026-11-11T07:00:00-05:00'},
             'end': {'dateTime': '2026-11-11T18:00:00-05:00'}}]


@pytest.mark.parametrize('states', [{1: None, 2: None}, {1: None, 2: busy()},
                                   {1: RuntimeError('private provider diagnostic'), 2: busy()}])
def test_uncertain_capacity_is_not_known_empty(availability, states):
    availability.update(states)
    with pytest.raises(queries.AvailabilityUnknownError) as error:
        queries.check_availability(service_type='Oil', preferred_date='2026-11-11')
    assert 'private' not in str(error.value)


@pytest.mark.parametrize('states,expected', [({1: [], 2: None}, ['2026-11-11 10:00:00']),
                                          ({1: busy(), 2: busy()}, [])])
def test_verified_available_and_known_empty_keep_list_contract(availability, states, expected):
    availability.update(states)
    assert queries.check_availability(service_type='Oil', preferred_date='2026-11-11') == expected


def test_unknown_is_not_reported_when_another_required_component_is_known_impossible(availability, monkeypatch):
    availability.update({1: None, 2: busy()})
    monkeypatch.setattr(queries, 'get_qualified_agent_ids', lambda name, **kwargs: [1] if name == 'Oil' else [2])
    assert queries.check_availability(services_list=['Oil', 'Brake'], preferred_date='2026-11-11') == []


def test_no_generated_candidates_remains_known_empty(availability, monkeypatch):
    monkeypatch.setattr(queries, '_generate_dynamic_slots', lambda *a, **kw: [])
    assert queries.check_availability(service_type='Oil', preferred_date='2026-11-11') == []


def test_voice_unknown_result_is_explicit_and_does_not_create_any_booking(monkeypatch):
    monkeypatch.setattr(telephony, 'check_availability', Mock(side_effect=queries.AvailabilityUnknownError()))
    create = Mock()
    monkeypatch.setattr(telephony, 'create_service_request', create)
    result = TestClient(app).post('/api/v1/voice/tools', json={'name': 'check_availability',
        'arguments': {'service_type': 'Oil', 'preferred_date': '2026-11-11'}}).json()['result']
    assert result['success'] is False
    assert result['error_code'] == 'AVAILABILITY_UNKNOWN'
    assert result['availability_status'] == 'unknown' and result['retryable'] is True
    assert result['available_slots'] == []
    assert 'no open' not in result['message'].lower()
    create.assert_not_called()


@pytest.mark.parametrize('name', ['cba_webbook', 'cba_webhook', 'transfer_call', 'handoff'])
def test_summary_preparation_does_not_claim_completed_transfer(monkeypatch, name):
    monkeypatch.setattr(telephony, 'is_within_business_hours', lambda: True)
    monkeypatch.setattr(telephony, 'lookup_customer_by_phone', lambda phone: {'name': 'Test', 'phone': phone})
    monkeypatch.setattr(telephony, 'handoff_node', lambda state: {'handoff_summary': 'Prepared context'})
    callback = Mock()
    monkeypatch.setattr(telephony, 'create_callback_request', callback)
    result = TestClient(app).post('/api/v1/voice/tools', json={'name': name,
        'arguments': {'phone': '5550100001', 'issue_description': 'Human please'}}).json()['result']
    assert result['success'] is False
    assert result['handoff_status'] == 'unavailable' and result['transfer_completed'] is False
    assert result['summary'] == 'Prepared context'
    assert 'transfer_phone_number' not in result
    assert 'transferred' not in result['message'].lower()
    callback.assert_not_called()


def test_lead_time_failure_does_not_invent_suggestions_after_unknown_calendar(monkeypatch):
    monkeypatch.setattr(queries, 'check_availability', Mock(side_effect=queries.AvailabilityUnknownError()))
    monkeypatch.setattr(booking.timezone_service, 'now_in_business_tz', lambda: datetime(2026, 11, 11, 10))
    monkeypatch.setattr('serviceBot.api.portal.load_config', lambda: {'min_booking_buffer_hours': 4})
    valid, earliest, suggestions = booking.validate_appointment_lead_time('2026-11-11 10:15:00')
    assert valid is False and earliest > datetime(2026, 11, 11, 10, 15)
    assert suggestions == []


def test_graph_tool_exposes_unknown_and_preserves_verified_lists(monkeypatch):
    from serviceBot.graph.nodes import _availability_tool_result
    monkeypatch.setattr(queries, 'check_availability', Mock(side_effect=queries.AvailabilityUnknownError()))
    assert _availability_tool_result(service_type='Oil')['availability_status'] == 'unknown'
    for verified in ([], ['2026-11-11 10:00:00']):
        monkeypatch.setattr(queries, 'check_availability', lambda value=verified, **kwargs: value)
        assert _availability_tool_result(service_type='Oil') == verified


def test_summary_owner_explicitly_does_not_perform_transfer(monkeypatch):
    from serviceBot.graph.nodes import handoff_node
    monkeypatch.setattr(telephony, 'is_within_business_hours', lambda: True)
    result = handoff_node({'messages': [], 'customer': {'name': 'Test'}})
    assert result['handoff_status'] == 'summary_prepared'
    assert result['transfer_completed'] is False
    assert 'Test' in result['handoff_summary']


def test_known_local_blocks_remain_known_empty_despite_unknown_provider(availability):
    cursor = queries.dict_cursor(None)
    cursor.fetchall.side_effect = [[{'id': 1}, {'id': 2}], [
        {'staff_agent_id': staff, 'slot_datetime': datetime(2026, 11, 11, 10)} for staff in (1, 2)], []]
    assert queries.check_availability(service_type='Oil', preferred_date='2026-11-11') == []


@pytest.mark.parametrize('slots,status', [([], 'unavailable'), (['2026-11-11 10:00:00'], 'available')])
def test_voice_verified_availability_keeps_success_contract(monkeypatch, slots, status):
    monkeypatch.setattr(telephony, 'check_availability', lambda **kwargs: slots)
    result = TestClient(app).post('/api/v1/voice/tools', json={'name': 'check_availability',
        'arguments': {'service_type': 'Oil', 'preferred_date': '2026-11-11'}}).json()['result']
    assert result['success'] is True
    assert result['availability_status'] == status
    assert result['available_slots'] == slots


def test_unreadable_local_capacity_is_unknown_even_when_provider_is_free(availability):
    availability.update({1: [], 2: []})
    cursor = queries.dict_cursor(None)
    cursor.fetchall.side_effect = [[{'id': 1}, {'id': 2}], RuntimeError('private database diagnostic')]
    with pytest.raises(queries.AvailabilityUnknownError) as error:
        queries.check_availability(service_type='Oil', preferred_date='2026-11-11')
    assert 'private' not in str(error.value)


@pytest.mark.parametrize('failure', ['catalog', 'service_id', 'membership'])
@pytest.mark.parametrize('qualified_state', ['busy', 'unknown'])
def test_failed_qualification_cannot_offer_unqualified_free_staff(monkeypatch, failure, qualified_state):
    class Cursor:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, sql, params=None):
            self.sql = sql
            if (failure == 'catalog' and 'SELECT name, description' in sql
                    or failure == 'service_id' and 'SELECT id FROM services WHERE' in sql
                    or failure == 'membership' and 'FROM service_staff_agents' in sql):
                raise RuntimeError('private qualification lookup diagnostic')
        def fetchall(self):
            if 'FROM staff_agents' in self.sql: return [{'id': 1}, {'id': 2}]
            if 'FROM services' in self.sql: return [{'name': 'Oil', 'duration_minutes': 30}]
            if 'FROM service_staff_agents' in self.sql: return [{'staff_agent_id': 1}]
            return []
        def fetchone(self): return {'id': 5}
    from contextlib import nullcontext
    monkeypatch.setattr(queries, 'get_db_connection', lambda: nullcontext(object()))
    monkeypatch.setattr(queries, 'dict_cursor', lambda _: Cursor())
    monkeypatch.setattr(queries, '_generate_dynamic_slots', lambda *a, **kw: ['2026-11-11 10:00:00'])
    monkeypatch.setattr('serviceBot.services.google_calendar.fetch_agent_events',
        lambda staff, *a: (busy() if qualified_state == 'busy' else None) if staff == 1 else [])
    with pytest.raises(queries.AvailabilityUnknownError):
        queries.check_availability(service_type='Oil', preferred_date='2026-11-11')


@pytest.fixture
def portal_availability(monkeypatch):
    cursor = MagicMock()
    cursor.__enter__.return_value = cursor
    cursor.fetchall.side_effect = [[{'id': 1, 'name': 'One'}], [], [], []]
    connection = MagicMock()
    connection.__enter__.return_value = connection
    monkeypatch.setattr(queries, 'get_db_connection', lambda: connection)
    monkeypatch.setattr(queries, 'dict_cursor', lambda _: cursor)
    monkeypatch.setattr('serviceBot.services.calendar_sync.get_configured_business_hours', lambda: [10])
    monkeypatch.setattr('serviceBot.services.calendar_sync.get_configured_business_days', lambda: list(range(7)))
    state = {'events': None}
    monkeypatch.setattr('serviceBot.services.google_calendar.fetch_agent_events', lambda *a: state['events'])
    return state, cursor


def test_portal_unknown_calendar_is_not_known_empty(portal_availability):
    with pytest.raises(queries.AvailabilityUnknownError):
        queries.get_available_slots_for_date('2026-11-11', duration_minutes=30)


@pytest.mark.parametrize('events,has_slots', [([], True), (busy(), False)])
def test_portal_verified_free_and_known_busy_preserved(portal_availability, events, has_slots):
    state, _ = portal_availability
    state['events'] = events
    assert bool(queries.get_available_slots_for_date('2026-11-11', duration_minutes=30)) is has_slots


def test_portal_capacity_read_failure_cannot_offer_free_slots(portal_availability):
    state, cursor = portal_availability
    state['events'] = []
    cursor.fetchall.side_effect = [[{'id': 1, 'name': 'One'}], RuntimeError('private capacity SQL')]
    with pytest.raises(queries.AvailabilityUnknownError):
        queries.get_available_slots_for_date('2026-11-11', duration_minutes=30)


def test_portal_known_local_conflicts_dominate_unknown_provider(portal_availability):
    _, cursor = portal_availability
    cursor.fetchall.side_effect = [[{'id': 1, 'name': 'One'}], [
        {'staff_agent_id': 1, 'slot_datetime': datetime(2026, 11, 11, 10, minute)} for minute in (0, 30)], [], []]
    assert queries.get_available_slots_for_date('2026-11-11', duration_minutes=30) == []


def test_portal_unknown_endpoint_is_retryable_safe_503(monkeypatch):
    monkeypatch.setattr(queries, 'get_available_slots_for_date', Mock(side_effect=queries.AvailabilityUnknownError()))
    response = TestClient(app).get('/api/v1/portal/available-slots?date=2026-11-11')
    assert response.status_code == 503
    detail = response.json()['detail']
    assert detail['error_code'] == 'AVAILABILITY_UNKNOWN' and detail['retryable'] is True
    assert detail['availability_status'] == 'unknown' and detail['available_slots'] == []


@pytest.mark.parametrize('mode,expected', [('unknown_service', []), ('mappingless', []), ('inactive_mapping', [99])])
def test_strict_qualification_preserves_successful_unrestricted_and_raw_mapping_contract(monkeypatch, mode, expected):
    from contextlib import nullcontext
    cursor = MagicMock()
    cursor.__enter__.return_value = cursor
    cursor.fetchone.return_value = None if mode == 'unknown_service' else {'id': 5}
    cursor.fetchall.return_value = [{'staff_agent_id': 99}] if mode == 'inactive_mapping' else []
    monkeypatch.setattr(queries, 'get_db_connection', lambda: nullcontext(object()))
    monkeypatch.setattr(queries, 'dict_cursor', lambda _: cursor)
    monkeypatch.setattr(queries, 'get_service_required_fields', lambda name, **kwargs: {'name': name})
    assert queries.get_qualified_agent_ids('Owned Oil', strict=True) == expected


def test_inactive_only_mapping_never_becomes_unrestricted_free_capacity(availability, monkeypatch):
    availability.update({1: [], 2: []})
    monkeypatch.setattr(queries, 'get_qualified_agent_ids', lambda name, **kwargs: [99])
    assert queries.check_availability(service_type='Oil', preferred_date='2026-11-11') == []
