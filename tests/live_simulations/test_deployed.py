"""Deployed smoke contracts: no real providers or deployment writes."""
import copy
import json
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest

from live_simulations import workflow
from live_simulations.core import SimulationError


def config():
    return {'schema_version': 1, 'environment': 'simulation', 'target': 'deployed',
            'deployed_url': 'https://app.example', 'agent_id': 'reference',
            'app_port': 8011, 'gateway_port': 8010,
            'variables': {'customer_name': 'Synthetic', 'customer_phone': '4242704893',
                          'customer_email': 'simulation@example.test'},
            'email_receiver': 'test@example.com', 'allowlisted_emails': ['test@example.com'],
            'allowlisted_phone_numbers': ['+14242704893'], 'whatsapp_ready': True,
            'budget': {'monthly_credits': 100000, 'remaining_credits': 90000,
                       'verified_credit_units': True, 'case_upper_estimate': 1}}


@pytest.mark.parametrize('tier,count', [('minimal', 6), ('medium', 16), ('full', 50)])
def test_deployed_preview_routes_without_local_runtime(monkeypatch, tier, count):
    monkeypatch.setattr(workflow.Runtime, 'prepare', lambda c: pytest.fail('local runtime created'))
    value = workflow.execute(config(), tier)
    assert value['target'] == 'deployed'
    assert len(value['selected']) == count
    assert value['acceptance_scope'] == 'conversation_and_api_smoke'
    if tier != 'minimal':
        assert value['unsupported_cases']


@pytest.mark.parametrize('url', ['http://app.example', 'https://app.example/path',
                                'https://user:pass@app.example', 'https://app.example?x=1',
                                'https://app.example/#x', 'https://app.example:bad'])
def test_deployed_origin_rejects_ambiguous_destinations(url):
    from live_simulations.deployed import origin
    with pytest.raises(SimulationError): origin(url)


def test_tool_override_is_native_and_does_not_mutate_reference():
    from live_simulations.deployed import native_override
    agent = {'conversation_config': {'agent': {'prompt': {'tools': [
        {'type': 'webhook', 'name': 'book', 'api_schema': {
            'url': 'https://app.example/api/v1/voice/tools?name=book',
            'request_headers': {'Existing': 'value'}}}]}}}, 'platform_settings': {}}
    before = copy.deepcopy(agent)
    result = native_override(agent, 'https://app.example', 'webhook')
    tool = result['conversation_config']['agent']['prompt']['tools'][0]
    assert tool['api_schema']['request_headers']['Existing'] == 'value'
    assert tool['api_schema']['request_headers']['X-Caller-ID'] == '{{caller_phone}}'
    assert 'X-Live-Simulation-Token' not in tool['api_schema']['request_headers']
    assert agent == before
    agent['conversation_config']['agent']['prompt']['tools'][0]['api_schema']['url'] = 'https://other.example/api/v1/voice/tools'
    with pytest.raises(SimulationError, match='destination'): native_override(agent, 'https://app.example', 'webhook')


def test_provider_materialized_text_default_matches_but_material_change_fails():
    from live_simulations.core import fingerprint
    from live_simulations.deployed import native_override
    reference = {'conversation_config': {'agent': {'text_behavior_overrides': None, 'prompt': {'tools': [
        {'type': 'webhook', 'name': 'book', 'api_schema': {
            'url': 'https://app.example/api/v1/voice/tools?name=book'}}]}}}}
    created = copy.deepcopy(reference)
    created['conversation_config']['agent']['text_behavior_overrides'] = {'whatsapp': {
        'verbosity': None, 'output_format': None, 'interaction_budget': None, 'disable_max_duration': True}}
    expected = native_override(reference, 'https://app.example', 'hook')
    assert fingerprint(expected) == fingerprint(native_override(created, 'https://app.example', 'hook'))
    assert reference['conversation_config']['agent']['text_behavior_overrides'] is None
    created['conversation_config']['agent']['text_behavior_overrides']['whatsapp']['disable_max_duration'] = False
    assert fingerprint(expected) != fingerprint(native_override(created, 'https://app.example', 'hook'))


def test_lifecycle_requires_same_booking_for_move_and_preserves_baseline():
    from live_simulations.deployed import lifecycle_checks
    values = {'customer_phone': '4242704893', 'new_time': '2026-11-02 10:00:00'}
    before = [{'id': 8, 'booking_type': 'appointment', 'status': 'pending',
               'booking_time': '2026-11-01 10:00:00'}]
    after = [{'id': 9, 'booking_type': 'appointment', 'status': 'pending',
              'booking_time': values['new_time']}]
    checks = lifecycle_checks('C02', values, before, after)
    assert any(not c['passed'] and 'identity' in c['name'] for c in checks)
    after[0]['id'] = 8
    assert all(c['passed'] for c in lifecycle_checks('C02', values, before, after))


def test_cancel_does_not_pass_for_missing_record():
    from live_simulations.deployed import lifecycle_checks
    checks = lifecycle_checks('C03', {}, [{'id': 8}], [])
    assert any(not c['passed'] for c in checks)


@pytest.mark.parametrize('case_id,field,kind', [('C02', 'new_time', 'appointment'),
                                             ('C05', 'new_callback_time', 'callback')])
@pytest.mark.parametrize('observed', ['2026-11-02 10:00:00', '2026-11-02T15:00:00+00:00'])
def test_lifecycle_reschedule_requires_actual_time_change(case_id, field, kind, observed):
    from live_simulations.deployed import lifecycle_checks
    row = {'id': 8, 'booking_type': kind, 'status': 'pending',
           'booking_time': observed}
    checks = lifecycle_checks(case_id, {field: '2026-11-02 10:00:00'}, [row], [row.copy()])
    assert any(not c['passed'] and 'changed' in c['name'] for c in checks)


@pytest.mark.parametrize('observed', ['2026-11-02T10:00:00.000000',
                                    '2026-11-02T15:00:00+00:00',
                                    '2026-11-02T10:00:00-05:00'])
def test_lifecycle_accepts_equivalent_iso_booking_times(observed):
    from live_simulations.deployed import lifecycle_checks
    row = {'id': 8, 'booking_type': 'appointment', 'status': 'pending', 'booking_time': observed}
    checks = lifecycle_checks('C01', {'appointment_time': '2026-11-02 10:00:00'}, [], [row])
    assert all(c['passed'] for c in checks)
    assert all('confirmed' not in c['name'] for c in checks)


