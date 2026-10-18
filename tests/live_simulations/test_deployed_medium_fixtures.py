"""Offline deployed medium ownership and native state contracts."""
from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest

from live_simulations import deployed_medium as medium
from live_simulations.core import SimulationError, load_catalog


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(medium, '_now', lambda _config: datetime(2026,11,8,10,tzinfo=UTC))
    config = {'deployed_url': 'https://app.example.test', 'variables': {'customer_name': 'Preserved Name', 'customer_phone': '4242704893', 'customer_email': 'admin@example.test'},
              'allowlisted_phone_numbers': ['+14242704893'], 'allowlisted_emails': ['one@example.test', 'two@example.test', 'admin@example.test'],
              'deployed_medium': {'database_env': 'MEDIUM_TEST_DATABASE', 'ownership_id': 'medium-test-owner', 'technician_ids': [7, 12], 'services': {
                  'oil': {'id': 101, 'name': 'medium-test-owner Oil', 'duration_minutes': 60, 'price_range': '$60'},
                  'second': {'id': 102, 'name': 'medium-test-owner Second', 'duration_minutes': 30, 'price_range': '$30'},
                  'split': {'id': 103, 'name': 'medium-test-owner Split', 'duration_minutes': 60, 'price_range': '$60'}}}}
    resources = deepcopy(config['deployed_medium']['services'])
    for item in config['deployed_medium']['services'].values(): item.pop('id')
    manifest = {'run_id': 'a'*32, 'baseline': [], 'results': [], 'stage_authorization': {'authorization_id': 'authorized-medium'}, 'deployed_medium': {'services': resources, 'operations': [], 'owned_request_ids': [], 'blocks': [], 'blocked': False}}
    saves = []
    campaign = SimpleNamespace(config=config, manifest=manifest, folder=tmp_path, save=lambda: saves.append(deepcopy(manifest)))
    calls = []
    def transport(request):
        import json
        calls.append((request.method, request.url.path, json.loads(request.content) if request.content else None))
        if request.url.path.endswith('/voice/tools'):
            return httpx.Response(200, json={'result': {'success': True, 'service_request_id': 51}})
        return httpx.Response(200, json=[])
    client = httpx.Client(transport=httpx.MockTransport(transport))
    monkeypatch.setenv('MEDIUM_TEST_DATABASE', 'postgresql://unused/readonly')
    return config, campaign, client, calls, saves


def case(cid):
    return next(c for c in load_catalog() if c['id'] == cid)


VALUES = {'customer_name': 'Preserved Name', 'customer_phone': '4242704893', 'appointment_time': '2026-11-09 10:00:00', 'new_time': '2026-11-10 10:00:00', 'callback_time': '2026-11-09 14:00:00'}


def test_readiness_rejects_missing_second_deployed_binding_before_mutation(setup, monkeypatch):
    config, _campaign, client, calls, _saves = setup
    config['deployed_medium']['technician_ids'] = [7]
    assert medium.readiness(config, client, [case('C07'), case('C16')], [])
    assert not any(method != 'GET' for method, _, _ in calls)


def test_readiness_rejects_unowned_catalog_names(setup):
    config, _campaign, client, calls, _saves = setup
    config['deployed_medium']['services']['oil']['name'] = 'Original Oil Change'
    assert medium.readiness(config, client, [case('C13')], [])
    assert not any(method != 'GET' for method, _, _ in calls)


def test_fresh_case_adapts_exact_catalog_names_without_mutation(setup, monkeypatch):
    _config, campaign, client, calls, _saves = setup
    adapter = medium.Adapter(campaign, client)
    adapted, ids = adapter.arrange(case('C13'), VALUES)
    assert ids == []
    assert 'medium-test-owner Oil' in adapted['scenario']
    assert 'medium-test-owner Second' in adapted['scenario']
    assert not calls


