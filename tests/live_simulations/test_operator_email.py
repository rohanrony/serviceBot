"""Operator receipt keeps native email acceptance pending, without paid traffic."""
import itertools
import json
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from live_simulations import runner
from live_simulations.core import SimulationError
from tests.live_simulations.test_stage_authorization import MEDIUM, config
from tests.live_simulations.test_stage_authorization import captured as stage_captured

captured = stage_captured


@pytest.mark.parametrize('mode', ['manual', '', None, True, 'Operator'])
def test_invalid_mode_rejected_during_offline_preview(mode):
    settings = config()
    settings['email_receipt_mode'] = mode
    with pytest.raises(SimulationError, match='email receipt mode'):
        runner.preview(settings, 'medium', MEDIUM)


def test_operator_mode_requires_isolated_stage_authorization():
    settings = config()
    settings['email_receipt_mode'] = 'operator'
    settings.pop('stage_authorization')
    with pytest.raises(SimulationError, match='isolated stage'):
        runner.preview(settings, 'medium', MEDIUM)


@pytest.mark.parametrize('mode', ['native', 'operator'])
def test_preflight_only_omits_receiver_probe_in_operator_mode(tmp_path, monkeypatch, mode):
    settings = config()
    settings.update(email_receipt_mode=mode, whatsapp_ready=True,
                    allowlisted_phone_numbers=['+12125551234'],
                    allowlisted_emails=['fixture@example.test'],
                    staff=[{'phone': '+12125551234', 'email': 'fixture@example.test'}])
    runtime = SimpleNamespace(config=settings, folder=tmp_path, run_id='owned',
                              rows=lambda *args: [], manifest={}, save=lambda: None)
    (tmp_path / 'app/serviceBot').mkdir(parents=True)
    (tmp_path / 'app/serviceBot/config.json').write_text('{"gmail_enabled": true}')
    (tmp_path / 'gateway.json').write_text('{"token": "owned-token"}')
    monkeypatch.setattr(runner.fixtures, 'validate_setup', lambda *args: None)
    monkeypatch.setattr(runner, 'load_reference', lambda *args: {'version_id': 'v'})
    monkeypatch.setattr(runner, 'credentials', lambda *args: {'1': 'calendar-token'})
    monkeypatch.setattr(runner, 'current_remaining', lambda *args: 900)
    secrets, urls = [], []
    def secret(config, key):
        secrets.append(key)
        return 'synthetic-token'
    monkeypatch.setattr(runner, 'secret', secret)
    class Response:
        def raise_for_status(self): pass
        def json(self): return {'run_folder': 'owned', 'emailAddress': 'fixture@example.test'}
    class Client:
        def get(self, url, **kwargs):
            urls.append(url)
            return Response()
    provider = SimpleNamespace(verify_webhook=lambda *args: None, override=lambda *args: {})
    assert runner.preflight(runtime, [], provider, Client()) == ({}, 900)
    assert any('calendar/v3/' in url for url in urls)
    assert 'twilio_sid' in secrets and 'twilio_token' in secrets
    assert ('gmail_receiver_token' in secrets) == (mode == 'native')
    assert any('gmail.googleapis.com' in url for url in urls) == (mode == 'native')


@pytest.mark.parametrize('mode', ['native', 'operator'])
def test_outcome_retains_original_required_email_assertion(monkeypatch, mode):
    settings = config()
    settings['email_receipt_mode'] = mode
    runtime = SimpleNamespace(config=settings, manifest={}, rows=lambda *args: [], url='http://owned')
    monkeypatch.setattr(runner.evidence, 'sql_checks', lambda *args: [])
    monkeypatch.setattr(runner.evidence, 'local_invariants', lambda *args: [])
    monkeypatch.setattr(runner.evidence, 'verify_tools', lambda *args: [])
    monkeypatch.setattr(runner.evidence, 'browser_readback', lambda *args: [])
    monkeypatch.setattr(runner, 'traces', lambda *args: [])
    monkeypatch.setattr(runner, 'secret', lambda *args: 'native-token')
    native_calls = []
    def receipt(*args):
        native_calls.append(args)
        return {'name': 'receiving inbox contains expected content', 'passed': True}
    monkeypatch.setattr(runner.evidence, 'email_receipt', receipt)
    @contextmanager
    def playwright():
        browser = SimpleNamespace(new_page=lambda: None, close=lambda: None)
        yield SimpleNamespace(chromium=SimpleNamespace(launch=lambda **kwargs: browser))
    monkeypatch.setattr('playwright.sync_api.sync_playwright', playwright)
    case = {'id': 'C07', 'checks': [], 'setup': 'empty', 'required_evidence': ['email']}
    checks = runner.outcome(runtime, case, {'customer_email': 'fixture@example.test',
                            'customer_name': 'Synthetic'}, 0, {}, None)
    assert case['required_evidence'] == ['email']
    inbox = next(c for c in checks if c['name'] == 'receiving inbox contains expected content')
    assert inbox['passed'] is (mode == 'native')
    if mode == 'operator':
        assert inbox['status'] == 'unverified'
        assert 'native' in inbox['reason'].lower()
        assert native_calls == []
    else:
        assert len(native_calls) == 1


