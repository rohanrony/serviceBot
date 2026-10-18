"""Never-created seven-case recovery binds the longer prefix and owned prompt revision."""
import copy
import hashlib
import json

import pytest

from live_simulations import agent_policy, deployed, deployed_medium, workflow
from live_simulations.core import SimulationError, fingerprint, private_json
from tests.test_deployed_remaining_continuation import captured as captured_fixture
from tests.test_deployed_remaining_continuation import remaining as remaining_fixture
from tests.test_deployed_remaining_continuation import unpaid as unpaid_fixture

captured = captured_fixture
unpaid = unpaid_fixture
remaining = remaining_fixture
SUFFIX = [f'C{i:02}' for i in range(10, 17)]


def archive(campaign, name):
    destination = campaign.folder / name
    destination.mkdir(parents=True)
    hashes = {}
    for filename in ('manifest.json', 'report.json', 'report.md'):
        data = (campaign.folder / filename).read_bytes()
        (destination / filename).write_bytes(data)
        (destination / filename).chmod(0o400)
        hashes[filename] = hashlib.sha256(data).hexdigest()
    private_json(destination / 'hashes.json', hashes)
    return hashes


@pytest.fixture
def ready(remaining, monkeypatch):
    s, c = remaining, remaining.campaign
    provider_state, _ = deployed.provider_readiness(s.c, None)
    provider = provider_state['provider']
    source = copy.deepcopy(provider_state['override'])
    source['conversation_config']['agent']['prompt']['prompt'] = 'Original owned agent instructions.'
    source_fp = fingerprint(source)
    # Seed this fixture's old snapshots with the original text-bearing prompt
    # before creating the later numbered attempt, retaining a genuine hash chain.
    first = c.manifest['unpaid_continuations'][0]
    old_path = c.folder / first['archive'] / 'manifest.json'
    original = json.loads(old_path.read_text()); original['reference_fingerprint'] = source_fp
    old_path.chmod(0o600); old_path.write_text(json.dumps(original, indent=2) + '\n'); old_path.chmod(0o400)
    first['files_sha256']['manifest.json'] = hashlib.sha256(old_path.read_bytes()).hexdigest()
    first['original_manifest_sha256'] = first['files_sha256']['manifest.json']
    c.manifest['reference_fingerprint'] = source_fp
    c.save(); c.report()
    ledger_path = c.root / 'usage-ledger.json'
    ledger = json.loads(ledger_path.read_text())
    ledger['unpaid_continuations'][0].update(first)
    private_json(ledger_path, ledger)
    deployed._archive_unpaid(c, ledger, previous_attempt=2, kind='remaining_continuations',
        extra_names=['reconciliation/c08-effect-cleanup.json'],
        selected=[f'C{i:02}' for i in range(9, 17)], prior_spent=1114)
    result = {'id': 'suite-C09', 'agent_id': 'owned-clone', 'test_runs': [{
        'test_id': 'test-C09', 'test_invocation_id': 'suite-C09', 'status': 'failed', 'credits_used': 905,
        'agent_responses': [{'tool_results': [{'tool_name': 'create_service_request', 'request_id': 'create-call-C09',
            'is_error': False, 'result_value': json.dumps({'result': {'success': True, 'service_request_id': 52}})}]}]}]}
    private_json(c.folder / 'C09-1-provider.json', result)
    s.prefix_receipts['suite-C09'] = result
    ledger = json.loads(ledger_path.read_text())
    ledger['entries'].append({'run_id': c.run_id, 'case_id': 'C09', 'test_id': 'test-C09',
        'invocation_id': 'suite-C09', 'credits': '905', 'unsettled': False,
        'authorization_id': s.c['stage_authorization']['authorization_id'],
        'stage_authorization': copy.deepcopy(s.c['stage_authorization'])})
    private_json(ledger_path, ledger)
    c.manifest.update(status='failed', spent_credits='2019', aggregate_spent_credits='2019')
    c.manifest['provider_tests'].append('test-C09'); c.manifest['invocations'].append('suite-C09')
    c.manifest['results'].extend({'case_id': cid, 'attempt': 3, 'repeat': 1, 'status': 'blocked',
        'functional_status': 'blocked', 'reason': 'Unresolved stage resource, cleanup or charge; no further paid work'}
        for cid in ['C09'] + SUFFIX)
    fixture = c.manifest['deployed_medium']
    fixture.update(owned_request_ids=[51, 52], current_case='C09')
    c.save(); c.report()
    archive(c, 'attempts/attempt-3-before-reconciliation')
    receipt = {'run_id': c.run_id, 'case_id': 'C09', 'status': 'settled', 'owned_request_ids': [52],
        'cancelled_request_ids': [52], 'restored_block_ids': [], 'provider_create_request_id': 'create-call-C09',
        'provider_receipt_sha256': hashlib.sha256((c.folder / 'C09-1-provider.json').read_bytes()).hexdigest(),
        'pre_reconciliation_archive': 'attempts/attempt-3-before-reconciliation', 'baseline_unchanged': True,
        'identity_verified': True, 'google_current_event_deleted': True, 'native_calendar_effects_settled': True,
        'ambiguous_cancel_reconciled': True}
    receipt_path = c.folder / 'reconciliation/c09-effect-cleanup.json'; private_json(receipt_path, receipt)
    c.manifest['reconciliations'] = [{'path': 'reconciliation/c09-effect-cleanup.json', 'sha256': hashlib.sha256(receipt_path.read_bytes()).hexdigest()}]
    source_path = c.folder / 'agent-policy/source-override.json'; private_json(source_path, source)
    desired = agent_policy.apply_service_policy(source)
    s.c['owned_agent_policy'] = agent_policy.SERVICE_POLICY_VERSION
    revision = {'status': 'observed', 'protected_reference_unchanged': True, 'policy_version': agent_policy.SERVICE_POLICY_VERSION,
        'agent_id': 'owned-clone', 'source_fingerprint': source_fp, 'new_fingerprint': fingerprint(desired),
        'source_override_path': 'agent-policy/source-override.json',
        'source_override_sha256': hashlib.sha256(source_path.read_bytes()).hexdigest(),
        'old_prompt_sha256': hashlib.sha256(source['conversation_config']['agent']['prompt']['prompt'].encode()).hexdigest(),
        'new_prompt_sha256': hashlib.sha256(desired['conversation_config']['agent']['prompt']['prompt'].encode()).hexdigest()}
    c.manifest['agent_revisions'] = [revision]
    provider_state.update(source_override=source, override=desired)
    monkeypatch.setattr(provider, 'agent', lambda *args: copy.deepcopy(desired))
    s.native_rows.append({'id': 52, 'customer_id': 5, 'customer_phone': s.c['variables']['customer_phone'],
        'customer_name': 'Original', 'status': 'cancelled', 'reservation_id': None})
    s.effects.append({**copy.deepcopy(s.effects[0]), 'id': 52})
    monkeypatch.setattr(deployed_medium, '_request_rows', lambda config, ids: copy.deepcopy([r for r in s.native_rows if r['id'] in ids]))
    monkeypatch.setattr(deployed_medium, '_effect_rows', lambda config, ids: copy.deepcopy([r for r in s.effects if r['id'] in ids]))
    c.save(); c.report()
    s.source, s.desired, s.revision, s.receipt52 = source, desired, revision, receipt_path
    return s


