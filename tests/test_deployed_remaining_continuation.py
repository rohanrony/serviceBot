"""Paid prefix remains failed; only a proven never-created suffix may continue."""
import copy
import hashlib
import json

import pytest

from live_simulations import deployed, deployed_medium, workflow
from live_simulations.core import SimulationError, private_json
from tests.live_simulations.test_unpaid_continuation import captured as captured_fixture
from tests.live_simulations.test_unpaid_continuation import unpaid as unpaid_fixture

captured = captured_fixture
unpaid = unpaid_fixture
SUFFIX = [f'C{i:02}' for i in range(9, 17)]


@pytest.fixture
def remaining(unpaid, monkeypatch):
    s = unpaid
    c = s.campaign
    # Preserve the real original zero-submit evidence and its admission before
    # constructing captured terminal prefix receipts.
    ledger_path = c.root / 'usage-ledger.json'
    ledger = json.loads(ledger_path.read_text())
    deployed._archive_unpaid(c, ledger)
    provider_state, _ = deployed.provider_readiness(s.c, None)
    provider = provider_state['provider']
    receipts, charges = {}, []
    for cid, credits, status in [('C07', 331, 'passed'), ('C08', 783, 'failed')]:
        test, invocation = 'test-' + cid, 'suite-' + cid
        tools = ([{'tool_results': [{'tool_name': 'create_service_request', 'request_id': 'create-call-C08', 'is_error': False,
                    'result_value': json.dumps({'result': {'success': True, 'service_request_id': 51}})}]}]
                 if cid == 'C08' else [])
        result = {'id': invocation, 'agent_id': 'owned-clone', 'test_runs': [
            {'test_id': test, 'test_invocation_id': invocation, 'status': status,
             'credits_used': credits, 'agent_responses': tools}]}
        private_json(c.folder / f'{cid}-1-provider.json', result)
        receipts[invocation] = result
        charges.append({'run_id': c.run_id, 'case_id': cid, 'test_id': test,
                        'invocation_id': invocation, 'credits': str(credits), 'unsettled': False,
                        'authorization_id': s.c['stage_authorization']['authorization_id'],
                        'stage_authorization': copy.deepcopy(s.c['stage_authorization'])})
    monkeypatch.setattr(provider, 'get', lambda invocation: copy.deepcopy(receipts[invocation]), raising=False)
    monkeypatch.setattr(deployed, 'provider_readiness', lambda *args: (provider_state, []))
    c.manifest.update(status='blocked', spent_credits='1114', aggregate_spent_credits='1114',
        provider_tests=['test-C07', 'test-C08'], invocations=['suite-C07', 'suite-C08'], test_create_pending=None,
        results=c.manifest['results'] + [
            {'case_id': cid, 'attempt': 2, 'repeat': 1, 'status': 'incomplete' if cid == 'C07' else 'blocked',
             'functional_status': 'passed' if cid == 'C07' else 'blocked',
             'reason': 'Unresolved stage resource, cleanup or charge; no further paid work' if cid in SUFFIX else 'prefix outcome'}
            for cid in ['C07', 'C08'] + SUFFIX])
    fixture = c.manifest['deployed_medium']
    fixture.update(owned_request_ids=[51], current_request_ids=[], current_case='C08', fixture_rows=[],
        blocks=[{'original': {'id': 849, 'staff_agent_id': 7, 'slot_datetime': '2026-11-02 10:00:00',
                             'is_booked': False, 'reservation_status': 'AVAILABLE',
                             'service_request_id': None, 'active_reservation': False}, 'restored': True}])
    receipt = {'run_id': c.run_id, 'status': 'settled', 'owned_request_ids': [51],
        'cancelled_request_ids': [51], 'restored_block_ids': [849], 'provider_create_request_id': 'create-call-C08',
        'case_id': 'C08', 'baseline_unchanged': True, 'google_current_event_deleted': True,
        'native_calendar_effects_settled': True,
        'provider_receipt_sha256': hashlib.sha256((c.folder / 'C08-1-provider.json').read_bytes()).hexdigest()}
    c.save(); c.report()
    pre = c.folder / 'attempts/attempt-2-before-reconciliation'
    pre.mkdir()
    hashes = {}
    for name in ('manifest.json', 'report.json', 'report.md'):
        data = (c.folder / name).read_bytes()
        (pre / name).write_bytes(data)
        (pre / name).chmod(0o400)
        hashes[name] = hashlib.sha256(data).hexdigest()
    private_json(pre / 'hashes.json', hashes)
    receipt['pre_reconciliation_archive'] = 'attempts/attempt-2-before-reconciliation'
    path = c.folder / 'reconciliation/c08-effect-cleanup.json'
    private_json(path, receipt)
    c.manifest['remaining_reconciliation'] = {'path': 'reconciliation/c08-effect-cleanup.json',
                                            'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    c.save(); c.report()
    ledger = json.loads(ledger_path.read_text()); ledger['entries'] = charges
    private_json(ledger_path, ledger)
    s.prefix_receipts = receipts
    s.receipt_path = path
    s.rows.append({'id': 51, 'phone': s.c['variables']['customer_phone'], 'status': 'cancelled'})
    native_rows = [{'id': 51, 'customer_id': 5, 'customer_phone': s.c['variables']['customer_phone'],
                    'status': 'cancelled', 'reservation_id': None, 'customer_name': 'Original'}]
    s.c['existing_customer_identity'] = {'id': 5, 'name': 'Original'}
    effects = [{'id': 51, 'active_count': 0, 'segment_count': 0, 'projection_statuses': ['DELIVERED'],
                'has_event': True, 'request_calendar_status': 'DELETED', 'reservation_calendar_statuses': ['DELETED']}]
    s.native_rows, s.effects = native_rows, effects
    monkeypatch.setattr(deployed_medium, '_request_rows', lambda *args: copy.deepcopy(native_rows))
    monkeypatch.setattr(deployed_medium, '_effect_rows', lambda *args: copy.deepcopy(effects))
    monkeypatch.setattr(deployed_medium, '_slots', lambda *args: copy.deepcopy([fixture['blocks'][0]['original']]))
    s.before = (c.folder / 'manifest.json').read_bytes()
    return s


def invoke(state, **kwargs):
    return deployed.execute(state.c, 'medium', live=True, requested=SUFFIX,
                            run_id=state.campaign.run_id, continue_remaining=True, **kwargs)


def test_exact_suffix_reuses_resources_preserves_prefix_failure_and_aggregate_budget(remaining, monkeypatch):
    monkeypatch.setattr(deployed, 'current_remaining', lambda *args: 7200)
    result = invoke(remaining)
    assert [event for event in remaining.events if event in ['C07', 'C08'] + SUFFIX] == SUFFIX
    assert 'clone' not in remaining.events and 'catalog' not in remaining.events
    assert result['spent_credits'] == '1914'
    assert result['latest_attempt_functional_status'] == 'passed'
    assert result['stage_functional_status'] == 'failed'
    assert result['status'] == 'failed'
    assert result['stage_case_outcomes']['C08'] == 'failed'
    assert all(row['attempt'] == 3 for row in result['results'][-8:])
    admission = result['remaining_continuations'][0]
    assert admission['attempt'] == 3 and admission['prior_spent_credits'] == '1114'
    assert admission['selected'] == SUFFIX
    archive = remaining.campaign.folder / admission['archive']
    assert (archive / 'manifest.json').read_bytes() == remaining.before
    assert (archive / 'reconciliation/c08-effect-cleanup.json').read_bytes() == remaining.receipt_path.read_bytes()
    ledger = json.loads((remaining.campaign.root / 'usage-ledger.json').read_text())
    assert len(ledger['stage_authorizations']) == 1
    assert len(ledger['entries']) == 10
    with pytest.raises(SimulationError): invoke(remaining)


@pytest.mark.parametrize('unsafe', ['prefix_credits', 'prefix_pending', 'provider_mismatch', 'extra_charge',
    'suffix_intent_cleared', 'suffix_pending', 'suffix_artifact', 'global_unknown', 'receipt_hash',
    'request_active', 'wrong_customer', 'projection_pending', 'block_pending', 'archive_changed',
    'repeated', 'cap', 'quota', 'clone', 'catalog', 'duplicate_result', 'charge_scope', 'native_name', 'missing_reservation_projection'])
def test_unsafe_suffix_admission_has_no_effect_or_archive(remaining, monkeypatch, unsafe):
    c = remaining.campaign
    ledger_path = c.root / 'usage-ledger.json'
    ledger = json.loads(ledger_path.read_text())
    if unsafe == 'prefix_credits': ledger['entries'][0]['credits'] = '332'
    if unsafe == 'prefix_pending': remaining.prefix_receipts['suite-C08']['test_runs'][0]['status'] = 'pending'
    if unsafe == 'provider_mismatch': remaining.prefix_receipts['suite-C08']['test_runs'][0]['test_id'] = 'other'
    if unsafe == 'extra_charge': ledger['entries'].append({**ledger['entries'][0], 'case_id': 'C09'})
    if unsafe == 'suffix_intent_cleared': c.manifest['test_creation_intents'] = [{'case_id': 'C09', 'status': 'cleared'}]
    if unsafe == 'suffix_pending': c.manifest['test_create_pending'] = 'C09'
    if unsafe == 'suffix_artifact': private_json(c.folder / 'C09-1-provider.json', {})
    if unsafe == 'global_unknown': ledger['entries'].append({'run_id': 'other', 'unsettled': True})
    if unsafe == 'receipt_hash': c.manifest['remaining_reconciliation']['sha256'] = 'bad'
    if unsafe == 'request_active': remaining.native_rows[0]['status'] = 'confirmed'
    if unsafe == 'wrong_customer': remaining.native_rows[0]['customer_id'] = 99
    if unsafe == 'projection_pending': remaining.effects[0]['projection_statuses'] = ['PENDING']
    if unsafe == 'block_pending': c.manifest['deployed_medium']['blocks'][0]['restored'] = False
    if unsafe == 'archive_changed':
        old = c.folder / 'attempts/attempt-1/manifest.json'; old.chmod(0o600); old.write_text('{}')
    if unsafe == 'repeated': c.manifest['remaining_continuations'] = [{'attempt': 3}]
    if unsafe == 'cap': remaining.c['stage_authorization']['credit_ceiling'] = 12000
    if unsafe == 'quota': monkeypatch.setattr(deployed, 'current_remaining', lambda *args: 7199)
    if unsafe == 'clone': c.manifest['reference_fingerprint'] = 'other'
    if unsafe == 'duplicate_result': c.manifest['results'].append(copy.deepcopy(c.manifest['results'][-1]))
    if unsafe == 'charge_scope': ledger['entries'][0]['stage_authorization']['case_ids'] = ['C07']
    if unsafe == 'native_name': remaining.native_rows[0]['customer_name'] = 'Other identity'
    if unsafe == 'missing_reservation_projection': remaining.effects[0]['reservation_calendar_statuses'] = []
    if unsafe == 'catalog':
        def reject(*args): raise SimulationError('changed catalog')
        monkeypatch.setattr(deployed_medium, 'validate_retained_catalog', reject)
    c.save(); private_json(ledger_path, ledger)
    before = (c.folder / 'manifest.json').read_bytes()
    with pytest.raises(SimulationError): invoke(remaining)
    assert remaining.events == []
    assert (c.folder / 'manifest.json').read_bytes() == before
    assert not (c.folder / 'attempts/attempt-2').exists()


@pytest.mark.parametrize('requested', [['C08'] + SUFFIX, SUFFIX[:-1], None])
def test_only_exact_never_submitted_suffix_can_continue(remaining, requested):
    with pytest.raises(SimulationError):
        deployed.execute(remaining.c, 'medium', live=True, requested=requested,
                         run_id=remaining.campaign.run_id, continue_remaining=True)
    assert remaining.events == []


def test_workflow_and_cli_expose_explicit_remaining_flag(monkeypatch):
    from live_simulations import __main__ as cli
    seen = []
    monkeypatch.setattr(cli, 'load_config', lambda *args: {'target': 'deployed'})
    monkeypatch.setattr(workflow, 'execute', lambda *args, **kwargs: seen.append(kwargs) or {'status': 'failed', 'run_id': 'a' * 32})
    assert cli.main(['workflow', '--target', 'deployed', '--tier', 'medium', '--live',
                     '--run-id', 'a' * 32, '--cases', ','.join(SUFFIX), '--continue-remaining']) == 1
    assert seen[0]['continue_remaining'] is True


def test_saved_future_allowance_counts_only_suffix_not_already_paid_prefix(remaining, monkeypatch):
    remaining.c['budget']['remaining_credits'] = 7200
    monkeypatch.setattr(deployed, 'current_remaining', lambda *args: 7200)
    result = invoke(remaining)
    assert result['spent_credits'] == '1914'
    assert [event for event in remaining.events if event in SUFFIX] == SUFFIX
