import pytest
from live_simulations.runner import preview, campaign_status
from live_simulations.core import SimulationError


def test_preview_is_offline_and_reports_subset_and_full_preflight_shortfall():
    config = {'budget': {'monthly_credits': 100000, 'remaining_credits': 90000,
                         'verified_credit_units': True, 'case_upper_estimate': 10}}
    result = preview(config, 'minimal', ['C03'])
    assert result['selected'] == ['C01', 'C02', 'C03']
    assert result['complete_tier'] is False
    assert result['estimated_credits'] == '30'
    config['budget']['case_upper_estimate'] = 1000
    assert preview(config, 'minimal')['status'] == 'over_budget'
    config['budget'].pop('verified_credit_units')
    assert preview(config, 'minimal')['status'] == 'budget_unverified'


def test_failed_blocked_incomplete_and_empty_results_never_pass():
    assert campaign_status([]) == 'incomplete'
    assert campaign_status([{'status': 'passed'}, {'status': 'blocked'}]) == 'blocked'
    assert campaign_status([{'status': 'failed'}, {'status': 'passed'}]) == 'failed'
    assert campaign_status([{'status': 'passed'}, {'status': 'incomplete'}]) == 'incomplete'
    assert campaign_status([{'status': 'passed'}]) == 'passed'


def test_live_guard_precedes_all_runtime_or_provider_access():
    from live_simulations.runner import run_campaign
    with pytest.raises(SimulationError, match='requires --live'):
        run_campaign(None, 'minimal')


@pytest.mark.parametrize('interrupted', [False, True])
def test_unsettled_billing_stops_campaign_without_repeating_paid_work(tmp_path, monkeypatch, interrupted):
    """Exercise campaign/ledger transitions; business/provider checks have separate tests."""
    from contextlib import contextmanager
    from live_simulations import runner
    from live_simulations.core import private_json
    from live_simulations.provider import ElevenLabs
    import json
    class Owned:
        run_id = 'b' * 32
        root = tmp_path
        folder = tmp_path / run_id
        config = {'environment': 'simulation', 'agent_id': 'reference', 'post_call_webhook_id': 'isolated', 'tunnel_url': 'https://tunnel.example',
                  'budget': {'verified_credit_units': True, 'monthly_credits': 100000,
                             'remaining_credits': 90000, 'case_upper_estimate': 1, 'reset_unix': 2000000000},
                  'variables': {'customer_name': 'Synthetic', 'customer_phone': '2125551234', 'customer_email': 'fixture@example.test'}}
        manifest = {'results': [], 'invocations': [], 'provider_tests': [], 'calendar_events': [], 'cleanup': {}}
        def save(self): private_json(self.folder / 'manifest.json', self.manifest)
        def stop(self): pass
        def rows(self, *args): return []
        def snapshot(self): return {'service_requests': [], 'sms_log': []}
    runtime = Owned(); runtime.folder.mkdir()
    calls = []
    class Provider:
        def __init__(self, key): pass
        def subscription(self): return {'next_character_count_reset_unix': 2000000000, 'character_refresh_period': 'monthly_period', 'character_limit': 100000, 'character_count': 10000}
        def create_agent(self, override, run_id): return 'owned-agent'
        def agent(self, agent_id): return {'platform_settings': {'workspace_overrides': {'webhooks': {'post_call_webhook_id': 'isolated'}}}}
        def verify_webhook(self, *args): pass
        def create(self, *args): return 'owned-test'
        def run(self, *args): calls.append(args); return {'id': 'owned-invocation'}
        def wait(self, *args):
            if interrupted: raise KeyboardInterrupt()
            return {'test_runs': [{'status': 'passed', 'credits_used': None}]}
        credits = staticmethod(ElevenLabs.credits)
    @contextmanager
    def running(runtime): yield runtime
    monkeypatch.setattr(runner, 'ElevenLabs', Provider)
    monkeypatch.setattr(runner, 'running', running)
    monkeypatch.setattr(runner, 'secret', lambda *args: 'synthetic-boundary')
    monkeypatch.setattr(runner, 'preflight', lambda *args: ({'platform_settings': {'workspace_overrides': {'webhooks': {'post_call_webhook_id': 'isolated'}}}}, 90000))
    monkeypatch.setattr(runner, 'collect_events', lambda *args: None)
    monkeypatch.setattr(runner, 'remove_events', lambda *args: None)
    monkeypatch.setattr(runner.fixtures, 'seed', lambda *args: None)
    monkeypatch.setattr(runner.fixtures, 'arrange', lambda *args: {})
    monkeypatch.setattr(runner.fixtures, 'actions', lambda *args: None)
    monkeypatch.setattr(runner, 'outcome', lambda *args: [{'name': 'captured outcome', 'passed': True}])
    if interrupted:
        with pytest.raises(KeyboardInterrupt): runner.run_campaign(runtime, 'minimal', live=True)
    else:
        assert runner.run_campaign(runtime, 'minimal', live=True)['status'] == 'failed'
    assert len(calls) == 1
    ledger = json.loads((tmp_path / 'usage-ledger.json').read_text())
    assert ledger['entries'][0]['unsettled'] is True
    assert runtime.manifest['unsettled_usage'] is True
    assert 'unsettled' in (runtime.folder / 'report.md').read_text().lower()


