"""Offline differential-stage admission and durable authorization contracts."""
import json
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from live_simulations import runner
from live_simulations.core import SimulationError, private_json

REAL_PREFLIGHT = runner.preflight

MEDIUM = [f'C{i:02}' for i in range(7, 17)]
FULL = [f'C{i:02}' for i in range(17, 51)]


def config(tier='medium'):
    return {'environment': 'simulation', 'agent_id': 'reference',
            'post_call_webhook_id': 'isolated', 'tunnel_url': 'https://tunnel.example',
            'stage_authorization': {'authorization_id': 'medium-owned-once', 'tier': tier,
                                    'case_ids': MEDIUM if tier == 'medium' else FULL,
                                    'credit_ceiling': 2000},
            'budget': {'verified_credit_units': True, 'monthly_credits': 1000,
                       'remaining_credits': 900, 'case_upper_estimate': 10,
                       'reset_unix': 2000000000},
            'variables': {'customer_name': 'Synthetic', 'customer_phone': '2125551234',
                          'customer_email': 'fixture@example.test'}}


@pytest.mark.parametrize('tier,selected', [('medium', MEDIUM), ('full', FULL)])
def test_exact_stage_has_distinct_cap_and_preserves_default(tier, selected):
    settings = config(tier)
    result = runner.preview(settings, tier, selected)
    assert result['status'] == 'planned'
    assert result['selected'] == selected
    assert result['complete_tier'] is False
    assert result['tier_cap'] == '2000'
    assert result['admission_limit'] == '1600.0'
    assert result['stage_authorization'] == settings['stage_authorization']
    settings.pop('stage_authorization')
    assert runner.preview(settings, tier, selected)['status'] == 'over_budget'


@pytest.mark.parametrize('mutation', ['blank', 'wrong_tier', 'partial', 'duplicate', 'zero', 'deployed', 'repeat', 'default'])
def test_invalid_stage_scope_rejected(mutation):
    settings = config()
    selected, repeat = MEDIUM, 1
    auth = settings['stage_authorization']
    if mutation == 'blank': auth['authorization_id'] = ' '
    if mutation == 'wrong_tier': auth['tier'] = 'full'
    if mutation == 'partial': selected = MEDIUM[:-1]
    if mutation == 'duplicate': auth['case_ids'] = MEDIUM + ['C07']
    if mutation == 'zero': auth['credit_ceiling'] = 0
    if mutation == 'deployed': settings['target'] = 'deployed'
    if mutation == 'repeat': repeat = 2
    if mutation == 'default': selected = None
    with pytest.raises(SimulationError, match='stage|Stage'):
        runner.preview(settings, 'medium', selected, repeat)


@pytest.fixture
def captured(tmp_path, monkeypatch):
    settings = config()
    root = tmp_path
    runtime = SimpleNamespace(root=root, folder=root / 'owned', run_id='b' * 32,
                              config=settings, manifest={'results': [], 'invocations': [],
                              'provider_tests': [], 'calendar_events': [], 'cleanup': {}})
    runtime.folder.mkdir()
    runtime.save = lambda: private_json(runtime.folder / 'manifest.json', runtime.manifest)
    runtime.stop = lambda: None
    runtime.rows = lambda *args: []
    runtime.snapshot = lambda: {'service_requests': [], 'sms_log': []}
    calls = []
    class Provider:
        unknown = False
        def __init__(self, key): pass
        def create_agent(self, override, run_id):
            manifest = json.loads((runtime.folder / 'manifest.json').read_text())
            assert manifest['stage_authorization'] == settings['stage_authorization']
            calls.append('agent')
            return 'owned-agent'
        def agent(self, agent_id): return {'platform_settings': {'workspace_overrides': {'webhooks': {}}}}
        def verify_webhook(self, *args): pass
        def create(self, spec, *args): return spec['id']
        def run(self, agent, test, override):
            calls.append(test)
            ledger = json.loads((root / 'usage-ledger.json').read_text())
            assert ledger['entries'][-1]['stage_authorization'] == settings['stage_authorization']
            assert ledger['entries'][-1]['authorization_id'] == 'medium-owned-once'
            return {'id': 'invocation-' + test}
        def wait(self, *args): return {'test_runs': [{'status': 'passed'}]}
        def credits(self, result): return None if self.unknown else 10
    @contextmanager
    def running(runtime): yield runtime
    monkeypatch.setattr(runner, 'ElevenLabs', Provider)
    monkeypatch.setattr(runner, 'running', running)
    monkeypatch.setattr(runner, 'secret', lambda *args: 'offline')
    monkeypatch.setattr(runner, 'preflight', lambda *args: ({'platform_settings': {'workspace_overrides': {'webhooks': {}}}}, 900))
    monkeypatch.setattr(runner, 'current_remaining', lambda *args: 900)
    monkeypatch.setattr(runner, 'collect_events', lambda *args: None)
    monkeypatch.setattr(runner, 'remove_events', lambda *args: None)
    monkeypatch.setattr(runner.fixtures, 'seed', lambda *args: None)
    monkeypatch.setattr(runner.fixtures, 'arrange', lambda *args: {})
    monkeypatch.setattr(runner.fixtures, 'actions', lambda *args: None)
    monkeypatch.setattr(runner, 'outcome', lambda *args: [{'name': 'captured', 'passed': True}])
    return runtime, calls, Provider


