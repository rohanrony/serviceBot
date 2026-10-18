"""Deployed campaigns with native API smoke and scoped medium observations.

Acceptance remains incomplete while native provider evidence is unavailable.
Budgets, durable invocation intents and bounded fixture ownership are shared.
"""
from __future__ import annotations

import contextlib
import copy
import hashlib
import json
import os
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import httpx

from . import deployed_medium, evidence, fixtures
from .core import (
    ROOT,
    Budget,
    SimulationError,
    fingerprint,
    load_catalog,
    number,
    private_json,
    redact,
    render,
    secret,
    select_cases,
)
from .provider import ElevenLabs
from .runner import (
    campaign_lock,
    case_variables,
    claim_stage,
    current_remaining,
    email_mode,
    estimates,
    functional_checks,
    load_reference,
    preview,
    stage_authorization,
)

MISSING_EVIDENCE = [
    'scoped database/reservation invariants', 'reloaded browser portal',
    'native Google calendar effects', 'signed WhatsApp callback and delivery',
    'receiving Gmail inbox', 'native tool request/result trace',
]


def origin(value):
    try:
        parsed = urlparse(value or '')
        port = parsed.port
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
                or parsed.path not in ('', '/') or parsed.query or parsed.fragment
                or (port is not None and port != 443)):
            raise ValueError()
    except (ValueError, TypeError):
        raise SimulationError('deployed_url must be an explicit HTTPS origin (no credentials/path/query)') from None
    return value.rstrip('/')


def phone(value):
    digits = re.sub(r'\D', '', str(value or ''))
    return '+' + ('1' + digits if len(digits) == 10 else digits)


def scoped(rows, number):
    if not isinstance(rows, list):
        raise SimulationError('Deployment booking API must return a list')
    return [r for r in rows if phone(r.get('phone')) == phone(number)]


def get(client, url, path):
    response = client.get(url + path)
    if response.status_code != 200:
        raise SimulationError('Readiness GET ' + path + ' returned HTTP ' + str(response.status_code))
    return response.json()


def preserved_customer_name(config, baseline, client=None):
    binding = config.get('existing_customer_identity')
    if binding is not None and (config.get('preserve_existing_bookings') is not True or not baseline):
        raise SimulationError('Explicit customer identity requires preservation and a nonempty scoped baseline')
    if config.get('preserve_existing_bookings') is not True or not baseline:
        return None
    names = [row.get('customer_name') for row in baseline]
    if binding is not None:
        if (not isinstance(binding, dict) or type(binding.get('id')) is not int or binding['id'] <= 0
                or not isinstance(binding.get('name'), str) or not binding['name'].strip()
                or binding['name'] not in names or client is None):
            raise SimulationError('Explicit customer identity requires an exact baseline name and native verification')
        try:
            response = client.post(origin(config.get('deployed_url')) + '/api/v1/voice/tools', json={
                'name': 'verify_caller_identity', 'arguments': {
                    'phone': fixtures.variables(config)['customer_phone'],
                    'claimed_name': binding['name'], 'read_only': True}})
            actual = response.json()['result']
            if (response.status_code != 200 or actual.get('success') is not True
                    or actual.get('read_only') is not True or actual.get('is_existing_customer') is not True
                    or actual.get('is_verified_existing_customer') is not True
                    or actual.get('customer_id') != binding['id'] or actual.get('customer_name') != binding['name']):
                raise ValueError()
        except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError):
            raise SimulationError('Native customer identity does not match the explicit binding') from None
        return binding['name']
    if (any(not isinstance(name, str) or not name.strip() for name in names)
            or len(set(names)) != 1):
        raise SimulationError('Preserved customer name must be nonblank and consistent across baseline records')
    return names[0]


def deployment_readiness(config, client):
    """Read only; inspect every reachable receiver rather than editing staff."""
    url = origin(config.get('deployed_url'))
    values = fixtures.variables(config)
    allowed_phones = {phone(v) for v in config.get('allowlisted_phone_numbers', [])}
    allowed_emails = {v.lower() for v in config.get('allowlisted_emails', [])}
    problems, baseline = [], []
    if phone(values['customer_phone']) not in allowed_phones:
        problems.append('Designated customer phone must be allowlisted')
    if config.get('email_receiver', '').lower() not in allowed_emails:
        problems.append('Designated receiving inbox must be allowlisted')
    if not config.get('whatsapp_ready'):
        problems.append('Verify current WhatsApp enrollment/window, then set whatsapp_ready=true')
    for path in ('/health', '/api/v1/portal/secrets', '/api/v1/portal/gmail-config', '/api/v1/portal/agents',
                 '/api/v1/portal/service-requests'):
        try:
            data = get(client, url, path)
            if path == '/health':
                if data.get('status') != 'healthy':
                    problems.append('Deployment is not healthy')
            elif path.endswith('/secrets'):
                # Consume only the public agent identity, never credential metadata.
                active_agent = data.get('elevenlabs_agent', {}).get('display_value')
                if not isinstance(active_agent, str) or not active_agent.strip():
                    problems.append('Cannot verify the active deployed ElevenLabs agent identity')
                elif active_agent != config.get('agent_id'):
                    problems.append('Configured reference agent differs from the active deployed ElevenLabs agent')
            elif path.endswith('/gmail-config'):
                if not data.get('gmail_enabled'):
                    problems.append('Enable Gmail on the deployed app')
                for field in ('gmail_sender', 'gmail_recipient'):
                    if not data.get(field) or data[field].lower() not in allowed_emails:
                        problems.append('Deployed ' + field + ' is outside the designated email allowlist')
                if data.get('admin_phone_number') and phone(data['admin_phone_number']) not in allowed_phones:
                    problems.append('Deployed admin phone is outside the designated phone allowlist')
            elif path.endswith('/agents'):
                if not isinstance(data, list) or not data:
                    problems.append('Deployment must expose its reachable technician list')
                    continue
                for member in data:
                    if member.get('is_active') is False:
                        continue
                    if (member.get('email', '').lower() not in allowed_emails
                            or phone(member.get('phone_number')) not in allowed_phones):
                        problems.append('Technician ID ' + str(member.get('id')) + ' has a non-allowlisted notification destination')
            else:
                baseline = scoped(data, values['customer_phone'])
                try:
                    preserved_customer_name(config, baseline, client)
                except SimulationError as exc:
                    problems.append(str(exc))
                if (config.get('preserve_existing_bookings') is not True
                        and any(r.get('status') not in ('cancelled', 'cancelled_by_customer', 'completed', 'done') for r in baseline)):
                    problems.append('Customer already has an active booking; use a designated empty test baseline')
        except (httpx.HTTPError, ValueError, SimulationError, AttributeError):
            problems.append('Cannot verify deployment endpoint ' + path)
    return problems, baseline


