"""Offline admission guards for the separately approved linked visit repair."""
from copy import deepcopy

import pytest

from live_simulations import deployed
from live_simulations.core import SimulationError


def authorization():
    return {'authorization_id': 'explicit-repair', 'source_run_id': 'original-run',
            'approved': True, 'retry_cases': ['C15'], 'new_cases': ['C16'], 'credit_ceiling': 11250}


def test_repair_authorization_is_explicit_and_exact():
    value = authorization()
    assert deployed._linked_repair_authorization({'linked_repair_authorization': value}, 'original-run') == value


@pytest.mark.parametrize(('field', 'value'), [('approved', False), ('approved', 1),
    ('authorization_id', ''), ('source_run_id', 'fork'), ('retry_cases', ['C14', 'C15']),
    ('new_cases', ['C15', 'C16']), ('credit_ceiling', 12000), ('credit_ceiling', True)])
def test_repair_rejects_unsafe_authorization(field, value):
    candidate = deepcopy(authorization()); candidate[field] = value
    with pytest.raises(SimulationError):
        deployed._linked_repair_authorization({'linked_repair_authorization': candidate}, 'original-run')


def test_repair_requires_authorization():
    with pytest.raises(SimulationError):
        deployed._linked_repair_authorization({}, 'original-run')


def test_book_effect_requires_exact_array_and_unique_matched_result():
    effect = {'owned_request_ids': [57, 58], 'provider_tool_name': 'book_appointment',
              'provider_request_id': 'book-owned'}
    tool = {'tool_name': 'book_appointment', 'request_id': 'book-owned', 'is_error': False,
            'result_value': {'result': {'success': True, 'appointments': [
                {'service_request_id': 57}, {'service_request_id': 58}]}}}
    saved = {'test_runs': [{'agent_responses': [{'tool_results': [tool], 'tool_calls': [
        {'tool_name': 'book_appointment', 'request_id': 'book-owned', 'params_as_json': '{}'}]}]}]}
    deployed._repair_provider_effect(saved, effect, 'C13')
    for key, value in [('is_error', True), ('request_id', 'other'), ('tool_name', 'create_service_request')]:
        bad = deepcopy(saved); bad['test_runs'][0]['agent_responses'][0]['tool_results'][0][key] = value
        with pytest.raises(SimulationError): deployed._repair_provider_effect(bad, effect, 'C13')
    for ids in ([57], [57, 58, 59]):
        bad = deepcopy(saved)
        bad['test_runs'][0]['agent_responses'][0]['tool_results'][0]['result_value']['result']['appointments'] = [
            {'service_request_id': value} for value in ids]
        with pytest.raises(SimulationError): deployed._repair_provider_effect(bad, effect, 'C13')
    saved['test_runs'][0]['agent_responses'][0]['tool_results'].append(deepcopy(tool))
    with pytest.raises(SimulationError): deployed._repair_provider_effect(saved, effect, 'C13')


@pytest.mark.parametrize('missing', ['visit_group_id', 'visit_start', 'visit_anchor_id', 'visit_member_ids', 'empty'])
def test_lookup_requires_real_native_metadata_witness(missing):
    from types import SimpleNamespace

    config = {'deployed_url': 'https://native.example.test', 'variables': {'customer_phone': '+12125550198'}}
    row = {'visit_group_id': None, 'visit_start': None, 'visit_anchor_id': None, 'visit_member_ids': []}
    rows = [row]
    if missing == 'empty': rows = []
    else: del row[missing]
    response = SimpleNamespace(status_code=200, json=lambda: {'result': {'success': True, 'appointments': rows}})
    client = SimpleNamespace(post=lambda *args, **kwargs: response)
    with pytest.raises(SimulationError): deployed._repair_lookup(config, client)