def test_lifecycle_uses_explicit_business_timezone_and_rejects_bad_times():
    from live_simulations.deployed import lifecycle_checks
    row = {'id': 8, 'booking_type': 'callback', 'status': 'pending',
           'booking_time': '2026-11-02T18:00:00Z'}
    values = {'callback_time': '2026-11-02 10:00:00'}
    assert all(c['passed'] for c in lifecycle_checks('C04', values, [], [row], 'America/Los_Angeles'))
    for bad in ('bad-time', None, '2026-11-02T18:00:00.000001Z'):
        row['booking_time'] = bad
        assert any(not c['passed'] for c in lifecycle_checks('C04', values, [], [row], 'America/Los_Angeles'))


def test_readiness_collects_mismatched_receivers_and_does_not_write():
    from live_simulations.deployed import deployment_readiness
    requests = []
    def handle(request):
        requests.append(request)
        data = {'/health': {'status': 'healthy'},
                '/api/v1/portal/secrets': {'elevenlabs_agent': {'display_value': 'reference'}},
                '/api/v1/portal/gmail-config': {'gmail_enabled': True,
                    'gmail_sender': 'test@example.com', 'gmail_recipient': 'other@example.com'},
                '/api/v1/portal/agents': [{'id': 7, 'email': 'other@example.com',
                                         'phone_number': '+14242704893'}],
                '/api/v1/portal/service-requests': []}
        return httpx.Response(200, json=data[request.url.path])
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        problems, baseline = deployment_readiness(config(), client)
    assert len(problems) >= 2
    assert baseline == []
    assert all(r.method == 'GET' for r in requests)


@pytest.mark.parametrize('preserve', [False, True])
def test_existing_active_customer_booking_requires_explicit_preservation(preserve):
    from live_simulations.deployed import deployment_readiness
    def handle(request):
        data = {'/health': {'status': 'healthy'},
                '/api/v1/portal/secrets': {'elevenlabs_agent': {'display_value': 'reference'}},
                '/api/v1/portal/gmail-config': {'gmail_enabled': True,
                    'gmail_sender': 'test@example.com', 'gmail_recipient': 'test@example.com'},
                '/api/v1/portal/agents': [{'id': 7, 'email': 'test@example.com',
                                         'phone_number': '+14242704893'}],
                '/api/v1/portal/service-requests': [{'id': 3, 'phone': '4242704893', 'status': 'pending'}]}
        return httpx.Response(200, json=data[request.url.path])
    c = config()
    c['preserve_existing_bookings'] = preserve
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        problems, baseline = deployment_readiness(c, client)
    assert any('active booking' in p for p in problems) is (not preserve)
    assert baseline == [{'id': 3, 'phone': '4242704893', 'status': 'pending'}]


@pytest.mark.parametrize('active,status,expected_problem', [
    ('reference', 200, False), ('different', 200, True),
    ('', 200, True), (None, 200, True), ('reference', 503, True)])
def test_readiness_requires_actual_active_deployed_reference(active, status, expected_problem):
    from live_simulations.deployed import deployment_readiness
    seen = []
    def handle(request):
        seen.append(request)
        if request.url.path.endswith('/secrets'):
            return httpx.Response(status, json={'elevenlabs_agent': {'display_value': active},
                'elevenlabs_key': {'masked': 'must-not-appear-in-report'}})
        data = {'/health': {'status': 'healthy'},
                '/api/v1/portal/gmail-config': {'gmail_enabled': True,
                    'gmail_sender': 'test@example.com', 'gmail_recipient': 'test@example.com'},
                '/api/v1/portal/agents': [{'id': 7, 'email': 'test@example.com', 'phone_number': '+14242704893'}],
                '/api/v1/portal/service-requests': []}
        return httpx.Response(200, json=data[request.url.path])
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        problems, _ = deployment_readiness(config(), client)
    assert bool(problems) is expected_problem
    assert any(r.url.path.endswith('/secrets') for r in seen)
    assert all(r.method == 'GET' for r in seen)
    assert 'must-not-appear' not in str(problems)


def calibration_config():
    c = config()
    c['budget']['verified_credit_units'] = False
    c['calibration'] = {'credit_ceiling': 1500, 'case_upper_estimate': 1008,
                        'source_run_id': 'previous-calibration'}
    return c


def test_single_case_calibration_is_separate_from_tier_budget():
    c = calibration_config()
    value = workflow.execute(c, requested=['C01'])
    assert value['status'] == 'planned'
    assert value['calibration'] is True
    assert value['complete_tier'] is False
    assert value['tier_cap'] == '1500'
    assert value['estimated_credits'] == '1008'
    assert value['calibration_source_run_id'] == 'previous-calibration'
    c.pop('calibration')
    assert workflow.execute(c, requested=['C01'])['status'] == 'budget_unverified'


@pytest.mark.parametrize('requested,tier,repeat', [(None, 'minimal', 1),
    (['C01', 'C04'], 'minimal', 1), (['C02'], 'minimal', 1),
    (['C01'], 'medium', 1), (['C01'], 'minimal', 2)])
def test_calibration_rejects_larger_or_dependent_selection(requested, tier, repeat):
    with pytest.raises(SimulationError, match='calibration'):
        workflow.execute(calibration_config(), tier, requested=requested, repeat=repeat)


@pytest.mark.parametrize('field,value', [('credit_ceiling', 0),
    ('case_upper_estimate', -1), ('credit_ceiling', 'NaN'), ('source_run_id', '')])
def test_calibration_rejects_invalid_budget_and_provenance(field, value):
    c = calibration_config()
    c['calibration'][field] = value
    with pytest.raises(SimulationError):
        workflow.execute(c, requested=['C01'])


def test_calibration_reserves_twenty_percent_and_checks_estimated_cost():
    c = calibration_config()
    c['calibration']['case_upper_estimate'] = 1201
    assert workflow.execute(c, requested=['C01'])['status'] == 'over_budget'


