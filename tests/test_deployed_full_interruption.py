"""Synthetic offline C48 state-machine contracts, not native interruption proof."""
import copy
import json

import pytest

from live_simulations.core import SimulationError, fingerprint, private_json
from live_simulations.deployed_full_interruption import Binding, advance


def receipt(status, credits=None):
    return {'id': 'invocation-48', 'agent_id': 'owned-agent', 'cancelled': status == 'cancelled', 'test_runs': [{
        'test_id': 'test-48', 'test_invocation_id': 'invocation-48', 'status': status,
        'credits_used': credits, 'agent_responses': [
            {'tool_calls': [{'type': 'webhook', 'request_id': 'call-48', 'tool_name': 'book_appointment',
                             'tool_has_been_called': True,
                             'params_as_json': json.dumps({'service_type': 'Oil Change'}),
                             'tool_details': {'type': 'webhook', 'method': 'POST',
                                              'url': 'https://owned.invalid/api/v1/voice/tools?name=book_appointment'}}]},
            {'tool_results': [{'tool_name': 'book_appointment', 'request_id': 'call-48',
                               'is_error': False, 'result_value': json.dumps({'result': {
                                   'success': True, 'appointment_id': 31, 'appointments': [{
                                       'service_request_id': 31, 'reservation_id': 41, 'staff_agent_id': 4,
                                       'booking_time': '2026-11-11 10:00:00', 'duration_minutes': 60,
                                       'service_type': 'Oil Change', 'booking_type': 'appointment'}]}})}]}]}]}


@pytest.fixture
def setup(tmp_path):
    binding = Binding(run_id='a' * 32, case_id='C48', attempt=1, test_id='test-48',
                      agent_id='owned-agent', invocation_id='invocation-48')
    folder = tmp_path / binding.run_id
    expected = {'customer_id': 9, 'service_type': 'Oil Change', 'staff_agent_id': 4,
                'starts_at': '2026-11-11T10:00:00-05:00', 'ends_at': '2026-11-11T11:00:00-05:00',
                'duration_minutes': 60}
    journal = {'schema_version': 1, 'binding': binding.as_dict(), 'baseline': {
        'source': 'native_postgresql', 'customer_id': 9, 'observed_at_unix': 100, 'request_ids': [10], 'reservation_ids': [20], 'active_request_ids': []},
        'submitted_at_unix': 101, 'expected_booking': expected,
        'tool_url': 'https://owned.invalid/api/v1/voice/tools?name=book_appointment'}
    pre = {'schema_version': 1, 'binding': {k: v for k, v in binding.as_dict().items() if k != 'invocation_id'},
           **{k: journal[k] for k in ('baseline', 'expected_booking', 'tool_url')},
           'test_definition': {'id': binding.test_id, 'type': 'simulation', 'tool_mock_config': {
               'mocking_strategy': 'none', 'fallback_strategy': 'call_real_tool', 'mocked_tool_ids': []}},
           'invocation_request': {'tests': [{'test_id': binding.test_id}], 'repeat_count': 1}}
    private_json(folder / 'C48-1-pre-invocation.json', pre)
    journal['pre_invocation_sha256'] = fingerprint(pre)
    private_json(folder / 'C48-1-interruption-journal.json', journal)
    private_json(folder / 'manifest.json', {'run_id': binding.run_id, 'campaign_agent_id': binding.agent_id,
                                          'invocations': [binding.invocation_id], 'provider_tests': [binding.test_id]})
    private_json(tmp_path / 'usage-ledger.json', {'entries': [{**binding.as_dict(), 'unsettled': True,
                                                             'interruption_journal_sha256': fingerprint(journal),
                                                             'pre_invocation_sha256': fingerprint(pre)}]})
    booking = {'source': 'native_postgresql', 'customer_id': 9,
               'requests': [{'id': 31, 'customer_id': 9, 'service_type': 'Oil Change', 'status': 'pending',
                             'booking_type': 'appointment', 'duration_minutes': 60, 'staff_agent_id': 4,
                             'booking_start_at': expected['starts_at'], 'booking_end_at': expected['ends_at']}],
               'reservations': [{'id': 41, 'service_request_id': 31, 'staff_agent_id': 4, 'status': 'ACTIVE',
                                 'starts_at': expected['starts_at'], 'ends_at': expected['ends_at']}],
               'segments': [{'reservation_id': 41, 'staff_agent_id': 4,
                             'segment_start': f'2026-11-11T10:{minute:02}:00-05:00'} for minute in (0, 15, 30, 45)]}
    class Provider:
        def __init__(self):
            self.responses = [receipt('pending'), receipt('cancelled', 17)]
            self.cancels = []
            self.gets = []
            self.cancel_error = False
        def get(self, invocation):
            self.gets.append(invocation)
            return copy.deepcopy(self.responses.pop(0) if len(self.responses) > 1 else self.responses[0])
        def cancel(self, invocation):
            intent = folder / 'C48-1-cancel-intent.json'
            assert intent.exists(), 'intent must be durable before provider write'
            self.cancels.append(invocation)
            if self.cancel_error:
                raise SimulationError('ambiguous write')
    return tmp_path, binding, journal, booking, Provider()