def test_fixture_intent_is_saved_before_unknown_native_response(setup, monkeypatch):
    _config, campaign, client, _calls, saves = setup
    def unknown(request):
        assert saves[-1]['deployed_medium']['operations'][-1]['status'] == 'intent'
        raise httpx.ReadTimeout('unknown', request=request)
    client = httpx.Client(transport=httpx.MockTransport(unknown))
    adapter = medium.Adapter(campaign, client)
    with pytest.raises(SimulationError, match='unknown'):
        adapter.arrange(case('C10'), VALUES)
    assert campaign.manifest['deployed_medium']['blocked']
    with pytest.raises(SimulationError):
        adapter.arrange(case('C07'), VALUES)


def native_rows():
    return [{'id': 51, 'customer_phone': '4242704893', 'customer_name': 'Preserved Name', 'make': 'Toyota', 'model': 'Camry', 'year': 2021, 'service_type': 'medium-test-owner Oil', 'status': 'pending', 'booking_type': 'appointment', 'booking_time': VALUES['new_time'], 'duration_minutes': 60, 'staff_agent_id': 7, 'visit_group_id': 'group', 'reservation_id': 1, 'reservation_status': 'ACTIVE', 'calendar_integration_status': 'CREATED', 'request_calendar_status': 'CREATED', 'calendar_event_id': 'test-event', 'starts_at': VALUES['new_time'], 'ends_at': '2026-11-10 11:00:00', 'segment_count': 4, 'qualified': True},
            {'id': 52, 'customer_phone': '4242704893', 'customer_name': 'Preserved Name', 'make': 'Toyota', 'model': 'Camry', 'year': 2021, 'service_type': 'medium-test-owner Split', 'status': 'pending', 'booking_type': 'appointment', 'booking_time': '2026-11-10 11:00:00', 'duration_minutes': 60, 'staff_agent_id': 12, 'visit_group_id': 'group', 'reservation_id': 2, 'reservation_status': 'ACTIVE', 'calendar_integration_status': 'CREATED', 'request_calendar_status': 'CREATED', 'calendar_event_id': 'test-event', 'starts_at': '2026-11-10 11:00:00', 'ends_at': '2026-11-10 12:00:00', 'segment_count': 4, 'qualified': True}]


@pytest.mark.parametrize('defect', ['gap', 'missing', 'unqualified', 'wrong_start', 'wrong_group', 'same_staff'])
def test_native_linked_checks_reject_false_business_outcomes(setup, monkeypatch, defect):
    _config, campaign, client, _calls, _saves = setup
    adapter = medium.Adapter(campaign, client)
    rows = native_rows()
    monkeypatch.setattr(medium, '_request_rows', lambda *a: rows)
    adapter.owned_ids.update([51, 52])
    good = adapter.checks(case('C15'), VALUES, [], [{'id': 51}, {'id': 52}])
    assert good and all(c['passed'] for c in good), good
    if defect == 'gap': rows[1]['starts_at'] = '2026-11-10 11:15:00'
    if defect == 'missing': rows[1]['reservation_id'] = None
    if defect == 'unqualified': rows[1]['qualified'] = False
    if defect == 'wrong_start': rows[0]['starts_at'] = '2026-11-10 09:00:00'
    if defect == 'wrong_group': rows[1]['visit_group_id'] = 'other'
    if defect == 'same_staff': rows[1]['staff_agent_id'] = 7
    checks = adapter.checks(case('C15'), VALUES, [], [{'id': 51}, {'id': 52}])
    assert not all(c['passed'] for c in checks), checks


def test_new_nonowned_catalog_or_original_ids_cannot_be_registered(setup, monkeypatch):
    _config, campaign, client, _calls, _saves = setup
    campaign.manifest['baseline'] = [{'id': 11}]
    adapter = medium.Adapter(campaign, client)
    rows = native_rows()
    rows[0]['id'] = 11
    monkeypatch.setattr(medium, '_request_rows', lambda *a: rows)
    with pytest.raises(SimulationError):
        adapter.checks(case('C14'), VALUES, [], [{'id': 11}, {'id': 52}])


def test_cleanup_never_cancels_original_baseline(setup, monkeypatch):
    _config, campaign, client, calls, _saves = setup
    campaign.manifest['baseline'] = [{'id': 11}]
    adapter = medium.Adapter(campaign, client)
    adapter.owned_ids.add(11)
    with pytest.raises(SimulationError): adapter.cleanup_case()
    assert not calls