def native_override(agent, url, webhook_id):
    """Copy native tool authentication; never send an isolated gateway token."""
    for tool in agent['conversation_config'].get('agent', {}).get('prompt', {}).get('tools', []):
        if tool.get('type') == 'webhook':
            destination = urlparse(tool.get('api_schema', {}).get('url', ''))
            if (destination.scheme + '://' + destination.netloc != url
                    or destination.path != '/api/v1/voice/tools' or destination.fragment):
                raise SimulationError('Reference tool destination does not match the selected deployment')
    result = ElevenLabs.override(agent, url, '', webhook_id)
    # The provider materializes this built-in default when creating an agent.
    # Send it explicitly so read-back still compares every material setting.
    copied_agent = result['conversation_config']['agent']
    if copied_agent.get('text_behavior_overrides') is None:
        copied_agent['text_behavior_overrides'] = {'whatsapp': {
            'verbosity': None, 'output_format': None, 'interaction_budget': None,
            'disable_max_duration': True}}
    originals = {t['name']: t for t in agent['conversation_config']['agent']['prompt']['tools']}
    for tool in result['conversation_config']['agent']['prompt']['tools']:
        if tool.get('type') == 'webhook':
            schema = tool['api_schema']
            old = originals[tool['name']]['api_schema']
            schema['request_headers'] = copy.deepcopy(old.get('request_headers', {}))
            schema['request_headers'].pop('X-Live-Simulation-Token', None)
            schema['request_headers']['X-Caller-ID'] = '{{caller_phone}}'
            if old.get('auth_connection'):
                schema['auth_connection'] = copy.deepcopy(old['auth_connection'])
    return result


def provider_readiness(config, client):
    problems = []
    try:
        provider = ElevenLabs(secret(config, 'elevenlabs_key'), client=client)
        remaining = current_remaining(config, provider)
        reference = load_reference({**config, 'agent_id': config.get('agent_id')
                                    or os.getenv('ELEVENLABS_AGENT_ID', '')}, provider)
        url = origin(config.get('deployed_url'))
        webhook_id = config.get('post_call_webhook_id')
        if not webhook_id:
            hooks = provider.request('GET', '/v1/workspace/webhooks?include_usages=false').get('webhooks', [])
            matches = [h for h in hooks if h.get('webhook_url') == url + '/api/v1/telephony/webhook'
                       and h.get('auth_type') == 'hmac' and h.get('is_disabled') is False
                       and h.get('is_auto_disabled') is False]
            if len(matches) != 1:
                raise SimulationError('Set post_call_webhook_id to the existing enabled deployed HMAC webhook')
            webhook_id = matches[0]['webhook_id']
        provider.verify_webhook(webhook_id, url, reference)
        override = native_override(reference, url, webhook_id)
        if config.get('calibration') is not None:
            override['conversation_config']['agent']['prompt']['max_tokens'] = 256
        return {'provider': provider, 'remaining': remaining, 'override': override,
                'webhook_id': webhook_id}, problems
    except (SimulationError, KeyError, httpx.HTTPError):
        problems.append('Verify standard ElevenLabs key/agent, monthly billing period/units and deployed HMAC webhook')
        return {}, problems


def lifecycle_checks(case_id, values, before, after, business_timezone='America/New_York'):
    def booking_time(value):
        try:
            parsed = datetime.fromisoformat(value)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=ZoneInfo(business_timezone))
            return parsed.astimezone(timezone.utc)
        except (TypeError, ValueError):
            return None

    checks = []
    if case_id not in {f'C{i:02}' for i in range(1, 7)}:
        return [evidence.check('scenario-specific deployed state acceptance unavailable', False)]
    active = [r for r in after if r.get('status') not in ('cancelled', 'cancelled_by_customer', 'completed', 'done')]
    cancelled = case_id in ('C03', 'C06')
    checks.append(evidence.check('active request count', len(active) == (0 if cancelled else 1), len(active)))
    if case_id in ('C02', 'C03', 'C05', 'C06'):
        checks.append(evidence.check('booking identity preserved', bool(before) and {r['id'] for r in before} == {r['id'] for r in after}))
    if cancelled:
        checks.append(evidence.check('cancelled booking retained', bool(after) and all(r.get('status') == 'cancelled' for r in after)))
    else:
        field, kind = {'C01': ('appointment_time', 'appointment'), 'C02': ('new_time', 'appointment'),
                       'C04': ('callback_time', 'callback'), 'C05': ('new_callback_time', 'callback')}[case_id]
        target = booking_time(values[field])
        checks.append(evidence.check('exact recorded booking time and type', len(active) == 1
            and target is not None and booking_time(active[0].get('booking_time')) == target
            and active[0].get('booking_type') == kind))
        if case_id in ('C02', 'C05'):
            checks.append(evidence.check('booking time changed', len(before) == len(active) == 1
                and booking_time(before[0].get('booking_time')) is not None
                and booking_time(active[0].get('booking_time')) is not None
                and booking_time(before[0].get('booking_time')) != booking_time(active[0].get('booking_time'))))
    return checks


def result_status(checks, *, provider_passed):
    return 'incomplete' if provider_passed and checks and all(c['passed'] for c in checks) else 'failed'


def campaign_budget(config, tier, remaining):
    calibration = config.get('calibration')
    authorization = config.get('campaign_authorization')
    stage = config.get('stage_authorization')
    budget = Budget(config['budget']['monthly_credits'], tier, remaining,
                  credit_ceiling=(stage['credit_ceiling'] if stage is not None
                                  else authorization['credit_ceiling'] if authorization is not None
                                  else calibration['credit_ceiling'] if calibration is not None else None))
    if stage is None:
        budget.spent, _ = continuation_history(config)
    return budget


def continuation_history(config, ledger=None, current_run_id=None):
    """Validate settled immutable ancestry; no old manifest or ledger is rewritten."""
    authorization = config.get('campaign_authorization') or {}
    ancestor = authorization.get('continuation_of')
    total, ancestors = number(0), []
    if ancestor is None:
        return total, ancestors
    root = Path(config.get('artifact_root', ROOT / 'scratch/live-simulations')).resolve()
    try:
        if ledger is None:
            ledger = json.loads((root / 'usage-ledger.json').read_text())
        while ancestor is not None:
            if (not isinstance(ancestor, str) or not re.fullmatch(r'[0-9a-f]{32}', ancestor)
                    or ancestor in ancestors or ancestor == current_run_id):
                raise ValueError('invalid ancestry or cycle')
            folder = root / ancestor
            if folder.is_symlink() or folder.resolve().parent != root or (folder / 'manifest.json').is_symlink():
                raise ValueError('invalid ancestor path')
            manifest = json.loads((folder / 'manifest.json').read_text())
            old_authorization = manifest.get('campaign_authorization', {})
            if (manifest.get('run_id') != ancestor or manifest.get('target') != 'deployed'
                    or manifest.get('deployed_url') != origin(config.get('deployed_url'))
                    or manifest.get('status') not in ('failed', 'incomplete', 'completed')
                    or not manifest.get('results')
                    or any(r.get('status') not in ('passed', 'failed', 'blocked', 'incomplete') for r in manifest['results'])
                    or manifest.get('agent_create_pending') or manifest.get('test_create_pending')
                    or manifest.get('unsettled_usage')
                    or not old_authorization.get('authorization_id')
                    or old_authorization['authorization_id'] == authorization.get('authorization_id')
                    or number(old_authorization.get('credit_ceiling'), positive=True) != number(authorization['credit_ceiling'], positive=True)):
                raise ValueError('ancestor is not final or authorization differs')
            charges = [e for e in ledger['entries'] if e.get('run_id') == ancestor]
            if (not charges or any(e.get('unsettled') is not False or e.get('credits') is None
                    or not isinstance(e.get('invocation_id'), str) or not e['invocation_id']
                    or e.get('authorization_id') != old_authorization['authorization_id'] for e in charges)
                    or len({e['invocation_id'] for e in charges}) != len(charges)
                    or {e['invocation_id'] for e in charges} != set(manifest.get('invocations', []))):
                raise ValueError('ancestor ledger is incomplete or unsettled')
            spent = sum((number(e['credits']) for e in charges), number(0))
            if number(manifest.get('spent_credits')) != spent:
                raise ValueError('ancestor spending differs from ledger')
            total += spent
            ancestors.append(ancestor)
            ancestor = old_authorization.get('continuation_of')
        if any(e.get('run_id') not in ancestors and e.get('run_id') != current_run_id
                and (e.get('continuation_of') in ancestors
                     or any(a in ancestors for a in e.get('continuation_ancestors', []))) for e in ledger['entries']):
            raise ValueError('ancestor already consumed by another paid continuation')
    except (OSError, ValueError, KeyError, TypeError, SimulationError) as exc:
        raise SimulationError('Invalid continuation history: ' + str(exc)) from None
    return total, ancestors