def run(setup, **kwargs):
    root, binding, _, booking, provider = setup
    return advance(root, binding=binding, provider=provider,
                   observe_booking=lambda: copy.deepcopy(booking), **kwargs)


def test_owned_canonical_catalog_service_is_used_in_native_and_provider_proof(setup):
    from live_simulations.deployed_full_interruption import _booking, _executed_booking
    _, _, journal, booking, _ = setup
    name = 'full_owned_20261019 Oil Change'
    journal['expected_booking']['service_type'] = name
    booking['requests'][0]['service_type'] = name
    run_receipt = receipt('cancelled', 17)['test_runs'][0]
    call = run_receipt['agent_responses'][0]['tool_calls'][0]
    call['params_as_json'] = json.dumps({'service_type': name})
    result = run_receipt['agent_responses'][1]['tool_results'][0]
    payload = json.loads(result['result_value'])
    payload['result']['appointments'][0]['service_type'] = name
    result['result_value'] = json.dumps(payload)
    assert _booking(booking, journal) == booking
    assert _executed_booking(run_receipt, journal, booking)['native_request_id'] == 31
    call['params_as_json'] = json.dumps({'service_type': 'Oil Change'})
    with pytest.raises(SimulationError):
        _executed_booking(run_receipt, journal, booking)


def test_verified_interruption_is_not_recovery_or_full_support(setup):
    result = run(setup)
    assert result['status'] == 'verified_interruption'
    assert result['interruption_verified'] is True
    assert result['recovery_booking_prerequisites_verified'] is True
    assert result['recovery_prerequisites_verified'] is False
    assert 'separate_paid_budget' in result['remaining_recovery_prerequisites']
    assert result['recovery_started'] is False
    assert result['full_case_supported'] is False
    assert result['global_stop'] is False
    assert setup[4].cancels == ['invocation-48']
    ledger = json.loads((setup[0] / 'usage-ledger.json').read_text())
    assert ledger['entries'][0]['credits'] == '17'
    assert ledger['entries'][0]['unsettled'] is False


@pytest.mark.parametrize('key,value', [('case_id', 'C47'), ('attempt', 2), ('invocation_id', 'other'),
                                     ('agent_id', 'other'), ('test_id', 'other'), ('run_id', 'b' * 32)])
def test_exact_journal_ownership_required_before_provider_access(setup, key, value):
    values = setup[1].as_dict() | {key: value}
    with pytest.raises(SimulationError):
        advance(setup[0], binding=Binding(**values), provider=setup[4], observe_booking=lambda: setup[3])
    assert setup[4].gets == setup[4].cancels == []