def test_prepare_catalog_requires_durable_stage_claim(setup):
    _config, campaign, client, calls, _saves = setup
    campaign.manifest.pop('stage_authorization')
    with pytest.raises(SimulationError):
        medium.Adapter(campaign, client).prepare_catalog()
    assert not calls


def test_prepare_catalog_journals_before_each_native_creation(setup):
    _config, campaign, client, _calls, saves = setup
    campaign.manifest.pop('deployed_medium')
    resources = []
    def native(request):
        import json
        if request.method == 'POST':
            assert saves[-1]['deployed_medium']['operations'][-1]['status'] == 'intent'
            body = json.loads(request.content)
            assert body['name'].startswith('medium-test-owner')
            assert body['agent_ids'] in ([7], [12])
            item = {**body, 'id': 101+len(resources), 'assigned_agent_ids': body['agent_ids']}
            resources.append(item)
            return httpx.Response(201, json={'success': True, 'id': item['id']})
        return httpx.Response(200, json=resources)
    client = httpx.Client(transport=httpx.MockTransport(native))
    medium.Adapter(campaign, client).prepare_catalog()
    assert len(resources) == 3
    assert len(campaign.manifest['deployed_medium']['services']) == 3


@pytest.mark.parametrize('defect', ['wrong_vehicle', 'missing_reservation', 'wrong_service', 'wrong_duration'])
def test_single_intake_checks_reject_wrong_native_business_state(setup, monkeypatch, defect):
    _config, campaign, client, _calls, _saves = setup
    adapter = medium.Adapter(campaign, client)
    rows = native_rows()[:1]
    rows[0].update(booking_time=VALUES['appointment_time'], starts_at=VALUES['appointment_time'], ends_at='2026-11-09 11:00:00', make='Toyota', model='Camry', year=2021)
    monkeypatch.setattr(medium, '_request_rows', lambda *a: rows)
    assert all(c['passed'] for c in adapter.checks(case('C11'), VALUES, [], [{'id': 51}]))
    if defect == 'wrong_vehicle': rows[0]['year'] = 2020
    if defect == 'missing_reservation': rows[0]['reservation_id'] = None
    if defect == 'wrong_service': rows[0]['service_type'] = 'medium-test-owner Second'
    if defect == 'wrong_duration': rows[0]['duration_minutes'] = 30
    assert not all(c['passed'] for c in adapter.checks(case('C11'), VALUES, [], [{'id': 51}]))


def test_occupied_cleanup_refuses_changed_or_reserved_slot(setup, monkeypatch):
    _config, campaign, client, calls, _saves = setup
    adapter = medium.Adapter(campaign, client)
    owned = {'id': 9, 'staff_agent_id': 7, 'slot_datetime': VALUES['appointment_time'], 'is_booked': True, 'reservation_status': 'BLOCKED', 'service_request_id': None, 'updated_at': '2026-10-18 10:00:00', 'active_reservation': False}
    original = {**owned, 'is_booked': False, 'reservation_status': 'AVAILABLE', 'updated_at': '2026-10-18 09:00:00'}
    adapter.state['blocks'].append({'original': original, 'owned': owned, 'restored': False})
    monkeypatch.setattr(medium, '_slots', lambda *a: [{**owned, 'updated_at': '2026-10-18 11:00:00'}])
    with pytest.raises(SimulationError, match='changed'):
        adapter.cleanup_case()
    assert not calls


def test_planned_names_accept_explicit_live_test_campaign_prefix(setup):
    config, _campaign, _client, _calls, _saves = setup
    config['deployed_medium']['ownership_id'] = '93b7e8ab491d4eb389b767a8017389dc'
    for key, item in config['deployed_medium']['services'].items():
        item['name'] = 'LIVE TEST 93b7e8ab ' + key
    assert medium._definitions(config)