def recovery_seed(config, current=None):
    authorization = config.get('campaign_authorization') or {}
    if 'resume_request_id' not in authorization:
        return None
    request_id = authorization['resume_request_id']
    ancestor = authorization.get('continuation_of')
    if (type(request_id) is not int or request_id <= 0 or not authorization.get('recovery_cases')
            or not isinstance(ancestor, str) or not re.fullmatch(r'[0-9a-f]{32}', ancestor)):
        raise SimulationError('Owned recovery seed requires explicit recovery cases and an ancestor')
    root = Path(config.get('artifact_root', ROOT / 'scratch/live-simulations')).resolve()
    try:
        folder = root / ancestor
        if folder.is_symlink() or folder.resolve().parent != root or (folder / 'manifest.json').is_symlink():
            raise ValueError()
        manifest = json.loads((folder / 'manifest.json').read_text())
        baseline = manifest['baseline']
        original_ids = {int(row['id']) for row in baseline} if isinstance(baseline, list) else {int(key) for key in baseline}
        if request_id in original_ids:
            raise ValueError()
        ledger = json.loads((root / 'usage-ledger.json').read_text())
        paid_cases = {entry.get('case_id') for entry in ledger['entries'] if entry.get('run_id') == ancestor}
        candidate = None
        for result in manifest['results']:
            case_id = result['case_id']
            if not re.fullmatch(r'C0[1-6]', case_id):
                raise ValueError()
            evidence_path = folder / f'{case_id}-{result.get("repeat", 1)}-evidence.json'
            if evidence_path.is_symlink():
                raise ValueError()
            required = case_id in paid_cases or result.get('functional_status') in ('passed', 'failed')
            if not evidence_path.exists():
                if required:
                    raise ValueError()
                continue
            evidence_rows = json.loads(evidence_path.read_text())['after']
            matching = [row for row in evidence_rows if row.get('id') == request_id]
            if len(matching) > 1:
                raise ValueError()
            if matching:
                candidate = matching[0]
        kind = candidate.get('booking_type') if candidate else None
        group = {'appointment': {'C02', 'C03'}, 'callback': {'C05', 'C06'}}.get(kind, set())
        designated_phone = phone(fixtures.variables(config)['customer_phone'])
        baseline_rows = baseline if isinstance(baseline, list) else baseline.values()
        known_baseline_phones = [row.get('phone') for row in baseline_rows
                                 if isinstance(row.get('phone'), str) and row.get('phone') != '[phone]']
        if (not candidate or not set(authorization['recovery_cases']) <= group
                or candidate.get('status') not in ('pending', 'confirmed', 'in_progress', 'rescheduled')
                or (candidate.get('phone') != '[phone]' and phone(candidate.get('phone')) != designated_phone)
                or any(phone(value) != designated_phone for value in known_baseline_phones)):
            raise ValueError()
        def instant(value):
            value = datetime.fromisoformat(str(value))
            if value.tzinfo is None:
                value = value.replace(tzinfo=ZoneInfo(config.get('app_config', {}).get('business_timezone', 'America/New_York')))
            return value.astimezone(timezone.utc)
        start = instant(candidate['booking_time'])
        move_case = 'C02' if kind == 'appointment' else 'C05'
        selected = {case['id'] for case in select_cases(load_catalog(), 'minimal', authorization['recovery_cases'])}
        move_result = next((row for row in manifest['results'] if row['case_id'] == move_case), {})
        if move_case in selected and move_result.get('functional_status') != 'passed':
            target = fixtures.variables(config)['new_time' if kind == 'appointment' else 'new_callback_time']
            if instant(target) == start:
                raise ValueError()
        if current is not None:
            fresh = [row for row in current if row.get('id') == request_id]
            if (len(fresh) != 1 or phone(fresh[0].get('phone')) != designated_phone
                    or redact(fresh[0]) != redact(candidate)):
                raise ValueError()
            return fresh[0]
        return candidate
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        raise SimulationError('Owned recovery seed lacks exact current active ancestor evidence or a changed target') from None


def recovery_selection(config):
    authorization = config.get('campaign_authorization') or {}
    if 'resume_request_id' in authorization and 'recovery_cases' not in authorization:
        raise SimulationError('Owned recovery seed requires explicit recovery cases')
    if 'recovery_cases' not in authorization:
        return None
    requested = authorization['recovery_cases']
    ancestor = authorization.get('continuation_of')
    allowed = {f'C{i:02}' for i in range(1, 7)}
    if (not isinstance(requested, list) or not requested
            or any(not isinstance(case, str) or case not in allowed for case in requested)
            or len(set(requested)) != len(requested)
            or not isinstance(ancestor, str) or not re.fullmatch(r'[0-9a-f]{32}', ancestor)):
        raise SimulationError('Campaign recovery requires unique minimal cases and a continuation ancestor')
    selected = select_cases(load_catalog(), 'minimal', requested)
    seed = recovery_seed(config)
    root = Path(config.get('artifact_root', ROOT / 'scratch/live-simulations')).resolve()
    try:
        folder = root / ancestor
        if folder.is_symlink() or folder.resolve().parent != root or (folder / 'manifest.json').is_symlink():
            raise ValueError()
        manifest = json.loads((folder / 'manifest.json').read_text())
        results = manifest['results']
        if (not isinstance(results, list)
                or any(not isinstance(row, dict) or row.get('case_id') not in allowed for row in results)
                or len({row.get('case_id') for row in results}) != len(results)):
            raise ValueError()
        retained = []
        for case in selected:
            rows = [row for row in results if row.get('case_id') == case['id']]
            if (seed is not None and case['id'] not in requested and len(rows) == 1
                    and rows[0].get('functional_status') == 'passed'
                    and rows[0].get('status') in ('passed', 'incomplete')
                    and case['id'] in ({'C01', 'C02'} if seed['booking_type'] == 'appointment' else {'C04', 'C05'})):
                continue
            if (len(rows) != 1 or rows[0].get('status') not in ('failed', 'blocked')
                    or rows[0].get('functional_status') not in (None, 'failed', 'blocked', 'not_run')):
                raise ValueError()
            retained.append(case['id'])
    except (OSError, ValueError, KeyError, TypeError):
        raise SimulationError('Campaign recovery requires unique failed or blocked ancestor results for every dependency') from None
    return retained