@pytest.mark.parametrize('status', ['passed', 'failed', 'cancelled'])
def test_completion_before_cancel_is_failed_interruption_but_settles_charge(setup, status):
    setup[4].responses = [receipt(status, 19)]
    result = run(setup)
    assert result['interruption_verified'] is False
    assert result['status'] == 'failed_interruption'
    assert setup[4].cancels == []
    assert result['credits'] == '19'


@pytest.mark.parametrize('change', ['seeded_request', 'seeded_reservation', 'duplicate', 'reservation', 'segments'])
def test_pending_without_genuine_new_owned_booking_never_cancels(setup, change):
    booking = setup[3]
    if change == 'seeded_request': booking['requests'][0]['id'] = 10
    if change == 'seeded_reservation': booking['reservations'][0]['id'] = 20
    if change == 'duplicate': booking['requests'].append(copy.deepcopy(booking['requests'][0]))
    if change == 'reservation': booking['reservations'][0]['service_request_id'] = 999
    if change == 'segments': booking['segments'].pop()
    result = run(setup)
    assert result['global_stop'] is True
    assert result['interruption_verified'] is False
    assert setup[4].cancels == []


def test_ambiguous_cancel_resumes_get_only_and_never_writes_twice(setup):
    setup[4].cancel_error = True
    first = run(setup)
    assert first['global_stop'] is True
    assert len(setup[4].cancels) == 1
    setup[4].cancel_error = False
    resumed = run(setup, reconcile_only=True)
    assert resumed['interruption_verified'] is True
    assert len(setup[4].cancels) == 1
    assert set(setup[4].gets) == {'invocation-48'}
    assert run(setup)['credits'] == '17'
    assert len(setup[4].cancels) == 1


def test_timeout_never_uses_wait_or_repeats_cancel(setup):
    setup[4].responses = [receipt('pending')]
    result = run(setup, max_polls=2)
    assert result['global_stop'] is True
    assert result['status'] == 'awaiting_terminal'
    assert len(setup[4].cancels) == 1
    result = run(setup, reconcile_only=True, max_polls=1)
    assert result['global_stop'] is True
    assert len(setup[4].cancels) == 1


@pytest.mark.parametrize('change', ['credits', 'tool_result', 'call_pair', 'mock', 'http', 'identity', 'status'])
def test_terminal_uncertainty_cannot_become_interruption_proof(setup, change):
    terminal = setup[4].responses[-1]
    test_run = terminal['test_runs'][0]
    call = test_run['agent_responses'][0]['tool_calls'][0]
    result = test_run['agent_responses'][1]['tool_results'][0]
    if change == 'credits': test_run['credits_used'] = None
    if change == 'tool_result': result['result_value'] = {'result': {'success': True, 'appointment_id': 99}}
    if change == 'call_pair': result['request_id'] = 'other'
    if change == 'mock': call['tool_has_been_called'] = False
    if change == 'http': call['tool_details']['url'] = 'https://other.invalid/api/v1/voice/tools'
    if change == 'identity': terminal['agent_id'] = 'foreign'
    if change == 'status': test_run['status'] = 'passed'
    outcome = run(setup)
    assert outcome['interruption_verified'] is False
    assert outcome['recovery_prerequisites_verified'] is False
    if change != 'status': assert outcome['global_stop'] is True


def test_changed_booking_after_cancel_blocks_recovery(setup):
    calls = 0
    def observe():
        nonlocal calls
        calls += 1
        booking = copy.deepcopy(setup[3])
        if calls > 1: booking['requests'][0]['status'] = 'cancelled'
        return booking
    outcome = advance(setup[0], binding=setup[1], provider=setup[4], observe_booking=observe)
    assert outcome['global_stop'] is True
    assert outcome['interruption_verified'] is False


def test_read_only_reconcile_without_intent_never_cancels(setup):
    outcome = run(setup, reconcile_only=True)
    assert outcome['interruption_verified'] is False
    assert setup[4].cancels == []


def test_foreign_extra_run_and_invalid_credits_rejected(setup):
    setup[4].responses[-1]['test_runs'].append(receipt('cancelled', 0)['test_runs'][0])
    assert run(setup)['global_stop'] is True


