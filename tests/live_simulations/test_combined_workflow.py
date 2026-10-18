"""Real shell orchestration, captured pytest and live boundaries; no paid work."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


@pytest.fixture
def captured(tmp_path):
    script = Path(__file__).resolve().parents[2] / 'run_tests.sh'
    shutil.copy2(script, tmp_path / 'run_tests.sh')
    executable = '''#!PYTHON
import json, os, sys
from pathlib import Path
stage = 'live' if Path(sys.argv[0]).name == 'run_live_simulations.sh' else ('e2e' if any(a.endswith('/e2e') for a in sys.argv[1:]) else 'unit')
with open(os.environ['CAPTURE'], 'a') as f: f.write(json.dumps([stage, sys.argv[1:]]) + '\\n')
sys.exit(int(os.environ.get(stage.upper() + '_EXIT', '0')))
'''.replace('PYTHON', sys.executable)
    for path in (tmp_path / '.venv/bin/pytest', tmp_path / 'run_live_simulations.sh'):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(executable)
        path.chmod(0o755)
    def run(*args, **overrides):
        log = tmp_path / 'capture.jsonl'
        log.unlink(missing_ok=True)
        result = subprocess.run([str(tmp_path / 'run_tests.sh'), '--verify', *args],
                                env={**os.environ, 'CAPTURE': str(log), **overrides},
                                capture_output=True, text=True)
        calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
        return result, calls
    return run


@pytest.mark.parametrize('tier', ['minimal', 'medium', 'full'])
def test_verify_consumes_live_tier_and_runs_it_after_both_offline_suites(captured, tier):
    result, calls = captured('--live-tier', tier, '-k', 'booking')
    assert result.returncode == 0, result.stderr
    assert [stage for stage, args in calls] == ['unit', 'e2e', 'live']
    for stage, args in calls[:2]:
        assert '--live-tier' not in args and tier not in args
        assert args[-2:] == ['-k', 'booking']
    assert calls[2][1] == ['--tier', tier, '--live']


@pytest.mark.parametrize('failed', ['UNIT_EXIT', 'E2E_EXIT'])
def test_offline_failure_runs_both_suites_and_skips_live(captured, failed):
    result, calls = captured('--live-tier', 'minimal', **{failed: '1'})
    assert result.returncode == 1
    assert [stage for stage, args in calls] == ['unit', 'e2e']
    assert 'skipped' in result.stdout.lower()


def test_default_verify_stays_offline(captured):
    result, calls = captured()
    assert result.returncode == 0
    assert [stage for stage, args in calls] == ['unit', 'e2e']


@pytest.mark.parametrize('args', [('--live-tier', 'unknown'), ('--live-tier',), ('--live-config',),
                                  ('--live-config', 'private.json'), ('--live-run-id',)])
def test_invalid_live_options_fail_before_any_suite(captured, args):
    result, calls = captured(*args)
    assert result.returncode == 2
    assert calls == []


def test_live_config_and_run_id_are_forwarded_only_to_live_workflow(captured):
    result, calls = captured('--live-config', '/tmp/test config.json', '--live-tier', 'medium',
                             '--live-run-id', 'a' * 32, LIVE_EXIT='3')
    assert result.returncode == 3
    assert calls[-1][1] == ['--tier', 'medium', '--live', '--config', '/tmp/test config.json', '--run-id', 'a' * 32]
    assert all('--live-config' not in args and '/tmp/test config.json' not in args for stage, args in calls[:2])


@pytest.mark.parametrize('flag', ['--help', '-h', '--collect-only', '--co', '--version', '--fixtures', '--setup-plan', '--setup-only'])
def test_information_or_collection_only_cannot_unlock_live_execution(captured, flag):
    result, calls = captured('--live-tier', 'minimal', flag)
    assert result.returncode == 2
    assert calls == []