def test_ten_calls_only_and_single_use_even_before_first_charge(captured):
    runtime, calls, _ = captured
    result = runner.run_campaign(runtime, 'medium', MEDIUM, live=True)
    assert result['status'] == 'passed'
    assert calls == ['agent'] + MEDIUM
    assert result['spent_credits'] == '100'
    ledger = json.loads((runtime.root / 'usage-ledger.json').read_text())
    assert len(ledger['entries']) == 10
    runtime.manifest = {'results': [], 'invocations': []}
    with pytest.raises(SimulationError, match='authorization.*used|authorization.*claimed'):
        runner.run_campaign(runtime, 'medium', MEDIUM, live=True)
    assert calls == ['agent'] + MEDIUM


@pytest.mark.parametrize('historical', [False, True])
def test_unknown_charge_globally_stops_stage(captured, historical):
    runtime, calls, provider = captured
    if historical:
        private_json(runtime.root / 'usage-ledger.json', {'entries': [{'run_id': 'older', 'unsettled': True}]})
        with pytest.raises(SimulationError, match='Unsettled'):
            runner.run_campaign(runtime, 'medium', MEDIUM, live=True)
        assert calls == []
    else:
        provider.unknown = True
        result = runner.run_campaign(runtime, 'medium', MEDIUM, live=True)
        assert calls == ['agent', 'C07']
        assert result['unsettled_usage'] is True
        with pytest.raises(SimulationError, match='already attempted'):
            runner.run_campaign(runtime, 'medium', MEDIUM, live=True)


def test_earlier_settled_minimal_spend_is_not_charged_to_stage(captured):
    runtime, calls, _ = captured
    old = {'run_id': 'minimal-ancestor', 'credits': '4527', 'unsettled': False}
    private_json(runtime.root / 'usage-ledger.json', {'entries': [old]})
    assert runner.run_campaign(runtime, 'medium', MEDIUM, live=True)['spent_credits'] == '100'
    ledger = json.loads((runtime.root / 'usage-ledger.json').read_text())
    assert ledger['entries'][0] == old
    assert calls == ['agent'] + MEDIUM


def test_stage_reserve_and_fresh_quota_both_limit_admission(captured, monkeypatch):
    runtime, calls, _ = captured
    runtime.config['stage_authorization']['credit_ceiling'] = 124
    assert runner.preview(runtime.config, 'medium', MEDIUM)['status'] == 'over_budget'
    runtime.config['stage_authorization']['credit_ceiling'] = 125
    assert runner.preview(runtime.config, 'medium', MEDIUM)['status'] == 'planned'
    monkeypatch.setattr(runner, 'preflight', lambda *args: ({}, 99))
    with pytest.raises(SimulationError, match='remaining allowance'):
        runner.run_campaign(runtime, 'medium', MEDIUM, live=True)
    assert calls == []
    runtime.manifest = {'results': [], 'invocations': []}
    with pytest.raises(SimulationError, match='authorization.*used|authorization.*claimed'):
        runner.run_campaign(runtime, 'medium', MEDIUM, live=True)
    assert calls == []


def test_selected_range_setup_validation_precedes_provider_access(captured, monkeypatch):
    runtime, calls, _ = captured
    selected = runner.select_cases(runner.load_catalog(), 'medium', MEDIUM)
    witnessed = []
    def unavailable(config, cases):
        witnessed.extend(c['id'] for c in cases)
        raise SimulationError('C15 missing second calendar binding')
    monkeypatch.setattr(runner.fixtures, 'validate_setup', unavailable)
    monkeypatch.setattr(runner, 'load_reference', lambda *args: pytest.fail('provider accessed'))
    with pytest.raises(SimulationError, match='C15'):
        REAL_PREFLIGHT(runtime, selected, None, None)
    assert witnessed == MEDIUM
    assert calls == []