@pytest.fixture
def revision_chain(tmp_path):
    import hashlib
    import json
    from types import SimpleNamespace

    from live_simulations import agent_policy
    from live_simulations.core import fingerprint

    source = {'conversation_config': {'agent': {'prompt': {'prompt': 'Protected original prompt'}}},
              'tools': ['unchanged'], 'voice': 'unchanged'}
    v1 = agent_policy.apply_service_policy(source)
    linked = agent_policy.apply_linked_visit_policy(v1)
    revisions = []
    for i, (old, new, version) in enumerate([(source, v1, agent_policy.SERVICE_POLICY_VERSION),
                                           (v1, linked, agent_policy.LINKED_VISIT_POLICY_VERSION)]):
        path = tmp_path / f'source-{i}.json'; path.write_text(json.dumps(old))
        revisions.append({'source_override_path': path.name,
            'source_override_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'source_fingerprint': fingerprint(old), 'new_fingerprint': fingerprint(new),
            'status': 'observed', 'policy_version': version, 'agent_id': 'owned',
            'protected_reference_unchanged': True,
            'old_prompt_sha256': hashlib.sha256(old['conversation_config']['agent']['prompt']['prompt'].encode()).hexdigest(),
            'new_prompt_sha256': hashlib.sha256(new['conversation_config']['agent']['prompt']['prompt'].encode()).hexdigest()})
    campaign = SimpleNamespace(folder=tmp_path, config={'agent_id': 'protected',
        'owned_agent_linked_policy': agent_policy.LINKED_VISIT_POLICY_VERSION}, manifest={
            'agent_revisions': revisions, 'campaign_agent_id': 'owned', 'reference_fingerprint': fingerprint(v1)})
    return campaign, {'source_override': source, 'override': v1}, linked


def test_exact_two_prompt_revisions_only_change_expected_prompt(revision_chain):
    campaign, state, linked = revision_chain
    desired, extras = deployed._repair_revision(campaign, state, linked)
    assert desired == linked and len(extras) == 2


@pytest.mark.parametrize('unsafe', ['missing', 'protected', 'unobserved', 'fork', 'source_hash',
    'prompt_hash', 'voice_changed', 'wrong_policy', 'source_changed', 'current_changed'])
def test_repair_rejects_revision_chain_forks(revision_chain, unsafe):
    campaign, state, actual = revision_chain
    second = campaign.manifest['agent_revisions'][1]
    if unsafe == 'missing': campaign.manifest['agent_revisions'].pop()
    if unsafe == 'protected': second['agent_id'] = 'protected'
    if unsafe == 'unobserved': second['status'] = 'pending'
    if unsafe == 'fork': second['source_fingerprint'] = 'fork'
    if unsafe == 'source_hash': second['source_override_sha256'] = 'other'
    if unsafe == 'prompt_hash': second['new_prompt_sha256'] = 'other'
    if unsafe == 'voice_changed': actual['voice'] = 'different'
    if unsafe == 'wrong_policy': campaign.config['owned_agent_linked_policy'] = 'arbitrary'
    if unsafe == 'source_changed': state['source_override']['tools'] = ['different']
    if unsafe == 'current_changed': campaign.manifest['reference_fingerprint'] = 'different'
    with pytest.raises(SimulationError): deployed._repair_revision(campaign, state, actual)


# Reuse the captured provider and immutable history fixtures; no native I/O.
from tests.test_deployed_monotonic_recovery import captured as captured_fixture
from tests.test_deployed_monotonic_recovery import monotonic as monotonic_fixture
from tests.test_deployed_monotonic_recovery import ready as ready_fixture
from tests.test_deployed_monotonic_recovery import remaining as remaining_fixture
from tests.test_deployed_monotonic_recovery import unpaid as unpaid_fixture

captured = captured_fixture
monotonic = monotonic_fixture
ready = ready_fixture
remaining = remaining_fixture
unpaid = unpaid_fixture