def test_check_never_creates_provider_resources(monkeypatch):
    from live_simulations import deployed
    c = config()
    monkeypatch.setattr(deployed, 'deployment_readiness', lambda *a: ([], []))
    monkeypatch.setattr(deployed, 'provider_readiness', lambda *a: ({}, ['missing provider binding']))
    value = deployed.execute(c, 'minimal', check=True)
    assert value['status'] == 'blocked'
    assert value['problems'] == ['missing provider binding']


def test_missing_budget_blocks_live_before_network_or_artifacts(monkeypatch, tmp_path):
    from live_simulations import deployed
    c = config()
    c['budget']['verified_credit_units'] = False
    c['artifact_root'] = str(tmp_path / 'runs')
    monkeypatch.setattr(deployed, 'deployment_readiness', lambda *a: pytest.fail('network'))
    with pytest.raises(SimulationError, match='budget_unverified'):
        deployed.execute(c, 'minimal', live=True)
    assert not (tmp_path / 'runs').exists()


def test_missing_evidence_never_becomes_tier_acceptance():
    from live_simulations.deployed import result_status
    assert result_status([{'passed': True}], provider_passed=True) == 'incomplete'
    assert result_status([{'passed': False}], provider_passed=True) == 'failed'
    assert result_status([{'passed': True}], provider_passed=False) == 'failed'


def test_deployed_quote_criterion_uses_live_catalog_and_preserves_other_criteria():
    from live_simulations.core import load_catalog
    from live_simulations.deployed import deployed_scenario
    case = load_catalog()[0]
    original = copy.deepcopy(case)
    rendered = deployed_scenario(case, {'appointment_time': '2026-11-02 10:00:00',
        'customer_name': 'Synthetic', 'customer_phone': '4242704893'})
    assert rendered['success_conditions'][:-1] == original['success_conditions'][:-1]
    criterion = rendered['success_conditions'][-1]
    assert 'retrieve' in criterion and 'deployed' in criterion
    assert 'returned price range and duration' in criterion
    assert '$80' not in criterion and '$120' not in criterion
    assert case == original


def test_live_workflow_dispatches_deployed_without_isolated_setup(monkeypatch):
    from live_simulations import deployed
    seen = []
    monkeypatch.setattr(deployed, 'execute', lambda c, tier, **kw: seen.append((tier, kw)) or {'status': 'incomplete'})
    monkeypatch.setattr(workflow.Runtime, 'prepare', lambda c: pytest.fail('local setup'))
    workflow.execute(config(), 'minimal', live=True)
    assert seen[0][0] == 'minimal'
    assert seen[0][1]['live'] is True


def test_ambiguous_paid_submission_is_retained_and_never_retried(monkeypatch, tmp_path):
    from decimal import Decimal

    from live_simulations import deployed
    c = config()
    c.update(artifact_root=str(tmp_path), evidence_timeout_seconds=1)
    c['budget']['reset_unix'] = 123
    calls = []
    agent = {'conversation_config': {'agent': {'prompt': {'tools': [
        {'type': 'webhook', 'name': 'book', 'api_schema': {
            'url': 'https://app.example/api/v1/voice/tools?name=book'}}]}}}}
    override = deployed.native_override(agent, c['deployed_url'], 'hook')
    provider = SimpleNamespace(
        create_agent=lambda *a: 'clone',
        agent=lambda *a: {**override}, resolve_reference=lambda a: a,
        create=lambda *a: 'owned-test')
    def run(*args):
        calls.append('paid')
        raise SimulationError('ambiguous provider write')
    provider.run = run
    monkeypatch.setattr(deployed, 'deployment_readiness', lambda *a: ([], []))
    monkeypatch.setattr(deployed, 'provider_readiness', lambda *a: (
        {'provider': provider, 'remaining': Decimal(90000), 'override': override, 'webhook_id': 'hook'}, []))
    monkeypatch.setattr(deployed, 'current_remaining', lambda *a: Decimal(90000))
    monkeypatch.setattr(deployed, 'get', lambda *a: [])
    result = deployed.execute(c, 'minimal', live=True, requested=['C02'])
    assert calls == ['paid']
    assert result['unsettled_usage'] is True
    assert result['results'][1]['reason'] == 'Failed or blocked lifecycle prerequisite'
    ledger = json.loads((tmp_path / 'usage-ledger.json').read_text())
    assert ledger['entries'][0]['unsettled'] is True
    assert (tmp_path / result['run_id'] / 'report.md').exists()
    with pytest.raises(SimulationError, match='Unsettled'):
        deployed.execute(c, 'minimal', live=True, requested=['C01'])
    assert calls == ['paid']


def test_unsupported_fixtures_block_entire_selection_without_creating_artifacts(monkeypatch, tmp_path):
    from live_simulations import deployed
    c = config()
    c['artifact_root'] = str(tmp_path / 'runs')
    monkeypatch.setattr(deployed, 'deployment_readiness', lambda *a: ([], []))
    monkeypatch.setattr(deployed, 'provider_readiness', lambda *a: ({}, []))
    with pytest.raises(SimulationError, match='Isolated fixtures'):
        deployed.execute(c, 'medium', live=True)
    assert not (tmp_path / 'runs').exists()


def test_deployed_check_cli_uses_deployed_default_config_and_exposes_problems(monkeypatch, capsys):
    from live_simulations import __main__ as cli
    seen = []
    monkeypatch.setattr(cli, 'load_config', lambda p: seen.append(p) or config())
    monkeypatch.setattr(workflow, 'execute', lambda *a, **kw: {'status': 'blocked', 'problems': ['receiver mismatch']})
    assert cli.main(['workflow', '--target', 'deployed', '--check']) == 2
    assert seen == ['scratch/live-simulations.deployed.json']
    assert 'receiver mismatch' in capsys.readouterr().out


@pytest.mark.parametrize('mode', ['empty', 'preserve', 'mutated', 'name_mutated', 'calibration', 'over_budget',
                                  'authorized', 'authorized_unknown', 'authorized_overspend', 'authorized_continuation', 'authorized_recovery', 'authorized_seed'])