def test_settlement_is_idempotent_but_conflicting_existing_charge_blocks(setup):
    run(setup)
    path = setup[0] / 'usage-ledger.json'
    ledger = json.loads(path.read_text())
    ledger['entries'][0]['credits'] = '999'
    private_json(path, ledger)
    with pytest.raises(SimulationError): run(setup)
    assert len(setup[4].cancels) == 1


@pytest.mark.parametrize('change', ['missing_baseline', 'late_baseline', 'active_baseline', 'unbound_journal', 'duplicate_charge'])
def test_preinvocation_baseline_cannot_be_retrofitted(setup, change):
    root, binding, journal, _, provider = setup
    journal = copy.deepcopy(journal)
    if change == 'missing_baseline': journal.pop('baseline')
    if change == 'late_baseline': journal['baseline']['observed_at_unix'] = 102
    if change == 'active_baseline': journal['baseline']['active_request_ids'] = [31]
    path = root / 'usage-ledger.json'
    ledger = json.loads(path.read_text())
    if change == 'duplicate_charge': ledger['entries'].append(copy.deepcopy(ledger['entries'][0]))
    if change != 'unbound_journal': ledger['entries'][0]['interruption_journal_sha256'] = fingerprint(journal)
    else: journal['expected_booking']['staff_agent_id'] = 99
    private_json(root / binding.run_id / 'C48-1-interruption-journal.json', journal)
    private_json(path, ledger)
    with pytest.raises(SimulationError): run(setup)
    assert provider.gets == provider.cancels == []


@pytest.mark.parametrize('failure', ['exclusive_write', 'file_fsync', 'directory_fsync'])
def test_intent_durability_failure_never_calls_cancel(setup, monkeypatch, failure):
    from live_simulations import deployed_full_interruption as controller

    def fail(*args, **kwargs): raise OSError('private filesystem diagnostic')
    if failure == 'exclusive_write': monkeypatch.setattr(controller, '_intent', fail)
    elif failure == 'file_fsync': monkeypatch.setattr(controller.os, 'fsync', fail)
    else: monkeypatch.setattr(controller, '_sync_directory', fail)
    # Even saving the stop report can fail on a broken disk. Nothing writes to provider.
    try:
        outcome = run(setup)
        assert outcome['global_stop'] is True
    except OSError:
        pass
    assert setup[4].cancels == []


def test_crash_after_intent_before_cancel_resumes_without_cancel_post(setup, monkeypatch):
    class ProcessCrash(BaseException):
        pass
    def crash(invocation): raise ProcessCrash
    monkeypatch.setattr(setup[4], 'cancel', crash)
    with pytest.raises(ProcessCrash): run(setup)
    assert (setup[0] / setup[1].run_id / 'C48-1-cancel-intent.json').exists()
    setup[4].responses = [receipt('pending')]
    result = run(setup, max_polls=1)
    assert result['status'] == 'awaiting_terminal'
    assert setup[4].cancels == []


def test_campaign_lock_prevents_concurrent_owner_from_cancelling(setup):
    from live_simulations.runner import campaign_lock

    with campaign_lock(setup[0]), pytest.raises(SimulationError, match='Another campaign'):
        run(setup)
    assert setup[4].gets == setup[4].cancels == []


def test_provider_get_timeout_after_intent_resumes_same_handle_only(setup):
    run(setup, max_polls=1)
    calls = len(setup[4].cancels)
    setup[4].get = lambda _: (_ for _ in ()).throw(SimulationError('provider unavailable'))
    assert run(setup)['global_stop'] is True
    assert len(setup[4].cancels) == calls == 1


@pytest.mark.parametrize('value', [-1, 'NaN', True, 'infinity'])
def test_invalid_actual_credit_values_block_global_progress(setup, value):
    setup[4].responses[-1]['test_runs'][0]['credits_used'] = value
    result = run(setup)
    assert result['global_stop'] is True
    assert result['interruption_verified'] is False
    assert json.loads((setup[0] / 'usage-ledger.json').read_text())['entries'][0]['unsettled'] is True


