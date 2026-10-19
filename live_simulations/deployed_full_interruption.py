"""C48 cancellation controller for an already journaled owned invocation.

This module neither submits paid work nor supplies adapter/CLI capability. Observers
must read native rows; synthetic test observations are not deployment evidence.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path

from .core import SimulationError, fingerprint, number, private_json, redact
from .provider import ElevenLabs
from .runner import campaign_lock


@dataclass(frozen=True)
class Binding:
    run_id: str
    case_id: str
    attempt: int
    test_id: str
    agent_id: str
    invocation_id: str

    def as_dict(self):
        return asdict(self)

    def validate(self):
        if (not isinstance(self.run_id, str) or not re.fullmatch(r'[0-9a-f]{32}', self.run_id)
                or self.case_id != 'C48' or type(self.attempt) is not int or self.attempt < 1
                or any(not isinstance(v, str) or not v or not re.fullmatch(r'[\w-]+', v)
                       for v in (self.test_id, self.agent_id, self.invocation_id))):
            raise SimulationError('Exact owned C48 invocation binding is required')


def _positive_id(value):
    return type(value) is int and value > 0


def _same_binding(saved, expected):
    return (isinstance(saved, dict) and saved.keys() == expected.keys()
            and all(type(saved[key]) is type(value) and saved[key] == value for key, value in expected.items()))


def _external(callback, *args):
    """Callback exception types do not make their diagnostic text safe to retain."""
    try:
        return callback(*args)
    except Exception:  # noqa: BLE001 - sanitize provider/native callbacks, including SimulationError.
        raise SimulationError('Provider or native interruption observation unavailable') from None


def _read(path):
    if path.is_symlink():
        raise SimulationError('Interruption artifact must not be a symlink')
    try:
        value = json.loads(path.read_text())
    except (OSError, ValueError):
        raise SimulationError('Required interruption journal is unavailable') from None
    if not isinstance(value, dict):
        raise SimulationError('Invalid interruption journal')
    return value


def _sync_directory(folder):
    fd = os.open(folder, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _intent(path, value):
    """Exclusive immutable intent; every write/fsync must finish before cancel."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(value, stream, allow_nan=False, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    _sync_directory(path.parent)


def _context(root, binding):
    binding.validate()
    folder = root / binding.run_id
    if folder.is_symlink() or not folder.is_dir():
        raise SimulationError('Owned campaign folder is unavailable')
    pre = _read(folder / f'C48-{binding.attempt}-pre-invocation.json')
    journal = _read(folder / f'C48-{binding.attempt}-interruption-journal.json')
    manifest = _read(folder / 'manifest.json')
    ledger = _read(root / 'usage-ledger.json')
    entries = ledger.get('entries')
    if not isinstance(entries, list) or any(not isinstance(e, dict) for e in entries):
        raise SimulationError('Invalid common usage ledger')
    matches = [e for e in entries if e.get('invocation_id') == binding.invocation_id]
    if (journal.get('schema_version') != 1 or not _same_binding(journal.get('binding'), binding.as_dict())
            or manifest.get('run_id') != binding.run_id
            or manifest.get('campaign_agent_id') != binding.agent_id
            or binding.invocation_id not in manifest.get('invocations', [])
            or binding.test_id not in manifest.get('provider_tests', [])
            or len(matches) != 1
            or not _same_binding({key: matches[0].get(key) for key in binding.as_dict()}, binding.as_dict())
            or matches[0].get('interruption_journal_sha256') != fingerprint(journal)):
        raise SimulationError('Interruption journal does not bind exact owned invocation')
    if (not isinstance(pre.get('test_definition'), dict)
            or pre.get('schema_version') != 1
            or not _same_binding(pre.get('binding'), {k: v for k, v in binding.as_dict().items() if k != 'invocation_id'})
            or journal.get('pre_invocation_sha256') != fingerprint(pre)
            or matches[0].get('pre_invocation_sha256') != fingerprint(pre)
            or any(pre.get(k) != journal.get(k) for k in ('baseline', 'expected_booking', 'tool_url'))
            or pre.get('test_definition', {}).get('id') != binding.test_id
            or pre.get('test_definition', {}).get('type') != 'simulation'
            or pre.get('test_definition', {}).get('tool_mock_config') != {
                'mocking_strategy': 'none', 'fallback_strategy': 'call_real_tool', 'mocked_tool_ids': []}
            or pre.get('invocation_request') != {'tests': [{'test_id': binding.test_id}], 'repeat_count': 1}):
        raise SimulationError('Immutable native pre-invocation baseline and unmocked test/request receipt are required')
    baseline = journal.get('baseline', {})
    try:
        if (baseline.get('source') != 'native_postgresql'
                or not _positive_id(baseline.get('customer_id'))
                or not _positive_id(journal['expected_booking'].get('customer_id'))
                or not _positive_id(journal['expected_booking'].get('staff_agent_id'))
                or baseline.get('customer_id') != journal['expected_booking']['customer_id']
                or type(baseline['observed_at_unix']) not in (int, float)
                or type(journal['submitted_at_unix']) not in (int, float)
                or not number(baseline['observed_at_unix'], positive=True) < number(journal['submitted_at_unix'], positive=True)
                or baseline['active_request_ids'] != []
                or any(not isinstance(baseline[k], list)
                       or any(not _positive_id(i) for i in baseline[k])
                       for k in ('request_ids', 'reservation_ids'))
                or not isinstance(journal['tool_url'], str)
                or not journal['tool_url'].startswith('https://')):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise SimulationError('Pre-invocation native baseline is required; it cannot be retrofitted') from None
    return folder, journal, ledger, matches[0]