def test_minimal_native_campaign_runs_six_lifecycle_cases_without_local_services(monkeypatch, tmp_path, mode):
    from decimal import Decimal

    from live_simulations import deployed
    c = config()
    if mode in ('calibration', 'over_budget'):
        c = calibration_config()
    if mode.startswith('authorized'):
        c['campaign_authorization'] = {'authorization_id': 'approved-six-case', 'credit_ceiling': 8160}
        c['budget'].update(monthly_credits=45676, case_upper_estimate=1088)
    original_manifest = None
    if mode in ('authorized_continuation', 'authorized_recovery', 'authorized_seed'):
        c, _, seed_row = (seeded_recovery_config(tmp_path) if mode == 'authorized_seed'
                         else recovery_config(tmp_path) if mode == 'authorized_recovery' else continuation_config(tmp_path))
        ancestor_path = tmp_path / c['campaign_authorization']['continuation_of'] / 'manifest.json'
        original_manifest = ancestor_path.read_bytes()
    if mode != 'empty':
        c['preserve_existing_bookings'] = True
    c.update(artifact_root=str(tmp_path), evidence_timeout_seconds=1)
    c['budget']['reset_unix'] = 123
    values = {'customer_name': 'Synthetic', 'customer_phone': '4242704893',
              'customer_email': 'simulation@example.test',
              'appointment_time': '2026-11-02 10:00:00', 'new_time': '2026-11-03 10:00:00',
              'callback_time': '2026-11-02 14:00:00', 'new_callback_time': '2026-11-03 14:00:00',
              'business_timezone': 'America/New_York'}
    if mode == 'authorized_seed':
        values.update(customer_phone=c['variables']['customer_phone'], new_time=c['variables']['new_time'])
    baseline = [] if mode == 'empty' else [{'id': 99, 'phone': values['customer_phone'],
        'customer_name': 'Existing Customer',
        'status': 'confirmed', 'booking_type': 'appointment', 'booking_time': '2026-11-05 10:00:00'}]
    if mode == 'authorized_seed':
        baseline.append(seed_row.copy())
    rows, submitted, state = copy.deepcopy(baseline), [], {}
    agent = {'conversation_config': {'agent': {'prompt': {'tools': [
        {'type': 'webhook', 'name': 'book', 'api_schema': {
            'url': 'https://app.example/api/v1/voice/tools?name=book'}}]}}}}
    override = deployed.native_override(agent, c['deployed_url'], 'hook')
    def create(case, *args):
        state['case'] = case['id']
        state['intake_name'] = args[1]['customer_name']
        if baseline:
            assert args[1]['customer_name'] == 'Existing Customer'
            assert 'Existing Customer' in case['scenario']
        else:
            assert args[1]['customer_name'] == values['customer_name'] + ' ' + args[0][:8]
        if mode in ('calibration', 'over_budget'):
            assert case['max_turns'] <= 8
        else:
            assert case['max_turns'] == 12
        if baseline:
            assert '2026-11-05' in args[1]['recent_booking_context']
        return 'test-' + case['id']
    def run(*args):
        assert args == ('clone', 'test-' + state['case'])
        submitted.append(state['case'])
        return {'id': 'invocation-' + state['case']}
    def wait(*args):
        case_id = state['case']
        # Native intake updates customers.name; portal joins show it on old rows.
        for row in rows:
            row['customer_name'] = state['intake_name']
        if mode == 'mutated':
            rows[0]['status'] = 'cancelled'
        if mode == 'name_mutated':
            rows[0]['customer_name'] = 'Unexpected Rename'
        if case_id in ('C01', 'C04'):
            field, kind = ('appointment_time', 'appointment') if case_id == 'C01' else ('callback_time', 'callback')
            rows.append({'id': len(rows) + 1, 'phone': values['customer_phone'], 'booking_type': kind,
                         'booking_time': values[field], 'status': 'pending'})
        elif case_id in ('C02', 'C05'):
            rows[-1]['booking_time'] = values['new_time' if case_id == 'C02' else 'new_callback_time']
        else:
            rows[-1]['status'] = 'cancelled'
        return {'test_runs': [{'status': 'passed', 'credits_used': 1}]}
    provider = SimpleNamespace(create_agent=lambda *a: 'clone', agent=lambda *a: override,
        resolve_reference=lambda a: a, create=create, run=run, wait=wait,
        credits=lambda r: None if mode == 'authorized_unknown' else Decimal(
            9000 if mode == 'authorized_overspend' else 1600 if mode == 'over_budget' else 1))
    monkeypatch.setattr(deployed, 'deployment_readiness', lambda *a: ([], copy.deepcopy(baseline)))
    monkeypatch.setattr(deployed, 'provider_readiness', lambda *a: (
        {'provider': provider, 'remaining': Decimal(90000), 'override': override, 'webhook_id': 'hook'}, []))
    monkeypatch.setattr(deployed, 'current_remaining', lambda *a: Decimal(90000))
    monkeypatch.setattr(deployed.fixtures, 'variables', lambda *a: values.copy())
    monkeypatch.setattr(deployed, 'get', lambda *a: copy.deepcopy(rows))
    result = deployed.execute(c, 'minimal', live=True,
        requested=['C01'] if mode in ('calibration', 'over_budget') else None)
    assert result['reference_agent_id'] == c['agent_id']
    if mode in ('authorized_unknown', 'authorized_overspend'):
        assert submitted == ['C01']
        assert result['results'][0]['functional_status'] == 'failed'
        assert result['campaign_authorization'] == c['campaign_authorization']
        ledger = json.loads((tmp_path / 'usage-ledger.json').read_text())
        assert len(ledger['entries']) == 1
        assert ledger['entries'][0]['authorization_id'] == 'approved-six-case'
        assert ledger['entries'][0]['unsettled'] is (mode == 'authorized_unknown')
        assert result['spent_credits'] == ('0' if mode == 'authorized_unknown' else '9000')
        return
    if mode in ('mutated', 'name_mutated'):
        assert submitted == ['C01']
        assert result['results'][0]['functional_status'] == 'failed'
        assert result['status'] == 'failed'
        return
    if mode in ('calibration', 'over_budget'):
        assert submitted == ['C01']
        assert result['calibration']['credit_ceiling'] == 1500
        assert result['complete_tier'] is False
        assert result['results'][0]['functional_status'] == ('failed' if mode == 'over_budget' else 'passed')
        assert result['status'] == ('failed' if mode == 'over_budget' else 'incomplete')
        assert result['baseline'] == baseline
        return
    expected_cases = (['C02', 'C03'] if mode == 'authorized_seed' else ['C01', 'C02', 'C03']
                      if mode == 'authorized_recovery' else ['C01', 'C02', 'C03', 'C04', 'C05', 'C06'])
    assert submitted == expected_cases
    assert all(r['functional_status'] == 'passed' for r in result['results'])
    assert result['status'] == 'incomplete'
    assert result['spent_credits'] == str(len(expected_cases))
    assert result['unsettled_usage'] is False
    assert all(r['status'] == 'cancelled' for r in rows if r['id'] != 99)
    assert rows[:1] == baseline[:1] if mode == 'authorized_seed' else rows[:len(baseline)] == baseline
    if mode == 'authorized_seed':
        assert [row['id'] for row in result['baseline']] == [99]
        assert result['owned_recovery']['source_row'] == seed_row
        assert result['recovery_source_baseline'] == baseline
        assert len(rows) == 2  # No C01 replay and no new booking.
    if mode in ('authorized', 'authorized_continuation', 'authorized_recovery', 'authorized_seed'):
        assert result['campaign_authorization'] == c['campaign_authorization']
        ledger = json.loads((tmp_path / 'usage-ledger.json').read_text())
        current_charges = [e for e in ledger['entries'] if e['run_id'] == result['run_id']]
        assert len(current_charges) == len(expected_cases)
        assert all(e['authorization_id'] == c['campaign_authorization']['authorization_id'] and not e['unsettled'] for e in current_charges)
        if original_manifest is not None:
            assert ancestor_path.read_bytes() == original_manifest
            assert result['prior_spent_credits'] == '634'
            assert result['aggregate_spent_credits'] == str(634 + len(expected_cases))
            assert result['complete_tier'] is (mode not in ('authorized_recovery', 'authorized_seed'))
            assert all(e['continuation_ancestors'] == ['a' * 32] for e in current_charges)
        provider.create_agent = lambda *a: pytest.fail('Authorization reuse created a clone')
        provider.create = lambda *a: pytest.fail('Authorization reuse created a test')
        with pytest.raises(SimulationError, match='authorization.*used|continuation'):
            deployed.execute(c, 'minimal', live=True)


