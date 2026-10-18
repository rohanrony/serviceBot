"""Guided composition of the existing campaign owner, with no duplicate state."""
from __future__ import annotations

import json
import shlex
import sys

from . import fixtures
from .core import SimulationError
from .runner import preview, run_campaign, write_report
from .runtime import Runtime, running


def execute(config, tier='minimal', *, live=False, run_id=None, requested=None, repeat=1,
            config_path='scratch/live-simulations.local.json', check=False, continue_unpaid=False):
    if config.get('target') == 'deployed':
        from .deployed import execute as deployed_execute
        return deployed_execute(config, tier, live=live, check=check, run_id=run_id,
                                requested=requested, repeat=repeat, continue_unpaid=continue_unpaid)
    if continue_unpaid:
        raise SimulationError('Unpaid continuation is available only for deployed medium')
    if check:
        raise SimulationError('--check is available for --target deployed')
    if type(repeat) is not int or not 1 <= repeat <= 20:
        raise SimulationError('Repetitions must be between 1 and 20')
    planned = preview(config, tier, requested, repeat)
    if not live:
        return planned
    if planned['status'] != 'planned':
        raise SimulationError('Workflow cannot start: ' + planned['status'])
    if not run_id and not sys.stdin.isatty():
        raise SimulationError('New live setup requires an interactive terminal; supply a prepared --run-id for unattended execution')
    runtime = Runtime(config, run_id) if run_id else Runtime.prepare(config)
    if runtime.manifest.get('results') or runtime.manifest.get('invocations'):
        raise SimulationError('This campaign was already attempted; prepare a new run and retain its original results')
    print(json.dumps({'run_id': runtime.run_id, 'tier': tier, 'selected': planned['selected'],
                      'report': str(runtime.folder / 'report.md')}, indent=2), flush=True)
    try:
        if not run_id:
            fixtures.seed(runtime, fixtures.variables(config))
            with running(runtime):
                print('Account setup portal: ' + runtime.url + '/portal/', flush=True)
                print('Keep your HTTPS tunnel pointing to ' + runtime.gateway_url + '.', flush=True)
                print('Connect test calendars/Gmail, index the simulation knowledge file, and verify '
                      'the registered webhook, WhatsApp recipients and configured receiving inbox.\n'
                      'See docs/LIVE_SIMULATIONS.md for setup details. '
                      'Continuing launches paid conversations and real notifications.', flush=True)
                try:
                    input('Press Enter when setup is ready, or Ctrl+C to retain this prepared run: ')
                except EOFError:
                    raise SimulationError('Setup input ended; runtime retained for --run-id continuation') from None
        return run_campaign(runtime, tier, requested, live=True, repeat=repeat)
    except BaseException:
        runtime.manifest['status'] = 'incomplete'
        runtime.save()
        raise
    finally:
        write_report(runtime)
        print('Report: ' + str(runtime.folder / 'report.md'), flush=True)
        print('Run ID: ' + runtime.run_id + '. Cleanup when ready: '
              '.venv/bin/python -m live_simulations cleanup --config '
              + shlex.quote(str(config_path)) + ' --run-id ' + runtime.run_id + ' --live', flush=True)