@pytest.fixture
def repair_prefix(monotonic):
    import hashlib
    import json

    from live_simulations.core import fingerprint, private_json

    state, campaign = monotonic, monotonic.campaign
    ledger_path = campaign.root / 'usage-ledger.json'
    ledger = json.loads(ledger_path.read_text())
    prior = campaign.manifest['unsubmitted_continuations'][-1]
    deployed._archive_unpaid(campaign, ledger, previous_attempt=4, kind='unsubmitted_continuations',
        selected=[f'C{i:02}' for i in range(11, 17)], prior_spent=2500,
        metadata={'agent_revision_fingerprint': fingerprint(state.desired),
                  'agent_revision_source_fingerprint': fingerprint(state.source),
                  'previous_admission_sha256': hashlib.sha256(json.dumps(prior, sort_keys=True).encode()).hexdigest()})
    ledger = json.loads(ledger_path.read_text())
    for cid, credits in zip([f'C{i:02}' for i in range(11, 16)], [722, 619, 649, 498, 409]):
        ledger['entries'].append({'run_id': campaign.run_id, 'case_id': cid, 'test_id': 'test-' + cid,
            'invocation_id': 'suite-' + cid, 'credits': str(credits), 'unsettled': False,
            'authorization_id': state.c['stage_authorization']['authorization_id'],
            'stage_authorization': deepcopy(state.c['stage_authorization'])})
        campaign.manifest['provider_tests'].append('test-' + cid)
        campaign.manifest['invocations'].append('suite-' + cid)
    campaign.manifest.update(status='failed', spent_credits='5397')
    campaign.manifest['deployed_medium']['current_case'] = 'C16'
    campaign.manifest['results'].append({'case_id': 'C15', 'attempt': 5, 'repeat': 1,
                                        'functional_status': 'failed', 'status': 'failed'})
    private_json(campaign.folder / 'C15-1-evidence.json', {'checks': [
        {'name': 'exact requested visit start', 'passed': False}]})
    private_json(ledger_path, ledger); campaign.save()
    state.ledger = ledger
    return state


def test_nine_case_prefix_preserves_failed_c15_and_has_5397_actual_credits(repair_prefix):
    state = repair_prefix
    charges, _ = deployed._repair_prefix(state.campaign, state.ledger,
        state.c['stage_authorization'], {**authorization(), 'source_run_id': state.campaign.run_id})
    assert len(charges) == 9 and sum(int(e['credits']) for e in charges) == 5397


@pytest.mark.parametrize('unsafe', ['reused', 'ledger_reused', 'global_unknown', 'spent', 'prefix_credit',
    'prefix_identity', 'current_ids', 'unknown_operation', 'c16_intent', 'c15_pass', 'native_start_pass',
    'duplicate_test', 'pending', 'claim', 'no_progress', 'prior_archive', 'original_cap'])
def test_repair_prefix_rejects_unsafe_state_without_mutation(repair_prefix, unsafe):
    import json

    state = repair_prefix; campaign = state.campaign; manifest = campaign.manifest; ledger = state.ledger
    if unsafe == 'reused': manifest['repair_admissions'] = [{}]
    if unsafe == 'ledger_reused': ledger['repair_admissions'] = [{'run_id': campaign.run_id}]
    if unsafe == 'global_unknown': ledger['entries'].append({'run_id': 'other', 'unsettled': True})
    if unsafe == 'spent': manifest['spent_credits'] = '0'
    if unsafe == 'prefix_credit': ledger['entries'][-1]['credits'] = '408'
    if unsafe == 'prefix_identity': ledger['entries'][-1]['run_id'] = 'other'
    if unsafe == 'current_ids': manifest['deployed_medium']['current_request_ids'] = [62]
    if unsafe == 'unknown_operation': manifest['deployed_medium']['operations'].append({'status': 'unknown'})
    if unsafe == 'c16_intent': manifest['test_creation_intents'] = [{'case_id': 'C16', 'status': 'cleared'}]
    if unsafe == 'c15_pass': manifest['results'][-1]['functional_status'] = 'passed'
    if unsafe == 'native_start_pass':
        (campaign.folder / 'C15-1-evidence.json').write_text(json.dumps({'checks': []}))
    if unsafe == 'duplicate_test': manifest['provider_tests'][-1] = manifest['provider_tests'][-2]
    if unsafe == 'pending': manifest['test_create_pending'] = 'C16'
    if unsafe == 'claim': ledger['stage_authorizations'] = []
    if unsafe == 'original_cap':
        state.c['stage_authorization']['credit_ceiling'] = 12000
        manifest['stage_authorization']['credit_ceiling'] = 12000
        ledger['stage_authorizations'][0]['credit_ceiling'] = 12000
        for entry in ledger['entries']: entry['stage_authorization']['credit_ceiling'] = 12000
    if unsafe == 'no_progress': manifest['unsubmitted_continuations'].pop()
    if unsafe == 'prior_archive': manifest['unsubmitted_continuations'][0]['files_sha256']['manifest.json'] = 'other'
    before = (campaign.folder / 'manifest.json').read_bytes()
    with pytest.raises(SimulationError):
        deployed._repair_prefix(campaign, ledger, state.c['stage_authorization'],
                                {**authorization(), 'source_run_id': campaign.run_id})
    assert (campaign.folder / 'manifest.json').read_bytes() == before