def test_final_checks_require_created_native_calendar_projection(setup, monkeypatch):
    _config, campaign, client, _calls, _saves = setup
    adapter = medium.Adapter(campaign, client)
    rows = native_rows()
    monkeypatch.setattr(medium, '_request_rows', lambda *a: rows)
    for row in rows: row['calendar_integration_status'] = 'PENDING_CALENDAR'
    assert not all(c['passed'] for c in adapter.final_checks(case('C15'), VALUES, [{'id': 51}, {'id': 52}]))
    for row in rows:
        row.update(calendar_integration_status='CREATED', request_calendar_status='CREATED', calendar_event_id='event-'+str(row['id']))
    assert all(c['passed'] for c in adapter.final_checks(case('C15'), VALUES, [{'id': 51}, {'id': 52}]))


def test_cleanup_waits_for_calendar_outbox_and_deleted_projection_without_sleep(setup, monkeypatch):
    _config, campaign, client, _calls, _saves = setup
    adapter = medium.Adapter(campaign, client)
    adapter.current_ids.add(51)
    adapter.owned_ids.add(51)
    rows = native_rows()[:1]
    rows[0].update(status='cancelled', reservation_id=None)
    monkeypatch.setattr(medium, '_request_rows', lambda *a: rows)
    effects = [{'id': 51, 'active_count': 0, 'segment_count': 0, 'has_event': True, 'request_calendar_status': 'PENDING_CALENDAR', 'reservation_calendar_statuses': ['CREATED'], 'projection_statuses': ['DELIVERED', 'PENDING']}]
    monkeypatch.setattr(medium, '_effect_rows', lambda *a: effects)
    pauses = []
    def settled(delay):
        pauses.append(delay)
        effects[0].update(request_calendar_status='DELETED', reservation_calendar_statuses=['DELETED'], projection_statuses=['DELIVERED','DELIVERED'])
    monkeypatch.setattr(medium, '_sleep', settled)
    adapter.cleanup_case()
    assert pauses and not adapter.current_ids


def test_cleanup_failed_projection_blocks_next_case(setup, monkeypatch):
    _config, campaign, client, _calls, _saves = setup
    adapter = medium.Adapter(campaign, client)
    adapter.current_ids.add(51)
    adapter.owned_ids.add(51)
    rows = native_rows()[:1]
    rows[0].update(status='cancelled', reservation_id=None)
    monkeypatch.setattr(medium, '_request_rows', lambda *a: rows)
    monkeypatch.setattr(medium, '_effect_rows', lambda *a: [{'id':51, 'active_count':0, 'segment_count':0, 'has_event':True, 'request_calendar_status':'FAILED', 'reservation_calendar_statuses':['FAILED'], 'projection_statuses':['FAILED_REVERTED']}])
    with pytest.raises(SimulationError, match='cleanup'):
        adapter.cleanup_case()
    assert adapter.current_ids == {51}
    with pytest.raises(SimulationError): adapter.arrange(case('C07'), VALUES)


def test_selected_occupied_setup_rejects_missing_future_slots_before_paid_work(setup, monkeypatch):
    config, _campaign, _client, calls, _saves = setup
    monkeypatch.setattr(medium, '_occupied_slots', lambda *a: (_ for _ in ()).throw(SimulationError('occupied slots unavailable')))
    # Run the preflight setup validator directly: the complete selected list,
    # including its later occupied case, must be evaluated before admission.
    with pytest.raises(SimulationError, match='occupied'):
        medium._validate_selected_slots(config, [case('C07'), case('C08')])
    assert not calls


