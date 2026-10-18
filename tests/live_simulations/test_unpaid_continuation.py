"""Same-run zero-submit continuation retains evidence and never replaces resources."""
import copy
import hashlib
import json

import pytest

from live_simulations import deployed, deployed_medium, workflow
from live_simulations.core import SimulationError, fingerprint, private_json
from tests.live_simulations.test_deployed_medium_stage import MEDIUM
from tests.live_simulations.test_deployed_medium_stage import captured as stage_captured

captured = stage_captured
REAL_CATALOG_VALIDATOR = deployed_medium.validate_retained_catalog


@pytest.fixture
def unpaid(captured, monkeypatch):
    state = captured
    c = state.c
    c['deployed_medium'].update(ownership_id='medium-owned-123', technician_ids=[7, 11], services={
        key: {'name': 'medium-owned-123 ' + key, 'duration_minutes': 60,
              'price_range': '$10', 'source_id': index}
        for index, key in enumerate(('oil', 'second', 'split'), 1)})
    campaign = deployed.Campaign(c, 'medium', MEDIUM)
    provider_state, _ = deployed.provider_readiness(c, None)
    services = {key: {**value, 'id': 100 + index,
                      'assigned_agent_ids': [11 if key == 'split' else 7]}
                for index, (key, value) in enumerate(c['deployed_medium']['services'].items())}
    operations = [{'method': 'POST', 'path': '/api/v1/portal/services', 'status': 'observed',
                   'ids': [value['id']]} for value in services.values()]
    baseline = deployed.deployment_readiness(c, None)[1]
    campaign.manifest.update(attempted=True, status='blocked', tier='medium', complete_tier=False,
        stage_authorization=copy.deepcopy(c['stage_authorization']), baseline=baseline,
        campaign_agent_id='owned-clone', reference_fingerprint=fingerprint(provider_state['override']),
        agent_create_pending=False, provider_tests=[], invocations=[],
        results=[{'case_id': cid, 'repeat': 1, 'status': 'blocked', 'reason': 'read failed'} for cid in MEDIUM],
        deployed_medium={'services': services, 'operations': operations, 'owned_request_ids': [],
                         'current_request_ids': [], 'blocks': [], 'blocked': False})
    campaign.save()
    campaign.report()
    private_json(campaign.root / 'usage-ledger.json', {'entries': [], 'stage_authorizations': [
        {**copy.deepcopy(c['stage_authorization']), 'run_id': campaign.run_id}]})
    monkeypatch.setattr(deployed_medium, 'readiness', lambda *args, **kwargs: [])
    monkeypatch.setattr(deployed_medium, 'validate_retained_catalog', lambda *args: None, raising=False)
    state.campaign = campaign
    state.original_manifest = (campaign.folder / 'manifest.json').read_bytes()
    state.original_reports = {name: (campaign.folder / name).read_bytes() for name in ('report.json', 'report.md')}
    return state


def continue_run(state, **kwargs):
    return deployed.execute(state.c, 'medium', live=True, requested=MEDIUM,
                            run_id=state.campaign.run_id, continue_unpaid=True, **kwargs)


def test_same_run_reuses_catalog_and_clone_preserves_original_evidence(unpaid):
    result = continue_run(unpaid)
    assert result['run_id'] == unpaid.campaign.run_id
    assert unpaid.events.count('clone') == unpaid.events.count('catalog') == 0
    assert [item for item in unpaid.events if item in MEDIUM] == MEDIUM
    assert len(result['unpaid_continuations']) == 1
    admission = result['unpaid_continuations'][0]
    assert admission['attempt'] == 2
    assert admission['original_manifest_sha256'] == hashlib.sha256(unpaid.original_manifest).hexdigest()
    archive = unpaid.campaign.folder / admission['archive']
    assert (archive / 'manifest.json').read_bytes() == unpaid.original_manifest
    for name, data in unpaid.original_reports.items():
        assert (archive / name).read_bytes() == data
    ledger = json.loads((unpaid.campaign.root / 'usage-ledger.json').read_text())
    assert len(ledger['stage_authorizations']) == 1
    assert len(ledger['entries']) == 10
    assert result['results'][:10] == json.loads(unpaid.original_manifest)['results']
    assert all(row['attempt'] == 2 for row in result['results'][10:])
    with pytest.raises(SimulationError): continue_run(unpaid)


