"""Medium simulation contracts against native HTTP and disposable PostgreSQL."""
import json
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from live_simulations import fixtures
from live_simulations.core import SimulationError, render

CASES = {c['id']: c for c in json.loads(Path('live_simulations/scenarios.json').read_text())}


@pytest.fixture
def owned_runtime(live_server, db, scenario, tmp_path, freeze_business_clock):
    from serviceBot.db.connection import get_db_connection
    freeze_business_clock(scenario['start'] - timedelta(days=2))
    config = {'staff': [{'name': f'Test {i}', 'email': f'test{i}@example.test', 'phone': f'+1555010000{i}'} for i in (1, 2)],
              'calendar_ids': {'1': 'primary', '2': 'primary'}}
    values = fixtures.variables({'variables': {'customer_name': 'Synthetic Customer', 'customer_phone': '5550100001', 'customer_email': 'receiver@example.test'}})
    values.update(appointment_time=scenario['start'].isoformat(' '), new_time=(scenario['start'] + timedelta(days=1)).isoformat(' '), callback_time=scenario['start'].replace(hour=14).isoformat(' '))
    def verify():
        assert db('SELECT current_database() AS name')[0]['name'].startswith('voice_e2e_')
    runtime = SimpleNamespace(config=config, url=live_server, folder=tmp_path, connection=get_db_connection, rows=db, verify_ownership=verify)
    fixtures.seed(runtime, values)
    return runtime, values


@pytest.mark.parametrize('case_id', ['C15', 'C16'])
def test_linked_arrangement_creates_native_two_service_visit(owned_runtime, case_id):
    runtime, values = owned_runtime
    fixtures.arrange(runtime, CASES[case_id], values)
    rows = runtime.rows('SELECT service_type, staff_agent_id, visit_group_id, duration_minutes FROM service_requests ORDER BY id')
    assert [r['service_type'] for r in rows] == ['Oil Change', 'Brake Inspection']
    assert len({r['staff_agent_id'] for r in rows}) == 2
    assert len({r['visit_group_id'] for r in rows}) == 1
    assert rows[0]['visit_group_id']
    assert sum(r['duration_minutes'] for r in rows) == 120


def check(runtime, values, case_id, name):
    item = next(c for c in render(CASES[case_id]['checks'], values) if c['name'] == name)
    result = runtime.rows(item['query'], item.get('params', []))
    assert next(iter(result[0].values())) == item['expect']


def test_medium_checks_reject_missing_business_outcomes(owned_runtime):
    runtime, values = owned_runtime
    for case_id, name in [('C10', 'unselected booking preserved'), ('C12', 'requested callback type and time'), ('C14', 'two distinct qualified specialists'), ('C15', 'exact new visit start')]:
        with pytest.raises(AssertionError):
            check(runtime, values, case_id, name)


@pytest.mark.parametrize('profile', ['split', 'linked', 'split_unavailable', 'three_services'])
def test_selected_setup_rejects_later_case_without_calendar_binding(profile):
    config = {'staff': [{'name': 'One'}, {'name': 'Two'}], 'calendar_ids': {'1': 'primary'}}
    with pytest.raises(SimulationError, match='calendar'):
        fixtures.validate_setup(config, [{'id': 'C01', 'setup': 'fresh'}, {'id': 'C15', 'setup': profile}])


def test_selected_setup_accepts_two_designated_bindings():
    fixtures.validate_setup({'staff': [{'name': 'One'}, {'name': 'Two'}], 'calendar_ids': {'1': 'primary', '2': 'primary'}}, [CASES['C15']])


def test_c10_preserves_unselected_native_booking(owned_runtime):
    runtime, values = owned_runtime
    fixtures.arrange(runtime, CASES['C10'], values)
    check(runtime, values, 'C10', 'unselected booking preserved')
    runtime.rows("UPDATE service_requests SET booking_time=%s WHERE service_type='Tire Rotation'", [values['new_time']])
    with pytest.raises(AssertionError):
        check(runtime, values, 'C10', 'unselected booking preserved')


def test_c12_requires_requested_native_callback(owned_runtime):
    runtime, values = owned_runtime
    payload = {'name': 'create_service_request', 'arguments': {'customer_name': values['customer_name'], 'phone': values['customer_phone'], 'make': 'Toyota', 'model': 'Camry', 'year': 2021, 'service_type': 'Unusual sound', 'issue_description': 'Unusual intermittent sound', 'booking_type': 'callback', 'booking_time': values['callback_time']}}
    fixtures.actions(runtime, [{'kind': 'http', 'path': '/api/v1/voice/tools', 'json': payload}], values)
    check(runtime, values, 'C12', 'requested callback type and time')
    runtime.rows("UPDATE service_requests SET booking_type='appointment'")
    with pytest.raises(AssertionError):
        check(runtime, values, 'C12', 'requested callback type and time')
    runtime.rows("UPDATE service_requests SET booking_type='callback',booking_time=%s", [values['new_time']])
    with pytest.raises(AssertionError):
        check(runtime, values, 'C12', 'requested callback type and time')