def test_c13_accepts_only_fully_qualified_exact_consolidated_visit(setup, monkeypatch):
    _config, campaign, client, _calls, _saves = setup
    adapter = medium.Adapter(campaign, client)
    row = native_rows()[0]
    row.update(service_type='medium-test-owner Oil, medium-test-owner Second', duration_minutes=90,
               booking_time=VALUES['appointment_time'], starts_at=VALUES['appointment_time'], ends_at='2026-11-09 11:30:00',
               segment_count=6, visit_group_id=None, qualified=False,
               qualified_service_names=['medium-test-owner Oil', 'medium-test-owner Second'],
               reservation_segments=['2026-11-09 10:00:00','2026-11-09 10:15:00','2026-11-09 10:30:00','2026-11-09 10:45:00','2026-11-09 11:00:00','2026-11-09 11:15:00'])
    monkeypatch.setattr(medium, '_request_rows', lambda *a: [row])
    assert all(c['passed'] for c in adapter.checks(case('C13'), VALUES, [], [{'id':51}]))
    for defect, change in [('qualification', {'qualified_service_names':['medium-test-owner Oil']}),
                           ('duration', {'duration_minutes':75}), ('segments', {'segment_count':5}),
                           ('gap', {'reservation_segments':['2026-11-09 10:00:00','2026-11-09 10:15:00','2026-11-09 10:45:00','2026-11-09 11:00:00','2026-11-09 11:15:00','2026-11-09 11:30:00']}),
                           ('window', {'ends_at':'2026-11-09 11:15:00'}), ('staff', {'staff_agent_id':12})]:
        original = deepcopy(row)
        row.update(change)
        assert not all(c['passed'] for c in adapter.checks(case('C13'), VALUES, [], [{'id':51}])), defect
        row.clear()
        row.update(original)


@pytest.mark.parametrize('when', ['2026-11-09 15:00:00', None])
def test_preflight_rejects_original_booking_date_or_undated_consolidation_target(setup, when):
    config, _campaign, _client, calls, _saves = setup
    config['variables'].update(VALUES)
    with pytest.raises(SimulationError, match='original'):
        medium._validate_original_dates(config, [case('C07'),case('C13')], [{'id':11, 'status':'pending', 'booking_time':when}])
    assert not calls


@pytest.mark.parametrize('cid', ['C14', 'C15'])
def test_split_cases_never_adopt_single_consolidated_request(setup, monkeypatch, cid):
    _config, campaign, client, _calls, _saves = setup
    adapter = medium.Adapter(campaign, client)
    row = native_rows()[0]
    row['service_type'] = 'medium-test-owner Oil, medium-test-owner Second'
    monkeypatch.setattr(medium, '_request_rows', lambda *a: [row])
    with pytest.raises(SimulationError, match='Unexpected customer/service'):
        adapter.checks(case(cid), VALUES, [], [{'id':51}])


def test_original_date_guard_excludes_verified_other_profile_with_same_phone(setup):
    config, _campaign, _client, _calls, _saves = setup
    config['variables'].update(VALUES)
    config['existing_customer_identity'] = {'id':5, 'name':'Preserved Name'}
    medium._validate_original_dates(config, [case('C13')], [{'id':17, 'customer_id':6, 'status':'pending', 'booking_time':None}])
    with pytest.raises(SimulationError, match='original'):
        medium._validate_original_dates(config, [case('C13')], [{'id':15, 'customer_id':5, 'status':'pending', 'booking_time':None}])
    with pytest.raises(SimulationError):
        medium._validate_original_dates(config, [case('C13')], [{'id':15, 'status':'pending', 'booking_time':None}])


def test_owned_outcome_cannot_use_another_profile_with_same_phone_and_name(setup, monkeypatch):
    config, campaign, client, _calls, _saves = setup
    config['existing_customer_identity'] = {'id':5, 'name':'Preserved Name'}
    row = native_rows()[0]
    row['customer_id'] = 6
    monkeypatch.setattr(medium, '_request_rows', lambda *a: [row])
    with pytest.raises(SimulationError, match='customer'):
        medium.Adapter(campaign, client).checks(case('C11'), VALUES, [], [{'id':51}])


def test_occupied_slot_rejects_past_start_before_database_or_mutation(setup, monkeypatch):
    config, _campaign, _client, calls, _saves = setup
    monkeypatch.setattr(medium, '_now', lambda _config: datetime(2026,11,10,10,tzinfo=UTC))
    monkeypatch.setattr(medium, '_slots', lambda *a: pytest.fail('past interval must fail before database observation'))
    with pytest.raises(SimulationError, match='future'):
        medium._occupied_slots(config, VALUES, 60)
    assert not calls