@pytest.mark.parametrize('unsafe', ['charge', 'auth_charge', 'global_unknown', 'test', 'invocation', 'test_key_none',
    'test_pending', 'agent_pending', 'unknown_op', 'pending_op', 'booking', 'block', 'current_case',
    'duplicate_claim', 'claim_mismatch', 'ledger_admission', 'scope', 'origin', 'ceiling', 'baseline', 'clone', 'catalog', 'previous_admission'])
def test_every_unsafe_state_rejects_before_effects_or_evidence_rewrite(unpaid, monkeypatch, unsafe):
    manifest = unpaid.campaign.manifest
    ledger_path = unpaid.campaign.root / 'usage-ledger.json'
    ledger = json.loads(ledger_path.read_text())
    if unsafe == 'charge': ledger['entries'].append({'run_id': unpaid.campaign.run_id, 'unsettled': False, 'credits': '0'})
    if unsafe == 'auth_charge': ledger['entries'].append({'run_id': 'another', 'authorization_id': 'approved-medium-only', 'unsettled': False, 'credits': '0'})
    if unsafe == 'global_unknown': ledger['entries'].append({'run_id': 'another', 'unsettled': True})
    if unsafe == 'test': manifest['provider_tests'] = ['test']
    if unsafe == 'invocation': manifest['invocations'] = ['inv']
    if unsafe == 'test_key_none': manifest['test_create_pending'] = None
    if unsafe == 'test_pending': manifest['test_create_pending'] = 'C07'
    if unsafe == 'agent_pending': manifest['agent_create_pending'] = True
    if unsafe == 'unknown_op': manifest['deployed_medium']['operations'][0]['status'] = 'unknown'
    if unsafe == 'pending_op': manifest['deployed_medium']['operations'][0]['status'] = 'intent'
    if unsafe == 'booking': manifest['deployed_medium']['owned_request_ids'] = [99]
    if unsafe == 'block': manifest['deployed_medium']['blocks'] = [{'restored': True}]
    if unsafe == 'current_case': manifest['deployed_medium']['current_case'] = 'C07'
    if unsafe == 'duplicate_claim': ledger['stage_authorizations'] *= 2
    if unsafe == 'claim_mismatch': ledger['stage_authorizations'][0]['credit_ceiling'] = 20000
    if unsafe == 'ledger_admission': ledger['unpaid_continuations'] = [{'run_id': unpaid.campaign.run_id, 'attempt': 2}]
    if unsafe == 'scope': manifest['selected'] = MEDIUM[:-1]
    if unsafe == 'origin': manifest['deployed_url'] = 'https://other.example'
    if unsafe == 'ceiling': unpaid.c['stage_authorization']['credit_ceiling'] = 20000
    if unsafe == 'baseline': monkeypatch.setattr(deployed, 'deployment_readiness', lambda *args: ([], []))
    if unsafe == 'clone': manifest['reference_fingerprint'] = 'different'
    if unsafe == 'catalog':
        def reject(*args): raise SimulationError('catalog mismatch')
        monkeypatch.setattr(deployed_medium, 'validate_retained_catalog', reject)
    if unsafe == 'previous_admission': manifest['unpaid_continuations'] = [{'attempt': 2}]
    unpaid.campaign.save()
    private_json(ledger_path, ledger)
    before = (unpaid.campaign.folder / 'manifest.json').read_bytes()
    with pytest.raises(SimulationError): continue_run(unpaid)
    assert unpaid.events == []
    assert (unpaid.campaign.folder / 'manifest.json').read_bytes() == before
    assert not (unpaid.campaign.folder / 'attempts').exists()


@pytest.mark.parametrize('live,check,tier,run_id', [(False, False, 'medium', 'same'),
    (False, True, 'medium', 'same'), (True, True, 'medium', 'same'),
    (True, False, 'minimal', 'same'), (True, False, 'medium', None)])