def test_deployed_cleanup_rejects_unknown_resource_creation_and_preserves_manifest(tmp_path):
    from live_simulations.deployed import Campaign, manage
    c = config()
    c['artifact_root'] = str(tmp_path)
    campaign = Campaign(c, 'minimal', ['C01'])
    campaign.manifest.update(attempted=True, agent_create_pending=True)
    campaign.save()
    with pytest.raises(SimulationError, match='Ambiguous resource'):
        manage(c, campaign.run_id, 'cleanup', live=True)
    assert (campaign.folder / 'manifest.json').exists()


def authorized_config():
    c = config()
    c['campaign_authorization'] = {'authorization_id': 'approved-six-case', 'credit_ceiling': 8160}
    c['budget'].update(monthly_credits=45676, case_upper_estimate=1088)
    return c


@pytest.mark.parametrize('verified,ceiling,status', [(True, 8160, 'planned'),
                                                    (False, 8160, 'budget_unverified'),
                                                    (True, 8159, 'over_budget')])
def test_campaign_authorization_preview_preserves_reserve_and_verified_units(verified, ceiling, status):
    from live_simulations import deployed
    c = authorized_config()
    c['budget']['verified_credit_units'] = verified
    c['campaign_authorization']['credit_ceiling'] = ceiling
    result = deployed.execute(c)
    assert result['selected'] == [f'C{i:02}' for i in range(1, 7)]
    assert result['complete_tier'] is True
    assert result['status'] == status
    if verified:
        assert result['estimated_credits'] == '6528'
        assert result['tier_cap'] == str(ceiling)
        assert result['admission_limit'] == str(ceiling * Decimal('.8'))


@pytest.mark.parametrize('tier,requested,repeat,calibration', [
    ('medium', None, 1, False), ('full', None, 1, False),
    ('minimal', ['C01'], 1, False), ('minimal', [], 1, False),
    ('minimal', None, 2, False), ('minimal', None, 1, True)])
def test_campaign_authorization_rejects_other_scope_before_provider(monkeypatch, tier, requested, repeat, calibration):
    from live_simulations import deployed
    c = authorized_config()
    if calibration:
        c['calibration'] = calibration_config()['calibration']
    monkeypatch.setattr(deployed, 'provider_readiness', lambda *a: pytest.fail('Provider reached'))
    with pytest.raises(SimulationError, match='authorization'):
        deployed.execute(c, tier, live=True, requested=requested, repeat=repeat)


@pytest.mark.parametrize('authorization', [False, {}, {'authorization_id': ' ', 'credit_ceiling': 8160},
    {'authorization_id': 9, 'credit_ceiling': 8160}, {'authorization_id': 'id', 'credit_ceiling': 0},
    {'authorization_id': 'id', 'credit_ceiling': 'NaN'}])
def test_campaign_authorization_requires_explicit_identity_and_positive_ceiling(authorization):
    from live_simulations import deployed
    c = authorized_config()
    c['campaign_authorization'] = authorization
    with pytest.raises(SimulationError):
        deployed.execute(c)


def test_campaign_authorization_cannot_bypass_unverified_units_or_headroom(monkeypatch):
    from live_simulations import deployed
    c = authorized_config()
    c['budget']['remaining_credits'] = 6527
    assert deployed.execute(c)['status'] == 'over_budget'
    c['budget']['verified_credit_units'] = False
    monkeypatch.setattr(deployed, 'provider_readiness', lambda *a: pytest.fail('Unverified live campaign reached provider'))
    with pytest.raises(SimulationError, match='budget_unverified'):
        deployed.execute(c, live=True)


@pytest.mark.parametrize('names', [[None], [''], ['   '], ['Existing Customer', None],
                                   ['Existing Customer', 'Other Customer']])
