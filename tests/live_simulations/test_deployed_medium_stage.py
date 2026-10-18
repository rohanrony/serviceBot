"""Exact deployed medium authorization and captured adapter orchestration."""
import copy
import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from live_simulations import deployed, deployed_medium, runner
from live_simulations.core import SimulationError, load_catalog, private_json
from tests.live_simulations.test_deployed import config as base_config

MEDIUM = [f'C{i:02}' for i in range(7, 17)]


def config():
    value = base_config()
    value.update(email_receipt_mode='operator', deployed_medium={'browser_readback': True})
    value['budget'].update(case_upper_estimate=900, reset_unix=123)
    value['stage_authorization'] = {'authorization_id': 'approved-medium-only', 'tier': 'medium',
                                    'case_ids': MEDIUM, 'credit_ceiling': 11250}
    return value


def test_preview_explicit_deployed_stage_preserves_isolated_guard():
    c = config()
    planned = deployed.execute(c, 'medium', requested=MEDIUM)
    assert planned['status'] == 'planned'
    assert planned['selected'] == MEDIUM
    assert planned['unsupported_cases'] == []
    assert planned['estimated_credits'] == '9000'
    assert planned['tier_cap'] == '11250'
    assert planned['complete_tier'] is False
    assert planned['acceptance_scope'] == 'deployed_medium_native_state'
    assert 'receiving Gmail inbox' in planned['missing_acceptance_evidence']
    assert 'scoped database/reservation invariants' not in planned['missing_acceptance_evidence']
    with pytest.raises(SimulationError):
        runner.preview(c, 'medium', MEDIUM)


@pytest.mark.parametrize('mutation', ['full', 'minimal', 'partial', 'repeat', 'mixed', 'calibration', 'invalid_email'])
def test_no_other_deployed_stage_is_authorized(mutation):
    c, tier, requested, repeat = config(), 'medium', MEDIUM, 1
    if mutation == 'full': tier, requested = 'full', [f'C{i:02}' for i in range(17, 51)]
    if mutation == 'minimal': tier, requested = 'minimal', None
    if mutation == 'partial': requested = MEDIUM[:-1]
    if mutation == 'repeat': repeat = 2
    if mutation == 'mixed': c['campaign_authorization'] = {'authorization_id': 'old', 'credit_ceiling': 100}
    if mutation == 'calibration': c['calibration'] = {'credit_ceiling': 100}
    if mutation == 'invalid_email': c['email_receipt_mode'] = 'manual'
    with pytest.raises(SimulationError):
        deployed.execute(c, tier, requested=requested, repeat=repeat)