def test_provider_effect_requires_matched_call_and_result():
    effect = {'owned_request_ids': [51], 'provider_tool_name': 'create_service_request',
              'provider_request_id': 'owned-call'}
    result = {'tool_name': 'create_service_request', 'request_id': 'owned-call', 'is_error': False,
              'result_value': {'success': True, 'service_request_id': 51}}
    saved = {'test_runs': [{'agent_responses': [{'tool_results': [result]}]}]}
    with pytest.raises(SimulationError): deployed._repair_provider_effect(saved, effect, 'C08')


def test_captured_public_repair_offsets_preserve_old_artifacts_and_total_budget(repair_prefix, monkeypatch):
    import json

    from live_simulations.core import private_json

    state = repair_prefix; campaign = state.campaign
    state.c['linked_repair_authorization'] = {**authorization(), 'source_run_id': campaign.run_id}
    for cid, credits in zip([f'C{i:02}' for i in range(11, 16)], [722, 619, 649, 498, 409]):
        result = {'id': 'suite-' + cid, 'agent_id': 'owned-clone', 'test_runs': [{
            'test_id': 'test-' + cid, 'test_invocation_id': 'suite-' + cid,
            'status': 'passed', 'credits_used': credits}]}
        private_json(campaign.folder / (cid + '-1-provider.json'), result)
        state.prefix_receipts['suite-' + cid] = result
    (campaign.folder / 'C15-portal.png').write_bytes(b'old-png')
    old = {name: (campaign.folder / name).read_bytes() for name in ('C15-1-provider.json', 'C15-1-evidence.json', 'C15-portal.png')}
    campaign.manifest['stage_case_outcomes'] = {'C07': 'passed', 'C08': 'failed', 'C09': 'failed', 'C10': 'failed', 'C15': 'failed'}
    campaign.save()
    monkeypatch.setattr(deployed, '_repair_settlement', lambda *args: ({'owned_request_ids': [51,52,53,54]}, []))
    monkeypatch.setattr(deployed, '_repair_revision', lambda *args: (state.desired, []))
    monkeypatch.setattr(deployed, '_repair_lookup', lambda *args: state.events.append('lookup-capability'))
    monkeypatch.setattr(deployed, 'current_remaining', lambda *args: 1800)
    result = deployed.execute(state.c, 'medium', live=True, run_id=campaign.run_id,
                              requested=['C15', 'C16'], repair_linked_visit=True)
    assert [event for event in state.events if event in [f'C{i:02}' for i in range(7,17)]] == ['C15','C16']
    assert state.events.index('lookup-capability') < state.events.index('C15')
    assert 'clone' not in state.events and 'catalog' not in state.events
    assert result['spent_credits'] == '5597'
    assert result['stage_case_outcomes']['C15'] == 'failed'
    assert result['latest_attempt_functional_status'] == 'passed'
    assert [row['repeat'] for row in result['results'][-2:]] == [2,1]
    assert (campaign.folder / 'C15-2-provider.json').exists()
    assert (campaign.folder / 'C16-1-provider.json').exists()
    for name, data in old.items(): assert (campaign.folder / name).read_bytes() == data
    ledger = json.loads((campaign.root / 'usage-ledger.json').read_text())
    assert len(ledger['stage_authorizations']) == 1 and len(ledger['repair_admissions']) == 1
    assert [row['repeat'] for row in ledger['entries'][-2:]] == [2,1]
    with pytest.raises(SimulationError):
        deployed.execute(state.c, 'medium', live=True, run_id=campaign.run_id,
                         requested=['C15','C16'], repair_linked_visit=True)