def test_top_level_cancelled_flag_is_not_terminal_run_evidence(setup):
    pending = receipt('pending') | {'cancelled': True}
    setup[4].responses = [pending]
    outcome = run(setup, max_polls=1)
    assert outcome['interruption_verified'] is False
    assert outcome['global_stop'] is True


@pytest.mark.parametrize('field,value', [('service_request_id', 99), ('reservation_id', 99), ('staff_agent_id', 99),
                                       ('booking_time', '2026-11-11 11:00:00'), ('duration_minutes', 90),
                                       ('booking_type', 'callback')])
def test_provider_returned_appointment_must_match_native_reservation(setup, field, value):
    result = setup[4].responses[-1]['test_runs'][0]['agent_responses'][1]['tool_results'][0]
    envelope = json.loads(result['result_value'])
    envelope['result']['appointments'][0][field] = value
    result['result_value'] = envelope
    assert run(setup)['interruption_verified'] is False


def test_unrelated_common_ledger_entries_preserved_and_unknown_charge_blocks_progress(setup):
    path = setup[0] / 'usage-ledger.json'
    ledger = json.loads(path.read_text())
    unrelated = {'run_id': 'b' * 32, 'case_id': 'C17', 'invocation_id': 'other', 'unsettled': True,
                 'nested': {'preserve': [1, 2]}}
    ledger['entries'].append(copy.deepcopy(unrelated))
    ledger['other_metadata'] = {'retain': 7}
    private_json(path, ledger)
    outcome = run(setup)
    assert outcome['interruption_verified'] is True
    assert outcome['global_stop'] is True
    assert outcome['recovery_prerequisites_verified'] is False
    after = json.loads(path.read_text())
    assert after['entries'][1] == unrelated
    assert after['other_metadata'] == ledger['other_metadata']


def test_cancel_ack_without_terminal_receipt_is_not_proof(setup):
    setup[4].responses = [receipt('pending')]
    assert run(setup, max_polls=1)['interruption_verified'] is False
    assert len(setup[4].cancels) == 1


def test_no_agent_test_paid_run_or_wait_interface_is_needed(setup):
    assert set(vars(type(setup[4]))) >= {'get', 'cancel'}
    assert not hasattr(setup[4], 'run') and not hasattr(setup[4], 'wait')
    assert run(setup)['interruption_verified'] is True


def test_unknown_terminal_charge_can_reconcile_later_without_second_cancel(setup):
    setup[4].responses[-1]['test_runs'][0]['credits_used'] = None
    first = run(setup)
    assert first['global_stop'] is True
    assert json.loads((setup[0] / 'usage-ledger.json').read_text())['entries'][0]['unsettled'] is True
    setup[4].responses = [receipt('cancelled', 23)]
    later = run(setup, reconcile_only=True)
    assert later['interruption_verified'] is True and later['credits'] == '23'
    assert len(setup[4].cancels) == 1
    assert len(list((setup[0] / setup[1].run_id).glob('C48-1-terminal-*.json'))) == 2


def test_durable_evidence_excludes_provider_secrets(setup):
    setup[4].responses[-1]['test_runs'][0]['agent_responses'][0]['tool_calls'][0]['tool_details']['headers'] = {
        'Authorization': 'secret-private-value'}
    assert run(setup)['interruption_verified'] is True
    files = list((setup[0] / setup[1].run_id).glob('*.json'))
    assert all('secret-private-value' not in path.read_text() for path in files)
    assert any('[redacted]' in path.read_text() for path in files)


@pytest.mark.parametrize('change', ['unknown_status', 'foreign_test', 'foreign_invocation', 'no_runs', 'foreign_agent'])
def test_pending_provider_scope_is_verified_before_cancellation(setup, change):
    pending = setup[4].responses[0]
    if change == 'unknown_status': pending['test_runs'][0]['status'] = 'running'
    if change == 'foreign_test': pending['test_runs'][0]['test_id'] = 'foreign'
    if change == 'foreign_invocation': pending['id'] = 'foreign'
    if change == 'no_runs': pending['test_runs'] = []
    if change == 'foreign_agent': pending['agent_id'] = 'foreign'
    assert run(setup)['global_stop'] is True
    assert setup[4].cancels == []