def _provider_run(result, binding):
    if (not isinstance(result, dict) or result.get('id') != binding.invocation_id
            or result.get('agent_id') != binding.agent_id
            or type(result.get('cancelled')) is not bool
            or not isinstance(result.get('test_runs'), list) or len(result['test_runs']) != 1):
        raise SimulationError('Provider invocation identity or scope differs')
    run = result['test_runs'][0]
    if (not isinstance(run, dict) or run.get('test_id') != binding.test_id
            or run.get('test_invocation_id') != binding.invocation_id
            or run.get('status') not in ('pending', 'passed', 'failed', 'cancelled')):
        raise SimulationError('Provider test identity or status is unknown')
    return run


def _booking(observation, journal):
    """Validate relational native readback, not an operator ready/success flag."""
    try:
        expected = journal['expected_booking']
        baseline = journal['baseline']
        requests, reservations, segments = (observation[k] for k in ('requests', 'reservations', 'segments'))
        if observation['source'] != 'native_postgresql' or len(requests) != 1 or len(reservations) != 1:
            raise ValueError
        request, reservation = requests[0], reservations[0]
        start, end = (datetime.fromisoformat(expected[k]) for k in ('starts_at', 'ends_at'))
        if (not _positive_id(expected['customer_id']) or not _positive_id(expected['staff_agent_id'])
                or start.tzinfo is None or end.tzinfo is None or start.second or start.microsecond or start.minute % 15
                or expected['service_type'] != 'Oil Change' or expected['duration_minutes'] != 60
                or end - start != timedelta(minutes=60)
                or not all(_positive_id(value) for value in (observation['customer_id'], request['id'],
                    request['customer_id'], request['staff_agent_id'], reservation['id'],
                    reservation['service_request_id'], reservation['staff_agent_id']))
                or request['id'] in baseline['request_ids'] or reservation['id'] in baseline['reservation_ids']
                or request['customer_id'] != observation['customer_id'] or request['customer_id'] != expected['customer_id']
                or request['service_type'] != expected['service_type'] or request['booking_type'] != 'appointment'
                or request['status'] not in ('pending', 'scheduled', 'confirmed')
                or request['duration_minutes'] != 60
                or request['staff_agent_id'] != expected['staff_agent_id']
                or request['booking_start_at'] != expected['starts_at'] or request['booking_end_at'] != expected['ends_at']
                or reservation['service_request_id'] != request['id'] or reservation['status'] != 'ACTIVE'
                or reservation['staff_agent_id'] != expected['staff_agent_id']
                or reservation['starts_at'] != expected['starts_at'] or reservation['ends_at'] != expected['ends_at']):
            raise ValueError
        expected_segments = {start + timedelta(minutes=offset) for offset in (0, 15, 30, 45)}
        if (len(segments) != 4 or {datetime.fromisoformat(s['segment_start']) for s in segments} != expected_segments
                or any(not _positive_id(s['reservation_id']) or not _positive_id(s['staff_agent_id'])
                       or s['reservation_id'] != reservation['id'] or s['staff_agent_id'] != expected['staff_agent_id']
                       for s in segments)):
            raise ValueError
        return observation
    except (KeyError, TypeError, ValueError):
        raise SimulationError('Native booking and reservation are not a new exact owned C48 effect') from None


