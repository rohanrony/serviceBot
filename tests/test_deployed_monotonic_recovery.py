"""Pure offline monotonic recovery: immutable paid prefix grows; suffix never replays."""
import copy
import hashlib
import json

import pytest

from live_simulations import deployed
from live_simulations.core import SimulationError, fingerprint, private_json
from tests.test_deployed_unsubmitted_recovery import archive
from tests.test_deployed_unsubmitted_recovery import captured as captured_fixture
from tests.test_deployed_unsubmitted_recovery import ready as ready_fixture
from tests.test_deployed_unsubmitted_recovery import remaining as remaining_fixture
from tests.test_deployed_unsubmitted_recovery import unpaid as unpaid_fixture

captured = captured_fixture
unpaid = unpaid_fixture
remaining = remaining_fixture
ready = ready_fixture
SUFFIX = [f'C{i:02}' for i in range(11, 17)]


def canonical(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


@pytest.fixture
def monotonic(ready):
    s, c = ready, ready.campaign
    ledger_path = c.root / 'usage-ledger.json'
    ledger = json.loads(ledger_path.read_text())
    prior = c.manifest['remaining_continuations'][0]
    deployed._archive_unpaid(c, ledger, previous_attempt=3, kind='unsubmitted_continuations',
        extra_names=['reconciliation/c09-effect-cleanup.json'], selected=[f'C{i:02}' for i in range(10, 17)],
        prior_spent=2019, metadata={'agent_revision_fingerprint': fingerprint(s.desired),
            'agent_revision_source_fingerprint': fingerprint(s.source),
            'previous_admission_sha256': hashlib.sha256(json.dumps(prior, sort_keys=True).encode()).hexdigest()})
    result = {'id': 'suite-C10', 'agent_id': 'owned-clone', 'test_runs': [{
        'test_id': 'test-C10', 'test_invocation_id': 'suite-C10', 'status': 'failed', 'credits_used': 481,
        'agent_responses': []}]}
    private_json(c.folder / 'C10-1-provider.json', result)
    s.prefix_receipts['suite-C10'] = result
    ledger = json.loads(ledger_path.read_text())
    ledger['entries'].append({'run_id': c.run_id, 'case_id': 'C10', 'test_id': 'test-C10',
        'invocation_id': 'suite-C10', 'credits': '481', 'unsettled': False,
        'authorization_id': s.c['stage_authorization']['authorization_id'],
        'stage_authorization': copy.deepcopy(s.c['stage_authorization'])})
    private_json(ledger_path, ledger)
    c.manifest.update(status='failed', spent_credits='2500', aggregate_spent_credits='2500',
                      reference_fingerprint=fingerprint(s.desired))
    c.manifest['provider_tests'].append('test-C10'); c.manifest['invocations'].append('suite-C10')
    c.manifest['results'].extend({'case_id': cid, 'attempt': 4, 'repeat': 1, 'status': 'failed' if cid == 'C10' else 'blocked',
        'functional_status': 'failed' if cid == 'C10' else 'blocked',
        'reason': 'prefix evaluation failed' if cid == 'C10' else 'Unresolved stage resource, cleanup or charge; no further paid work'}
        for cid in ['C10'] + SUFFIX)
    fixture = c.manifest['deployed_medium']
    indices = []
    for request_id in (53, 54):
        indices.append(len(fixture['operations']))
        fixture['operations'].append({'method': 'POST', 'path': '/api/v1/voice/tools',
            'body': {'name': 'create_service_request', 'arguments': {'phone': s.c['variables']['customer_phone'],
                'customer_name': 'Original', 'service_type': 'Owned service'}},
            'status': 'observed', 'ids': [request_id]})
        s.native_rows.append({'id': request_id, 'customer_id': 5, 'customer_phone': s.c['variables']['customer_phone'],
            'customer_name': 'Original', 'status': 'cancelled', 'reservation_id': None})
        s.effects.append({**copy.deepcopy(s.effects[0]), 'id': request_id})
    fixture.update(owned_request_ids=[51, 52, 53, 54], current_case='C10')
    c.save(); c.report()
    archive(c, 'attempts/attempt-4-before-reconciliation')
    operations = [fixture['operations'][index] for index in indices]
    receipt = {'run_id': c.run_id, 'case_id': 'C10', 'status': 'settled', 'owned_request_ids': [53, 54],
        'cancelled_request_ids': [53, 54], 'restored_block_ids': [], 'provenance': 'native_fixture_operations',
        'fixture_operation_indices': indices, 'fixture_operations_sha256': canonical(operations),
        'provider_receipt_sha256': hashlib.sha256((c.folder / 'C10-1-provider.json').read_bytes()).hexdigest(),
        'pre_reconciliation_archive': 'attempts/attempt-4-before-reconciliation', 'baseline_unchanged': True,
        'identity_verified': True, 'google_current_event_deleted': True, 'native_calendar_effects_settled': True,
        'ambiguous_cancel_reconciled': True}
    path = c.folder / 'reconciliation/c10-effect-cleanup.json'; private_json(path, receipt)
    c.manifest['reconciliations'].append({'path': 'reconciliation/c10-effect-cleanup.json',
                                         'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    c.save(); c.report()
    s.receipt10, s.operation_indices = path, indices
    return s


def invoke(s, requested=SUFFIX):
    return deployed.execute(s.c, 'medium', live=True, run_id=s.campaign.run_id,
                            requested=requested, continue_unsubmitted=True)


def test_monotonic_prefix_growth_uses_six_cases_and_current_revision(monotonic, monkeypatch):
    monotonic.c['budget']['remaining_credits'] = 5400
    monkeypatch.setattr(deployed, 'current_remaining', lambda *args: 5400)
    result = invoke(monotonic)
    assert [event for event in monotonic.events if event in [f'C{i:02}' for i in range(7, 17)]] == SUFFIX
    assert result['spent_credits'] == '3100'
    assert result['stage_functional_status'] == 'failed' and result['latest_attempt_functional_status'] == 'passed'
    assert all(result['stage_case_outcomes'][cid] == 'failed' for cid in ('C08', 'C09', 'C10'))
    assert [record['attempt'] for record in result['unsubmitted_continuations']] == [4, 5]
    assert result['unsubmitted_continuations'][-1]['prior_spent_credits'] == '2500'
    assert all(row['attempt'] == 5 for row in result['results'][-6:])
    assert 'clone' not in monotonic.events and 'catalog' not in monotonic.events
    with pytest.raises(SimulationError): invoke(monotonic)


@pytest.mark.parametrize('unsafe', ['paid_replay', 'gap', 'no_progress', 'history_hash', 'history_ledger',
    'pending_charge', 'global_unknown', 'suffix_intent', 'fixture_hash', 'fixture_indices', 'fixture_wrong_method',
    'request_active', 'revision_stale', 'quota', 'prefix_credits', 'prior_admission_scope'])
def test_monotonic_admission_rejects_unsafe_history_without_effect(monotonic, monkeypatch, unsafe):
    c = monotonic.campaign; ledger_path = c.root / 'usage-ledger.json'
    ledger = json.loads(ledger_path.read_text()); requested = SUFFIX
    if unsafe == 'paid_replay': requested = ['C10'] + SUFFIX
    if unsafe == 'gap': requested = SUFFIX[1:]
    if unsafe == 'no_progress': ledger['entries'].pop(); c.manifest['provider_tests'].pop(); c.manifest['invocations'].pop()
    if unsafe == 'history_hash': c.manifest['unsubmitted_continuations'][0]['previous_admission_sha256'] = 'other'
    if unsafe == 'history_ledger': ledger['unsubmitted_continuations'] = []
    if unsafe == 'prior_admission_scope': c.manifest['unsubmitted_continuations'][0]['selected'] = SUFFIX
    if unsafe == 'pending_charge': ledger['entries'][-1]['unsettled'] = True
    if unsafe == 'global_unknown': ledger['entries'].append({'run_id': 'another', 'unsettled': True})
    if unsafe == 'suffix_intent': c.manifest['test_creation_intents'] = [{'case_id': 'C11', 'status': 'cleared'}]
    if unsafe in ('fixture_hash', 'fixture_indices', 'fixture_wrong_method'):
        receipt = json.loads(monotonic.receipt10.read_text())
        if unsafe == 'fixture_hash': receipt['fixture_operations_sha256'] = 'other'
        if unsafe == 'fixture_indices': receipt['fixture_operation_indices'] = [0, 1]
        if unsafe == 'fixture_wrong_method':
            c.manifest['deployed_medium']['operations'][monotonic.operation_indices[0]]['method'] = 'DELETE'
        private_json(monotonic.receipt10, receipt)
        c.manifest['reconciliations'][-1]['sha256'] = hashlib.sha256(monotonic.receipt10.read_bytes()).hexdigest()
    if unsafe == 'request_active': monotonic.native_rows[-1]['status'] = 'confirmed'
    if unsafe == 'revision_stale': c.manifest['reference_fingerprint'] = fingerprint(monotonic.source)
    if unsafe == 'quota': monkeypatch.setattr(deployed, 'current_remaining', lambda *args: 5399)
    if unsafe == 'prefix_credits': ledger['entries'][-1]['credits'] = '480'
    c.save(); private_json(ledger_path, ledger); before = (c.folder / 'manifest.json').read_bytes()
    with pytest.raises(SimulationError): invoke(monotonic, requested)
    assert monotonic.events == []
    assert (c.folder / 'manifest.json').read_bytes() == before
    assert not (c.folder / 'attempts/attempt-4').exists()