def authorization_plan(config, tier, requested, repeat):
    authorization = config['campaign_authorization']
    if (not isinstance(authorization, dict) or tier != 'minimal' or requested is not None
            or repeat != 1 or config.get('calibration') is not None):
        raise SimulationError('Campaign authorization requires all six minimal cases once, without calibration')
    if (not isinstance(authorization.get('authorization_id'), str)
            or not authorization['authorization_id'].strip()):
        raise SimulationError('Campaign authorization requires a nonblank authorization_id')
    number(authorization.get('credit_ceiling'), positive=True)
    recovery = recovery_selection(config)
    prior_spent, _ = continuation_history(config)
    planned = preview(config, tier, recovery, repeat)
    if 'resume_request_id' in authorization:
        planned.update(selected=recovery, complete_tier=False, resume_request_id=authorization['resume_request_id'])
    planned['campaign_authorization'] = copy.deepcopy(authorization)
    if config.get('budget', {}).get('verified_credit_units') is not True:
        return planned
    try:
        budget = campaign_budget(config, tier, config['budget']['remaining_credits'])
        cases = ([case for case in load_catalog() if case['id'] in recovery]
                 if 'resume_request_id' in authorization else select_cases(load_catalog(), tier, recovery))
        estimate = sum(estimates(config, cases))
    except SimulationError:
        return planned
    planned.update(tier_cap=str(budget.cap), admission_limit=str(budget.cap * number('.8')),
                   estimated_credits=str(estimate),
                   prior_spent_credits=str(prior_spent), aggregate_estimated_credits=str(prior_spent + estimate),
                   status='planned' if budget.can_start(estimate) else 'over_budget')
    return planned


def calibration_plan(config, tier, requested, repeat):
    calibration = config['calibration']
    if (not isinstance(calibration, dict) or tier != 'minimal' or repeat != 1
            or not isinstance(requested, list) or len(requested) != 1
            or requested[0] not in ('C01', 'C04')):
        raise SimulationError('Single-case calibration requires exactly C01 or C04, minimal tier and one repetition')
    if not isinstance(calibration.get('source_run_id'), str) or not calibration['source_run_id'].strip():
        raise SimulationError('Single-case calibration requires prior sample provenance')
    number(calibration.get('credit_ceiling'), positive=True)
    estimate = number(calibration.get('case_upper_estimate'), positive=True)
    budget = campaign_budget(config, tier, config['budget']['remaining_credits'])
    return {'tier': tier, 'selected': requested, 'complete_tier': False,
            'calibration': True, 'calibration_source_run_id': calibration['source_run_id'],
            'tier_cap': str(budget.cap), 'admission_limit': str(budget.cap * number('.8')),
            'estimated_credits': str(estimate),
            'status': 'planned' if budget.can_start(estimate) else 'over_budget',
            'notes': ['Single-case exploratory calibration; subscription credit-unit mapping remains unverified.',
                      'WhatsApp/email/application model costs are separate.']}


def unchanged(baseline_index, observed):
    current = {row['id']: row for row in observed}
    return all(current.get(key) == row for key, row in baseline_index.items())


def deployed_scenario(case, values):
    result = render(case, values)
    if case['id'] in {f'C{i:02}' for i in range(1, 7)}:
        result['max_turns'] = 12
    result['success_conditions'] = [
        ('Before booking, retrieve service facts from the deployed catalog tools or knowledge base. '
         'Quote exactly the returned price range and duration for each requested service, '
         'then obtain explicit acceptance before creating the booking.')
        if condition.startswith('Before booking, quote catalog facts accurately:') else condition
        for condition in result['success_conditions']]
    return result


class Campaign:
    """Local artifact ownership only. There is deliberately no database handle."""
    def __init__(self, config, tier, selected, run_id=None, *, allow_attempted=False):
        self.config = config
        self.root = Path(config.get('artifact_root', ROOT / 'scratch/live-simulations')).resolve()
        self.run_id = run_id or uuid.uuid4().hex
        if not re.fullmatch(r'[0-9a-f]{32}', self.run_id):
            raise SimulationError('Invalid deployed run ID')
        self.folder = self.root / self.run_id
        if self.folder.is_symlink() or self.folder.resolve().parent != self.root:
            raise SimulationError('Invalid deployed artifact path')
        if run_id:
            self.manifest = json.loads((self.folder / 'manifest.json').read_text())
            if (self.manifest.get('target') != 'deployed'
                    or self.manifest.get('run_id') != self.run_id
                    or self.manifest.get('deployed_url') != origin(config.get('deployed_url'))):
                raise SimulationError('Run manifest does not match deployed target')
            if self.manifest.get('attempted') and not allow_attempted:
                raise SimulationError('Campaign already attempted; retain report, reconcile unknown usage and use a new run')
        else:
            self.manifest = {'run_id': self.run_id, 'target': 'deployed',
                'deployed_url': origin(config.get('deployed_url')), 'tier': tier,
                'selected': selected, 'status': 'prepared', 'results': [],
                'provider_tests': [], 'invocations': [], 'created_at': time.time(),
                'missing_acceptance_evidence': MISSING_EVIDENCE}
        self.save()

    def save(self):
        private_json(self.folder / 'manifest.json', self.manifest)

    def report(self):
        private_json(self.folder / 'report.json', redact(self.manifest))
        lines = ['# Deployed live simulation ' + self.run_id, '',
                 'Status: **' + self.manifest['status'] + '**',
                 ('Scope: deployed medium native state and scoped browser observations.'
                  if self.manifest.get('stage_authorization') else
                  'Scope: conversation/API smoke; complete acceptance requires isolated observations.'), '',
                 'Missing acceptance evidence: ' + ', '.join(self.manifest.get('missing_acceptance_evidence', MISSING_EVIDENCE)), '']
        if self.manifest.get('continuation_ancestors'):
            lines += ['Prior verified credits: ' + self.manifest.get('prior_spent_credits', 'unknown'),
                      'Current run credits: ' + self.manifest.get('spent_credits', 'unknown'),
                      'Aggregate credits: ' + self.manifest.get('aggregate_spent_credits', 'unknown'), '']
        lines.extend(f'- {r["case_id"]}' + (f' (attempt {r.get("attempt", 1)})' if self.manifest.get('unpaid_continuations') else '') + f': smoke **{r.get("functional_status", "not_run")}**, '
                     f'acceptance **{r["status"]}** — {r.get("reason", "")}'
                     for r in self.manifest['results'])
        lines.extend(['', ('Owned medium fixtures and catalog are cleaned only after settled effects; unresolved resources are retained.'
                           if self.manifest.get('stage_authorization') else
                           'Deployment records and calendars are retained. No automatic business-data cleanup.')])
        (self.folder / 'report.md').write_text('\n'.join(lines) + '\n')
        print('Report: ' + str(self.folder / 'report.md'), flush=True)


