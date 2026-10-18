"""python -m live_simulations --help"""
from __future__ import annotations

import argparse
import json
import sys
import time

from . import fixtures
from .core import SimulationError, load_config, redact
from .runner import (
    campaign_status,
    cleanup,
    preview,
    reconcile,
    run_campaign,
    write_report,
)
from .runtime import Runtime, running


def main(argv=None):
    parser = argparse.ArgumentParser(description='Opt-in, budgeted ElevenLabs live acceptance')
    sub = parser.add_subparsers(dest='command', required=True)
    for command in ('plan', 'prepare', 'serve', 'run', 'workflow', 'cleanup', 'report', 'reconcile', 'confirm-handset'):
        p = sub.add_parser(command)
        p.add_argument('--config', required=command != 'workflow',
                       default=None)
        if command == 'workflow':
            p.add_argument('--target', choices=('isolated', 'deployed'))
            p.add_argument('--check', action='store_true', help='Read-only deployed readiness check; no paid submissions')
            p.add_argument('--continue-unpaid', action='store_true', help='Explicit same-run zero-submit deployed medium continuation')
        if command in ('plan', 'run', 'workflow'):
            p.add_argument('--tier', choices=('minimal', 'medium', 'full'), default='minimal')
            p.add_argument('--cases', help='Comma-separated subset; includes lifecycle prerequisites')
            p.add_argument('--repeat', type=int, default=1)
        if command not in ('plan', 'prepare'):
            p.add_argument('--run-id', required=command != 'workflow')
        if command in ('serve', 'run', 'workflow', 'cleanup'):
            p.add_argument('--live', action='store_true')
        if command == 'confirm-handset':
            p.add_argument('--message-sid', required=True)
    args = parser.parse_args(argv)
    try:
        if args.command in ('run', 'serve') and not args.live:
            raise SimulationError(args.command + ' requires --live before provider effects are enabled')
        if hasattr(args, 'repeat') and not 1 <= args.repeat <= 20:
            raise SimulationError('Repetitions must be between 1 and 20')
        if args.command == 'workflow' and args.config is None:
            args.config = ('scratch/live-simulations.deployed.json' if args.target == 'deployed'
                           else 'scratch/live-simulations.local.json')
        config = load_config(args.config)
        if getattr(args, 'target', None):
            config['target'] = args.target
        requested = args.cases.split(',') if getattr(args, 'cases', None) else None
        if args.command == 'workflow':
            from .workflow import execute
            value = execute(config, args.tier, live=args.live, run_id=args.run_id,
                            requested=requested, repeat=args.repeat, config_path=args.config, check=args.check, continue_unpaid=args.continue_unpaid)
            print(json.dumps(redact(value if not args.live else {
                'status': value['status'], 'run_id': value['run_id']}), indent=2))
            return {'passed': 0, 'planned': 0, 'failed': 1, 'blocked': 2, 'incomplete': 3}.get(value['status'], 2)
        if config.get('target') == 'deployed':
            from .deployed import manage
            if args.command not in ('report', 'reconcile', 'cleanup'):
                raise SimulationError('Use workflow --target deployed for deployed preview/check/run')
            return manage(config, args.run_id, args.command, live=getattr(args, 'live', False))
        if args.command == 'plan':
            value = preview(config, args.tier, requested, repeat=args.repeat)
            print(json.dumps(value, indent=2))
            return 0 if value['status'] == 'planned' else 2
        if args.command == 'prepare':
            runtime = Runtime.prepare(config)
            fixtures.seed(runtime, fixtures.variables(config))
            print(json.dumps({'run_id': runtime.run_id, 'portal': runtime.url + '/portal/',
                              'next': 'serve --live for account setup, then stop it before run --live'}, indent=2))
            return 0
        runtime = Runtime(config, args.run_id)
        if args.command == 'serve':
            with running(runtime):
                print('Isolated portal: ' + runtime.url + '/portal/', flush=True)
                while True:
                    time.sleep(1)
        elif args.command == 'run':
            result = run_campaign(runtime, args.tier, requested, live=True, repeat=args.repeat)
            print(json.dumps(redact({'status': result['status'], 'report': str(runtime.folder / 'report.md')})))
            return {'passed': 0, 'failed': 1, 'blocked': 2, 'incomplete': 3}[result['status']]
        elif args.command == 'cleanup':
            cleanup(runtime, live=args.live)
            print('Owned resources cleaned; evidence retained at ' + str(runtime.folder))
        elif args.command == 'report':
            write_report(runtime)
            print((runtime.folder / 'report.md').read_text())
        elif args.command == 'reconcile':
            reconcile(runtime)
            print('Provider billing reconciled; original results retained')
        elif args.command == 'confirm-handset':
            # Only permit attestation for a SID actually captured in this campaign.
            text = '\n'.join(p.read_text() for p in runtime.folder.glob('C*-evidence*.json'))
            if args.message_sid not in text or not runtime.manifest.get('awaiting_handset_confirmation'):
                raise SimulationError('Handset confirmation must reference this campaign delivery evidence')
            runtime.manifest['handset_confirmation'] = {'sid': args.message_sid, 'at': time.time(), 'source': 'operator'}
            runtime.manifest['awaiting_handset_confirmation'] = False
            runtime.manifest['status'] = campaign_status(runtime.manifest['results'])
            runtime.save()
            write_report(runtime)
        return 0
    except KeyboardInterrupt:
        print('Interrupted; owned resources and incomplete evidence retained for cleanup.', file=sys.stderr)
        return 3
    except (SimulationError, OSError, ValueError) as exc:
        print(json.dumps({'status': 'blocked', 'reason': redact(str(exc))}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