def test_preserved_customer_requires_single_nonblank_baseline_name_before_resource_creation(monkeypatch, tmp_path, names):
    from live_simulations import deployed
    c = config()
    c.update(preserve_existing_bookings=True, artifact_root=str(tmp_path))
    baseline = [{'id': index, 'customer_name': name} for index, name in enumerate(names)]
    monkeypatch.setattr(deployed, 'deployment_readiness', lambda *a: ([], baseline))
    provider = SimpleNamespace(create_agent=lambda *a: pytest.fail('Invalid baseline created a provider resource'))
    monkeypatch.setattr(deployed, 'provider_readiness', lambda *a: ({'provider': provider, 'remaining': 90000, 'override': {}}, []))
    with pytest.raises(SimulationError, match='customer name'):
        deployed.execute(c, live=True)
    checked = deployed.execute(c, check=True)
    assert checked['status'] == 'blocked'
    assert any('customer name' in problem for problem in checked['problems'])


@pytest.mark.parametrize('names,blocked', [(['Existing Customer', 'Existing Customer'], False),
                                         (['Existing Customer', 'Other Customer'], True), ([None], True)])
def test_readiness_checks_preserved_customer_identity(monkeypatch, names, blocked):
    from live_simulations import deployed
    c = config()
    c['preserve_existing_bookings'] = True
    baseline = [{'id': index, 'customer_name': name, 'phone': c['variables']['customer_phone'], 'status': 'pending'}
                for index, name in enumerate(names)]
    data = {'/health': {'status': 'healthy'},
            '/api/v1/portal/secrets': {'elevenlabs_agent': {'display_value': 'reference'}},
            '/api/v1/portal/gmail-config': {'gmail_enabled': True, 'gmail_sender': 'test@example.com', 'gmail_recipient': 'test@example.com'},
            '/api/v1/portal/agents': [{'id': 7, 'email': 'test@example.com', 'phone_number': c['variables']['customer_phone']}],
            '/api/v1/portal/service-requests': baseline}
    monkeypatch.setattr(deployed, 'get', lambda _client, _url, path: data[path])
    problems, observed = deployed.deployment_readiness(c, object())
    assert observed == baseline
    assert bool(problems) is blocked
    if blocked:
        assert all('customer name' in problem for problem in problems)


@pytest.mark.parametrize('customer_id,name,verified', [(7, 'Existing Customer', True),
    (8, 'Existing Customer', True), (7, 'Other Customer', True), (7, 'Existing Customer', False)])
def test_explicit_customer_binding_requires_fresh_exact_native_identity(customer_id, name, verified):
    from live_simulations import deployed
    c = config()
    c.update(preserve_existing_bookings=True, existing_customer_identity={'id': 7, 'name': 'Existing Customer'})
    baseline = [{'customer_name': 'Existing Customer'}, {'customer_name': 'Another Profile'}]
    calls = []
    def respond(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={'result': {'success': True, 'read_only': True,
            'is_existing_customer': True, 'is_verified_existing_customer': verified,
            'customer_id': customer_id, 'customer_name': name}})
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        if (customer_id, name, verified) == (7, 'Existing Customer', True):
            assert deployed.preserved_customer_name(c, baseline, client) == 'Existing Customer'
        else:
            with pytest.raises(SimulationError, match='identity'):
                deployed.preserved_customer_name(c, baseline, client)
    assert calls == [{'name': 'verify_caller_identity', 'arguments': {
        'phone': c['variables']['customer_phone'], 'claimed_name': 'Existing Customer', 'read_only': True}}]


def continuation_config(tmp_path):
    c = authorized_config()
    c['artifact_root'] = str(tmp_path)
    parent = 'a' * 32
    c['campaign_authorization'].update(authorization_id='new-approved-continuation', continuation_of=parent)
    c['budget']['case_estimates'] = {f'C{i:02}': 1088 if i == 1 else 900 for i in range(1, 7)}
    manifest = {'run_id': parent, 'target': 'deployed', 'deployed_url': c['deployed_url'],
        'status': 'failed', 'results': [{'case_id': 'C01', 'status': 'failed'}],
        'invocations': ['old-invoke'], 'spent_credits': '634', 'unsettled_usage': False,
        'campaign_authorization': {'authorization_id': 'old-approved', 'credit_ceiling': 8160}}
    (tmp_path / parent).mkdir()
    (tmp_path / parent / 'manifest.json').write_text(json.dumps(manifest))
    ledger = {'entries': [{'run_id': parent, 'authorization_id': 'old-approved',
        'invocation_id': 'old-invoke', 'credits': '634', 'unsettled': False}]}
    (tmp_path / 'usage-ledger.json').write_text(json.dumps(ledger))
    return c, manifest, ledger


def test_continuation_preview_counts_prior_spend_and_preserves_reserve(tmp_path):
    from live_simulations import deployed
    c, _, _ = continuation_config(tmp_path)
    result = deployed.execute(c)
    assert result['status'] == 'planned'
    assert result['prior_spent_credits'] == '634'
    assert result['estimated_credits'] == '5588'
    assert result['aggregate_estimated_credits'] == '6222'
    c['budget'].pop('case_estimates')
    assert deployed.execute(c)['status'] == 'over_budget'


@pytest.mark.parametrize('problem', ['missing', 'cycle', 'running', 'pending', 'unsettled',
    'spend', 'authorization', 'target', 'cap', 'fork', 'invocation'])
def test_continuation_rejects_unverifiable_or_reused_history(tmp_path, problem):
    from live_simulations import deployed
    c, manifest, ledger = continuation_config(tmp_path)
    parent = c['campaign_authorization']['continuation_of']
    if problem == 'missing':
        (tmp_path / parent / 'manifest.json').unlink()
    elif problem == 'cycle': manifest['campaign_authorization']['continuation_of'] = parent
    elif problem == 'running': manifest['status'] = 'running'
    elif problem == 'pending': manifest['agent_create_pending'] = True
    elif problem == 'unsettled': ledger['entries'][0]['unsettled'] = True
    elif problem == 'spend': manifest['spent_credits'] = '633'
    elif problem == 'authorization': ledger['entries'][0]['authorization_id'] = 'wrong'
    elif problem == 'target': manifest['deployed_url'] = 'https://other.example'
    elif problem == 'cap': manifest['campaign_authorization']['credit_ceiling'] = 9000
    elif problem == 'invocation': manifest['invocations'] = ['other-invoke']
    elif problem == 'fork': ledger['entries'].append({'run_id': 'b' * 32, 'continuation_ancestors': [parent], 'credits': '1', 'unsettled': False})
    if problem != 'missing': (tmp_path / parent / 'manifest.json').write_text(json.dumps(manifest))
    (tmp_path / 'usage-ledger.json').write_text(json.dumps(ledger))
    with pytest.raises(SimulationError, match='continuation'):
        deployed.execute(c)