def _unpaid_campaign(config, run_id):
    """Open existing evidence read-only; admission is separately proven under lock."""
    campaign = Campaign.__new__(Campaign)
    campaign.config = config
    campaign.root = Path(config.get('artifact_root', ROOT / 'scratch/live-simulations')).resolve()
    if not isinstance(run_id, str) or not re.fullmatch(r'[0-9a-f]{32}', run_id):
        raise SimulationError('Invalid unpaid continuation run ID')
    campaign.run_id, campaign.folder = run_id, campaign.root / run_id
    if campaign.folder.is_symlink() or campaign.folder.resolve().parent != campaign.root:
        raise SimulationError('Invalid unpaid continuation artifact path')
    path = campaign.folder / 'manifest.json'
    if path.is_symlink():
        raise SimulationError('Invalid unpaid continuation manifest path')
    campaign.manifest = json.loads(path.read_text())
    return campaign


def _prove_unpaid(campaign, ledger, auth, selected):
    manifest = campaign.manifest
    claims = [claim for claim in ledger.get('stage_authorizations', [])
              if claim.get('authorization_id') == auth['authorization_id'] or claim.get('run_id') == campaign.run_id]
    expected_claim = {**auth, 'run_id': campaign.run_id}
    fixture = manifest.get('deployed_medium', {})
    operations = fixture.get('operations', [])
    services = fixture.get('services', {})
    service_ids = {item.get('id') for item in services.values()}
    if (manifest.get('target') != 'deployed' or manifest.get('run_id') != campaign.run_id
            or manifest.get('deployed_url') != origin(campaign.config.get('deployed_url'))
            or manifest.get('tier') != 'medium' or manifest.get('selected') != selected
            or manifest.get('stage_authorization') != auth or auth.get('credit_ceiling') != 11250
            or manifest.get('attempted') is not True or manifest.get('status') != 'blocked'
            or claims != [expected_claim] or manifest.get('unpaid_continuations')
            or any(record.get('run_id') == campaign.run_id or record.get('authorization_id') == auth['authorization_id']
                   for record in ledger.get('unpaid_continuations', []))
            or any(e.get('unsettled') or e.get('run_id') == campaign.run_id
                   or e.get('authorization_id') == auth['authorization_id'] for e in ledger['entries'])
            or manifest.get('provider_tests') or manifest.get('invocations')
            or 'test_create_pending' in manifest or manifest.get('agent_create_pending')
            or manifest.get('unsettled_usage') or number(manifest.get('spent_credits', 0)) != 0
            or not isinstance(manifest.get('campaign_agent_id'), str) or not manifest['campaign_agent_id']
            or fixture.get('blocked') or fixture.get('owned_request_ids') or fixture.get('current_request_ids')
            or fixture.get('blocks') or 'current_case' in fixture or fixture.get('fixture_rows')
            or len(services) != 3 or len(operations) != 3
            or any(op.get('status') != 'observed' or op.get('method') != 'POST'
                   or op.get('path') != '/api/v1/portal/services' or len(op.get('ids', [])) != 1 for op in operations)
            or {op['ids'][0] for op in operations} != service_ids
            or [row.get('case_id') for row in manifest.get('results', [])] != selected
            or any(row.get('status') != 'blocked' or row.get('checks') for row in manifest.get('results', []))
            or any(reason != 'Owned catalog retained: unresolved stage or provider effects'
                   for reason in manifest.get('cleanup_blockers', []))):
        raise SimulationError('Unpaid continuation proof failed; retain the blocked execution')


def _archive_unpaid(campaign, ledger):
    destination = campaign.folder / 'attempts' / 'attempt-1'
    if destination.exists() or destination.is_symlink():
        raise SimulationError('Unpaid continuation archive already exists')
    originals = {}
    for name in ('manifest.json', 'report.json', 'report.md'):
        path = campaign.folder / name
        if path.is_symlink() or not path.is_file():
            raise SimulationError('Unpaid continuation original evidence is incomplete')
        originals[name] = path.read_bytes()
    destination.mkdir(parents=True, mode=0o700)
    hashes = {}
    for name, data in originals.items():
        path = destination / name
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
        hashes[name] = hashlib.sha256(data).hexdigest()
    destination.chmod(0o500)
    admission = {'attempt': 2, 'archive': str(destination.relative_to(campaign.folder)),
                 'original_manifest_sha256': hashes['manifest.json'], 'files_sha256': hashes,
                 'authorization_id': campaign.manifest['stage_authorization']['authorization_id'],
                 'credit_ceiling': campaign.manifest['stage_authorization']['credit_ceiling'],
                 'admitted_at': time.time()}
    ledger.setdefault('unpaid_continuations', []).append({**admission, 'run_id': campaign.run_id})
    private_json(campaign.root / 'usage-ledger.json', ledger)
    campaign.manifest.setdefault('unpaid_continuations', []).append(admission)
    campaign.save()


def execute(config, tier='minimal', *, live=False, check=False, run_id=None,
            requested=None, repeat=1, continue_unpaid=False, **kwargs):
    if not continue_unpaid:
        return _execute(config, tier, live=live, check=check, run_id=run_id,
                        requested=requested, repeat=repeat, **kwargs)
    if (not live or check or tier != 'medium' or not run_id or config.get('target') != 'deployed'
            or repeat != 1 or config.get('stage_authorization') is None):
        raise SimulationError('Unpaid continuation requires explicit live same-run deployed medium execution')
    planned = preview(config, tier, requested, repeat, target='deployed')
    if planned['status'] != 'planned':
        raise SimulationError('Unpaid continuation budget cannot admit selected coverage')
    root = Path(config.get('artifact_root', ROOT / 'scratch/live-simulations')).resolve()
    with campaign_lock(root), httpx.Client(timeout=30, trust_env=False, follow_redirects=False) as client:
        campaign = _unpaid_campaign(config, run_id)
        ledger = json.loads((root / 'usage-ledger.json').read_text())
        auth = stage_authorization(config, tier, requested, planned['selected'], repeat, target='deployed')
        _prove_unpaid(campaign, ledger, auth, planned['selected'])
        cases = select_cases(load_catalog(), tier, planned['selected'])
        designated = fixtures.variables(config)
        for case in cases:
            bound = case_variables(config, designated, case)
            if any(bound[key] != designated[key] for key in ('customer_phone', 'customer_name', 'customer_email')):
                raise SimulationError('Unpaid continuation per-case recipient identity differs')
        problems, baseline = deployment_readiness(config, client)
        if baseline != campaign.manifest.get('baseline'):
            raise SimulationError('Unpaid continuation native baseline differs')
        existing_name = preserved_customer_name(config, baseline, client)
        services = campaign.manifest['deployed_medium']['services']
        deployed_medium.validate_retained_catalog(config, client, services)
        problems.extend(deployed_medium.readiness(config, client, cases, baseline, retained_catalog=services))
        state, provider_problems = provider_readiness(config, client)
        problems.extend(provider_problems)
        if problems:
            raise SimulationError('Unpaid continuation readiness failed: ' + '; '.join(problems))
        provider = state['provider']
        actual = native_override(provider.resolve_reference(provider.agent(campaign.manifest['campaign_agent_id'])),
                                 origin(config.get('deployed_url')), state['webhook_id'])
        expected = campaign.manifest.get('reference_fingerprint')
        if fingerprint(actual) != expected or fingerprint(state['override']) != expected:
            raise SimulationError('Unpaid continuation clone fingerprint differs')
        remaining = current_remaining(config, provider)
        budget = campaign_budget(config, tier, remaining)
        if not budget.can_start(sum(estimates(config, cases))):
            raise SimulationError('Unpaid continuation fresh quota or reserve cannot admit coverage')
        state['remaining'] = remaining
        _archive_unpaid(campaign, ledger)
        campaign.manifest['unpaid_continuations'][-1]['resolved_retention_reasons'] = list(campaign.manifest.get('cleanup_blockers', []))
        campaign.save()
        return _execute(config, tier, live=True, requested=requested, repeat=repeat,
                        _campaign=campaign, _admission={'baseline': baseline, 'state': state, 'existing_name': existing_name})


