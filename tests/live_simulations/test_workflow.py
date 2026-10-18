"""Workflow composition never calls real providers in automated validation."""
from contextlib import contextmanager
from types import SimpleNamespace
import subprocess
from pathlib import Path

import pytest

from live_simulations import workflow
from live_simulations.core import SimulationError


@pytest.fixture
def harness(monkeypatch, tmp_path):
    events = []
    runtime = SimpleNamespace(run_id='a' * 32, folder=tmp_path, url='http://127.0.0.1:8011',
                              gateway_url='http://127.0.0.1:8010', manifest={'status': 'prepared'}, save=lambda: events.append('save'))
    @contextmanager
    def running(value):
        events.append('setup-start')
        try: yield value
        finally: events.append('setup-stop')
    def campaign(value, tier, requested=None, **kwargs):
        events.append(('run', tier, requested, kwargs))
        value.manifest['status'] = 'passed'
        return value.manifest
    monkeypatch.setattr(workflow, 'Runtime', SimpleNamespace(prepare=lambda config: (events.append('prepare') or runtime)))
    monkeypatch.setattr(workflow, 'running', running)
    monkeypatch.setattr(workflow.fixtures, 'seed', lambda *args: events.append('seed'))
    monkeypatch.setattr(workflow.fixtures, 'variables', lambda config: {})
    monkeypatch.setattr(workflow, 'run_campaign', campaign)
    monkeypatch.setattr(workflow, 'write_report', lambda r: events.append('report'))
    monkeypatch.setattr(workflow.sys.stdin, 'isatty', lambda: True)
    monkeypatch.setattr('builtins.input', lambda prompt: events.append('setup-ready') or '')
    config = {'budget': {'monthly_credits': 100000, 'remaining_credits': 90000,
                         'verified_credit_units': True, 'case_upper_estimate': 1}}
    return config, runtime, events


@pytest.mark.parametrize('tier,count', [('minimal', 6), ('medium', 16), ('full', 50)])
def test_default_workflow_previews_all_tiers_without_runtime_or_provider_access(harness, tier, count):
    config, runtime, events = harness
    result = workflow.execute(config, tier)
    assert len(result['selected']) == count
    assert result['status'] == 'planned'
    assert events == []


@pytest.mark.parametrize('tier', ['minimal', 'medium', 'full'])
def test_live_workflow_stops_setup_before_running_selected_tier(harness, tier, capsys):
    config, runtime, events = harness
    assert workflow.execute(config, tier, live=True)['status'] == 'passed'
    assert events[:5] == ['prepare', 'seed', 'setup-start', 'setup-ready', 'setup-stop']
    assert events[5] == ('run', tier, None, {'live': True, 'repeat': 1})
    assert events[-1] == 'report'
    assert runtime.run_id in capsys.readouterr().out


def test_prepared_run_does_not_prepare_seed_or_prompt_again(harness, monkeypatch):
    config, runtime, events = harness
    monkeypatch.setattr(workflow, 'Runtime', lambda config, run_id: runtime)
    monkeypatch.setattr(workflow.sys.stdin, 'isatty', lambda: False)
    workflow.execute(config, 'medium', run_id=runtime.run_id, live=True, requested=['C03'], repeat=2)
    assert events[0] == ('run', 'medium', ['C03'], {'live': True, 'repeat': 2})
    assert 'seed' not in events and 'setup-start' not in events


def test_noninteractive_new_live_run_is_blocked_before_resource_creation(harness, monkeypatch):
    config, runtime, events = harness
    monkeypatch.setattr(workflow.sys.stdin, 'isatty', lambda: False)
    with pytest.raises(SimulationError, match='run-id'):
        workflow.execute(config, 'minimal', live=True)
    assert events == []


def test_interrupted_setup_retains_report_and_never_runs_campaign(harness, monkeypatch, capsys):
    config, runtime, events = harness
    def interrupted(prompt): raise KeyboardInterrupt()
    monkeypatch.setattr('builtins.input', interrupted)
    with pytest.raises(KeyboardInterrupt): workflow.execute(config, 'minimal', live=True)
    assert runtime.manifest['status'] == 'incomplete'
    assert events[-3:] == ['setup-stop', 'save', 'report']
    assert not any(isinstance(e, tuple) and e[0] == 'run' for e in events)
    assert 'cleanup' in capsys.readouterr().out


def test_workflow_cli_exposes_tiers_and_rejects_invalid_value():
    from live_simulations.__main__ import main
    with pytest.raises(SystemExit) as exc: main(['workflow', '--tier', 'unknown'])
    assert exc.value.code == 2


def test_root_shell_entrypoint_works_from_another_directory(tmp_path):
    script = Path(__file__).resolve().parents[2] / 'run_live_simulations.sh'
    result = subprocess.run([str(script), '--help'], cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0
    assert '--tier {minimal,medium,full}' in result.stdout


def test_attempted_run_status_cannot_be_overwritten_by_workflow(harness, monkeypatch):
    config, runtime, events = harness
    runtime.manifest.update(status='passed', results=[{'case_id': 'C01', 'status': 'passed'}])
    monkeypatch.setattr(workflow, 'Runtime', lambda config, run_id: runtime)
    with pytest.raises(SimulationError, match='attempted'):
        workflow.execute(config, 'minimal', run_id=runtime.run_id, live=True)
    assert runtime.manifest['status'] == 'passed'
    assert events == []


@pytest.mark.parametrize('tier,count', [('minimal', 6), ('medium', 16), ('full', 50)])
def test_shell_preview_routes_each_tier_to_real_cli(tmp_path, tier, count):
    import json
    config = {'schema_version': 1, 'environment': 'simulation', 'app_port': 8011, 'gateway_port': 8010,
              'budget': {'verified_credit_units': True, 'monthly_credits': 100000, 'remaining_credits': 90000,
                         'case_upper_estimate': 1}}
    path = tmp_path / 'config.json'
    path.write_text(json.dumps(config))
    script = Path(__file__).resolve().parents[2] / 'run_live_simulations.sh'
    result = subprocess.run([str(script), '--tier', tier, '--config', str(path)], cwd=tmp_path,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert len(json.loads(result.stdout)['selected']) == count