def test_continuation_revalidates_history_under_lock_before_provider_writes(monkeypatch, tmp_path):
    from live_simulations import deployed
    c, manifest, _ = continuation_config(tmp_path)
    monkeypatch.setattr(deployed, 'deployment_readiness', lambda *a: ([], []))
    def readiness(*args):
        manifest['spent_credits'] = '633'
        (tmp_path / ('a' * 32) / 'manifest.json').write_text(json.dumps(manifest))
        return {'provider': SimpleNamespace(create_agent=lambda *a: pytest.fail('Changed ancestry created resource'))}, []
    monkeypatch.setattr(deployed, 'provider_readiness', readiness)
    with pytest.raises(SimulationError, match='continuation'):
        deployed.execute(c, live=True)


@pytest.mark.parametrize('binding', [{'id': 7, 'name': 'Not In Baseline'},
                                    {'id': True, 'name': 'Existing Customer'},
                                    {'id': 7, 'name': ''}])
def test_explicit_customer_binding_rejects_invalid_binding_without_native_request(binding):
    from live_simulations import deployed
    c = config()
    c.update(preserve_existing_bookings=True, existing_customer_identity=binding)
    with (
        httpx.Client(transport=httpx.MockTransport(lambda _: pytest.fail('Invalid binding sent request'))) as client,
        pytest.raises(SimulationError, match='identity'),
    ):
        deployed.preserved_customer_name(c, [{'customer_name': 'Existing Customer'}], client)


def test_explicit_customer_binding_fails_closed_on_native_transport_error():
    from live_simulations import deployed
    c = config()
    c.update(preserve_existing_bookings=True, existing_customer_identity={'id': 7, 'name': 'Existing Customer'})
    def unavailable(request):
        raise httpx.ConnectError('unavailable', request=request)
    with (
        httpx.Client(transport=httpx.MockTransport(unavailable)) as client,
        pytest.raises(SimulationError, match='identity'),
    ):
        deployed.preserved_customer_name(c, [{'customer_name': 'Existing Customer'}], client)


@pytest.mark.parametrize('preserve,baseline', [(False, [{'customer_name': 'Existing Customer'}]), (True, [])])
def test_explicit_customer_binding_requires_preserved_scoped_baseline(preserve, baseline):
    from live_simulations import deployed
    c = config()
    c.update(preserve_existing_bookings=preserve, existing_customer_identity={'id': 7, 'name': 'Existing Customer'})
    with pytest.raises(SimulationError, match='identity'):
        deployed.preserved_customer_name(c, baseline)


def recovery_config(tmp_path):
    c, manifest, ledger = continuation_config(tmp_path)
    c['campaign_authorization']['recovery_cases'] = ['C03']
    manifest['results'] = [{'case_id': 'C01', 'status': 'failed', 'functional_status': 'failed'},
                           {'case_id': 'C02', 'status': 'blocked'}, {'case_id': 'C03', 'status': 'blocked'},
                           {'case_id': 'C04', 'status': 'incomplete', 'functional_status': 'passed'}]
    (tmp_path / ('a' * 32) / 'manifest.json').write_text(json.dumps(manifest))
    return c, manifest, ledger


def test_recovery_expands_only_failed_blocked_chain_with_prior_spend(tmp_path):
    from live_simulations import deployed
    c, _, _ = recovery_config(tmp_path)
    result = deployed.execute(c)
    assert result['selected'] == ['C01', 'C02', 'C03']
    assert result['complete_tier'] is False
    assert result['status'] == 'planned'
    assert result['estimated_credits'] == '2888'
    assert result['prior_spent_credits'] == '634'


@pytest.mark.parametrize('problem', ['no_ancestor', 'empty', 'duplicate', 'unknown', 'passed',
    'functional_pass', 'missing', 'duplicate_result', 'inconsistent'])