def _execute(config, tier='minimal', *, live=False, check=False, run_id=None,
             requested=None, repeat=1, _campaign=None, _admission=None, **_):
    if type(repeat) is not int or not 1 <= repeat <= 20:
        raise SimulationError('Repetitions must be between 1 and 20')
    url = origin(config.get('deployed_url'))
    calibration = config.get('calibration')
    authorization = config.get('campaign_authorization')
    stage = config.get('stage_authorization')
    planned = (preview(config, tier, requested, repeat, target='deployed') if stage is not None
               else authorization_plan(config, tier, requested, repeat) if authorization is not None
               else calibration_plan(config, tier, requested, repeat) if calibration is not None
               else preview(config, tier, requested, repeat))
    cases = ([case for case in load_catalog() if case['id'] in planned['selected']]
             if planned.get('resume_request_id') is not None else select_cases(load_catalog(), tier, planned['selected']))
    if stage is not None:
        designated = fixtures.variables(config)
        for case in cases:
            bound = case_variables(config, designated, case)
            if any(bound[key] != designated[key] for key in ('customer_phone', 'customer_name', 'customer_email')):
                raise SimulationError('Per-case customer identity must match the designated deployed recipient')
    unsupported = ([] if stage is not None else
                   [c['id'] for c in cases if c['id'] not in {f'C{i:02}' for i in range(1, 7)}
                    or c['setup'] not in ('fresh', 'continue') or c.get('requires_binding')])
    missing = ([item for item in MISSING_EVIDENCE
                if item not in ('scoped database/reservation invariants', 'reloaded browser portal')]
               if stage is not None else MISSING_EVIDENCE)
    if stage is not None and not config.get('deployed_medium', {}).get('browser_readback'):
        missing = [*missing, 'reloaded browser portal']
    planned.update(target='deployed', deployed_url=url,
                   acceptance_scope=('deployed_medium_native_state' if stage is not None else
                                     'single_case_calibration_smoke' if calibration is not None else 'conversation_and_api_smoke'),
                   unsupported_cases=unsupported, missing_acceptance_evidence=missing)
    if not live and not check:
        return planned
    if live and check:
        raise SimulationError('Choose --check or --live, not both')
    if live and planned['status'] != 'planned':
        raise SimulationError('Workflow cannot start: ' + planned['status'] + '; configure verified monthly budget and case estimates')
    with httpx.Client(timeout=30, trust_env=False, follow_redirects=False) as client:
        if _admission is None:
            problems, baseline = deployment_readiness(config, client)
        else:
            problems, baseline = [], _admission['baseline']
        seed = recovery_seed(config, baseline)
        try:
            existing_name = (_admission['existing_name'] if _admission is not None
                             else preserved_customer_name(config, baseline, client))
        except SimulationError as exc:
            if check:
                return {**planned, 'status': 'blocked', 'problems': [*problems, str(exc)]}
            raise
        if planned['status'] != 'planned':
            problems.append('Budget is ' + planned['status'] + ': verify units, monthly allowance, reset and conservative case estimates')
        if unsupported:
            problems.append('Isolated fixtures/state assertions are required for cases: ' + ', '.join(unsupported))
        if stage is not None and _admission is None:
            problems.extend(deployed_medium.readiness(config, client, cases, baseline))
        state, provider_problems = ((_admission['state'], []) if _admission is not None
                                    else provider_readiness(config, client))
        problems.extend(provider_problems)
        if check:
            return {**planned, 'status': 'blocked' if problems else 'planned', 'problems': problems}
        if problems:
            raise SimulationError('; '.join(problems))
        campaign = _campaign or Campaign(config, tier, planned['selected'], run_id)
        manifest = campaign.manifest
        manifest.update(baseline=copy.deepcopy(baseline), complete_tier=planned['complete_tier'],
                        reference_agent_id=config.get('agent_id'),
                        acceptance_scope=planned['acceptance_scope'], missing_acceptance_evidence=missing)
        if calibration is not None:
            manifest.update(calibration=copy.deepcopy(calibration), acceptance_scope='single_case_calibration_smoke')
        if authorization is not None:
            manifest['campaign_authorization'] = copy.deepcopy(authorization)
        campaign.save()
        print('Deployed campaign: ' + campaign.run_id + ' at ' + url, flush=True)
        with (contextlib.nullcontext() if _campaign is not None else campaign_lock(campaign.root)):
            ledger_path = campaign.root / 'usage-ledger.json'
            ledger = json.loads(ledger_path.read_text()) if ledger_path.exists() else {'entries': []}
            if any(e.get('unsettled') for e in ledger['entries']):
                raise SimulationError('Unsettled prior invocation blocks paid work; reconcile before retrying')
            if authorization is not None and any(
                    e.get('authorization_id') == authorization['authorization_id']
                    and e.get('run_id') != campaign.run_id for e in ledger['entries']):
                raise SimulationError('Campaign authorization already used by another run')
            if stage is not None:
                stage = stage_authorization(config, tier, requested, planned['selected'], repeat, target='deployed')
                if _campaign is None:
                    claim_stage(campaign, ledger, stage)
            prior_spent, ancestors = continuation_history(config, ledger, campaign.run_id)
            recovery_selection(config)  # Revalidate immediate-ancestor eligibility under the campaign lock.
            if seed is not None:
                seed = recovery_seed(config, scoped(get(client, url, '/api/v1/portal/service-requests'), fixtures.variables(config)['customer_phone']))
                manifest['recovery_source_baseline'] = copy.deepcopy(baseline)
                baseline = [row for row in baseline if row['id'] != seed['id']]
                manifest['baseline'] = copy.deepcopy(baseline)
                manifest['owned_recovery'] = {'source_run_id': authorization['continuation_of'],
                    'request_id': seed['id'], 'source_row': copy.deepcopy(seed), 'raw_initial_row': copy.deepcopy(seed),
                    'comparison_mode': 'redacted ancestor evidence plus raw designated-phone verification'}
            manifest.update(prior_spent_credits=str(prior_spent), continuation_ancestors=ancestors)
            campaign.save()
            provider, override = state['provider'], state['override']
            budget = campaign_budget(config, tier, state['remaining'])
            case_estimates = ([number(calibration['case_upper_estimate'], positive=True)]
                              if calibration is not None else estimates(config, cases))
            if not budget.can_start(sum(case_estimates) * repeat):
                raise SimulationError('Current remaining allowance cannot admit selected coverage')
            values = fixtures.variables(config)
            values['customer_name'] = existing_name or values['customer_name'] + ' ' + campaign.run_id[:8]
            values['run_id'] = campaign.run_id
            base_values = copy.deepcopy(values)
            baseline_index = {r['id']: r for r in baseline}
            previous, failed, group_ids = [], set(), set()
            if seed is not None:
                previous, group_ids = [copy.deepcopy(seed)], {seed['id']}
            adapter = deployed_medium.Adapter(campaign, client) if stage is not None else None
            stage_blocked = False
            try:
                manifest.update(attempted=True, status='running', agent_create_pending=False,
                                reference_fingerprint=fingerprint(override))
                campaign.save()
                if adapter is not None and _campaign is None:
                    stage_blocked = True
                    adapter.prepare_catalog()
                    stage_blocked = False
                manifest['agent_create_pending'] = _campaign is None
                campaign.save()
                try:
                    if _campaign is None:
                        manifest['campaign_agent_id'] = provider.create_agent(override, campaign.run_id)
                except SimulationError as exc:
                    if 'ambiguous' not in str(exc):
                        manifest['agent_create_pending'] = False
                    raise
                manifest['agent_create_pending'] = False
                campaign.save()
                created = provider.resolve_reference(provider.agent(manifest['campaign_agent_id']))
                actual = native_override(created, url, state['webhook_id'])
                if fingerprint(actual) != fingerprint(override):
                    raise SimulationError('Created agent differs from approved native tool configuration')
                for iteration in range(repeat):
                    for case, estimate in zip(cases, case_estimates):
                        if adapter is not None:
                            values = case_variables(config, base_values, case)
                            # Native verified identity must keep its exact saved name;
                            # synthetic suffixing belongs to isolated fixture ownership.
                            values['customer_name'] = base_values['customer_name']
                            values['run_id'] = base_values['run_id']
                        entry = {'case_id': case['id'], 'repeat': iteration + 1, 'status': 'blocked',
                                 'attempt': 2 if _campaign is not None else 1}
                        manifest['results'].append(entry)
                        if adapter is not None and (stage_blocked or budget.unknown):
                            entry['reason'] = 'Unresolved stage resource, cleanup or charge; no further paid work'
                            entry['functional_status'] = 'blocked'
                            continue
                        if any(dep in failed for dep in case.get('dependencies', [])):
                            entry['reason'] = 'Failed or blocked lifecycle prerequisite'
                            failed.add(case['id'])
                            continue
                        if manifest.get('test_create_pending'):
                            entry['reason'] = 'Unresolved test resource creation; no automatic retry'
                            failed.add(case['id'])
                            continue
                        if adapter is None and case['setup'] == 'fresh':
                            if any(r.get('status') != 'cancelled' for r in previous):
                                entry['reason'] = 'Previous test booking remains active; no automatic cancellation/reset'
                                failed.add(case['id'])
                                continue
                            previous, group_ids = [], set()
                        case_started = False
                        read_stage = 'case admission'
                        try:
                            budget.remaining = min(budget.remaining, current_remaining(config, provider))
                            if not budget.can_start(estimate):
                                raise SimulationError('Insufficient verified budget or unknown usage')
                            adapted_case = case
                            if adapter is not None:
                                read_stage = 'native booking baseline before fixture'
                                pre_setup = scoped(get(client, url, '/api/v1/portal/service-requests'), values['customer_phone'])
                                if not unchanged(baseline_index, pre_setup):
                                    stage_blocked = True
                                    raise SimulationError('Existing customer records changed; stop before fixture setup')
                                case_started = True
                                read_stage = 'native fixture arrangement'
                                adapted_case, fixture_ids = adapter.arrange(case, values)
                                group_ids = set(fixture_ids)
                            read_stage = 'native booking context'
                            current = scoped(get(client, url, '/api/v1/portal/service-requests'), values['customer_phone'])
                            if not unchanged(baseline_index, current):
                                raise SimulationError('Existing customer records changed; stop before another paid submission')
                            if adapter is not None:
                                previous = [row for row in current if row['id'] in group_ids]
                            dynamic = {k: str(v) for k, v in values.items()}
                            context = '; '.join(f'{r.get("booking_type")}: {r.get("service_type")} at {r.get("booking_time")}'
                                                for r in current if r.get('status') not in ('cancelled', 'cancelled_by_customer', 'completed', 'done'))
                            dynamic.update(caller_phone=values['customer_phone'], system__caller_id=phone(values['customer_phone']),
                                           customer_name=values['customer_name'], recent_booking_context=context,
                                           upcoming_appointments_summary=context, recent_history_summary='',
                                           system__call_sid=campaign.run_id + case['id'] + str(iteration),
                                           system__conversation_id=campaign.run_id + case['id'] + str(iteration))
                            manifest['test_create_pending'] = case['id']
                            campaign.save()
                            try:
                                rendered = deployed_scenario(adapted_case, values)
                                if calibration is not None:
                                    rendered['max_turns'] = min(rendered['max_turns'], 8)
                                test_id = provider.create(rendered, campaign.run_id, dynamic, config['environment'])
                            except SimulationError as exc:
                                if 'ambiguous' not in str(exc):
                                    manifest['test_create_pending'] = None
                                raise
                            manifest['provider_tests'].append(test_id)
                            manifest['test_create_pending'] = None
                            campaign.save()
                            budget.remaining = min(budget.remaining, current_remaining(config, provider))
                            if not budget.can_start(estimate):
                                raise SimulationError('Current allowance cannot admit this paid conversation')
                            charge = {'run_id': campaign.run_id, 'case_id': case['id'], 'test_id': test_id,
                                      'period_reset': config['budget']['reset_unix'], 'unsettled': True}
                            if stage is not None:
                                charge.update(authorization_id=stage['authorization_id'], stage_authorization=copy.deepcopy(stage))
                            if authorization is not None:
                                charge['authorization_id'] = authorization['authorization_id']
                            if ancestors:
                                charge.update(continuation_of=authorization['continuation_of'], continuation_ancestors=ancestors)
                            ledger['entries'].append(charge)
                            private_json(ledger_path, ledger)
                            # The persisted clone was read back and verified above. A
                            # redundant inline override would clear its registered IDs.
                            invocation = provider.run(manifest['campaign_agent_id'], test_id)
                            invocation_id = invocation.get('id')
                            if not isinstance(invocation_id, str) or not invocation_id:
                                raise SimulationError('ambiguous paid request: missing invocation ID')
                            charge['invocation_id'] = invocation_id
                            manifest['invocations'].append(invocation_id)
                            private_json(ledger_path, ledger)
                            campaign.save()
                            result = provider.wait(invocation_id, config.get('timeout_seconds', 120))
                            credits = provider.credits(result)
                            budget.settle(invocation_id, credits)
                            charge.update(unsettled=credits is None, credits=None if credits is None else str(credits))
                            private_json(ledger_path, ledger)
                            private_json(campaign.folder / f'{case["id"]}-{iteration + 1}-provider.json', redact(result))
                            deadline = time.monotonic() + config.get('evidence_timeout_seconds', 90)
                            while True:
                                observed = scoped(get(client, url, '/api/v1/portal/service-requests'), values['customer_phone'])
                                new_ids = {r['id'] for r in observed} - {r['id'] for r in current}
                                group_ids.update(new_ids)
                                after = [r for r in observed if r['id'] in group_ids]
                                checks = (adapter.checks(case, values, previous, after) if adapter is not None else
                                          lifecycle_checks(case['id'], values, previous, after,
                                              config.get('app_config', {}).get('business_timezone', 'America/New_York')))
                                checks.append(evidence.check('existing customer records unchanged',
                                    unchanged(baseline_index, observed)))
                                if all(c['passed'] for c in checks) or time.monotonic() >= deadline:
                                    break
                                time.sleep(1)
                            if adapter is not None:
                                if not unchanged(baseline_index, observed):
                                    stage_blocked = True
                                checks.extend(adapter.final_checks(case, values, after))
                                if 'email' in case.get('required_evidence', []):
                                    checks.append({'name': 'receiving inbox contains expected content', 'passed': False,
                                                   'status': 'unverified',
                                                   'reason': 'Native receiving-inbox verification pending; operator receipt is separate.'})
                            checks += [evidence.check('actual credits verified', credits is not None),
                                       evidence.check('tier budget respected', budget.spent <= budget.cap)]
                            passed = bool(result.get('test_runs')) and all(r.get('status') == 'passed' for r in result['test_runs'])
                            acceptance_checks = functional_checks(checks, email_mode(config, target='deployed')) if adapter is not None else checks
                            status = result_status(acceptance_checks, provider_passed=passed)
                            functional_passed = passed and all(c['passed'] for c in acceptance_checks)
                            entry.update(status=status, functional_status='passed' if functional_passed else 'failed',
                                         checks=checks, reason=(('Native receiving-inbox verification pending; other missing acceptance evidence: ' + ', '.join(missing))
                                                               if adapter is not None and functional_passed else
                                                               'Missing full acceptance evidence' if functional_passed else 'Provider evaluation or API lifecycle failed'))
                            if not functional_passed:
                                failed.add(case['id'])
                            previous = after
                            private_json(campaign.folder / f'{case["id"]}-{iteration + 1}-evidence.json',
                                         redact({'checks': checks, 'before': current, 'after': after}))
                        except (SimulationError, httpx.HTTPError) as exc:
                            entry['reason'] = str(exc) if isinstance(exc, SimulationError) else 'Provider/deployment HTTP request failed; inspect retained evidence'
                            failed.add(case['id'])
                            if isinstance(exc, httpx.HTTPError):
                                entry['failure_diagnostic'] = {'stage': read_stage, 'type': type(exc).__name__,
                                    'status': exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None}
                            if adapter is not None:
                                stage_blocked = True
                            if any(e.get('unsettled') for e in ledger['entries']):
                                budget.unknown = True
                        finally:
                            if adapter is not None and case_started:
                                if any(e.get('unsettled') for e in ledger['entries']):
                                    stage_blocked = True
                                elif not stage_blocked:
                                    try:
                                        adapter.cleanup_case()
                                    except (SimulationError, httpx.HTTPError) as exc:
                                        stage_blocked = True
                                        entry.update(status='blocked', functional_status='blocked', reason='Owned cleanup pending: ' + str(exc))
                                if stage_blocked:
                                    manifest.setdefault('cleanup_blockers', []).append(case['id'] + ': owned stage effects unresolved')
                            manifest['spent_credits'] = str(budget.spent - prior_spent)
                            manifest['aggregate_spent_credits'] = str(budget.spent)
                            manifest['unsettled_usage'] = any(e.get('unsettled') and e['run_id'] == campaign.run_id for e in ledger['entries'])
                            campaign.save()
                statuses = {r['status'] for r in manifest['results']
                            if r.get('attempt', 1) == (2 if _campaign is not None else 1)}
                manifest['status'] = 'failed' if 'failed' in statuses else ('blocked' if 'blocked' in statuses else 'incomplete')
            except BaseException:
                manifest['status'] = 'incomplete'
                raise
            finally:
                if (adapter is not None and not stage_blocked
                        and not manifest.get('agent_create_pending')
                        and not manifest.get('test_create_pending')
                        and not [reason for reason in manifest.get('cleanup_blockers', [])
                                 if _campaign is None or reason not in manifest['unpaid_continuations'][-1].get('resolved_retention_reasons', [])]
                        and not any(e.get('unsettled') for e in ledger['entries'])):
                    try:
                        adapter.cleanup_catalog()
                    except (SimulationError, httpx.HTTPError) as exc:
                        manifest.setdefault('cleanup_blockers', []).append('Owned catalog cleanup pending: ' + str(exc))
                        manifest['status'] = 'incomplete'
                elif adapter is not None:
                    manifest.setdefault('cleanup_blockers', []).append('Owned catalog retained: unresolved stage or provider effects')
                campaign.save()
                campaign.report()
        return manifest