def test_c14_and_c15_check_specialists_and_exact_contiguous_move(owned_runtime):
    runtime, values = owned_runtime
    fixtures.arrange(runtime, CASES['C15'], values)
    check(runtime, values, 'C14', 'two distinct qualified specialists')
    with pytest.raises(AssertionError):
        check(runtime, values, 'C15', 'exact new visit start')
    first = runtime.rows('SELECT id FROM service_requests ORDER BY id LIMIT 1')[0]['id']
    fixtures.actions(runtime, [{'kind': 'http', 'path': '/api/v1/voice/tools', 'json': {'name': 'reschedule_appointment', 'arguments': {'phone': values['customer_phone'], 'appointment_id': first, 'new_appointment_datetime': values['new_time'], 'appointment_datetime': values['new_time'], 'customer_consent_obtained': True}}}], values)
    for name in ('exact new visit start', 'complete combined duration', 'contiguous full visit'):
        check(runtime, values, 'C15', name)
    runtime.rows('UPDATE service_requests SET staff_agent_id=CASE staff_agent_id WHEN 1 THEN 2 ELSE 1 END')
    with pytest.raises(AssertionError):
        check(runtime, values, 'C14', 'two distinct qualified specialists')
    runtime.rows('UPDATE service_requests SET staff_agent_id=1')
    with pytest.raises(AssertionError):
        check(runtime, values, 'C14', 'two distinct qualified specialists')
    runtime.rows('UPDATE service_requests SET staff_agent_id=2')
    with pytest.raises(AssertionError):
        check(runtime, values, 'C14', 'two distinct qualified specialists')
    runtime.rows("UPDATE appointment_reservations SET ends_at=ends_at+INTERVAL '15 minutes' WHERE service_request_id=%s AND status='ACTIVE'", [first])
    with pytest.raises(AssertionError):
        check(runtime, values, 'C15', 'contiguous full visit')


def test_selected_setup_rejects_single_specialist_even_with_two_calendar_keys():
    with pytest.raises(SimulationError, match='two designated test specialists'):
        fixtures.validate_setup({'staff': [{'name': 'One'}], 'calendar_ids': {'1': 'primary', '2': 'primary'}}, [CASES['C15']])


def test_contiguous_check_rejects_equal_span_with_internal_gap(owned_runtime):
    runtime, values = owned_runtime
    fixtures.arrange(runtime, CASES['C15'], values)
    # Preserve aggregate span and summed duration while corrupting an internal segment
    # boundary: the previous span-only oracle could accept this durable state.
    runtime.rows("UPDATE appointment_reservations SET ends_at=ends_at-INTERVAL '15 minutes' WHERE status='ACTIVE' AND service_request_id IN (SELECT id FROM service_requests WHERE service_type='Oil Change')")
    with pytest.raises(AssertionError):
        check(runtime, values, 'C15', 'contiguous full visit')


def test_c08_native_availability_excludes_occupied_and_offers_alternative(owned_runtime, api):
    from datetime import datetime

    from e2e.test_voice_and_reporting import voice
    runtime, values = owned_runtime
    fixtures.arrange(runtime, CASES['C08'], values)
    def available(when):
        stamp = datetime.fromisoformat(when)
        result = voice(api, 'check_availability', {'preferred_date': stamp.date().isoformat(), 'preferred_time': stamp.strftime('%I:%M %p'), 'service_type': 'Oil Change', 'booking_type': 'appointment'})
        assert result['success'], result
        return result['available_slots']
    assert values['appointment_time'] not in available(values['appointment_time'])
    assert values['new_time'] in available(values['new_time'])


def test_c13_native_setup_books_qualified_contiguous_ninety_minutes(owned_runtime, api):
    from e2e.test_voice_and_reporting import voice
    runtime, values = owned_runtime
    fixtures.arrange(runtime, CASES['C13'], values)
    result = voice(api, 'create_service_request', {'customer_name': values['customer_name'], 'phone': values['customer_phone'], 'make': 'Toyota', 'model': 'Camry', 'year': 2021, 'service_type': 'Oil Change and Tire Rotation', 'services': ['Oil Change', 'Tire Rotation'], 'issue_description': 'Oil Change and Tire Rotation', 'booking_type': 'appointment', 'booking_time': values['appointment_time']})
    assert result['success'], result
    for name in ('single qualified technician', 'complete combined duration', 'contiguous full visit'):
        check(runtime, values, 'C13', name)
    assert runtime.rows("SELECT count(*) AS count FROM service_staff_agents sa JOIN services s ON s.id=sa.service_id WHERE sa.staff_agent_id=1 AND s.name IN ('Oil Change','Tire Rotation')")[0]['count'] == 2


def test_c14_created_visit_has_authoritative_contiguous_duration(owned_runtime):
    runtime, values = owned_runtime
    fixtures.arrange(runtime, CASES['C15'], values)
    check(runtime, values, 'C14', 'contiguous full visit')


def test_contiguous_check_rejects_missing_active_reservation(owned_runtime):
    runtime, values = owned_runtime
    fixtures.arrange(runtime, CASES['C15'], values)
    runtime.rows("UPDATE appointment_reservations SET status='CANCELLED' WHERE service_request_id=(SELECT min(id) FROM service_requests)")
    with pytest.raises(AssertionError):
        check(runtime, values, 'C14', 'contiguous full visit')