def test_continuation_requires_explicit_live_same_run_medium(unpaid, live, check, tier, run_id):
    with pytest.raises(SimulationError, match='continuation'):
        deployed.execute(unpaid.c, tier, live=live, check=check, requested=MEDIUM,
                         run_id=unpaid.campaign.run_id if run_id else None, continue_unpaid=True)
    assert unpaid.events == []


def test_workflow_rejects_continuation_for_isolated_target(monkeypatch):
    with pytest.raises(SimulationError, match='continuation'):
        workflow.execute({'target': 'isolated'}, 'medium', continue_unpaid=True)


def test_cli_forwards_explicit_continuation(monkeypatch):
    from live_simulations import __main__ as cli
    seen = []
    monkeypatch.setattr(cli, 'load_config', lambda *args: {'target': 'deployed'})
    monkeypatch.setattr(workflow, 'execute', lambda *args, **kwargs: seen.append(kwargs) or {'status': 'incomplete', 'run_id': 'a' * 32})
    assert cli.main(['workflow', '--target', 'deployed', '--tier', 'medium', '--cases', ','.join(MEDIUM),
                     '--run-id', 'a' * 32, '--live', '--continue-unpaid']) == 3
    assert seen[0]['continue_unpaid'] is True


@pytest.mark.parametrize('failure', ['quota', 'readiness', 'recipient'])
def test_fresh_proofs_fail_without_archiving_or_admission(unpaid, monkeypatch, failure):
    if failure == 'quota': monkeypatch.setattr(deployed, 'current_remaining', lambda *args: 8999)
    if failure == 'readiness': monkeypatch.setattr(deployed_medium, 'readiness', lambda *args, **kwargs: ['native readiness failed'])
    if failure == 'recipient': unpaid.c['case_bindings'] = {'C16': {'variables': {'customer_email': 'different@example.test'}}}
    with pytest.raises(SimulationError): continue_run(unpaid)
    assert unpaid.events == []
    assert (unpaid.campaign.folder / 'manifest.json').read_bytes() == unpaid.original_manifest
    assert not (unpaid.campaign.folder / 'attempts').exists()


@pytest.mark.parametrize('mutation', ['none', 'native_name', 'native_agents', 'observer_name', 'observer_agents'])
def test_retained_catalog_requires_exact_native_and_observer_bindings(unpaid, monkeypatch, mutation):
    # Use the real implementation; the orchestration fixture captures its boundary.
    services = unpaid.campaign.manifest['deployed_medium']['services']
    native = [copy.deepcopy(item) for item in services.values()]
    observed = [{key: value for key, value in item.items() if key in ('id', 'name', 'duration_minutes', 'price_range')}
                for item in services.values()]
    agents = [{'service_id': item['id'], 'staff_agent_id': item['assigned_agent_ids'][0]} for item in services.values()]
    if mutation == 'native_name': native[0]['name'] = 'Original unrelated catalog'
    if mutation == 'native_agents': native[0]['assigned_agent_ids'] = [99]
    if mutation == 'observer_name': observed[0]['name'] = 'Changed'
    if mutation == 'observer_agents': agents[0]['staff_agent_id'] = 99
    monkeypatch.setattr(deployed_medium, '_get', lambda *args: native)
    monkeypatch.setattr(deployed_medium, '_read', lambda config, query, args: agents if 'service_staff_agents' in query else observed)
    if mutation == 'none':
        REAL_CATALOG_VALIDATOR(unpaid.c, None, services)
    else:
        with pytest.raises(SimulationError): REAL_CATALOG_VALIDATOR(unpaid.c, None, services)


def test_initial_zero_submit_read_failure_retains_sanitized_diagnostic(captured, monkeypatch):
    import httpx
    def read_failure(*args): raise httpx.ReadTimeout('private-token-and-customer-content')
    monkeypatch.setattr(deployed, 'get', read_failure)
    result = deployed.execute(captured.c, 'medium', live=True, requested=MEDIUM)
    assert [item for item in captured.events if item in MEDIUM] == []
    diagnostic = result['results'][0]['failure_diagnostic']
    assert diagnostic == {'stage': 'native booking baseline before fixture', 'type': 'ReadTimeout', 'status': None}
    assert 'private-token-and-customer-content' not in json.dumps(result)