def manage(config, run_id, command, *, live=False):
    """Read/reconcile artifacts or delete only owned ElevenLabs resources."""
    campaign = Campaign(config, '', [], run_id, allow_attempted=True)
    if command == 'report':
        campaign.report()
        print((campaign.folder / 'report.md').read_text())
        return 0
    if command == 'reconcile':
        from .runner import reconcile
        reconcile(campaign)
        if campaign.manifest.get('continuation_ancestors'):
            campaign.manifest['aggregate_spent_credits'] = str(number(campaign.manifest['prior_spent_credits'])
                + number(campaign.manifest['spent_credits']))
            campaign.save()
        campaign.report()
        return 0
    if command != 'cleanup' or not live:
        raise SimulationError('Deployed resource cleanup requires cleanup --live')
    with campaign_lock(campaign.root):
        manifest = campaign.manifest
        if manifest.get('agent_create_pending') or manifest.get('test_create_pending'):
            raise SimulationError('Ambiguous resource creation must be resolved before cleanup')
        path = campaign.root / 'usage-ledger.json'
        ledger = json.loads(path.read_text()) if path.exists() else {'entries': []}
        if any(e.get('unsettled') and e.get('run_id') == run_id for e in ledger['entries']):
            raise SimulationError('Reconcile unsettled usage before deleting provider evidence')
        provider = ElevenLabs(secret(config, 'elevenlabs_key'))
        for invocation in manifest['invocations']:
            result = provider.get(invocation)
            if not result.get('test_runs') or any(r.get('status') not in ('passed', 'failed', 'cancelled') for r in result['test_runs']):
                raise SimulationError('Provider execution is not settled; deployment records retained')
        cleanup = manifest.setdefault('cleanup', {'provider_tests': []})
        for test_id in manifest['provider_tests']:
            if test_id not in cleanup['provider_tests']:
                provider.delete_test(test_id)
                cleanup['provider_tests'].append(test_id)
                campaign.save()
        agent_id = manifest.get('campaign_agent_id')
        if agent_id and not cleanup.get('agent_removed'):
            agent = provider.agent(agent_id, missing_ok=True)
            if agent:
                if agent.get('name') != 'Live simulation ' + run_id or run_id not in agent.get('tags', []):
                    raise SimulationError('Provider agent ownership no longer matches manifest')
                provider.delete_agent(agent_id)
            cleanup['agent_removed'] = True
        cleanup['status'] = 'provider_resources_removed_deployment_data_retained'
        campaign.save()
        campaign.report()
    return 0