def test_recovery_rejects_unapproved_or_nonfailed_coverage(tmp_path, problem):
    from live_simulations import deployed
    c, manifest, _ = recovery_config(tmp_path)
    authorization = c['campaign_authorization']
    if problem == 'no_ancestor': authorization.pop('continuation_of')
    elif problem == 'empty': authorization['recovery_cases'] = []
    elif problem == 'duplicate': authorization['recovery_cases'] = ['C01', 'C01']
    elif problem == 'unknown': authorization['recovery_cases'] = ['C07']
    elif problem == 'passed': authorization['recovery_cases'] = ['C04']
    elif problem == 'functional_pass': manifest['results'][0]['functional_status'] = 'passed'
    elif problem == 'missing': manifest['results'].pop(1)
    elif problem == 'duplicate_result': manifest['results'].append(manifest['results'][0].copy())
    elif problem == 'inconsistent': manifest['results'][0]['functional_status'] = 'unknown'
    (tmp_path / ('a' * 32) / 'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(SimulationError, match='recovery'):
        deployed.execute(c)


def test_deployed_minimal_recipe_allows_twelve_turns_without_changing_catalog():
    from live_simulations import deployed
    from live_simulations.core import load_catalog
    for case in load_catalog()[:6]:
        original = copy.deepcopy(case)
        scenario = deployed.deployed_scenario(case, {'customer_name': 'Synthetic', 'customer_phone': '5550100001',
            'appointment_time': '2026-11-02 10:00:00', 'new_time': '2026-11-03 10:00:00',
            'callback_time': '2026-11-02 14:00:00', 'new_callback_time': '2026-11-03 14:00:00'})
        assert scenario['max_turns'] == 12
        assert case == original
        assert scenario['scenario']
        assert len(scenario['success_conditions']) == len(case['success_conditions'])


def test_recovery_eligibility_revalidated_before_clone_creation(monkeypatch, tmp_path):
    from live_simulations import deployed
    c, manifest, _ = recovery_config(tmp_path)
    monkeypatch.setattr(deployed, 'deployment_readiness', lambda *a: ([], []))
    def readiness(*args):
        manifest['results'][0].update(status='incomplete', functional_status='passed')
        (tmp_path / ('a' * 32) / 'manifest.json').write_text(json.dumps(manifest))
        return {'provider': SimpleNamespace(create_agent=lambda *a: pytest.fail('Ineligible recovery created clone'))}, []
    monkeypatch.setattr(deployed, 'provider_readiness', readiness)
    with pytest.raises(SimulationError, match='recovery'):
        deployed.execute(c, live=True)


def test_recovery_still_respects_aggregate_reserve(tmp_path):
    from live_simulations import deployed
    c, manifest, ledger = recovery_config(tmp_path)
    manifest['spent_credits'] = ledger['entries'][0]['credits'] = '6000'
    (tmp_path / ('a' * 32) / 'manifest.json').write_text(json.dumps(manifest))
    (tmp_path / 'usage-ledger.json').write_text(json.dumps(ledger))
    assert deployed.execute(c)['status'] == 'over_budget'


def seeded_recovery_config(tmp_path):
    c, manifest, ledger = recovery_config(tmp_path)
    c['variables']['customer_phone'] = '5550100001'
    c['campaign_authorization'].update(recovery_cases=['C02', 'C03'], resume_request_id=50)
    seed = {'id': 50, 'phone': '5550100001', 'customer_name': 'Existing Customer',
            'booking_type': 'appointment', 'booking_time': '2026-11-03 10:00:00', 'status': 'pending',
            'duration_minutes': 45, 'service_type': 'Oil Change'}
    manifest['baseline'] = [{'id': 99, 'phone': '5550100001', 'customer_name': 'Existing Customer'}]
    manifest['results'] = [{'case_id': 'C01', 'repeat': 1, 'status': 'incomplete', 'functional_status': 'passed'},
                           {'case_id': 'C02', 'repeat': 1, 'status': 'failed', 'functional_status': 'failed'},
                           {'case_id': 'C03', 'repeat': 1, 'status': 'blocked'}]
    ledger['entries'][0].update(case_id='C02')
    folder = tmp_path / ('a' * 32)
    (folder / 'manifest.json').write_text(json.dumps(manifest))
    (folder / 'C01-1-evidence.json').write_text(json.dumps({'after': [{**seed, 'booking_time': '2026-11-02 10:00:00'}]}))
    (folder / 'C02-1-evidence.json').write_text(json.dumps({'after': [seed]}))
    (tmp_path / 'usage-ledger.json').write_text(json.dumps(ledger))
    c['variables']['new_time'] = '2026-11-04 10:00:00'
    return c, manifest, seed


def test_owned_seed_omits_passed_dependency_without_replaying_it(tmp_path):
    from live_simulations import deployed
    c, _, seed = seeded_recovery_config(tmp_path)
    result = deployed.execute(c)
    assert result['selected'] == ['C02', 'C03']
    assert result['complete_tier'] is False
    assert result['estimated_credits'] == '1800'
    assert deployed.recovery_seed(c, [seed]) == seed


@pytest.mark.parametrize('problem', ['original', 'arbitrary', 'cancelled', 'missing', 'phone',
                                   'kind', 'time', 'changed', 'passed_requested', 'same_target'])
def test_owned_recovery_seed_rejects_unproven_or_changed_record(tmp_path, problem):
    from live_simulations import deployed
    c, manifest, seed = seeded_recovery_config(tmp_path)
    folder = tmp_path / ('a' * 32)
    current = seed.copy()
    if problem == 'original': manifest['baseline'].append(seed.copy())
    elif problem == 'arbitrary': c['campaign_authorization']['resume_request_id'] = 51
    elif problem == 'cancelled': seed['status'] = 'cancelled'
    elif problem == 'missing': (folder / 'C02-1-evidence.json').unlink()
    elif problem == 'phone': seed['phone'] = '5550100002'
    elif problem == 'kind': seed['booking_type'] = 'callback'
    elif problem == 'time': seed['booking_time'] = 'not-a-time'
    elif problem == 'changed': current['service_type'] = 'Unexpected service'
    elif problem == 'passed_requested': c['campaign_authorization']['recovery_cases'] = ['C01']
    elif problem == 'same_target': c['variables']['new_time'] = seed['booking_time']
    (folder / 'manifest.json').write_text(json.dumps(manifest))
    if problem != 'missing': (folder / 'C02-1-evidence.json').write_text(json.dumps({'after': [seed]}))
    with pytest.raises(SimulationError, match='recovery|seed'):
        deployed.recovery_selection(c)
        deployed.recovery_seed(c, [current])


def test_owned_recovery_rechecks_fresh_row_before_clone_under_lock(monkeypatch, tmp_path):
    from live_simulations import deployed
    c, _, seed = seeded_recovery_config(tmp_path)
    c['preserve_existing_bookings'] = True
    monkeypatch.setattr(deployed, 'deployment_readiness', lambda *a: ([], [seed.copy()]))
    monkeypatch.setattr(deployed, 'provider_readiness', lambda *a: ({
        'provider': SimpleNamespace(create_agent=lambda *a: pytest.fail('Changed seed created clone'))}, []))
    monkeypatch.setattr(deployed, 'get', lambda *a: [{**seed, 'service_type': 'Changed after readiness'}])
    with pytest.raises(SimulationError, match='seed'):
        deployed.execute(c, live=True)


def test_owned_seed_handles_actual_redacted_evidence_and_checks_fresh_caller(tmp_path):
    from live_simulations import deployed
    from live_simulations.core import redact
    c, _, seed = seeded_recovery_config(tmp_path)
    folder = tmp_path / ('a' * 32)
    for path in folder.glob('*-evidence.json'):
        path.write_text(json.dumps(redact(json.loads(path.read_text()))))
    assert deployed.recovery_selection(c) == ['C02', 'C03']
    assert deployed.recovery_seed(c, [seed]) == seed
    for changed in ({**seed, 'phone': '5550100002'}, {**seed, 'service_type': 'Unexpected change'}):
        with pytest.raises(SimulationError, match='seed'):
            deployed.recovery_seed(c, [changed])