def test_owned_journal_missing_is_not_reconstructed_from_existing_booking(setup):
    (setup[0] / setup[1].run_id / 'C48-1-interruption-journal.json').unlink()
    with pytest.raises(SimulationError): run(setup)
    assert setup[4].gets == setup[4].cancels == []


@pytest.mark.parametrize('change', ['mock_config', 'override', 'test_id', 'baseline_hash', 'missing_pre'])
def test_unmocked_native_preparation_receipts_are_required(setup, change):
    root, binding, journal, _, provider = setup
    folder = root / binding.run_id
    path = folder / 'C48-1-pre-invocation.json'
    pre = json.loads(path.read_text())
    if change == 'missing_pre': path.unlink()
    else:
        if change == 'mock_config': pre['test_definition']['tool_mock_config']['mocking_strategy'] = 'all'
        if change == 'override': pre['invocation_request']['agent_config_override'] = {'prompt': 'fake'}
        if change == 'test_id': pre['test_definition']['id'] = 'other'
        if change == 'baseline_hash': pre['baseline']['request_ids'] = []
        private_json(path, pre)
        if change != 'baseline_hash':
            # Even consistently rebound local configuration cannot authorize mocked/overridden work.
            journal['pre_invocation_sha256'] = fingerprint(pre)
            private_json(folder / 'C48-1-interruption-journal.json', journal)
            ledger = json.loads((root / 'usage-ledger.json').read_text())
            ledger['entries'][0].update(pre_invocation_sha256=fingerprint(pre),
                                        interruption_journal_sha256=fingerprint(journal))
            private_json(root / 'usage-ledger.json', ledger)
    with pytest.raises(SimulationError): run(setup)
    assert provider.gets == provider.cancels == []


def test_cancelled_run_without_invocation_cancelled_flag_is_contradictory(setup):
    setup[4].responses[-1]['cancelled'] = False
    assert run(setup)['interruption_verified'] is False


@pytest.mark.parametrize('stage', ['provider_initial', 'provider_after_intent', 'provider_cancel', 'observer_before', 'observer_after'])
def test_external_simulation_errors_never_persist_private_context(setup, stage):
    provider = setup[4]
    marker = 'private-callback-diagnostic-credential'
    real_get = provider.get
    gets = 0
    observations = 0
    def get(invocation):
        nonlocal gets
        gets += 1
        if (stage == 'provider_initial' and gets == 1) or (stage == 'provider_after_intent' and gets > 1):
            raise SimulationError(marker)
        return real_get(invocation)
    def observe():
        nonlocal observations
        observations += 1
        if (stage == 'observer_before' and observations == 1) or (stage == 'observer_after' and observations > 1):
            raise SimulationError(marker)
        return copy.deepcopy(setup[3])
    provider.get = get
    if stage == 'provider_cancel':
        def cancel(invocation):
            provider.cancels.append(invocation)
            raise SimulationError(marker)
        provider.cancel = cancel
    outcome = advance(setup[0], binding=setup[1], provider=provider, observe_booking=observe)
    assert outcome['global_stop'] is True and outcome['interruption_verified'] is False
    assert marker not in str(outcome)
    assert all(marker not in p.read_text() for p in setup[0].rglob('*.json'))
    assert len(provider.cancels) == (1 if stage in ('provider_after_intent', 'observer_after', 'provider_cancel') else 0)