def invoke(s, **kwargs):
    return deployed.execute(s.c, 'medium', live=True, run_id=s.campaign.run_id,
                            requested=SUFFIX, continue_unsubmitted=True, **kwargs)


def test_seven_untouched_cases_use_original_budget_and_verified_revision(ready, monkeypatch):
    ready.c['budget']['remaining_credits'] = 6300
    monkeypatch.setattr(deployed, 'current_remaining', lambda *args: 6300)
    result = invoke(ready)
    assert [event for event in ready.events if event in [f'C{i:02}' for i in range(7, 17)]] == SUFFIX
    assert 'clone' not in ready.events and 'catalog' not in ready.events
    assert result['spent_credits'] == '2719'
    assert result['stage_functional_status'] == 'failed'
    assert result['latest_attempt_functional_status'] == 'passed'
    assert result['stage_case_outcomes']['C08'] == result['stage_case_outcomes']['C09'] == 'failed'
    assert all(row['attempt'] == 4 for row in result['results'][-7:])
    admission = result['unsubmitted_continuations'][0]
    assert admission['prior_spent_credits'] == '2019' and admission['selected'] == SUFFIX
    assert admission['agent_revision_fingerprint'] == fingerprint(ready.desired)
    ledger = json.loads((ready.campaign.root / 'usage-ledger.json').read_text())
    assert len(ledger['stage_authorizations']) == 1 and len(ledger['entries']) == 10
    with pytest.raises(SimulationError): invoke(ready)