@pytest.fixture
def captured(tmp_path, monkeypatch):
    c = config()
    c.update(artifact_root=str(tmp_path), evidence_timeout_seconds=0)
    original = {'id': 1, 'phone': c['variables']['customer_phone'], 'status': 'completed',
                'customer_name': 'Original', 'service_type': 'Original', 'booking_type': 'appointment'}
    rows, events = [copy.deepcopy(original)], []
    state = SimpleNamespace(c=c, rows=rows, events=events, unknown=False, cleanup_fails=False,
                            prepare_fails=False, mutate_baseline=False, provider_failed=False,
                            observer_fails=False, clone_mismatch=False, clone_unknown=False, fixture_unknown=False,
                            values_seen={}, rendered_seen={}, dynamic_seen={}, cleanup_seen={})
    agent = {'conversation_config': {'agent': {'prompt': {'tools': [
        {'type': 'webhook', 'name': 'book', 'api_schema': {
            'url': 'https://app.example/api/v1/voice/tools?name=book'}}]}}}}
    override = deployed.native_override(agent, c['deployed_url'], 'hook')
    def manifest():
        paths = list(tmp_path.glob('*/manifest.json'))
        return json.loads(paths[-1].read_text())
    class Provider:
        def create_agent(self, *args):
            events.append('clone')
            assert events[0] == 'catalog'
            if state.clone_unknown: raise SimulationError('ambiguous clone creation')
            return 'owned-clone'
        def agent(self, *args):
            result = copy.deepcopy(override)
            if state.clone_mismatch: result['conversation_config']['agent']['prompt']['prompt'] = 'changed'
            return result
        def resolve_reference(self, value): return value
        def create(self, case, *args):
            assert case.get('native_adapted') is True
            state.rendered_seen[case['id']] = copy.deepcopy(case)
            state.dynamic_seen[case['id']] = copy.deepcopy(args[1])
            return case['id']
        def run(self, agent, test):
            events.append(test)
            ledger = json.loads((tmp_path / 'usage-ledger.json').read_text())
            assert ledger['entries'][-1]['stage_authorization'] == c['stage_authorization']
            assert ledger['entries'][-1]['authorization_id'] == 'approved-medium-only'
            rows.append({'id': int(test[1:]) + 100, 'phone': original['phone'],
                         'customer_name': 'Owned', 'service_type': 'Test', 'booking_type': 'appointment', 'status': 'confirmed'})
            if state.mutate_baseline: rows[0]['status'] = 'cancelled'
            return {'id': 'inv-' + test}
        def wait(self, *args): return {'test_runs': [{'status': 'failed' if state.provider_failed else 'passed'}]}
        def credits(self, result): return None if state.unknown else Decimal(100)
    class Adapter:
        def __init__(self, campaign, client): self.campaign = campaign
        def prepare_catalog(self):
            events.append('catalog')
            value = manifest()
            assert value['stage_authorization'] == c['stage_authorization']
            assert value['attempted'] is True
            ledger = json.loads((tmp_path / 'usage-ledger.json').read_text())
            assert ledger['stage_authorizations'][0]['authorization_id'] == 'approved-medium-only'
            if state.prepare_fails: raise SimulationError('ambiguous catalog resource')
        def arrange(self, case, values):
            events.append('arrange-' + case['id'])
            self.current_case, self.current_values = case['id'], copy.deepcopy(values)
            state.values_seen.setdefault(case['id'], {})['arrange'] = copy.deepcopy(values)
            if state.fixture_unknown: raise SimulationError('ambiguous fixture response')
            rows.append({'id': int(case['id'][1:]) + 200, 'phone': original['phone'],
                         'service_type': 'Fixture', 'booking_type': 'appointment', 'status': 'confirmed'})
            return {**case, 'native_adapted': True, 'native_case_start': '{{new_time}}'}, [rows[-1]['id']]
        def checks(self, case, values, before, after):
            state.values_seen[case['id']]['checks'] = copy.deepcopy(values)
            assert {r['id'] for r in after} == {int(case['id'][1:]) + 100, int(case['id'][1:]) + 200}
            assert {r['id'] for r in before} == {int(case['id'][1:]) + 200}
            return [{'name': 'native scoped state', 'passed': True}]
        def final_checks(self, *args):
            state.values_seen[args[0]['id']]['final_checks'] = copy.deepcopy(args[1])
            events.append('browser')
            return [{'name': 'scoped browser', 'passed': not state.observer_fails}]
        def cleanup_case(self):
            state.cleanup_seen[self.current_case] = self.current_values
            events.append('cleanup')
            if state.cleanup_fails: raise SimulationError('cleanup calendar pending')
            rows[:] = [r for r in rows if r['id'] == 1]
        def cleanup_catalog(self): events.append('catalog-cleanup')
    monkeypatch.setattr(deployed, 'deployment_readiness', lambda *args: ([], [copy.deepcopy(original)]))
    monkeypatch.setattr(deployed, 'preserved_customer_name', lambda *args: 'Original')
    monkeypatch.setattr(deployed, 'provider_readiness', lambda *args: (
        {'provider': Provider(), 'remaining': Decimal(90000), 'override': override, 'webhook_id': 'hook'}, []))
    monkeypatch.setattr(deployed, 'current_remaining', lambda *args: Decimal(90000))
    monkeypatch.setattr(deployed, 'get', lambda *args: copy.deepcopy(rows))
    monkeypatch.setattr(deployed_medium, 'readiness', lambda config, client, cases, baseline:
                        [] if [x['id'] for x in cases] == MEDIUM else ['wrong selection'])
    monkeypatch.setattr(deployed_medium, 'Adapter', Adapter)
    return state


def test_ten_calls_claim_before_catalog_and_clone_settled_cleanup_between(captured):
    state = captured
    old = {'run_id': 'old-minimal', 'credits': '4527', 'unsettled': False}
    private_json(state.c['artifact_root'] + '/usage-ledger.json', {'entries': [old]})
    result = deployed.execute(state.c, 'medium', requested=MEDIUM, live=True)
    assert [e for e in state.events if e in MEDIUM] == MEDIUM
    assert state.events[:2] == ['catalog', 'clone']
    assert state.events[-1] == 'catalog-cleanup'
    assert state.events.count('cleanup') == 10
    assert state.events.count('browser') == 10
    assert result['spent_credits'] == '1000'
    assert result['status'] == 'incomplete'
    assert all(r['functional_status'] == 'passed' and r['status'] == 'incomplete' for r in result['results'])
    assert all(any(check['name'] == 'receiving inbox contains expected content' and
                   check['passed'] is False and check['status'] == 'unverified'
                   for check in row['checks']) for row in result['results']
               if 'email' in next(case for case in load_catalog() if case['id'] == row['case_id'])['required_evidence'])
    prior = list(state.events)
    with pytest.raises(SimulationError, match='authorization.*used|authorization.*claimed'):
        deployed.execute(state.c, 'medium', requested=MEDIUM, live=True)
    assert state.events == prior


@pytest.mark.parametrize('failure', ['prepare_fails', 'unknown', 'cleanup_fails', 'fixture_unknown', 'mutate_baseline', 'clone_mismatch', 'clone_unknown'])
def test_unresolved_effects_stop_remaining_calls_and_retain_catalog(captured, failure):
    setattr(captured, failure, True)
    if failure in ('prepare_fails', 'clone_mismatch', 'clone_unknown'):
        with pytest.raises(SimulationError):
            deployed.execute(captured.c, 'medium', requested=MEDIUM, live=True)
    else:
        deployed.execute(captured.c, 'medium', requested=MEDIUM, live=True)
    assert len([e for e in captured.events if e in MEDIUM]) <= 1
    if failure != 'clone_mismatch':
        assert 'catalog-cleanup' not in captured.events
    if failure == 'unknown': assert 'cleanup' not in captured.events


