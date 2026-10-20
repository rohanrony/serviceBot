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

from . import agent_policy, deployed_medium, evidence, fixtures
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
    owned_campaign_scope,
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
        source_override = native_override(reference, url, webhook_id)
        override = source_override
        if config.get('owned_agent_policy') is not None:
            if config['owned_agent_policy'] != agent_policy.SERVICE_POLICY_VERSION:
                raise SimulationError('Unknown owned simulation policy version')
            override = agent_policy.apply_service_policy(source_override)
        if config.get('calibration') is not None:
            override['conversation_config']['agent']['prompt']['max_tokens'] = 256
        return {'provider': provider, 'remaining': remaining, 'override': override,
                'webhook_id': webhook_id, 'source_override': source_override}, problems
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
        if self.manifest.get('remaining_continuations') or self.manifest.get('unsubmitted_continuations'):
            admission = (self.manifest.get('unsubmitted_continuations') or self.manifest['remaining_continuations'])[-1]
            lines += ['Latest attempt scope: ' + ','.join(admission['selected']) + '; functional: ' + self.manifest.get('latest_attempt_functional_status', 'pending'),
                      'Whole-stage functional status: failed; prior paid provider failures are retained and were not replayed.', '']
        if self.manifest.get('continuation_ancestors'):
            lines += ['Prior verified credits: ' + self.manifest.get('prior_spent_credits', 'unknown'),
                      'Current run credits: ' + self.manifest.get('spent_credits', 'unknown'),
                      'Aggregate credits: ' + self.manifest.get('aggregate_spent_credits', 'unknown'), '']
        lines.extend(f'- {r["case_id"]}' + (f' (attempt {r.get("attempt", 1)})' if self.manifest.get('unpaid_continuations') or self.manifest.get('remaining_continuations') else '') + f': smoke **{r.get("functional_status", "not_run")}**, '
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


def _archive_unpaid(campaign, ledger, *, previous_attempt=1, kind='unpaid_continuations', extra_names=(), selected=None, prior_spent=None, metadata=None):
    destination = campaign.folder / 'attempts' / f'attempt-{previous_attempt}'
    if destination.exists() or destination.is_symlink():
        raise SimulationError('Unpaid continuation archive already exists')
    originals = {}
    for name in ('manifest.json', 'report.json', 'report.md', *extra_names):
        path = campaign.folder / name
        if path.is_symlink() or not path.is_file():
            raise SimulationError('Unpaid continuation original evidence is incomplete')
        originals[name] = path.read_bytes()
    destination.mkdir(parents=True, mode=0o700)
    hashes = {}
    for name, data in originals.items():
        path = destination / name
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
        hashes[name] = hashlib.sha256(data).hexdigest()
    destination.chmod(0o500)
    admission = {'attempt': previous_attempt + 1, 'archive': str(destination.relative_to(campaign.folder)),
                 'original_manifest_sha256': hashes['manifest.json'], 'files_sha256': hashes,
                 'authorization_id': campaign.manifest['stage_authorization']['authorization_id'],
                 'credit_ceiling': campaign.manifest['stage_authorization']['credit_ceiling'],
                 'admitted_at': time.time()}
    if selected is not None:
        admission.update(selected=selected, prior_spent_credits=str(prior_spent))
    admission.update(metadata or {})
    ledger.setdefault(kind, []).append({**admission, 'run_id': campaign.run_id})
    private_json(campaign.root / 'usage-ledger.json', ledger)
    campaign.manifest.setdefault(kind, []).append(admission)
    campaign.save()


def _artifact(campaign, relative):
    path = campaign.folder / str(relative)
    if (Path(str(relative)).is_absolute() or path.is_symlink()
            or campaign.folder.resolve() not in path.resolve().parents or not path.is_file()):
        raise SimulationError('Continuation artifact is unavailable or outside the owned run')
    return path


def _verified_archive(campaign, relative, hashes, *, allow_extra=False):
    required = {'manifest.json', 'report.json', 'report.md'}
    if (not required <= set(hashes)) or (not allow_extra and set(hashes) != required):
        raise SimulationError('Continuation archive hashes are incomplete')
    for name, expected in hashes.items():
        path = _artifact(campaign, str(Path(relative) / name))
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise SimulationError('Immutable prior attempt archive changed')
    return json.loads(_artifact(campaign, str(Path(relative) / 'manifest.json')).read_text())


def _monotonic_progress(campaign, ledger, charges):
    """Bind every shrinking suffix to an immutable admission and paid progress."""
    original = [f'C{i:02}' for i in range(7, 17)]
    paid = [entry.get('case_id') for entry in charges]
    if not 3 <= len(paid) < len(original) or paid != original[:len(paid)]:
        raise SimulationError('Paid cases do not form a unique contiguous prefix')
    history = campaign.manifest.get('unsubmitted_continuations', [])
    records = [record for record in ledger.get('unsubmitted_continuations', [])
               if record.get('run_id') == campaign.run_id
               or record.get('authorization_id') == campaign.manifest['stage_authorization']['authorization_id']]
    if len(records) != len(history):
        raise SimulationError('Monotonic admission ledger history differs')
    prior = campaign.manifest.get('remaining_continuations', [])
    if len(prior) != 1:
        raise SimulationError('Monotonic admission lacks the original paid continuation')
    previous, start, snapshots = prior[0], 3, []
    fields = ('attempt', 'selected', 'prior_spent_credits', 'original_manifest_sha256',
              'files_sha256', 'agent_revision_fingerprint', 'previous_admission_sha256')
    for index, (admission, record) in enumerate(zip(history, records)):
        selected = admission.get('selected', [])
        if (not selected or selected[0] not in original
                or any(record.get(field) != admission.get(field) for field in fields)):
            raise SimulationError('Monotonic admission record differs')
        current_start = original.index(selected[0])
        if (admission.get('attempt') != index + 4 or selected != original[current_start:]
                or (current_start != 3 if index == 0 else current_start <= start)
                or len(paid) <= current_start
                or number(admission.get('prior_spent_credits')) != sum((number(entry['credits']) for entry in charges[:current_start]), number(0))
                or admission.get('previous_admission_sha256') != hashlib.sha256(json.dumps(previous, sort_keys=True).encode()).hexdigest()):
            raise SimulationError('Monotonic admission has no strictly increasing settled progress')
        snapshot = _verified_archive(campaign, admission['archive'], admission['files_sha256'], allow_extra=True)
        if snapshot.get('unsubmitted_continuations', []) != history[:index]:
            raise SimulationError('Monotonic admission archive chain differs')
        snapshots.append(snapshot)
        previous, start = admission, current_start
    if not history and len(paid) != 3:
        raise SimulationError('A paid case lacks its original suffix admission')
    previous_selection = history[-1]['selected'] if history else [f'C{i:02}' for i in range(9, 17)]
    return {'prefix': paid, 'suffix': original[len(paid):],
            'previous_attempt': history[-1]['attempt'] if history else 3,
            'previous_selection': previous_selection, 'snapshots': snapshots,
            'previous_admission': previous}


def _fixture_creation_proof(campaign, receipt, snapshot):
    """A fixture-created request is bound to observed native operation records."""
    indices = receipt.get('fixture_operation_indices')
    source = snapshot.get('deployed_medium', {}).get('operations', [])
    current = campaign.manifest['deployed_medium']['operations']
    if (not isinstance(indices, list) or not indices or len(set(indices)) != len(indices)
            or any(type(index) is not int or index < 0 or index >= len(source) or index >= len(current) for index in indices)):
        raise SimulationError('Fixture creation operation indices differ')
    operations = [source[index] for index in indices]
    expected_name = campaign.config.get('existing_customer_identity', {}).get('name')
    expected_phone = fixtures.variables(campaign.config)['customer_phone']
    ids = []
    for index, op in zip(indices, operations):
        args = op.get('body', {}).get('arguments', {})
        if (current[index] != op or op.get('status') != 'observed' or op.get('method') != 'POST'
                or op.get('path') != '/api/v1/voice/tools' or op.get('body', {}).get('name') != 'create_service_request'
                or phone(args.get('phone')) != phone(expected_phone) or args.get('customer_name') != expected_name
                or not op.get('ids') or any(type(value) is not int for value in op['ids'])):
            raise SimulationError('Native fixture creation identity or observed operation differs')
        ids.extend(op['ids'])
    digest = hashlib.sha256(json.dumps(operations, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    if (digest != receipt.get('fixture_operations_sha256') or len(set(ids)) != len(ids)
            or sorted(ids) != sorted(receipt['owned_request_ids'])
            or set(ids) & {row['id'] for row in campaign.manifest['baseline']}):
        raise SimulationError('Native fixture creation hash or request identities differ')


def _prove_remaining(campaign, ledger, auth, suffix, *, unsubmitted=False):
    manifest, fixture = campaign.manifest, campaign.manifest.get('deployed_medium', {})
    original = [f'C{i:02}' for i in range(7, 17)]
    prefix = ['C07', 'C08']
    kind = 'unsubmitted_continuations' if unsubmitted else 'remaining_continuations'
    previous_attempt = 3 if unsubmitted else 2
    previous_selection = [f'C{i:02}' for i in range(9, 17)] if unsubmitted else original
    claims = [claim for claim in ledger.get('stage_authorizations', [])
              if claim.get('authorization_id') == auth['authorization_id'] or claim.get('run_id') == campaign.run_id]
    charges = [entry for entry in ledger['entries']
               if entry.get('run_id') == campaign.run_id or entry.get('authorization_id') == auth['authorization_id']]
    progress = _monotonic_progress(campaign, ledger, charges) if unsubmitted else None
    if progress is not None:
        prefix = progress['prefix']
        if suffix != progress['suffix']:
            raise SimulationError('Requested suffix is not the exact never-submitted remainder')
        previous_attempt, previous_selection = progress['previous_attempt'], progress['previous_selection']
    expected_spent = sum((number(entry.get('credits')) for entry in charges), number(0)) if unsubmitted else 1114
    if (manifest.get('target') != 'deployed' or manifest.get('run_id') != campaign.run_id
            or manifest.get('deployed_url') != origin(campaign.config.get('deployed_url'))
            or manifest.get('tier') != 'medium' or manifest.get('selected') != original
            or manifest.get('stage_authorization') != auth or auth.get('credit_ceiling') != 11250
            or claims != [{**auth, 'run_id': campaign.run_id}] or manifest.get('attempted') is not True
            or manifest.get('status') != ('failed' if unsubmitted else 'blocked')
            or (not unsubmitted and (manifest.get(kind) or any(record.get('run_id') == campaign.run_id
                   or record.get('authorization_id') == auth['authorization_id'] for record in ledger.get(kind, []))))
            or any(entry.get('unsettled') for entry in ledger['entries'])
            or len(charges) != len(prefix) or [entry.get('case_id') for entry in charges] != prefix
            or manifest.get('agent_create_pending') or manifest.get('test_create_pending')
            or manifest.get('unsettled_usage') or fixture.get('blocked') or fixture.get('current_request_ids')
            or fixture.get('current_case') != prefix[-1] or fixture.get('fixture_rows')
            or any(op.get('status') != 'observed' for op in fixture.get('operations', []))
            or any(not block.get('restored') for block in fixture.get('blocks', []))):
        raise SimulationError('Remaining continuation prefix or resource proof failed')
    if (manifest.get('provider_tests') != [entry['test_id'] for entry in charges]
            or manifest.get('invocations') != [entry['invocation_id'] for entry in charges]
            or len(set(manifest['provider_tests'])) != len(prefix) or len(set(manifest['invocations'])) != len(prefix)
            or any(entry.get('run_id') != campaign.run_id or entry.get('authorization_id') != auth['authorization_id']
                   or entry.get('stage_authorization') != auth for entry in charges)
            or number(manifest.get('spent_credits')) != expected_spent):
        raise SimulationError('Remaining continuation prefix identities or spending differ')
    admissions = manifest.get('unpaid_continuations', [])
    if len(admissions) != 1 or admissions[0].get('attempt') != 2:
        raise SimulationError('Remaining continuation lacks original attempt history')
    snapshots = [_verified_archive(campaign, admissions[0]['archive'], admissions[0]['files_sha256'])]
    if unsubmitted:
        prior = manifest.get('remaining_continuations', [])
        records = [record for record in ledger.get('remaining_continuations', []) if record.get('run_id') == campaign.run_id]
        if (len(prior) != 1 or prior[0].get('attempt') != 3 or prior[0].get('selected') != [f'C{i:02}' for i in range(9, 17)]
                or prior[0].get('prior_spent_credits') != '1114' or len(records) != 1
                or records[0].get('original_manifest_sha256') != prior[0].get('original_manifest_sha256')):
            raise SimulationError('Unsubmitted continuation prior admission differs')
        prior_snapshot = _verified_archive(campaign, prior[0]['archive'], prior[0]['files_sha256'], allow_extra=True)
        if (prior_snapshot.get('unpaid_continuations') != admissions
                or prior_snapshot.get('remaining_reconciliation') != manifest.get('remaining_reconciliation')):
            raise SimulationError('Unsubmitted continuation prior admission chain changed')
        snapshots.append(prior_snapshot)
        snapshots.extend(progress['snapshots'])
        added = manifest.get('reconciliations', [])
        bindings = [manifest.get('remaining_reconciliation', {}), *added]
        if (len(added) != len(prefix) - 2
                or len({binding.get('path') for binding in bindings}) != len(bindings)):
            raise SimulationError('Unsubmitted continuation reconciliation chain differs')
    else:
        bindings = [manifest.get('remaining_reconciliation', {})]
    receipts, extras = [], []
    for binding, cid in zip(bindings, prefix[1:]):
        receipt_path = _artifact(campaign, binding.get('path', ''))
        if hashlib.sha256(receipt_path.read_bytes()).hexdigest() != binding.get('sha256'):
            raise SimulationError('Remaining continuation reconciliation hash differs')
        receipt = json.loads(receipt_path.read_text())
        if (receipt.get('run_id') != campaign.run_id or receipt.get('status') != 'settled'
                or receipt.get('case_id') != cid or not receipt.get('pre_reconciliation_archive')
                or (receipt.get('provenance') != 'native_fixture_operations' and
                    (not isinstance(receipt.get('provider_create_request_id'), str) or not receipt['provider_create_request_id']))
                or any(receipt.get(key) is not True for key in ('baseline_unchanged', 'google_current_event_deleted', 'native_calendar_effects_settled'))):
            raise SimulationError('Remaining continuation prior effects are not reconciled')
        if cid >= 'C09' and (receipt.get('identity_verified') is not True or receipt.get('ambiguous_cancel_reconciled') is not True):
            raise SimulationError('C09 ambiguous cancellation is not independently reconciled')
        ids = receipt.get('owned_request_ids')
        if (not isinstance(ids, list) or not ids or any(type(value) is not int for value in ids)
                or (cid in ('C08', 'C09') and (len(ids) != 1 or receipt.get('provenance') == 'native_fixture_operations'))
                or ids != receipt.get('cancelled_request_ids')):
            raise SimulationError('Reconciled request identities differ')
        pre_archive = receipt['pre_reconciliation_archive']
        hashes = json.loads(_artifact(campaign, str(Path(pre_archive) / 'hashes.json')).read_text())
        snapshot = _verified_archive(campaign, pre_archive, hashes)
        snapshots.append(snapshot)
        if receipt.get('provenance') == 'native_fixture_operations':
            _fixture_creation_proof(campaign, receipt, snapshot)
        receipts.append(receipt)
        extras.extend([binding['path'], *[str(Path(pre_archive) / name) for name in ('manifest.json', 'report.json', 'report.md', 'hashes.json')]])
    for snapshot in (*snapshots, manifest):
        if (any(intent.get('case_id') in suffix for intent in snapshot.get('test_creation_intents', []))
                or snapshot.get('test_create_pending') in suffix):
            raise SimulationError('A remaining case has a historical test creation intent')
    attempt_rows = [row for row in manifest.get('results', []) if row.get('attempt', 1) == previous_attempt]
    if [row.get('case_id') for row in attempt_rows] != previous_selection:
        raise SimulationError('Remaining continuation prior attempt scope differs')
    latest = {row['case_id']: row for row in attempt_rows}
    if any(latest.get(cid, {}).get('status') != 'blocked'
           or latest[cid].get('reason') != 'Unresolved stage resource, cleanup or charge; no further paid work' for cid in suffix):
        raise SimulationError('A remaining case lacks the pre-creation guard outcome')
    if any(list(campaign.folder.glob(cid + '-*.json')) for cid in suffix):
        raise SimulationError('A remaining case already has execution artifacts')
    all_ids = [value for receipt in receipts for value in receipt['owned_request_ids']]
    all_blocks = [value for receipt in receipts for value in receipt.get('restored_block_ids', [])]
    if (len(set(all_ids)) != len(all_ids) or sorted(all_ids) != sorted(fixture.get('owned_request_ids', []))
            or all_blocks != [block['original']['id'] for block in fixture.get('blocks', [])]):
        raise SimulationError('Reconciliation chain does not cover all prior native effects')
    extras.extend(cid + '-1-provider.json' for cid in prefix)
    return charges, receipts, list(dict.fromkeys(extras))


def _prefix_results(campaign, provider, charges, receipt):
    receipts = receipt if isinstance(receipt, list) else [receipt]
    by_case = {item['case_id']: item for item in receipts}
    total = number(0)
    for entry in charges:
        cid = entry['case_id']
        expected_status = 'passed' if cid == 'C07' else 'failed' if cid in ('C08', 'C09', 'C10') else None
        expected_credits = number({'C07': 331, 'C08': 783, 'C09': 905, 'C10': 481}.get(cid, entry.get('credits')))
        path = _artifact(campaign, cid + '-1-provider.json')
        saved = json.loads(path.read_text())
        fresh = provider.get(entry['invocation_id'])
        for result in (saved, fresh):
            runs = result.get('test_runs', [])
            if (result.get('id') != entry['invocation_id'] or result.get('agent_id') != campaign.manifest['campaign_agent_id']
                    or len(runs) != 1 or runs[0].get('test_id') != entry['test_id']
                    or runs[0].get('test_invocation_id') != entry['invocation_id']
                    or runs[0].get('status') not in ('passed', 'failed')
                    or (expected_status is not None and runs[0].get('status') != expected_status)
                    or number(runs[0].get('credits_used')) != expected_credits
                    or number(entry.get('credits')) != expected_credits):
                raise SimulationError('Remaining continuation provider prefix receipt differs')
        if cid in by_case:
            receipt = by_case[cid]
            if hashlib.sha256(path.read_bytes()).hexdigest() != receipt.get('provider_receipt_sha256'):
                raise SimulationError('C08 reconciliation is not bound to the provider receipt')
            if receipt.get('provenance') == 'native_fixture_operations':
                total += expected_credits
                continue
            created = set()
            for response in saved['test_runs'][0].get('agent_responses', []):
                for tool in response.get('tool_results') or []:
                    if (tool.get('tool_name') != 'create_service_request' or tool.get('is_error')
                            or tool.get('request_id') != receipt['provider_create_request_id']):
                        continue
                    value = tool.get('result_value')
                    value = json.loads(value) if isinstance(value, str) else value
                    result = value.get('result', value)
                    if result.get('success') is True and type(result.get('service_request_id')) is int:
                        created.add(result['service_request_id'])
            if created != set(receipt['owned_request_ids']):
                raise SimulationError('C08 provider creation does not prove the reconciled request')
        total += expected_credits
    return total


def _remaining_effects(campaign, receipt):
    ids = receipt['owned_request_ids']
    rows = deployed_medium._request_rows(campaign.config, ids)
    identity = campaign.config.get('existing_customer_identity', {}).get('id')
    designated = fixtures.variables(campaign.config)
    if ({row['id'] for row in rows} != set(ids) or type(identity) is not int
            or any(row.get('customer_id') != identity or phone(row.get('customer_phone')) != phone(designated['customer_phone'])
                   or row.get('customer_name') != campaign.config['existing_customer_identity'].get('name')
                   or row.get('status') != 'cancelled' or row.get('reservation_id') for row in rows)):
        raise SimulationError('Prior reconciled native request is active or has a different owner')
    effects = deployed_medium._effect_rows(campaign.config, ids)
    if ({row['id'] for row in effects} != set(ids) or any(
            row.get('active_count') or row.get('segment_count') or not row.get('projection_statuses')
            or any(status != 'DELIVERED' for status in row['projection_statuses'])
            or (row.get('has_event') and (not row.get('reservation_calendar_statuses') or row.get('request_calendar_status') != 'DELETED'
                or any(status != 'DELETED' for status in row.get('reservation_calendar_statuses', [])))) for row in effects)):
        raise SimulationError('Prior native calendar effects are not settled')
    for block in campaign.manifest['deployed_medium']['blocks']:
        original = block['original']
        start = deployed_medium._dt(original['slot_datetime'], campaign.config)
        from datetime import timedelta
        slots = deployed_medium._slots(campaign.config, original['staff_agent_id'], start, start + timedelta(minutes=15))
        if len(slots) != 1 or any(deployed_medium._serial(slots[0]).get(key) != original.get(key) for key in
                ('id', 'staff_agent_id', 'slot_datetime', 'is_booked', 'reservation_status', 'service_request_id', 'active_reservation')):
            raise SimulationError('Prior occupied slot restoration changed')


def _verify_owned_revision(campaign, state, actual):
    config, manifest = campaign.config, campaign.manifest
    version = agent_policy.SERVICE_POLICY_VERSION
    revisions = manifest.get('agent_revisions', [])
    if config.get('owned_agent_policy') != version or len(revisions) != 1:
        raise SimulationError('Unsubmitted continuation requires the explicit owned policy revision')
    revision = revisions[0]
    source_path = _artifact(campaign, revision.get('source_override_path', ''))
    source = json.loads(source_path.read_text())
    desired = agent_policy.apply_service_policy(source)
    try:
        old_prompt = source['conversation_config']['agent']['prompt']['prompt']
        new_prompt = desired['conversation_config']['agent']['prompt']['prompt']
    except (KeyError, TypeError):
        raise SimulationError('Owned policy source snapshot is invalid') from None
    source_fp, desired_fp = fingerprint(source), fingerprint(desired)
    first = manifest['unpaid_continuations'][0]
    original = json.loads(_artifact(campaign, str(Path(first['archive']) / 'manifest.json')).read_text())
    history = manifest.get('unsubmitted_continuations', [])
    expected_current = desired_fp if history else source_fp
    if history and (history[-1].get('agent_revision_fingerprint') != desired_fp
                    or history[-1].get('agent_revision_source_fingerprint') != source_fp):
        raise SimulationError('Current owned policy is not bound to the prior admission')
    if (revision.get('protected_reference_unchanged') is not True
            or original.get('reference_fingerprint') != source_fp
            or revision.get('status') != 'observed' or revision.get('policy_version') != version
            or revision.get('agent_id') != manifest.get('campaign_agent_id')
            or revision.get('agent_id') == config.get('agent_id')
            or revision.get('source_override_sha256') != hashlib.sha256(source_path.read_bytes()).hexdigest()
            or revision.get('source_fingerprint') != source_fp or manifest.get('reference_fingerprint') != expected_current
            or revision.get('new_fingerprint') != desired_fp
            or revision.get('old_prompt_sha256') != hashlib.sha256(old_prompt.encode()).hexdigest()
            or revision.get('new_prompt_sha256') != hashlib.sha256(new_prompt.encode()).hexdigest()
            or fingerprint(state.get('source_override')) != source_fp
            or fingerprint(state['override']) != desired_fp or fingerprint(actual) != desired_fp):
        raise SimulationError('Owned prompt revision chain, protected source or observed clone differs')
    return {'agent_revision_fingerprint': desired_fp,
            'agent_revision_source_fingerprint': source_fp,
            'agent_revision_source_sha256': revision['source_override_sha256']}


def _linked_repair_authorization(config, run_id):
    authorization = config.get('linked_repair_authorization')
    if (not isinstance(authorization, dict)
            or not isinstance(authorization.get('authorization_id'), str)
            or not authorization['authorization_id'].strip()
            or authorization.get('source_run_id') != run_id
            or authorization.get('approved') is not True
            or authorization.get('retry_cases') != ['C15']
            or authorization.get('new_cases') != ['C16']
            or type(authorization.get('credit_ceiling')) is not int
            or authorization['credit_ceiling'] != 11250):
        raise SimulationError('Linked repair requires explicit exact same-run supplemental approval')
    return copy.deepcopy(authorization)


def _repair_binding(campaign, binding):
    if not isinstance(binding, dict):
        raise SimulationError('Linked repair reconciliation binding missing')
    path = _artifact(campaign, binding.get('path', ''))
    if hashlib.sha256(path.read_bytes()).hexdigest() != binding.get('sha256'):
        raise SimulationError('Linked repair reconciliation hash differs')
    return json.loads(path.read_text())


def _repair_revision(campaign, state, actual):
    revisions = campaign.manifest.get('agent_revisions', [])
    if (len(revisions) != 2 or campaign.config.get('owned_agent_linked_policy') != agent_policy.LINKED_VISIT_POLICY_VERSION):
        raise SimulationError('Linked repair requires the exact two-step owned prompt chain')
    previous = state['source_override']
    extras = []
    for revision, version, apply in zip(revisions,
            (agent_policy.SERVICE_POLICY_VERSION, agent_policy.LINKED_VISIT_POLICY_VERSION),
            (agent_policy.apply_service_policy, agent_policy.apply_linked_visit_policy)):
        path = _artifact(campaign, revision.get('source_override_path', ''))
        source = json.loads(path.read_text())
        desired = apply(source)
        old_prompt = source['conversation_config']['agent']['prompt']['prompt']
        new_prompt = desired['conversation_config']['agent']['prompt']['prompt']
        if (fingerprint(source) != fingerprint(previous) or revision.get('status') != 'observed'
                or revision.get('policy_version') != version or revision.get('protected_reference_unchanged') is not True
                or revision.get('agent_id') != campaign.manifest.get('campaign_agent_id')
                or revision.get('agent_id') == campaign.config.get('agent_id')
                or revision.get('source_override_sha256') != hashlib.sha256(path.read_bytes()).hexdigest()
                or revision.get('source_fingerprint') != fingerprint(source)
                or revision.get('new_fingerprint') != fingerprint(desired)
                or revision.get('old_prompt_sha256') != hashlib.sha256(old_prompt.encode()).hexdigest()
                or revision.get('new_prompt_sha256') != hashlib.sha256(new_prompt.encode()).hexdigest()):
            raise SimulationError('Linked repair owned revision chain differs')
        previous = desired
        extras.append(revision['source_override_path'])
    if (campaign.manifest.get('reference_fingerprint') != revisions[0]['new_fingerprint']
            or fingerprint(state['override']) != revisions[0]['new_fingerprint']
            or fingerprint(actual) != fingerprint(previous)):
        raise SimulationError('Linked repair current clone or protected source differs')
    return previous, extras


def _repair_lookup(config, client):
    response = client.post(origin(config.get('deployed_url')) + '/api/v1/voice/tools', json={
        'name': 'get_customer_appointments', 'arguments': {'phone': fixtures.variables(config)['customer_phone']},
        'tool_call_id': 'linked-repair-read-' + uuid.uuid4().hex})
    if response.status_code != 200:
        raise SimulationError('Linked repair lookup capability read failed')
    result = response.json().get('result', {})
    rows = result.get('appointments')
    required = {'visit_group_id', 'visit_start', 'visit_anchor_id', 'visit_member_ids'}
    # The preserved baseline provides a nonempty, real native capability witness.
    if (result.get('success') is not True or not isinstance(rows, list) or not rows
            or any(not isinstance(row, dict) or not required <= row.keys()
                   or not isinstance(row['visit_member_ids'], list) for row in rows)):
        raise SimulationError('Deployed lookup lacks authoritative linked visit metadata')


def _repair_prefix(campaign, ledger, auth, supplemental):
    manifest, fixture = campaign.manifest, campaign.manifest.get('deployed_medium', {})
    prefix = [f'C{i:02}' for i in range(7, 16)]
    charges = [e for e in ledger['entries'] if e.get('run_id') == campaign.run_id
               or e.get('authorization_id') == auth['authorization_id']]
    claims = [e for e in ledger.get('stage_authorizations', []) if e.get('run_id') == campaign.run_id
              or e.get('authorization_id') == auth['authorization_id']]
    if (manifest.get('target') != 'deployed' or manifest.get('run_id') != campaign.run_id
            or manifest.get('deployed_url') != origin(campaign.config.get('deployed_url'))
            or manifest.get('tier') != 'medium' or manifest.get('selected') != prefix + ['C16']
            or auth.get('credit_ceiling') != 11250
            or manifest.get('stage_authorization') != auth or claims != [{**auth, 'run_id': campaign.run_id}]
            or manifest.get('attempted') is not True or manifest.get('status') not in ('failed', 'blocked')
            or manifest.get('repair_admissions') or any(e.get('run_id') == campaign.run_id
                or e.get('repair_authorization_id') == supplemental['authorization_id'] for e in ledger.get('repair_admissions', []))
            or any(e.get('unsettled') for e in ledger['entries'])
            or [e.get('case_id') for e in charges] != prefix
            or any(e.get('run_id') != campaign.run_id or e.get('authorization_id') != auth['authorization_id']
                   or e.get('stage_authorization') != auth for e in charges)
            or manifest.get('provider_tests') != [e.get('test_id') for e in charges]
            or manifest.get('invocations') != [e.get('invocation_id') for e in charges]
            or len({e.get('test_id') for e in charges}) != 9 or len({e.get('invocation_id') for e in charges}) != 9
            or number(manifest.get('spent_credits')) != 5397
            or [number(e.get('credits')) for e in charges] != list(map(number, [331,783,905,481,722,619,649,498,409]))
            or manifest.get('agent_create_pending') or manifest.get('test_create_pending') or manifest.get('unsettled_usage')
            or fixture.get('blocked') or fixture.get('current_request_ids') or fixture.get('fixture_rows')
            or fixture.get('current_case') != 'C16' or any(o.get('status') != 'observed' for o in fixture.get('operations', []))
            or any(not b.get('restored') for b in fixture.get('blocks', []))):
        raise SimulationError('Linked repair prefix, authorization or resource proof failed')
    progress = _monotonic_progress(campaign, ledger, charges)
    if progress['previous_attempt'] != 5:
        raise SimulationError('Linked repair requires original attempt five')
    snapshots = list(progress['snapshots'])
    for kind in ('unpaid_continuations', 'remaining_continuations'):
        history = manifest.get(kind, [])
        records = [e for e in ledger.get(kind, []) if e.get('run_id') == campaign.run_id]
        if len(history) != 1 or len(records) != 1 or any(records[0].get(k) != v for k,v in history[0].items() if k != 'resolved_retention_reasons'):
            raise SimulationError('Linked repair original admission history differs')
        snapshots.append(_verified_archive(campaign, history[0]['archive'], history[0]['files_sha256'], allow_extra=True))
    extras = []
    # Retain every earlier reconciliation and its immutable pre-reconciliation archive.
    for binding in [manifest.get('remaining_reconciliation'), *manifest.get('reconciliations', [])]:
        receipt = _repair_binding(campaign, binding)
        pre = receipt.get('pre_reconciliation_archive', '')
        hashes = json.loads(_artifact(campaign, str(Path(pre) / 'hashes.json')).read_text())
        snapshots.append(_verified_archive(campaign, pre, hashes))
        extras.append(binding['path'])
    for snapshot in [*snapshots, manifest]:
        if (any(i.get('case_id') == 'C16' for i in snapshot.get('test_creation_intents', []))
                or snapshot.get('test_create_pending') == 'C16'):
            raise SimulationError('C16 has a historical provider creation intent')
    if list(campaign.folder.glob('C16-*.json')) or list(campaign.folder.glob('C15-2-*')):
        raise SimulationError('Linked repair sample already has execution artifacts')
    outcomes = [r for r in manifest.get('results', []) if r.get('attempt',1) == 5 and r.get('case_id') == 'C15']
    proof = json.loads(_artifact(campaign, 'C15-1-evidence.json').read_text())
    if (len(outcomes) != 1 or outcomes[0].get('functional_status') != 'failed'
            or not any(c.get('name') == 'exact requested visit start' and c.get('passed') is False
                       for c in proof.get('checks', []))):
        raise SimulationError('C15 lacks original native exact-start failure')
    extras.extend(p.name for p in campaign.folder.iterdir() if p.is_file()
                  and any(p.name.startswith(cid + '-') for cid in prefix))
    return charges, extras

def _repair_settlement(campaign, charges):
    manifest = campaign.manifest
    binding = manifest.get('linked_repair_reconciliation')
    bundle = _repair_binding(campaign, binding)
    required = ('identity_verified', 'original_ids_excluded', 'baseline_unchanged',
                'native_calendar_effects_settled', 'google_all_recorded_owned_events_deleted')
    ids = list(range(51,63))
    if (bundle.get('run_id') != campaign.run_id or bundle.get('status') != 'settled'
            or bundle.get('paid_prefix') != [e['case_id'] for e in charges]
            or number(bundle.get('spent_credits')) != 5397 or bundle.get('owned_request_ids') != ids
            or bundle.get('cancelled_request_ids') != ids
            or any(bundle.get(k) is not True for k in required)
            or sorted(manifest['deployed_medium'].get('owned_request_ids', [])) != ids):
        raise SimulationError('Linked repair native settlement bundle differs')
    pre = bundle.get('pre_reconciliation_archive', '')
    hashes = json.loads(_artifact(campaign, str(Path(pre) / 'hashes.json')).read_text())
    snapshot = _verified_archive(campaign, pre, hashes)
    effects = bundle.get('case_effects', {})
    expected = {'C07': [], 'C08': [51], 'C09': [52], 'C10':[53,54], 'C11':[55],
                'C12':[56], 'C13':[57,58], 'C14':[59,60], 'C15':[61,62]}
    if set(effects) != set(expected):
        raise SimulationError('Linked repair per-case effect scope differs')
    for cid, owned in expected.items():
        effect = effects[cid]
        if effect.get('owned_request_ids') != owned:
            raise SimulationError('Linked repair per-case native identities differ')
        if cid in ('C10','C15'):
            if effect.get('provenance') != 'native_fixture_operations':
                raise SimulationError('Linked repair fixture provenance missing')
            _fixture_creation_proof(campaign, effect, snapshot)
        elif owned:
            if effect.get('provenance') != 'provider_tool_result':
                raise SimulationError('Linked repair provider provenance missing')
            path = _artifact(campaign, cid + '-1-provider.json')
            if hashlib.sha256(path.read_bytes()).hexdigest() != effect.get('provider_receipt_sha256'):
                raise SimulationError('Linked repair provider effect hash differs')
            saved = json.loads(path.read_text())
            _repair_provider_effect(saved, effect, cid)
        _remaining_effects(campaign, {'owned_request_ids': owned}) if owned else None
    setup_binding = bundle.get('setup_reconciliation')
    if setup_binding not in manifest.get('setup_reconciliations', []):
        raise SimulationError('Linked repair setup receipt is not bound to manifest')
    setup = _repair_binding(campaign, setup_binding)
    if (setup.get('status') != 'settled' or setup.get('run_id') != campaign.run_id
            or setup.get('native_setup_rejected_no_effect') is not True or setup.get('new_request_ids') != []
            or setup.get('google_orphan_deleted') is not True or setup.get('native_fixture_retry') is not False
            or setup.get('owned_request_id') != 62):
        raise SimulationError('C16 rejected setup or owned orphan is unresolved')
    pre_setup = setup.get('pre_reconciliation_archive','')
    setup_hashes = json.loads(_artifact(campaign, str(Path(pre_setup)/'hashes.json')).read_text())
    setup_snapshot = _verified_archive(campaign, pre_setup, setup_hashes)
    index = setup.get('operation_index')
    operations = setup_snapshot.get('deployed_medium',{}).get('operations',[])
    current_ops = manifest['deployed_medium']['operations']
    if type(index) is not int or not 0 <= index < len(operations) or index >= len(current_ops):
        raise SimulationError('C16 rejected setup operation is missing')
    old, current = operations[index], current_ops[index]
    digest = hashlib.sha256(json.dumps(old,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    if (digest != setup.get('operation_sha256') or old.get('status') != 'unknown'
            or old.get('method') != 'POST' or old.get('path') != '/api/v1/voice/tools'
            or old.get('body',{}).get('name') != 'create_service_request'
            or current.get('body') != old.get('body') or current.get('status') != 'observed'
            or current.get('ids') != [] or current.get('outcome') != 'rejected_no_effect'):
        raise SimulationError('C16 original rejected setup proof differs')
    audit = _repair_binding(campaign, bundle.get('google_audit'))
    if (audit.get('run_id') != campaign.run_id or audit.get('owned_request_ids') != ids
            or any(audit.get(k) is not True for k in ('all_owned_requests_cancelled', 'no_owned_active_reservations',
                'all_recorded_google_events_deleted_or_absent', 'all_recorded_twilio_delivered'))
            or type(audit.get('signed_delivery_callbacks_completed')) is not int
            or audit['signed_delivery_callbacks_completed'] != 74
            or {r.get('id') for r in audit.get('requests', [])} != set(ids)
            or any(r.get('status') != 'cancelled' or r.get('calendar_integration_status') != 'DELETED'
                   for r in audit['requests'])
            or not audit.get('reservations') or any(r.get('service_request_id') not in ids
                or r.get('status') != 'CANCELLED' or r.get('calendar_integration_status') != 'DELETED'
                for r in audit['reservations'])
            or not audit.get('google') or any(r.get('deleted_or_absent') is not True for r in audit['google'])
            or not audit.get('outbox') or any(r.get('request_id') not in ids or r.get('status') != 'DELIVERED'
                                              for r in audit['outbox'])
            or not audit.get('twilio') or any(r.get('status') != 'delivered'
                or r.get('recipient_allowlisted') is not True or r.get('native_signed_delivered_callback_completed') is not True
                for r in audit['twilio'])):
        raise SimulationError('Linked repair native Google audit is unresolved')
    return bundle, [binding['path'], setup_binding['path'], bundle['google_audit']['path']]


def _repair_provider_effect(saved, effect, cid):
    expected_tool = 'book_appointment' if cid in ('C13','C14') else 'create_service_request'
    if effect.get('provider_tool_name') != expected_tool or not effect.get('provider_request_id'):
        raise SimulationError('Linked repair provider effect tool differs')
    matches, calls = [], []
    for response in saved.get('test_runs',[{}])[0].get('agent_responses',[]):
        for call in response.get('tool_calls') or []:
            if call.get('tool_name') == expected_tool and call.get('request_id') == effect['provider_request_id']:
                params = call.get('params_as_json')
                params = json.loads(params) if isinstance(params, str) else params
                if not isinstance(params, dict):
                    raise SimulationError('Linked repair provider call arguments are missing')
                calls.append(call)
        for tool in response.get('tool_results') or []:
            if (tool.get('tool_name') == expected_tool and tool.get('request_id') == effect['provider_request_id']
                    and tool.get('is_error') is False):
                value = tool.get('result_value')
                value = json.loads(value) if isinstance(value,str) else value
                if isinstance(value,dict):
                    result = value.get('result',value)
                    if result.get('success') is True:
                        matches.append(deployed_medium.Adapter._ids(result))
    if len(calls) != 1 or matches != [effect['owned_request_ids']]:
        raise SimulationError('Linked repair provider result does not prove exact owned effects')


def _repair_linked_visit(config, tier, live, check, run_id, requested, repeat):
    supplemental = _linked_repair_authorization(config,run_id)
    if (not live or check or tier != 'medium' or not run_id or config.get('target') != 'deployed'
            or requested != ['C15','C16'] or repeat != 1):
        raise SimulationError('Linked repair requires live same-run exact C15,C16 once')
    original = [f'C{i:02}' for i in range(7,17)]
    preview(config,tier,original,repeat,target='deployed')
    root = Path(config.get('artifact_root', ROOT/'scratch/live-simulations')).resolve()
    with campaign_lock(root), httpx.Client(timeout=30,trust_env=False,follow_redirects=False) as client:
        campaign = _unpaid_campaign(config,run_id)
        ledger = json.loads((root/'usage-ledger.json').read_text())
        auth = stage_authorization(config,tier,original,original,repeat,target='deployed')
        if supplemental['authorization_id'] == auth['authorization_id']:
            raise SimulationError('Repair approval must be distinct from the original stage claim')
        charges,extras = _repair_prefix(campaign,ledger,auth,supplemental)
        bundle,settlement_extras = _repair_settlement(campaign,charges)
        extras.extend(settlement_extras)
        problems,observed = deployment_readiness(config,client)
        baseline = campaign.manifest['baseline']
        originals = {r['id']:r for r in baseline}
        if not unchanged(originals,observed) or not ({r['id'] for r in observed}-set(originals)) <= set(bundle['owned_request_ids']):
            raise SimulationError('Linked repair protected native baseline changed')
        name = preserved_customer_name(config,baseline,client)
        cases = select_cases(load_catalog(),tier,requested)
        designated = fixtures.variables(config)
        for case in cases:
            bound = case_variables(config,designated,case)
            if any(bound[k] != designated[k] for k in ('customer_phone','customer_name','customer_email')):
                raise SimulationError('Linked repair recipient identity differs')
        services = campaign.manifest['deployed_medium']['services']
        deployed_medium.validate_retained_catalog(config,client,services)
        problems.extend(deployed_medium.readiness(config,client,cases,baseline,retained_catalog=services))
        _repair_lookup(config,client)
        state,provider_problems = provider_readiness(config,client)
        problems.extend(provider_problems)
        if problems or config.get('budget',{}).get('verified_credit_units') is not True:
            raise SimulationError('Linked repair native/provider readiness failed')
        provider = state['provider']
        # Existing strict terminal identity/actual-credit proofs apply to all nine saved and fresh results.
        spent = _prefix_results(campaign,provider,charges,[])
        c15 = json.loads(_artifact(campaign,'C15-1-provider.json').read_text())
        if c15['test_runs'][0].get('status') != 'passed' or spent != 5397:
            raise SimulationError('Linked repair original C15 provider evaluation differs')
        actual = native_override(provider.resolve_reference(provider.agent(campaign.manifest['campaign_agent_id'])),
                                origin(config.get('deployed_url')),state['webhook_id'])
        desired,revision_extras = _repair_revision(campaign,state,actual)
        state['override'] = desired
        remaining = current_remaining(config,provider)
        budget = campaign_budget(config,tier,remaining); budget.spent = spent
        if not budget.can_start(sum(estimates(config,cases))):
            raise SimulationError('Linked repair aggregate reserve or fresh quota cannot admit two cases')
        state['remaining'] = remaining
        extras.extend(revision_extras)
        extras.extend(p.name for p in campaign.folder.iterdir() if p.is_file() and (p.name.startswith('C15-') or p.name.startswith('C16-')))
        _archive_unpaid(campaign,ledger,previous_attempt=5,kind='repair_admissions',extra_names=list(dict.fromkeys(extras)),
            selected=requested,prior_spent=spent,metadata={'repair_authorization_id':supplemental['authorization_id'],
                'linked_repair_authorization':supplemental,'sample_offsets':{'C15':1,'C16':0},
                'agent_revision_fingerprint':fingerprint(desired)})
        campaign.manifest['repair_admissions'][-1]['resolved_retention_reasons'] = list(campaign.manifest.get('cleanup_blockers',[]))
        campaign.save()
        outcomes = dict(campaign.manifest.get('stage_case_outcomes',{})); outcomes['C15']='failed'
        return _execute(config,tier,live=True,requested=original,repeat=1,_campaign=campaign,
            _admission={'baseline':baseline,'state':state,'existing_name':name,'selected':requested,
                'attempt':6,'prior_stage_spent':spent,'prefix_outcomes':outcomes,'sample_offsets':{'C15':1,'C16':0}})


def _continue_remaining(config, tier, live, check, run_id, requested, repeat, *, unsubmitted=False):
    suffix = [f'C{i:02}' for i in range(10 if unsubmitted else 9, 17)]
    kind = 'unsubmitted_continuations' if unsubmitted else 'remaining_continuations'
    original = [f'C{i:02}' for i in range(7, 17)]
    if (not live or check or tier != 'medium' or not run_id or config.get('target') != 'deployed'
            or repeat != 1 or (not unsubmitted and requested != suffix)
            or (unsubmitted and not isinstance(requested, list))):
        raise SimulationError('Remaining continuation requires live same-run exact C09-C16 once')
    preview(config, tier, original, repeat, target='deployed')
    root = Path(config.get('artifact_root', ROOT / 'scratch/live-simulations')).resolve()
    with campaign_lock(root), httpx.Client(timeout=30, trust_env=False, follow_redirects=False) as client:
        campaign = _unpaid_campaign(config, run_id)
        ledger = json.loads((root / 'usage-ledger.json').read_text())
        auth = stage_authorization(config, tier, original, original, repeat, target='deployed')
        progress = None
        if unsubmitted:
            existing_charges = [entry for entry in ledger['entries'] if entry.get('run_id') == campaign.run_id
                                or entry.get('authorization_id') == auth['authorization_id']]
            progress = _monotonic_progress(campaign, ledger, existing_charges)
            suffix = progress['suffix']
            if requested != suffix:
                raise SimulationError('Requested suffix must exactly follow the settled paid prefix')
        charges, receipts, extras = _prove_remaining(campaign, ledger, auth, suffix, unsubmitted=unsubmitted)
        if config.get('budget', {}).get('verified_credit_units') is not True:
            raise SimulationError('Remaining continuation billing units are unverified')
        cases = select_cases(load_catalog(), tier, suffix)
        designated = fixtures.variables(config)
        for case in cases:
            bound = case_variables(config, designated, case)
            if any(bound[key] != designated[key] for key in ('customer_phone', 'customer_name', 'customer_email')):
                raise SimulationError('Remaining continuation recipient identity differs')
        problems, observed = deployment_readiness(config, client)
        baseline = campaign.manifest['baseline']
        originals = {row['id']: row for row in baseline}
        if not unchanged(originals, observed) or not ({row['id'] for row in observed} - set(originals)) <= {value for receipt in receipts for value in receipt['owned_request_ids']}:
            raise SimulationError('Remaining continuation original native baseline changed')
        existing_name = preserved_customer_name(config, baseline, client)
        services = campaign.manifest['deployed_medium']['services']
        deployed_medium.validate_retained_catalog(config, client, services)
        problems.extend(deployed_medium.readiness(config, client, cases, baseline, retained_catalog=services))
        state, provider_problems = provider_readiness(config, client)
        problems.extend(provider_problems)
        if problems:
            raise SimulationError('Remaining continuation readiness failed: ' + '; '.join(problems))
        provider = state['provider']
        spent = _prefix_results(campaign, provider, charges, receipts)
        for receipt in receipts:
            _remaining_effects(campaign, receipt)
        actual = native_override(provider.resolve_reference(provider.agent(campaign.manifest['campaign_agent_id'])),
                                 origin(config.get('deployed_url')), state['webhook_id'])
        metadata = {}
        if unsubmitted:
            metadata = _verify_owned_revision(campaign, state, actual)
            extras.append(campaign.manifest['agent_revisions'][0]['source_override_path'])
            prior = progress['previous_admission']
            metadata['previous_admission_sha256'] = hashlib.sha256(json.dumps(prior, sort_keys=True).encode()).hexdigest()
        elif (fingerprint(actual) != campaign.manifest.get('reference_fingerprint')
                or fingerprint(state['override']) != campaign.manifest.get('reference_fingerprint')):
            raise SimulationError('Remaining continuation retained clone changed')
        remaining = current_remaining(config, provider)
        budget = campaign_budget(config, tier, remaining)
        budget.spent = spent
        if not budget.can_start(sum(estimates(config, cases))):
            raise SimulationError('Remaining continuation aggregate ceiling, reserve or fresh quota cannot admit suffix')
        state['remaining'] = remaining
        _archive_unpaid(campaign, ledger, previous_attempt=progress['previous_attempt'] if unsubmitted else 2, kind=kind,
                        extra_names=extras, selected=suffix, prior_spent=spent, metadata=metadata)
        campaign.manifest[kind][-1]['resolved_retention_reasons'] = list(campaign.manifest.get('cleanup_blockers', []))
        campaign.save()
        return _execute(config, tier, live=True, requested=original, repeat=repeat, _campaign=campaign,
            _admission={'baseline': baseline, 'state': state, 'existing_name': existing_name,
                        'selected': suffix, 'attempt': progress['previous_attempt'] + 1 if unsubmitted else 3, 'prior_stage_spent': spent,
                        'prefix_outcomes': {entry['case_id']: json.loads(_artifact(campaign, entry['case_id'] + '-1-provider.json').read_text())['test_runs'][0]['status'] for entry in charges}})


def execute(config, tier='minimal', *, live=False, check=False, run_id=None,
            requested=None, repeat=1, continue_unpaid=False, continue_remaining=False, continue_unsubmitted=False,
            repair_linked_visit=False, **kwargs):
    if tier == 'full' and (live or check or requested is not None or config.get('stage_authorization')
                           or config.get('campaign_authorization') or config.get('calibration')):
        if continue_unpaid or continue_remaining or continue_unsubmitted or repair_linked_visit:
            raise SimulationError('Deployed full C17-C50 does not reuse medium continuation authority')
        if live:
            if check:
                raise SimulationError('Choose --check or --live, not both')
            from .deployed_full import FULL_IDS
            if requested is None or tuple(requested) != FULL_IDS:
                raise SimulationError('Deployed full authorization requires explicit C17-C50 exactly once')
            try:
                stage_authorization(config,tier,requested,list(FULL_IDS),repeat,target='deployed')
            except SimulationError:
                raise SimulationError('Full authorization scope or numeric ceiling is invalid') from None
            if config.get('stage_authorization') is None:
                raise SimulationError('Deployed native full execution is unavailable without explicit numeric full-stage authorization')
            return _execute(config,tier,live=True,run_id=run_id,requested=requested,repeat=repeat,**kwargs)
        return _full_delta_preflight(config, live=live, check=check, requested=requested, repeat=repeat)
    if repair_linked_visit:
        if continue_unpaid or continue_remaining or continue_unsubmitted:
            raise SimulationError('Choose one explicit continuation mode')
        return _repair_linked_visit(config, tier, live, check, run_id, requested, repeat)
    if continue_unsubmitted:
        if continue_unpaid or continue_remaining:
            raise SimulationError('Choose one explicit continuation mode')
        return _continue_remaining(config, tier, live, check, run_id, requested, repeat, unsubmitted=True)
    if continue_remaining:
        if continue_unpaid:
            raise SimulationError('Choose one explicit continuation mode')
        return _continue_remaining(config, tier, live, check, run_id, requested, repeat)
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


def _full_delta_preflight(config, *, live, check, requested, repeat):
    """Inspect remaining coverage without authorizing unimplemented native work."""
    from . import deployed_full

    if live and check:
        raise SimulationError('Choose --check or --live, not both')
    if not isinstance(requested, (list, tuple)) or tuple(requested) != deployed_full.FULL_IDS:
        raise SimulationError('Deployed full authorization requires explicit C17-C50 exactly once; earlier tiers are not replayed')
    authorization = config.get('stage_authorization')
    if authorization is not None and (not isinstance(authorization, dict) or authorization.get('tier') != 'full'):
        raise SimulationError('Full authorization cannot reuse the medium or malformed stage authorization')
    cases = select_cases(load_catalog(), 'full', requested)
    deployed_full.validate_delta(cases, repeat=repeat)
    if live:
        # This branch cannot create claims, fixtures, test definitions or paid
        # invocations. Config declarations are not native implementation/evidence.
        raise SimulationError('Deployed native full execution is unavailable until reviewed adapters, actual prerequisites and a new ceiling are ready')
    url = origin(config.get('deployed_url'))
    native = deployed_full.readiness(config, cases)
    report = {
        'tier': 'full', 'target': 'deployed', 'selected': list(deployed_full.FULL_IDS),
        'complete_tier': False, 'status': 'blocked', 'deployed_url': url,
        'acceptance_scope': 'full_delta_native_prerequisites', 'native_contracts': native,
        'implemented_case_ids': native['supported_case_ids'],
        'unsupported_cases': native['unsupported_case_ids'],
        'native_readiness_checked': False, 'new_paid_submissions': 0,
        'problems': ['Native full-case setup, durable assertions and cleanup are not yet completely implemented and proven',
                     'A separately approved full-stage ceiling is required; the medium authorization cannot fund full cases'],
        'notes': ['Preview makes no provider requests.',
                  '--check performs readiness observations only; no fixture, claim or paid resource is created.'],
    }
    budget = config.get('budget', {})
    remaining = budget.get('remaining_credits')
    if check:
        with httpx.Client(timeout=45, trust_env=False, follow_redirects=False) as client:
            problems, _baseline = deployment_readiness(config, client)
            state, provider_problems = provider_readiness(config, client)
            from . import deployed_full_adapter, deployed_full_execution
            try:
                native_problems = deployed_full_execution.prerequisites(config,client,cases,_baseline,deployed_full_adapter)
            except SimulationError:
                native_problems = ['Full native prerequisite observer is unavailable']
        report['problems'].extend([*problems, *provider_problems, *native_problems])
        report['native_readiness_checked'] = True
        if 'remaining' in state:
            remaining = state['remaining']
    report.update(estimated_credits=None, proposed_credit_ceiling=None,
                  credit_shortfall_to_estimate=None, partial_case_estimate_credits=None,
                  c48_recovery_upper_estimate=None, minimum_paid_invocations=len(cases) + 1,
                  missing_budget_estimates=[], credit_units_verified=budget.get('verified_credit_units') is True,
                  estimate_is_measured_bound=False)
    report['notes'].append('The partial 34-case subtotal excludes the additional paid C48 recovery invocation; both C48 phases require budget')
    allowance = estimate = recovery = None
    try:
        allowance = number(remaining)
        report['remaining_credits'] = str(allowance)
    except SimulationError:
        report['problems'].append('Full-delta remaining allowance is unverified')
    try:
        estimate = sum(estimates(config, cases))
        report['partial_case_estimate_credits'] = str(estimate)
    except SimulationError:
        report['problems'].append('Full-delta conservative case estimates are unverified')
    try:
        recovery = number(budget.get('c48_recovery_upper_estimate'), positive=True)
        report['c48_recovery_upper_estimate'] = str(recovery)
    except SimulationError:
        report['missing_budget_estimates'].append('c48_recovery_upper_estimate')
        report['problems'].append('A positive budget.c48_recovery_upper_estimate is required; the 34-case subtotal is not the total full estimate')
    if estimate is not None and recovery is not None:
        total = estimate + recovery
        report.update(estimated_credits=str(total),
                      proposed_credit_ceiling=format(total / number('.8', positive=True), 'f'))
        if allowance is not None:
            report['credit_shortfall_to_estimate'] = str(max(number(0), total - allowance))
            if total > allowance:
                report['problems'].append('Verified allowance is below the unmeasured full-delta estimate including both C48 phases')
    return report


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
    if _admission is not None and _admission.get('selected'):
        cases = select_cases(load_catalog(), tier, _admission['selected'])
        # The original claim remains the full ten-case scope; prior paid cases
        # consume ceiling capacity, but only the suffix needs fresh allowance.
        planned.update(status='planned', estimated_credits=str(sum(estimates(config, cases))))
    attempt_number = _admission.get('attempt', 2) if _admission is not None else 1
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
                   acceptance_scope=('deployed_full_native_state' if tier == 'full' and stage is not None else 'deployed_medium_native_state' if stage is not None else
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
            if tier == 'full':
                from . import deployed_full_adapter, deployed_full_execution
                problems.extend(deployed_medium.readiness(config, client, cases, baseline))
                problems.extend(deployed_full_execution.prerequisites(config,client,cases,baseline,deployed_full_adapter))
            else:
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
            if _admission is not None:
                budget.spent = _admission.get('prior_stage_spent', number(0))
            case_estimates = ([number(calibration['case_upper_estimate'], positive=True)]
                              if calibration is not None else estimates(config, cases))
            admission_estimate = sum(case_estimates) * repeat
            if tier == 'full':
                from . import deployed_full_execution
                admission_estimate = deployed_full_execution.total_estimate(config,case_estimates)
            if not budget.can_start(admission_estimate):
                raise SimulationError('Current remaining allowance cannot admit selected coverage')
            values = fixtures.variables(config)
            values['customer_name'] = existing_name or values['customer_name'] + ' ' + campaign.run_id[:8]
            values['run_id'] = campaign.run_id
            base_values = copy.deepcopy(values)
            baseline_index = {r['id']: r for r in baseline}
            previous, failed, group_ids = [], set(), set()
            if seed is not None:
                previous, group_ids = [copy.deepcopy(seed)], {seed['id']}
            if tier == 'full':
                from .deployed_full_adapter import Adapter as FullAdapter
                adapter = FullAdapter(campaign,client)
            else:
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
                        sample = iteration + 1 + ((_admission or {}).get('sample_offsets', {}).get(case['id'], 0))
                        if adapter is not None:
                            adapter.artifact_sample = sample
                        entry = {'case_id': case['id'], 'repeat': sample, 'status': 'blocked',
                                 'attempt': attempt_number}
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
                            if tier == 'full' and case['id'] == 'C50':
                                case_started = True
                                adapter.state['full_case_values']=copy.deepcopy(values)
                                adapter._save()
                                result = deployed_full_execution.run_c50(adapter,provider=provider,budget=budget,
                                    ledger=ledger,campaign=campaign,estimate=estimate)
                                verified = (result.get('history_verified') is True and result.get('full_case_verified') is True and result.get('global_stop') is False
                                    and not budget.unknown and budget.spent <= budget.cap
                                    and not any(e.get('unsettled') is not False for e in ledger['entries']))
                                entry.update(status='incomplete' if verified else 'blocked',
                                    functional_status='passed' if verified else 'blocked',
                                    checks=deployed_full_execution.special_checks(case,result,verified,budget),
                                    reason='C50 native proof verified; receiving inbox remains unverified' if verified else 'C50 native session/accounting requires reconciliation')
                                stage_blocked = not verified
                                if not verified:
                                    failed.add(case['id'])
                                continue
                            if tier == 'full' and case['id'] == 'C48':
                                case_started = True
                                adapter.state['full_case_values']=copy.deepcopy(values)
                                adapter._save()
                                result = deployed_full_execution.run_c48(adapter,provider=provider,budget=budget,
                                    ledger=ledger,campaign=campaign,estimate=estimate)
                                verified = (result.get('recovery_verified') is True and result.get('full_case_verified') is True
                                    and result.get('global_stop') is False
                                    and not budget.unknown and budget.spent <= budget.cap
                                    and not any(e.get('unsettled') is not False for e in ledger['entries']))
                                entry.update(status='incomplete' if verified else 'blocked',
                                    functional_status='passed' if verified else 'blocked',
                                    checks=deployed_full_execution.special_checks(case,result,verified,budget),
                                    reason='C48 native proof verified; receiving inbox remains unverified' if verified else 'C48 requires reconciliation before further paid work')
                                stage_blocked = not verified
                                if not verified:
                                    failed.add(case['id'])
                                continue
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
                                if tier=='full':
                                    adapter.attach_provider(provider)
                                    with owned_campaign_scope(campaign.root):
                                        adapted_case,fixture_ids=adapter.arrange(case,values)
                                    adapter.prepare_case_agent(case,provider)
                                else:
                                    adapted_case,fixture_ids=adapter.arrange(case,values)
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
                                           system__call_sid=campaign.run_id + case['id'] + str(sample - 1),
                                           system__conversation_id=campaign.run_id + case['id'] + str(sample - 1))
                            if tier=='full':
                                dynamic.update(adapter.case_dynamic_variables(case))
                            manifest['test_create_pending'] = case['id']
                            manifest.setdefault('test_creation_intents', []).append({'case_id': case['id'],
                                'attempt': attempt_number, 'repeat': sample, 'status': 'intent'})
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
                            manifest['test_creation_intents'][-1].update(status='observed', test_id=test_id)
                            manifest['provider_tests'].append(test_id)
                            manifest['test_create_pending'] = None
                            campaign.save()
                            budget.remaining = min(budget.remaining, current_remaining(config, provider))
                            if not budget.can_start(estimate):
                                raise SimulationError('Current allowance cannot admit this paid conversation')
                            charge = {'run_id': campaign.run_id, 'case_id': case['id'], 'test_id': test_id,
                                      'period_reset': config['budget']['reset_unix'], 'repeat': sample, 'unsettled': True}
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
                            if tier == 'full':
                                deployed_full_execution.bind_invocation(adapter,case,invocation_id,test_id)
                            if tier=='full':
                                def observe_native_case(case=case,values=values):
                                    with owned_campaign_scope(campaign.root):
                                        adapter.poll_during_call(case,values,provider)
                                result=provider.wait(invocation_id,config.get('timeout_seconds',120),observe=observe_native_case)
                            else:
                                result=provider.wait(invocation_id,config.get('timeout_seconds',120))
                            credits = provider.credits(result)
                            budget.settle(invocation_id, credits)
                            charge.update(unsettled=credits is None, credits=None if credits is None else str(credits))
                            private_json(ledger_path, ledger)
                            private_json(campaign.folder / f'{case["id"]}-{sample}-provider.json', redact(result))
                            deadline = time.monotonic() + config.get('evidence_timeout_seconds', 90)
                            while True:
                                observed = scoped(get(client, url, '/api/v1/portal/service-requests'), values['customer_phone'])
                                new_ids = {r['id'] for r in observed} - {r['id'] for r in current}
                                group_ids.update(new_ids)
                                after = [r for r in observed if r['id'] in group_ids]
                                checks = (deployed_full_execution.case_checks(adapter,case,values,previous,after,provider)
                                          if tier == 'full' else adapter.checks(case, values, previous, after) if adapter is not None else
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
                                if tier=='full':
                                    with owned_campaign_scope(campaign.root):
                                        checks.extend(adapter.final_checks(case,values,after))
                                else:
                                    checks.extend(adapter.final_checks(case,values,after))
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
                            private_json(campaign.folder / f'{case["id"]}-{sample}-evidence.json',
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
                                if tier=='full' and not any(e.get('unsettled') for e in ledger['entries']):
                                    try:
                                        adapter.restore_case_agent(case,provider)
                                    except (SimulationError,httpx.HTTPError):
                                        stage_blocked=True
                                        entry.update(status='blocked',functional_status='blocked',reason='Owned case agent restoration requires reconciliation')
                                if any(e.get('unsettled') for e in ledger['entries']):
                                    stage_blocked = True
                                elif not stage_blocked:
                                    try:
                                        if tier=='full':
                                            with owned_campaign_scope(campaign.root):
                                                adapter.cleanup_case()
                                        else:
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
                            if r.get('attempt', 1) == attempt_number}
                manifest['status'] = 'failed' if 'failed' in statuses else ('blocked' if 'blocked' in statuses else 'incomplete')
                manifest['latest_attempt_status'] = manifest['status']
                latest = [row for row in manifest['results'] if row.get('attempt', 1) == attempt_number]
                manifest['latest_attempt_functional_status'] = ('passed' if latest and all(row.get('functional_status') == 'passed' for row in latest) else 'failed')
                if _admission is not None and _admission.get('prior_stage_spent') is not None:
                    outcomes = dict(_admission.get('prefix_outcomes', {'C07': 'passed', 'C08': 'failed'}))
                    outcomes.update({row['case_id']: row.get('functional_status', row['status']) for row in latest
                                     if outcomes.get(row['case_id']) != 'failed'})
                    manifest.update(stage_case_outcomes=outcomes, stage_functional_status='failed', status='failed')
            except BaseException:
                manifest['status'] = 'incomplete'
                raise
            finally:
                if (adapter is not None and not stage_blocked
                        and not manifest.get('agent_create_pending')
                        and not manifest.get('test_create_pending')
                        and not [reason for reason in manifest.get('cleanup_blockers', [])
                                 if _campaign is None or reason not in (manifest.get('repair_admissions') or manifest.get('unsubmitted_continuations') or manifest.get('remaining_continuations') or manifest['unpaid_continuations'])[-1].get('resolved_retention_reasons', [])]
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
        from .deployed_full_session import reconcile_campaign
        reconcile(campaign,native_reconcile=reconcile_campaign)
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