def test_monthly_quota_is_rechecked_before_each_paid_case():
    from live_simulations import runner
    class Provider:
        def subscription(self):
            return {'next_character_count_reset_unix': 2000000000, 'character_refresh_period': 'monthly_period',
                    'character_limit': 100000, 'character_count': 12000}
    config = {'budget': {'reset_unix': 2000000000, 'monthly_credits': 100000}}
    assert runner.current_remaining(config, Provider()) == 88000
    config['budget']['reset_unix'] = 2000000001
    with pytest.raises(SimulationError, match='billing'):
        runner.current_remaining(config, Provider())


def test_failed_calendar_collection_retains_cleanup_blocker(tmp_path, monkeypatch):
    from live_simulations import runner
    class Owned:
        manifest = {'status': 'running'}
        def save(self): pass
    runtime = Owned()
    def broken(*args): raise RuntimeError('private provider data must not appear')
    monkeypatch.setattr(runner, 'collect_events', broken)
    runner.retain_effects(runtime)
    assert runtime.manifest['status'] == 'incomplete'
    assert runtime.manifest['cleanup_blockers'] == ['Calendar evidence collection failed']


def test_calendar_preflight_uses_granted_event_scope_without_reading_event_content(tmp_path, monkeypatch):
    """Calendar event grants cannot read calendar metadata; probe the used resource."""
    import json
    from types import SimpleNamespace
    from live_simulations import runner
    (tmp_path / 'app/serviceBot').mkdir(parents=True)
    (tmp_path / 'app/serviceBot/config.json').write_text(json.dumps({'gmail_enabled': True}))
    (tmp_path / 'gateway.json').write_text(json.dumps({'token': 'test-gateway'}))
    values = {'customer_phone': '4242704893', 'customer_email': 'fixture@example.test'}
    runtime = SimpleNamespace(folder=tmp_path, run_id='owned', rows=lambda *args: [], config={
        'tunnel_url': 'https://tunnel.example', 'whatsapp_ready': True,
        'allowlisted_phone_numbers': ['+14242704893'], 'allowlisted_emails': ['fixture@example.test'],
        'staff': [{'phone': '+14242704893', 'email': 'fixture@example.test'}]})
    monkeypatch.setattr(runner, 'load_reference', lambda *args: {})
    monkeypatch.setattr(runner.fixtures, 'variables', lambda *args: values)
    monkeypatch.setattr(runner, 'credentials', lambda *args: {'1': 'test-google-token'})
    monkeypatch.setattr(runner, 'secret', lambda *args: 'test-inbox-token')
    calls = []
    class Response:
        def raise_for_status(self): pass
        def json(self): return {'run_folder': 'owned'}
    class Client:
        def get(self, url, **kwargs):
            if 'gmail.googleapis.com' in url:
                raise RuntimeError('calendar probe completed')
            if 'www.googleapis.com/calendar/' in url:
                calls.append((url, kwargs))
            return Response()
    with pytest.raises(RuntimeError, match='calendar probe completed'):
        runner.preflight(runtime, [], None, Client())
    assert calls == [('https://www.googleapis.com/calendar/v3/calendars/primary/events', {
        'params': {'maxResults': 1, 'fields': 'kind'},
        'headers': {'Authorization': 'Bearer test-google-token'}})]