@pytest.mark.parametrize('change', [
    {'updated_at':'2026-10-18 11:00:00'}, {'is_booked':True}, {'reservation_status':'BLOCKED'},
    {'active_reservation':True}, {'service_request_id':77}, {'id':10}, {'staff_agent_id':12},
    {'slot_datetime':'2026-11-09 10:15:00'},
])
def test_occupied_block_rereads_exact_unchanged_slot_before_patch(setup, monkeypatch, change):
    _config, campaign, client, calls, _saves = setup
    adapter = medium.Adapter(campaign, client)
    original = {'id': 9,'staff_agent_id': 7,'slot_datetime': VALUES['appointment_time'],'is_booked': False,
                    'reservation_status': 'AVAILABLE','service_request_id': None,'updated_at': '2026-10-18 09:00:00','active_reservation': False}
    monkeypatch.setattr(medium, '_occupied_slots', lambda *a: [original])
    monkeypatch.setattr(medium, '_slots', lambda *a: [{**original, **change}])
    with pytest.raises(SimulationError):
        adapter._block(VALUES)
    assert not calls
    assert not adapter.state['blocks']


def test_partial_occupied_blocks_retain_first_owned_receipt_when_later_slot_changes(setup, monkeypatch):
    _config, campaign, _client, calls, _saves = setup
    first = {'id': 9,'staff_agent_id': 7,'slot_datetime': VALUES['appointment_time'],'is_booked': False,
                 'reservation_status': 'AVAILABLE','service_request_id': None,'updated_at': '2026-10-18 09:00:00','active_reservation': False}
    second = {**first, 'id':10, 'slot_datetime':'2026-11-09 10:15:00'}
    owned = {**first, 'is_booked':True, 'reservation_status':'BLOCKED', 'updated_at':'2026-10-18 10:00:00'}
    observations = iter([[first], [owned,second], [{**second, 'active_reservation':True}]])
    monkeypatch.setattr(medium, '_occupied_slots', lambda *a: [first,second])
    monkeypatch.setattr(medium, '_slots', lambda *a: next(observations))
    def response(request):
        calls.append(request.url.path)
        return httpx.Response(200, json={'success':True, 'id':9})
    adapter = medium.Adapter(campaign, httpx.Client(transport=httpx.MockTransport(response)))
    with pytest.raises(SimulationError, match='changed'):
        adapter._block(VALUES)
    assert calls == ['/api/v1/portal/calendar/9']
    assert len(adapter.state['blocks']) == 1
    assert adapter.state['blocks'][0]['owned'] == owned


def test_unknown_calendar_patch_retains_unresolved_owned_intent_and_blocks_next_case(setup, monkeypatch):
    _config, campaign, _client, _calls, _saves = setup
    original = {'id': 9,'staff_agent_id': 7,'slot_datetime': VALUES['appointment_time'],'is_booked': False,
                    'reservation_status': 'AVAILABLE','service_request_id': None,'updated_at': '2026-10-18 09:00:00','active_reservation': False}
    monkeypatch.setattr(medium, '_occupied_slots', lambda *a: [original])
    monkeypatch.setattr(medium, '_slots', lambda *a: [original])
    def unknown(request):
        raise httpx.ReadTimeout('captured unknown mutation', request=request)
    adapter = medium.Adapter(campaign, httpx.Client(transport=httpx.MockTransport(unknown)))
    with pytest.raises(SimulationError, match='unknown'):
        adapter._block(VALUES)
    assert adapter.state['blocked']
    assert adapter.state['operations'][-1]['status'] == 'unknown'
    assert adapter.state['blocks'][0]['owned'] is None
    with pytest.raises(SimulationError):
        adapter.arrange(case('C07'), VALUES)


def test_browser_error_evidence_reports_sanitized_stage_without_private_exception(setup, monkeypatch):
    import playwright.sync_api
    _config, campaign, client, _calls, _saves = setup
    def failed_driver():
        raise RuntimeError('sensitive customer or credential must not escape')
    monkeypatch.setattr(playwright.sync_api, 'sync_playwright', failed_driver)
    checks = medium.Adapter(campaign, client)._browser_checks(case('C07'), [])
    assert checks == [{'name':'reloaded browser owned scope', 'passed':False,
                       'observed':{'stage':'playwright_start', 'error_type':'RuntimeError', 'reason':'browser_failure'}}]