@pytest.mark.parametrize('other_failure', [False, True])
def test_pending_email_does_not_block_remaining_calls_or_hide_failure(captured, monkeypatch, other_failure):
    runtime, calls, _ = captured
    runtime.config['email_receipt_mode'] = 'operator'
    pending = {'name': 'receiving inbox contains expected content', 'passed': False,
               'status': 'unverified', 'reason': 'Native receiving-inbox verification pending; operator receipt separate.'}
    def outcome(runtime, case, *args):
        return [dict(pending), {'name': 'native business state',
                               'passed': not (other_failure and case['id'] == 'C07')}]
    monkeypatch.setattr(runner, 'outcome', outcome)
    sleeps = []
    monkeypatch.setattr(runner.time, 'sleep', lambda *args: sleeps.append(args))
    if other_failure:
        clock = itertools.count(0, 0.5)
        monkeypatch.setattr(runner.time, 'monotonic', lambda: next(clock))
        runtime.config['evidence_timeout_seconds'] = 1
    result = runner.run_campaign(runtime, 'medium', MEDIUM, live=True)
    assert calls == ['agent'] + MEDIUM
    assert len(sleeps) == int(other_failure)
    assert result['status'] == ('failed' if other_failure else 'incomplete')
    assert result['functional_status'] == ('failed' if other_failure else 'passed')
    for row in result['results']:
        failed = other_failure and row['case_id'] == 'C07'
        assert row['functional_status'] == ('failed' if failed else 'passed')
        assert row['status'] == ('failed' if failed else 'incomplete')
        assert row['checks'][0] == pending
        assert 'Native receiving-inbox verification pending' in row['reason']
    report = (runtime.folder / 'report.md').read_text()
    assert 'Functional status:' in report
    assert 'Functional result' in report
    assert 'Native receiving-inbox verification pending' in report
    assert json.loads((runtime.folder / 'report.json').read_text())['functional_status'] == result['functional_status']


def test_unknown_charge_still_stops_operator_campaign(captured, monkeypatch):
    runtime, calls, provider = captured
    runtime.config['email_receipt_mode'] = 'operator'
    provider.unknown = True
    monkeypatch.setattr(runner, 'outcome', lambda *args: [
        {'name': 'receiving inbox contains expected content', 'passed': False,
         'status': 'unverified', 'reason': 'Native receiving-inbox verification pending'}])
    monkeypatch.setattr(runner.time, 'sleep', lambda *args: pytest.fail('pending email must not sleep'))
    result = runner.run_campaign(runtime, 'medium', MEDIUM, live=True)
    assert calls == ['agent', 'C07']
    assert result['unsettled_usage'] is True
    assert result['results'][0]['functional_status'] == 'failed'
    assert result['results'][0]['status'] == 'failed'


def test_operator_mode_preserves_provider_evaluation_failure(captured, monkeypatch):
    runtime, _, provider = captured
    runtime.config['email_receipt_mode'] = 'operator'
    monkeypatch.setattr(provider, 'wait', lambda *args: {'test_runs': [{'status': 'failed'}]})
    monkeypatch.setattr(runner, 'outcome', lambda *args: [
        {'name': 'receiving inbox contains expected content', 'passed': False,
         'status': 'unverified', 'reason': 'Native receiving-inbox verification pending'}])
    result = runner.run_campaign(runtime, 'medium', MEDIUM, live=True)
    assert result['status'] == 'failed'
    assert result['functional_status'] == 'failed'
    assert all(row['status'] == row['functional_status'] == 'failed' for row in result['results'])
    assert all('provider conversation evaluation' in row['reason'] for row in result['results'])