@pytest.mark.parametrize('unsafe', ['prefix_credits', 'prefix_pending', 'suffix_cleared_intent', 'suffix_artifact',
    'global_unknown', 'receipt52_hash', 'receipt51_hash', 'prior_archive', 'request52_active', 'projection52_pending',
    'revision_unknown', 'revision_source_hash', 'revision_other_field', 'revision_prompt_hash', 'wrong_owned_agent',
    'protected_source_drift', 'policy_missing', 'policy_unknown', 'quota', 'repeated', 'protected_unchanged_false', 'initial_source_chain'])
def test_unsafe_prefix_effect_or_policy_proof_rejects_before_admission(ready, monkeypatch, unsafe):
    c = ready.campaign; ledger_path = c.root / 'usage-ledger.json'; ledger = json.loads(ledger_path.read_text())
    if unsafe == 'prefix_credits': ledger['entries'][-1]['credits'] = '906'
    if unsafe == 'prefix_pending': ready.prefix_receipts['suite-C09']['test_runs'][0]['status'] = 'pending'
    if unsafe == 'suffix_cleared_intent': c.manifest['test_creation_intents'] = [{'case_id': 'C10', 'status': 'cleared'}]
    if unsafe == 'suffix_artifact': private_json(c.folder / 'C10-1-provider.json', {})
    if unsafe == 'global_unknown': ledger['entries'].append({'run_id': 'other', 'unsettled': True})
    if unsafe == 'receipt52_hash': c.manifest['reconciliations'][-1]['sha256'] = 'other'
    if unsafe == 'receipt51_hash': c.manifest['remaining_reconciliation']['sha256'] = 'other'
    if unsafe == 'prior_archive':
        path = c.folder / 'attempts/attempt-2/manifest.json'; path.chmod(0o600); path.write_text('{}')
    if unsafe == 'request52_active': ready.native_rows[-1]['status'] = 'confirmed'
    if unsafe == 'projection52_pending': ready.effects[-1]['projection_statuses'] = ['PENDING']
    if unsafe == 'revision_unknown': c.manifest['agent_revisions'][0]['status'] = 'unknown'
    if unsafe == 'revision_source_hash': c.manifest['agent_revisions'][0]['source_override_sha256'] = 'other'
    if unsafe == 'revision_other_field': ready.desired['conversation_config']['agent']['language'] = 'fr'
    if unsafe == 'revision_prompt_hash': c.manifest['agent_revisions'][0]['new_prompt_sha256'] = 'other'
    if unsafe == 'wrong_owned_agent': c.manifest['agent_revisions'][0]['agent_id'] = ready.c['agent_id']
    if unsafe == 'protected_source_drift': ready.source['conversation_config']['agent']['prompt']['prompt'] += 'changed'
    if unsafe == 'policy_missing': ready.c.pop('owned_agent_policy')
    if unsafe == 'policy_unknown': ready.c['owned_agent_policy'] = 'other'
    if unsafe == 'quota': monkeypatch.setattr(deployed, 'current_remaining', lambda *args: 6299)
    if unsafe == 'repeated': c.manifest['unsubmitted_continuations'] = [{'attempt': 4}]
    if unsafe == 'protected_unchanged_false': c.manifest['agent_revisions'][0]['protected_reference_unchanged'] = False
    if unsafe == 'initial_source_chain':
        first = c.manifest['unpaid_continuations'][0]
        path = c.folder / first['archive'] / 'manifest.json'
        original = json.loads(path.read_text()); original['reference_fingerprint'] = 'other-original-source'
        path.chmod(0o600); path.write_text(json.dumps(original)); path.chmod(0o400)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        first['files_sha256']['manifest.json'] = digest; first['original_manifest_sha256'] = digest
        ledger['unpaid_continuations'][0].update(first)
    c.save(); private_json(ledger_path, ledger); before = (c.folder / 'manifest.json').read_bytes()
    with pytest.raises(SimulationError): invoke(ready)
    assert ready.events == []
    assert (c.folder / 'manifest.json').read_bytes() == before
    assert not (c.folder / 'attempts/attempt-3').exists()


def test_explicit_cli_and_workflow_authority(monkeypatch):
    from live_simulations import __main__ as cli
    seen = []
    monkeypatch.setattr(cli, 'load_config', lambda *args: {'target': 'deployed'})
    monkeypatch.setattr(workflow, 'execute', lambda *args, **kwargs: seen.append(kwargs) or {'status': 'failed', 'run_id': 'a' * 32})
    assert cli.main(['workflow', '--target', 'deployed', '--tier', 'medium', '--live', '--run-id', 'a' * 32,
                     '--cases', ','.join(SUFFIX), '--continue-unsubmitted']) == 1
    assert seen[0]['continue_unsubmitted'] is True