@pytest.mark.parametrize('failure', ['provider_failed', 'observer_fails'])
def test_native_or_provider_failure_remains_functionally_failed(captured, failure):
    setattr(captured, failure, True)
    result = deployed.execute(captured.c, 'medium', requested=MEDIUM, live=True)
    assert result['status'] == 'failed'
    assert all(r['functional_status'] == 'failed' for r in result['results'])


def test_global_unknown_and_whole_range_readiness_precede_mutations(captured, monkeypatch):
    private_json(captured.c['artifact_root'] + '/usage-ledger.json', {'entries': [{'run_id': 'other', 'unsettled': True}]})
    with pytest.raises(SimulationError, match='Unsettled'):
        deployed.execute(captured.c, 'medium', requested=MEDIUM, live=True)
    assert captured.events == []
    monkeypatch.setattr(deployed_medium, 'readiness', lambda *args: ['C16 missing native setup'])
    with pytest.raises(SimulationError, match='C16'):
        deployed.execute(captured.c, 'medium', requested=MEDIUM, live=True)
    assert captured.events == []


def test_attempted_stage_and_reserve_rejection_precede_mutations(captured):
    c = captured.c
    c['budget']['case_upper_estimate'] = 901
    assert deployed.execute(c, 'medium', requested=MEDIUM)['status'] == 'over_budget'
    with pytest.raises(SimulationError, match='over_budget'):
        deployed.execute(c, 'medium', requested=MEDIUM, live=True)
    assert captured.events == []
    c['budget']['case_upper_estimate'] = 900
    campaign = deployed.Campaign(c, 'medium', MEDIUM)
    campaign.manifest['attempted'] = True
    campaign.save()
    with pytest.raises(SimulationError, match='already attempted'):
        deployed.execute(c, 'medium', requested=MEDIUM, live=True, run_id=campaign.run_id)
    assert captured.events == []


@pytest.mark.parametrize('mode', [None, 'native'])
@pytest.mark.parametrize('action', ['preview', 'check', 'live'])
def test_deployed_medium_without_explicit_operator_rejected_before_any_effect(captured, monkeypatch, mode, action):
    if mode is None:
        captured.c.pop('email_receipt_mode')
    else:
        captured.c['email_receipt_mode'] = mode
    monkeypatch.setattr(deployed, 'deployment_readiness', lambda *args: pytest.fail('native readiness accessed'))
    monkeypatch.setattr(deployed, 'provider_readiness', lambda *args: pytest.fail('provider accessed'))
    with pytest.raises(SimulationError, match='explicit operator'):
        deployed.execute(captured.c, 'medium', requested=MEDIUM,
                         check=action == 'check', live=action == 'live')
    assert captured.events == []
    assert not (Path(captured.c['artifact_root']) / 'usage-ledger.json').exists()


def test_per_case_dates_are_shared_by_setup_render_dynamic_checks_and_cleanup(captured):
    captured.c['variables']['new_time'] = '2026-11-03 10:00:00'
    captured.c['case_bindings'] = {'C08': {'variables': {'new_time': '2026-11-04 11:00:00'}}}
    result = deployed.execute(captured.c, 'medium', requested=MEDIUM, live=True)
    assert [row['case_id'] for row in result['results']] == MEDIUM
    for cid in MEDIUM:
        expected = '2026-11-04 11:00:00' if cid == 'C08' else '2026-11-03 10:00:00'
        seen = captured.values_seen[cid]
        assert seen['arrange']['new_time'] == expected
        assert seen['arrange'] == seen['checks'] == seen['final_checks'] == captured.cleanup_seen[cid]
        assert captured.rendered_seen[cid]['native_case_start'] == expected
        assert captured.dynamic_seen[cid]['new_time'] == expected
        assert seen['arrange']['customer_name'] == 'Original'
        assert captured.dynamic_seen[cid]['customer_name'] == 'Original'
        assert seen['arrange']['run_id'] == result['run_id']


@pytest.mark.parametrize('field,value', [('customer_phone', '2125559999'),
                                        ('customer_email', 'other-allowed@example.test'),
                                        ('customer_name', 'Other identity')])
def test_per_case_identity_changes_rejected_before_claim_or_native_reads(captured, monkeypatch, field, value):
    captured.c['case_bindings'] = {'C16': {'variables': {field: value}}}
    captured.c['allowlisted_emails'].append('other-allowed@example.test')
    captured.c['allowlisted_phone_numbers'].append('+12125559999')
    monkeypatch.setattr(deployed, 'deployment_readiness', lambda *args: pytest.fail('native read before identity rejection'))
    with pytest.raises(SimulationError, match='identity'):
        deployed.execute(captured.c, 'medium', requested=MEDIUM, live=True)
    assert captured.events == []
    assert not (Path(captured.c['artifact_root']) / 'usage-ledger.json').exists()