def ids_one(setup):
    _, _, journal, booking, provider = setup
    journal['baseline']['customer_id'] = 1
    journal['expected_booking'].update(customer_id=1, staff_agent_id=1)
    booking['customer_id'] = 1
    booking['requests'][0].update(id=1, customer_id=1, staff_agent_id=1)
    booking['reservations'][0].update(id=1, service_request_id=1, staff_agent_id=1)
    for row in booking['segments']:
        row.update(reservation_id=1, staff_agent_id=1)
    for response in provider.responses:
        result = response['test_runs'][0]['agent_responses'][1]['tool_results'][0]
        envelope = json.loads(result['result_value'])
        envelope['result']['appointment_id'] = 1
        envelope['result']['appointments'][0].update(service_request_id=1, reservation_id=1, staff_agent_id=1)
        result['result_value'] = envelope
    rebind_journal(setup)


def rebind_journal(setup):
    root, binding, journal, _, _ = setup
    folder = root / binding.run_id
    pre = json.loads((folder / 'C48-1-pre-invocation.json').read_text())
    for key in ('baseline', 'expected_booking'):
        pre[key] = copy.deepcopy(journal[key])
    private_json(folder / 'C48-1-pre-invocation.json', pre)
    journal['pre_invocation_sha256'] = fingerprint(pre)
    private_json(folder / 'C48-1-interruption-journal.json', journal)
    ledger = json.loads((root / 'usage-ledger.json').read_text())
    ledger['entries'][0].update(pre_invocation_sha256=fingerprint(pre), interruption_journal_sha256=fingerprint(journal))
    private_json(root / 'usage-ledger.json', ledger)


@pytest.mark.parametrize('value', [True, 1.0, '1', 0, -1])
@pytest.mark.parametrize('field', [
    'expected.customer_id', 'expected.staff_agent_id', 'baseline.customer_id',
    'baseline.request_ids', 'baseline.reservation_ids', 'observation.customer_id',
    'request.id', 'request.customer_id', 'request.staff_agent_id',
    'reservation.id', 'reservation.service_request_id', 'reservation.staff_agent_id',
    'segment.reservation_id', 'segment.staff_agent_id',
    'result.appointment_id', 'appointment.service_request_id', 'appointment.reservation_id', 'appointment.staff_agent_id',
])
def test_all_native_relational_ids_require_positive_json_integer(setup, field, value):
    ids_one(setup)
    _, _, journal, booking, provider = setup
    area, key = field.split('.')
    if area in ('expected', 'baseline'):
        target = journal['expected_booking' if area == 'expected' else 'baseline']
        target[key] = [value] if key.endswith('_ids') else value
        rebind_journal(setup)
    elif area == 'observation': booking[key] = value
    elif area in ('request', 'reservation', 'segment'):
        target = booking[{'request': 'requests', 'reservation': 'reservations', 'segment': 'segments'}[area]][0]
        target[key] = value
    else:
        for receipt_value in provider.responses:
            result = receipt_value['test_runs'][0]['agent_responses'][1]['tool_results'][0]
            envelope = result['result_value']['result']
            target = envelope if area == 'result' else envelope['appointments'][0]
            target[key] = value
    before_booking = copy.deepcopy(booking)
    try:
        outcome = run(setup)
        assert outcome['interruption_verified'] is False
        assert outcome['global_stop'] is True
    except SimulationError:
        assert provider.cancels == []
    assert booking == before_booking
    if area not in ('result', 'appointment'):
        assert provider.cancels == []


def test_positive_integer_one_is_a_valid_relational_id(setup):
    ids_one(setup)
    assert run(setup)['interruption_verified'] is True


@pytest.mark.parametrize('value', [True, 1.0, '1'])
def test_journal_attempt_identity_is_not_coerced_by_json_equality(setup, value):
    root, binding, journal, _, provider = setup
    journal['binding']['attempt'] = value
    private_json(root / binding.run_id / 'C48-1-interruption-journal.json', journal)
    ledger = json.loads((root / 'usage-ledger.json').read_text())
    ledger['entries'][0].update(attempt=value, interruption_journal_sha256=fingerprint(journal))
    private_json(root / 'usage-ledger.json', ledger)
    with pytest.raises(SimulationError): run(setup)
    assert provider.gets == provider.cancels == []