def _decoded(value):
    return json.loads(value) if isinstance(value, str) else value


def _executed_booking(run, journal, booking):
    request_id = booking['requests'][0]['id']
    reservation_id = booking['reservations'][0]['id']
    calls, results = [], []
    try:
        for response in run.get('agent_responses', []):
            calls.extend(c for c in response.get('tool_calls', []) if c.get('tool_name') == 'book_appointment')
            results.extend(r for r in response.get('tool_results', []) if r.get('tool_name') == 'book_appointment')
        if len(calls) != 1 or len(results) != 1:
            raise ValueError
        call, result = calls[0], results[0]
        details = call['tool_details']
        arguments = _decoded(call['params_as_json'])
        value = _decoded(result['result_value'])
        value = value.get('result', value)
        if (call.get('type') != 'webhook' or call.get('tool_has_been_called') is not True
                or not isinstance(call.get('request_id'), str) or not call['request_id']
                or not isinstance(result.get('request_id'), str) or result['request_id'] != call['request_id']
                or details.get('type') != 'webhook' or details.get('method') != 'POST'
                or details.get('url') != journal['tool_url']
                or not isinstance(arguments, dict) or arguments.get('service_type') != 'Oil Change'
                or result.get('is_error') is not False or value.get('success') is not True
                or not _positive_id(value.get('appointment_id')) or value['appointment_id'] != request_id
                or not isinstance(value.get('appointments'), list) or len(value['appointments']) != 1):
            raise ValueError
        appointment = value['appointments'][0]
        expected = journal['expected_booking']
        returned_start = datetime.fromisoformat(appointment['booking_time'])
        expected_start = datetime.fromisoformat(expected['starts_at'])
        if returned_start.tzinfo is None:
            returned_start = returned_start.replace(tzinfo=expected_start.tzinfo)
        if (not _positive_id(appointment.get('service_request_id')) or appointment['service_request_id'] != request_id
                or not _positive_id(appointment.get('reservation_id')) or appointment['reservation_id'] != reservation_id
                or not _positive_id(appointment.get('staff_agent_id'))
                or appointment['staff_agent_id'] != expected['staff_agent_id']
                or appointment.get('duration_minutes') != 60 or appointment.get('booking_type') != 'appointment'
                or appointment.get('service_type') != 'Oil Change' or returned_start != expected_start):
            raise ValueError
        return {'provider_request_id': call['request_id'], 'native_request_id': request_id,
                'native_reservation_id': reservation_id}
    except (KeyError, TypeError, ValueError, AttributeError):
        raise SimulationError('Cancelled receipt lacks a paired executed native HTTP booking effect') from None


def _report(status, reason, *, credits=None, verified=False, stop=True, proof=None):
    return {'status': status, 'reason': reason, 'credits': credits, 'global_stop': stop,
            'interruption_verified': verified, 'recovery_booking_prerequisites_verified': verified,
            'recovery_prerequisites_verified': False,
            'remaining_recovery_prerequisites': ['reviewed_adapter_integration', 'separate_paid_budget',
                                                 'native_calendar_delivery_evidence', 'actual_recovery_execution'],
            'recovery_started': False, 'full_case_supported': False, 'proof': proof}


def _settle(root, ledger, entry, receipt):
    # Same common ledger semantics as runner.reconcile: unknown charges remain
    # unsettled; terminal actual credits replace no estimates and never accumulate twice.
    credits = ElevenLabs.credits(receipt)
    if credits is None:
        return None
    amount = str(number(credits))
    if entry.get('unsettled') is False and number(entry.get('credits')) != number(amount):
        raise SimulationError('Settled invocation credits conflict with provider readback')
    entry.update(unsettled=False, credits=amount)
    private_json(root / 'usage-ledger.json', ledger)
    return amount


def advance(root, *, binding, provider, observe_booking, reconcile_only=False, max_polls=3):
    """Observe bounded GETs, at most one cancel ever; never create/retry paid work.

    Caller supplies authenticated provider and an independently owned native reader.
    Existing attempt journal + ledger must precede this controller. Without a durable
    intent, reconcile_only never writes to the provider. No wait() is used because
    the provider wait helper itself cancels on timeout.
    """
    if type(max_polls) is not int or not 1 <= max_polls <= 100 or type(reconcile_only) is not bool:
        raise SimulationError('Invalid bounded interruption observation options')
    root = Path(root)
    with campaign_lock(root):
        folder, journal, ledger, entry = _context(root, binding)
        intent_path = folder / f'C48-{binding.attempt}-cancel-intent.json'
        state_path = folder / f'C48-{binding.attempt}-interruption.json'
        intent = _read(intent_path) if intent_path.exists() else None
        if intent is not None and (not _same_binding(intent.get('binding'), binding.as_dict())
                                   or intent.get('journal_sha256') != fingerprint(journal)):
            raise SimulationError('Existing cancellation intent belongs to another binding')

        def terminal(receipt):
            # Retain redacted source receipts, including unknown-credit revisions.
            # Digests identify the original unredacted response without persisting secrets.
            path = folder / f'C48-{binding.attempt}-terminal-{fingerprint(receipt)}.json'
            private_json(path, {'provider_sha256': fingerprint(receipt), 'receipt': redact(receipt)})
            _sync_directory(folder)
            return _settle(root, ledger, entry, receipt)

        def save(report):
            private_json(state_path, {'binding': binding.as_dict(), **report})
            _sync_directory(folder)
            return report

        try:
            receipt = _external(provider.get, binding.invocation_id)
            run = _provider_run(receipt, binding)
            if intent is None:
                if run['status'] != 'pending':
                    credits = terminal(receipt)
                    return save(_report('failed_interruption', 'Invocation completed before cancellation intent',
                                        credits=credits))
                if receipt['cancelled']:
                    return save(_report('blocked', 'Provider cancellation was already requested outside this intent'))
                if reconcile_only:
                    return save(_report('blocked', 'No cancellation intent; reconciliation cannot initiate cancellation'))
                booking = _booking(_external(observe_booking), journal)
                intent = {'binding': binding.as_dict(), 'journal_sha256': fingerprint(journal),
                          'pending_provider_sha256': fingerprint(receipt), 'native_booking': booking}
                _intent(intent_path, intent)
                try:
                    provider.cancel(binding.invocation_id)
                except Exception:  # noqa: BLE001 - ambiguous write is never retried.
                    return save(_report('awaiting_terminal', 'Cancellation outcome unknown; reconcile same handle with GET only'))
                receipt = None
            for _ in range(max_polls):
                if receipt is None:
                    receipt = _external(provider.get, binding.invocation_id)
                    run = _provider_run(receipt, binding)
                if run['status'] != 'pending':
                    credits = terminal(receipt)
                    if credits is None:
                        return save(_report('blocked', 'Actual terminal credits remain unknown'))
                    if run['status'] != 'cancelled':
                        return save(_report('failed_interruption', 'Invocation did not genuinely cancel', credits=credits))
                    if receipt['cancelled'] is not True:
                        raise SimulationError('Provider invocation cancellation flag contradicts cancelled run')
                    booking = _booking(_external(observe_booking), journal)
                    if booking != intent['native_booking']:
                        raise SimulationError('Native owned booking changed after cancellation intent')
                    effect = _executed_booking(run, journal, booking)
                    proof = {**effect, 'binding': binding.as_dict(), 'journal_sha256': fingerprint(journal),
                             'terminal_provider_sha256': fingerprint(receipt), 'native_booking_sha256': fingerprint(booking),
                             'pending_provider_sha256': intent['pending_provider_sha256']}
                    return save(_report('verified_interruption', 'Cancelled invocation, actual charge and native booking effect verified',
                                        credits=credits, verified=True, stop=any(e.get('unsettled') is not False for e in ledger['entries']), proof=proof))
                receipt = None
            return save(_report('awaiting_terminal', 'Same invocation remains pending; no cancellation retry'))
        except SimulationError as exc:
            # Conflicting settled charge is a ledger-integrity error, not reconcilable uncertainty.
            if str(exc) == 'Settled invocation credits conflict with provider readback':
                raise
            return save(_report('blocked', str(exc)))
        except Exception:  # noqa: BLE001 - provider/native read failures must stop further paid work.
            return save(_report('blocked', 'Interruption observation unavailable; reconcile same handle without writes'))
