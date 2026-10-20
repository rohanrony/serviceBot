"""Single owner for explicitly launched, budgeted live acceptance campaigns."""
from __future__ import annotations

import contextlib
import fcntl
import json
import os
import threading
import time
from datetime import datetime
from decimal import Decimal
from urllib.parse import quote, urlparse
from zoneinfo import ZoneInfo

import httpx

from . import evidence, fixtures
from .core import (
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
from .runtime import running


def estimates(config, cases):
    budget = config.get('budget', {})
    return [number(budget.get('case_estimates', {}).get(c['id'], budget.get('case_upper_estimate')), positive=True)
            for c in cases]


def case_variables(config, base, case):
    overrides = config.get('case_bindings', {}).get(case['id'], {}).get('variables', {})
    result = fixtures.variables({**config, 'variables': {**base, **overrides}})
    if base.get('run_id') and not result['customer_name'].endswith(base['run_id'][:8]):
        result['customer_name'] += ' ' + base['run_id'][:8]
    return result


def safe(runtime, value):
    names = list(runtime.config.get('secrets', {}).values()) + list(runtime.config.get('app_environment', {}).values())
    return redact(value, [os.environ.get(name, '') for name in names])


def caller_context(runtime, values):
    customers = runtime.rows('SELECT id,name FROM customers WHERE phone=%s', (values['customer_phone'],))
    context = {'caller_phone': values['customer_phone'], 'customer_name': '',
               'recent_booking_context': '', 'upcoming_appointments_summary': '', 'recent_history_summary': ''}
    if customers:
        context['customer_name'] = customers[0]['name']
        appointments = runtime.rows("SELECT service_type,booking_time,booking_type,issue_description FROM service_requests WHERE customer_id=%s AND status<>'cancelled' ORDER BY booking_time", (customers[0]['id'],))
        summary = '; '.join(f'{r["booking_type"]}: {r["service_type"]} at {r["booking_time"]} ({r["issue_description"]})' for r in appointments)
        context['upcoming_appointments_summary'] = summary
        context['recent_booking_context'] = summary
    return context


def stage_authorization(config, tier, requested, selected, repeat, *, target='isolated'):
    """Validate the explicit target delta; selection remains owned by select_cases."""
    if 'stage_authorization' not in config:
        return None
    auth = config['stage_authorization']
    expected = ([f'C{i:02}' for i in range(7, 17)] if tier == 'medium'
                else [f'C{i:02}' for i in range(17, 51)] if tier == 'full' else [])
    if (not isinstance(auth, dict) or not expected or requested is None
            or target not in ('isolated', 'deployed')
            or config.get('target') not in ((None, 'isolated') if target == 'isolated' else ('deployed',))
            or (target == 'deployed' and tier not in ('medium','full'))
            or config.get('environment', '').lower() in ('production', 'prod')
            or 'campaign_authorization' in config or config.get('calibration')
            or type(repeat) is not int or repeat != 1
            or auth.get('tier') != tier or auth.get('case_ids') != expected
            or selected != expected or list(requested) != expected
            or not isinstance(auth.get('authorization_id'), str)
            or not auth['authorization_id'].strip()):
        raise SimulationError('Invalid isolated stage authorization scope')
    try:
        number(auth.get('credit_ceiling'), positive=True)
    except SimulationError:
        raise SimulationError('Invalid stage authorization credit ceiling') from None
    # Copy so a later config mutation cannot change retained intent provenance.
    return json.loads(json.dumps(auth))


def claim_stage(runtime, ledger, auth):
    """Claim before resources exist, including attempts which never reach billing."""
    if auth is None:
        return
    claims = ledger.setdefault('stage_authorizations', [])
    identifier = auth['authorization_id']
    if (any(c.get('authorization_id') == identifier for c in claims)
            or any(e.get('authorization_id') == identifier for e in ledger['entries'])):
        raise SimulationError('Stage authorization already used or claimed')
    claims.append({**auth, 'run_id': runtime.run_id})
    runtime.manifest['stage_authorization'] = auth
    private_json(runtime.root / 'usage-ledger.json', ledger)
    runtime.save()


def email_mode(config, *, target='isolated'):
    mode = config.get('email_receipt_mode', 'native')
    if mode not in ('native', 'operator'):
        raise SimulationError('Invalid email receipt mode')
    if target == 'deployed' and mode != 'operator':
        raise SimulationError('Deployed medium requires explicit operator email receipt mode')
    if mode == 'operator' and (
            not isinstance(config.get('stage_authorization'), dict)
            or target not in ('isolated', 'deployed')
            or config.get('target') not in ((None, 'isolated') if target == 'isolated' else ('deployed',))
            or (target == 'deployed' and config['stage_authorization'].get('tier') not in ('medium','full'))
            or 'campaign_authorization' in config
            or str(config.get('environment', '')).lower() in ('production', 'prod')):
        raise SimulationError('Operator email receipt requires an isolated stage authorization')
    return mode


def pending_inbox(check, mode):
    return (mode == 'operator'
            and check.get('name') == 'receiving inbox contains expected content'
            and check.get('passed') is False and check.get('status') == 'unverified')


def functional_checks(checks, mode):
    return [check for check in checks if not pending_inbox(check, mode)]


def preview(config, tier, requested=None, repeat=1, *, target='isolated'):
    email_mode(config, target=target)
    catalog = load_catalog()
    cases = select_cases(catalog, tier, requested)
    result = {'tier': tier, 'selected': [c['id'] for c in cases],
              'complete_tier': requested is None, 'status': 'budget_unverified',
              'notes': ['Preview makes no provider requests.', 'WhatsApp/email/application model costs are separate.']}
    auth = stage_authorization(config, tier, requested, result['selected'], repeat, target=target)
    if auth is not None:
        result['stage_authorization'] = auth
    b = config.get('budget', {})
    if b.get('verified_credit_units') is not True:
        return result
    try:
        budget = Budget(b.get('monthly_credits'), tier, b.get('remaining_credits'),
                        credit_ceiling=auth['credit_ceiling'] if auth else None)
        estimate = sum(estimates(config, cases), Decimal(0)) * repeat
    except SimulationError:
        return result
    result.update(estimated_credits=str(estimate), tier_cap=str(budget.cap),
                  admission_limit=str(budget.cap * Decimal('.8')),
                  status='planned' if budget.can_start(estimate) else 'over_budget')
    result['external_bindings_required'] = [c['id'] for c in cases if c.get('requires_binding')
                                           and not config.get('case_bindings', {}).get(c['id'], {}).get('ready')]
    return result


def campaign_status(results):
    statuses = {r.get('status') for r in results}
    for status in ('failed', 'blocked', 'incomplete'):
        if status in statuses:
            return status
    return 'passed' if results and statuses == {'passed'} else 'incomplete'


_campaign_lock_owner = threading.local()


@contextlib.contextmanager
def campaign_lock(root):
    key = (os.getpid(), str(root.resolve()))
    active = getattr(_campaign_lock_owner, 'roots', set())
    if key in active:
        if key not in getattr(_campaign_lock_owner, 'coordinator_roots', set()):
            raise SimulationError('Another campaign owns this artifact root')
        yield
        return
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(root / '.campaign.lock', os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SimulationError('Another campaign owns this artifact root') from None
        _campaign_lock_owner.roots = active | {key}
        yield
    finally:
        _campaign_lock_owner.roots = active
        os.close(fd)


@contextlib.contextmanager
def owned_campaign_scope(root):
    """Explicitly delegate this thread's held lock to a stage coordinator.

    Ordinary nested campaign owners remain rejected. This capability is scoped
    to the exact PID/thread/canonical root and disappears on every exit path.
    """
    key = (os.getpid(), str(root.resolve()))
    if key not in getattr(_campaign_lock_owner,'roots',set()):
        raise SimulationError('Stage coordinator requires the existing campaign owner')
    previous = getattr(_campaign_lock_owner,'coordinator_roots',set())
    _campaign_lock_owner.coordinator_roots = previous | {key}
    try:
        yield
    finally:
        _campaign_lock_owner.coordinator_roots = previous


def traces(runtime, since=0):
    path = runtime.folder / 'trace.jsonl'
    if not path.exists():
        return []
    result = []
    for line in path.read_text().splitlines():
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if entry.get('at', 0) >= since:
            result.append(entry)
    return result


def collect_events(runtime):
    known = {(e.get('owner', 'staff:' + str(e.get('staff_agent_id'))), e['event_id']): e
             for e in runtime.manifest['calendar_events']}
    for row in runtime.rows('SELECT staff_agent_id,calendar_event_id FROM appointment_reservations WHERE calendar_event_id IS NOT NULL'):
        key = ('staff:' + str(row['staff_agent_id']), row['calendar_event_id'])
        if key not in known:
            entry = {'staff_agent_id': row['staff_agent_id'], 'owner': key[0], 'event_id': key[1], 'removed': False}
            runtime.manifest['calendar_events'].append(entry)
            known[key] = entry
    blockers = runtime.manifest.setdefault('cleanup_blockers', [])
    if (runtime.folder / 'calendar-observer-failed').exists() and 'Calendar observation failed' not in blockers:
        blockers.append('Calendar observation failed')
    effects = runtime.folder / 'calendar-effects.jsonl'
    if effects.exists():
        lines = effects.read_text().splitlines()
        offset = runtime.manifest.get('calendar_effects_read', 0)
        if len(lines) < offset:
            raise SimulationError('Calendar effect evidence was truncated')
        pending = set(runtime.manifest.get('pending_calendar_operations', []))
        for line in lines[offset:]:
            event = json.loads(line)
            operation = event.get('operation_id')
            if event.get('stage') == 'started':
                pending.add(operation)
                continue
            pending.discard(operation)
            if event.get('rejected'):
                continue
            if event['owner'] == 'unknown' or not event['event_id']:
                reason = 'Unattributed calendar mutation ' + event['request_fingerprint']
                if reason not in blockers:
                    blockers.append(reason)
                continue
            key = (event['owner'], event['event_id'])
            if key not in known:
                if event['method'] == 'DELETE':
                    reason = 'Unexpected calendar deletion outside run ownership: ' + event['event_id']
                    if reason not in blockers:
                        blockers.append(reason)
                    continue
                entry = {'owner': event['owner'], 'event_id': event['event_id'], 'calendar_id': event['calendar_id'],
                         'staff_agent_id': int(event['owner'].split(':')[1]) if event['owner'].startswith('staff:') else None,
                         'source': 'native_provider_response', 'case_id': event.get('case_id')}
                runtime.manifest['calendar_events'].append(entry)
                known[key] = entry
            known[key]['removed'] = event['method'] == 'DELETE' and not event.get('ambiguous')
        runtime.manifest['calendar_effects_read'] = len(lines)
        runtime.manifest['pending_calendar_operations'] = sorted(pending)
        if pending and not runtime.processes:
            reason = 'Application stopped with unresolved calendar writes'
            if reason not in blockers:
                blockers.append(reason)
    runtime.save()


def retain_effects(runtime):
    """A failed observer prevents resets; the campaign report must still survive."""
    try:
        collect_events(runtime)
    except Exception:
        blockers = runtime.manifest.setdefault('cleanup_blockers', [])
        if 'Calendar evidence collection failed' not in blockers:
            blockers.append('Calendar evidence collection failed')
        runtime.manifest['status'] = 'incomplete'
        runtime.save()


def credentials(runtime):
    """Use the application's own refresh/decrypt owner in the isolated snapshot."""
    target = runtime.folder / 'calendar-credentials.private.json'
    runtime.child("import json,os; from serviceBot.services.google_calendar import get_user_google_credentials; "
                  "from serviceBot.db.connection import get_db_connection; "
                  "c=get_db_connection(); conn=c.__enter__(); cur=conn.cursor(); "
                  "cur.execute('SELECT agent_id FROM user_google_accounts'); ids=[r[0] for r in cur.fetchall()]; "
                  "values={str(i):get_user_google_credentials(i)['access_token'] for i in ids}; "
                  "from serviceBot.services.gmail import get_gmail_access_token; "
                  "from serviceBot.api.portal import load_config; "
                  "values['system_gmail']=get_gmail_access_token() if load_config().get('gmail_enabled') else None; "
                  f"fd=os.open({str(target)!r},os.O_CREAT|os.O_WRONLY|os.O_TRUNC,0o600); "
                  "os.write(fd,json.dumps(values).encode()); os.close(fd); c.__exit__(None,None,None)")
    try:
        return json.loads(target.read_text())
    finally:
        target.unlink(missing_ok=True)


def remove_events(runtime, client):
    if runtime.manifest.get('cleanup_blockers'):
        raise SimulationError('Unattributed calendar effects prevent automatic cleanup/reset; evidence retained')
    outstanding = [e for e in runtime.manifest['calendar_events'] if not e.get('removed')]
    if not outstanding:
        return
    tokens = credentials(runtime)
    for event in outstanding:
        staff = 'system_gmail' if event.get('owner') == 'system_gmail' else str(event['staff_agent_id'])
        if not tokens.get(staff):
            raise SimulationError('Cannot clean up recorded calendar event without its account binding')
        calendar = event.get('calendar_id', runtime.config.get('calendar_ids', {}).get(staff, 'primary'))
        url = 'https://www.googleapis.com/calendar/v3/calendars/' + quote(calendar, safe='') + '/events/' + quote(event['event_id'], safe='')
        response = client.delete(url, headers={'Authorization': 'Bearer ' + tokens[staff]})
        if response.status_code not in (200, 204, 404, 410):
            raise SimulationError('Run-owned calendar cleanup failed; database retained')
        event['removed'] = True
        runtime.save()


def current_remaining(config, provider):
    """Reverify the billing period and live headroom before paid submission."""
    sub = provider.subscription()
    b = config['budget']
    reset = b.get('reset_unix')
    if (type(reset) is not int or reset <= time.time()
            or reset != sub.get('next_character_count_reset_unix')
            or sub.get('character_refresh_period') != 'monthly_period'):
        raise SimulationError('Monthly billing period must be reverified; quota rollover or unsupported period')
    # The explicit verified mapping is required; never infer a minutes-to-credit rate.
    if number(sub.get('character_limit')) != number(b['monthly_credits']):
        raise SimulationError('Verified monthly allowance does not match current account')
    return max(Decimal(0), number(sub['character_limit']) - number(sub['character_count']))


def load_reference(config, provider):
    agent_id = config.get('agent_id', '')
    if not agent_id or agent_id in config.get('protected_agent_ids', []):
        raise SimulationError('An explicit permitted reference-agent ID is required')
    return provider.resolve_reference(provider.agent(agent_id))


def preflight(runtime, cases, provider, client):
    config = runtime.config
    mode = email_mode(config)
    fixtures.validate_setup(config, cases)
    agent = load_reference(config, provider)
    url = urlparse(config.get('tunnel_url', ''))
    if (url.scheme != 'https' or not url.hostname or url.username or url.password
            or url.query or url.fragment or url.path not in ('', '/')):
        raise SimulationError('Tunnel URL must be an explicit HTTPS origin')
    settings = json.loads((runtime.folder / 'gateway.json').read_text())
    response = client.get(config['tunnel_url'].rstrip('/') + '/__simulation__/health',
                          headers={'X-Live-Simulation-Token': settings['token']})
    response.raise_for_status()
    if response.json().get('run_folder') != runtime.run_id:
        raise SimulationError('Tunnel points at another runtime')
    if not config.get('whatsapp_ready') or not config.get('allowlisted_phone_numbers'):
        raise SimulationError('Confirm current WhatsApp enrollment/window and recipient allowlist first')
    values = fixtures.variables(config)
    phones = set(config['allowlisted_phone_numbers'])
    customer = '+1' + values['customer_phone']
    if customer not in phones or any(member['phone'] not in phones for member in config.get('staff', [])):
        raise SimulationError('Every fixture customer/staff delivery phone must be allowlisted')
    allowed_emails = set(config.get('allowlisted_emails', []))
    if values['customer_email'] not in allowed_emails or any(m['email'] not in allowed_emails for m in config.get('staff', [])):
        raise SimulationError('Every fixture receiving email must be allowlisted')
    for member in runtime.rows('SELECT phone_number,email FROM staff_agents WHERE is_active=TRUE'):
        if member['phone_number'] not in phones or member['email'] not in allowed_emails:
            raise SimulationError('An active runtime technician is outside the delivery allowlist')
    for case in cases:
        binding = config.get('case_bindings', {}).get(case['id'], {})
        if case.get('requires_binding') and (not binding.get('ready') or not binding.get('checks')):
            raise SimulationError('External/failure fixture needs ready=true and explicit state checks: ' + case['id'])
        bound = case_variables(config, values, case)
        if '+1' + bound['customer_phone'] not in phones or bound['customer_email'] != values['customer_email']:
            raise SimulationError('Per-case customer must use an allowlisted phone and the designated receiving inbox')
        render(case, bound)
        render(binding, bound)
    app_config = json.loads((runtime.folder / 'app/serviceBot/config.json').read_text())
    if not app_config.get('gmail_enabled'):
        raise SimulationError('Enable and connect test Gmail in the isolated portal')
    # Reject configured notification destinations outside the explicit test allowlist.
    import re
    for key, value in app_config.items():
        if isinstance(value, str) and any(word in key.lower() for word in ('email', 'sender')) and re.fullmatch(r'[^@\s]+@[^@\s]+', value) and value not in allowed_emails:
            raise SimulationError('Isolated application has a non-allowlisted email destination')
        if isinstance(value, str) and ('phone' in key.lower()) and re.fullmatch(r'\+?\d[\d ()-]{8,}', value):
            normalized = re.sub(r'\D', '', value)
            if len(normalized) == 10:
                normalized = '1' + normalized
            if '+' + normalized not in phones:
                raise SimulationError('Isolated application has a non-allowlisted phone destination')
    tokens = credentials(runtime)
    if not tokens or any(str(i) not in tokens for i in range(1, len(config.get('staff', [])) + 1)):
        raise SimulationError('Connect every test technician Google account in the isolated portal')
    for staff, token in tokens.items():
        if not token:
            continue
        calendar = config.get('calendar_ids', {}).get(staff, 'primary')
        response = client.get('https://www.googleapis.com/calendar/v3/calendars/' + quote(calendar, safe='') + '/events',
                              params={'maxResults': 1, 'fields': 'kind'},
                              headers={'Authorization': 'Bearer ' + token})
        response.raise_for_status()
    secret(config, 'twilio_sid')
    secret(config, 'twilio_token')
    receiver = config.get('email_receiver', values['customer_email'])
    if receiver not in allowed_emails:
        raise SimulationError('Email receiving inbox must be explicitly allowlisted')
    if mode == 'native':
        inbox = secret(config, 'gmail_receiver_token')
        response = client.get('https://gmail.googleapis.com/gmail/v1/users/me/profile',
                              headers={'Authorization': 'Bearer ' + inbox})
        response.raise_for_status()
        if response.json().get('emailAddress', '').lower() != receiver.lower():
            raise SimulationError('Gmail receiving token belongs to a different inbox')
    remaining = current_remaining(config, provider)
    reset = config['budget']['reset_unix']
    provider.verify_webhook(config.get('post_call_webhook_id'), config['tunnel_url'], agent)
    override = provider.override(agent, config['tunnel_url'], settings['token'], config['post_call_webhook_id'])
    runtime.manifest['agent_fingerprint'] = fingerprint(override)
    runtime.manifest['agent_version'] = agent.get('version_id')
    runtime.manifest['billing_period_reset'] = reset
    runtime.save()
    return override, remaining


def outcome(runtime, case, values, started, before, client):
    binding = runtime.config.get('case_bindings', {}).get(case['id'], {})
    checks = evidence.sql_checks(runtime, case['checks'] + binding.get('checks', []), values)
    checks.extend(evidence.local_invariants(runtime))
    checks.append(evidence.check('calendar effects attributable to this run', not runtime.manifest.get('cleanup_blockers')
                                 and not runtime.manifest.get('pending_calendar_operations')))
    trace = [t for t in traces(runtime, started) if t.get('case_id') == case['id']]
    checks.extend(evidence.verify_tools(case, trace))
    rows = runtime.rows('SELECT id,service_type,issue_description,status,booking_time,booking_type,duration_minutes,calendar_event_id,staff_agent_id FROM service_requests ORDER BY id')
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            checks.extend(evidence.browser_readback(browser.new_page(), runtime.url, rows))
        finally:
            browser.close()
    required = set(case['required_evidence']) | set(binding.get('required_evidence', []))
    if case['setup'] == 'lost_response':
        checks.append(evidence.check('controlled lost response exercised', any(t.get('controlled_fault') == 'lost_response' for t in trace)))
    if case['id'] == 'C50':
        ids = [t.get('callback_json', {}).get('data', {}).get('conversation_id') for t in trace
               if t.get('path') == '/api/v1/telephony/webhook' and t.get('status_code', 0) in (200, 201)]
        ids = [value for value in ids if value]
        recorded = runtime.rows('SELECT call_id FROM crm_notes')
        checks.append(evidence.check('native signed post-call history linkage', bool(ids) and
                                      all(any(r['call_id'] == value for r in recorded) for value in ids)))
    if 'calendar' in required:
        tokens = credentials(runtime)
        zone = ZoneInfo(values['business_timezone'])
        for row in rows:
            event_id = row.get('calendar_event_id')
            old = next((r for r in before['service_requests'] if r['id'] == row['id']), {})
            if not event_id:
                event_id = old.get('calendar_event_id')
            if not event_id or str(row['staff_agent_id']) not in tokens:
                checks.append(evidence.check('recorded native calendar event', False))
                continue
            stamp = datetime.fromisoformat(str(row['booking_time'])).replace(tzinfo=zone).isoformat()
            from datetime import timedelta
            end = (datetime.fromisoformat(str(row['booking_time'])) + timedelta(minutes=row['duration_minutes'])).replace(tzinfo=zone).isoformat()
            checks.append(evidence.google_event(client, tokens[str(row['staff_agent_id'])],
                runtime.config.get('calendar_ids', {}).get(str(row['staff_agent_id']), 'primary'),
                event_id, stamp, row['status'] == 'cancelled', end))
            if old.get('calendar_event_id') and old['calendar_event_id'] != event_id:
                checks.append(evidence.google_event(client, tokens[str(old['staff_agent_id'])],
                    runtime.config.get('calendar_ids', {}).get(str(old['staff_agent_id']), 'primary'), old['calendar_event_id'], cancelled=True))
    if 'whatsapp' in required:
        last_id = max([r['id'] for r in before['sms_log']] or [0])
        logs = runtime.rows('SELECT * FROM sms_log WHERE id>%s', (last_id,))
        callbacks = [t['callback'] for t in traces(runtime, started) if 'callback' in t]
        checks.extend(evidence.whatsapp_checks(client, runtime, logs, callbacks,
            (secret(runtime.config, 'twilio_sid'), secret(runtime.config, 'twilio_token')),
            set(runtime.config['allowlisted_phone_numbers']), binding.get('expect_notification_failure', False),
            render(binding.get('whatsapp_fragments', ['Toyota', 'Camry']), values), binding.get('expected_error_code')))
    if 'email' in required:
        if email_mode(runtime.config) == 'operator':
            checks.append({'name': 'receiving inbox contains expected content',
                           'passed': False, 'status': 'unverified',
                           'reason': 'Native receiving-inbox verification pending; operator receipt is separate.'})
        else:
            checks.append(evidence.email_receipt(client, secret(runtime.config, 'gmail_receiver_token'),
                started, runtime.config.get('email_receiver', values['customer_email']), render(binding.get('email_fragments', ['{{customer_name}}', 'Toyota', 'Camry']), values)))
    return checks


def write_report(runtime):
    value = safe(runtime, runtime.manifest)
    private_json(runtime.folder / 'report.json', value)
    lines = [f'# Live simulation campaign {runtime.run_id}', '', f'Status: **{value["status"]}**',
             f'Functional status: **{value.get("functional_status", value["status"])}**',
             f'Tier: {value.get("tier", "not launched")}; complete tier: {value.get("complete_tier", False)}',
             f'ElevenLabs credits: {value.get("spent_credits", "unknown")} verified'
             + ('; unsettled charges remain' if value.get('unsettled_usage') else ''),
             'WhatsApp/email/application model charges: separate, not included in this credit budget.',
             '', '| Case | Result | Functional result | Detail |', '| --- | --- | --- | --- |']
    for row in value.get('results', []):
        lines.append(f'| {row["case_id"]} | {row["status"]} | {row.get("functional_status", row["status"])} | {row.get("reason", "")} |')
    lines += ['', 'Provider-confirmed delivery and handset confirmation are separate.',
              'Simulation transcripts do not establish real phone/audio behavior.',
              'Evidence retention: 30 days. Cleanup does not unsend messages.']
    (runtime.folder / 'report.md').write_text('\n'.join(lines) + '\n')


def run_campaign(runtime, tier, requested=None, *, live=False, repeat=1):
    if not live:
        raise SimulationError('run requires --live; no provider work started')
    config = runtime.config
    mode = email_mode(config)
    if type(repeat) is not int or not 1 <= repeat <= 20:
        raise SimulationError('Invalid repetition count')
    planned = preview(config, tier, requested, repeat)
    if planned['status'] != 'planned':
        raise SimulationError('Campaign cannot start: ' + planned['status'])
    if runtime.manifest.get('results') or runtime.manifest.get('invocations'):
        raise SimulationError('This campaign was already attempted; retain evidence and prepare a new run')
    cases = select_cases(load_catalog(), tier, requested) * repeat
    provider = ElevenLabs(secret(config, 'elevenlabs_key'))
    values = fixtures.variables(config)
    # Unique synthetic names make receiving-inbox correlation resistant to old campaigns.
    values['customer_name'] += ' ' + runtime.run_id[:8]
    values['run_id'] = runtime.run_id
    base_values = values
    runtime.manifest.update(tier=tier, complete_tier=requested is None, status='running',
                            selected=planned['selected'], email_receipt_mode=mode)
    with campaign_lock(runtime.root), httpx.Client(timeout=30, trust_env=False, follow_redirects=False) as client:
        ledger_path = runtime.root / 'usage-ledger.json'
        ledger = json.loads(ledger_path.read_text()) if ledger_path.exists() else {'entries': []}
        if any(e.get('unsettled') for e in ledger['entries']):
            raise SimulationError('Unsettled prior invocation blocks more paid work; reconcile its provider usage first')
        auth = stage_authorization(config, tier, requested, planned['selected'], repeat)
        if runtime.manifest.get('stage_authorization'):
            raise SimulationError('Stage authorization already claimed by this attempted run')
        claim_stage(runtime, ledger, auth)
        try:
            # Initial serve/setup created staff and connected accounts before this call.
            with running(runtime):
                override, remaining = preflight(runtime, cases, provider, client)
            budget = Budget(config['budget']['monthly_credits'], tier, remaining,
                            credit_ceiling=auth['credit_ceiling'] if auth else None)
            if not budget.can_start(sum(estimates(config, cases), Decimal(0))):
                raise SimulationError('Current remaining allowance cannot admit selected coverage')
            runtime.manifest['agent_create_pending'] = True
            runtime.save()
            try:
                runtime.manifest['campaign_agent_id'] = provider.create_agent(override, runtime.run_id)
            except SimulationError as exc:
                if 'ambiguous' not in str(exc):
                    runtime.manifest['agent_create_pending'] = False
                raise
            runtime.manifest['agent_create_pending'] = False
            runtime.save()
            created = provider.agent(runtime.manifest['campaign_agent_id'])
            actual = created.get('platform_settings', {}).get('workspace_overrides', {}).get('webhooks', {})
            if any(actual.get(k) != v for k, v in override['platform_settings']['workspace_overrides']['webhooks'].items()):
                raise SimulationError('Created agent callback settings differ from the isolated override')
            provider.verify_webhook(config['post_call_webhook_id'], config['tunnel_url'], created)
            failed = set()
            for attempt, (case, estimate) in enumerate(zip(cases, estimates(config, cases)), 1):
                values = case_variables(config, base_values, case)
                entry = {'case_id': case['id'], 'attempt': attempt, 'status': 'blocked', 'checks': []}
                runtime.manifest['results'].append(entry)
                if any(dependency in failed for dependency in case.get('dependencies', [])):
                    entry['reason'] = 'Failed or blocked prerequisite'
                    failed.add(case['id'])
                    continue
                if not budget.can_start(estimate):
                    entry.update(status='incomplete', reason='Budget exhausted or usage unverified')
                    failed.add(case['id'])
                    continue
                try:
                    if case['setup'] != 'continue':
                        remove_events(runtime, client)
                        fixtures.seed(runtime, values)
                    with running(runtime):
                        binding = fixtures.arrange(runtime, case, values)
                        # Setup effects have their own trace/baseline and are not counted
                        # as successful conversational tool calls.
                        before = runtime.snapshot()
                        started = time.time()
                        spec = render(case, values)
                        dynamic = {k: str(v) for k, v in values.items()}
                        dynamic.update(caller_context(runtime, values))
                        dynamic.update(system__caller_id='+1' + values['customer_phone'],
                                       system__call_sid=runtime.run_id + case['id'],
                                       system__conversation_id=runtime.run_id + case['id'])
                        runtime.manifest['test_create_pending'] = {'case_id': case['id'], 'attempt': attempt}
                        runtime.save()
                        try:
                            test_id = provider.create(spec, runtime.run_id, dynamic, config['environment'])
                        except SimulationError as exc:
                            if 'ambiguous' not in str(exc):
                                runtime.manifest['test_create_pending'] = None
                            raise
                        runtime.manifest['test_create_pending'] = None
                        runtime.manifest['provider_tests'].append(test_id)
                        runtime.save()
                        budget.remaining = min(budget.remaining, current_remaining(config, provider))
                        if not budget.can_start(estimate):
                            raise SimulationError('Current account allowance cannot admit this conversation')
                        charge = {'run_id': runtime.run_id, 'case_id': case['id'], 'test_id': test_id,
                                  'period_reset': config['budget']['reset_unix'], 'unsettled': True}
                        if auth is not None:
                            charge.update(authorization_id=auth['authorization_id'], stage_authorization=auth)
                        ledger['entries'].append(charge)
                        private_json(ledger_path, ledger)
                        invocation = provider.run(runtime.manifest['campaign_agent_id'], test_id, override)
                        invocation_id = invocation.get('id')
                        if not invocation_id:
                            raise SimulationError('ambiguous paid request: missing invocation ID')
                        charge['invocation_id'] = invocation_id
                        runtime.manifest['invocations'].append(invocation_id)
                        private_json(ledger_path, ledger)
                        runtime.save()
                        result = provider.wait(invocation_id, config.get('timeout_seconds', 120),
                                               lambda: collect_events(runtime))
                        credits = provider.credits(result)
                        budget.settle(invocation_id, credits)
                        charge.update(unsettled=credits is None, credits=None if credits is None else str(credits))
                        private_json(ledger_path, ledger)
                        private_json(runtime.folder / f'{case["id"]}-provider-{attempt}.json', safe(runtime, result))
                        private_json(runtime.folder / f'{case["id"]}-post-conversation-{attempt}.json', safe(runtime, runtime.snapshot()))
                        fixtures.actions(runtime, binding.get('after', []), values)
                        deadline = time.monotonic() + config.get('evidence_timeout_seconds', 90)
                        checks = []
                        while time.monotonic() < deadline:
                            collect_events(runtime)
                            checks = outcome(runtime, spec, values, started, before, client)
                            if all(c['passed'] for c in functional_checks(checks, mode)):
                                break
                            time.sleep(1)
                        checks.append(evidence.check('provider conversation evaluation',
                            all(r.get('status') == 'passed' for r in result['test_runs'])))
                        checks.append(evidence.check('actual credits verified', credits is not None))
                        checks.append(evidence.check('tier budget respected', budget.spent <= budget.cap))
                        functional = all(c['passed'] for c in functional_checks(checks, mode))
                        pending = any(pending_inbox(c, mode) for c in checks)
                        entry.update(checks=checks,
                                     functional_status='passed' if functional else 'failed',
                                     status=('incomplete' if pending else 'passed') if functional else 'failed',
                                     reason='; '.join(c.get('reason', c['name']) for c in checks if not c['passed']))
                        private_json(runtime.folder / f'{case["id"]}-evidence-{attempt}.json', safe(runtime, {'checks': checks, 'trace': traces(runtime, started), 'before': before, 'after': runtime.snapshot()}))
                except (SimulationError, httpx.HTTPError) as exc:
                    entry.update(status='blocked', reason=str(redact(str(exc))))
                    if 'ambiguous' in str(exc) or any(e.get('unsettled') for e in ledger['entries']):
                        budget.unknown = True
                finally:
                    runtime.stop()
                    private_json(runtime.folder / 'active-case.json', {})
                    retain_effects(runtime)
                    try:
                        private_json(runtime.folder / f'{case["id"]}-final-state-{attempt}.json', safe(runtime, runtime.snapshot()))
                    except Exception:
                        runtime.manifest.setdefault('cleanup_blockers', []).append('Final state export failed: ' + case['id'])
                    runtime.manifest['spent_credits'] = str(budget.spent)
                    runtime.save()
                entry.setdefault('functional_status', entry['status'])
                if entry['functional_status'] != 'passed':
                    failed.add(case['id'])
                else:
                    failed.discard(case['id'])
            runtime.manifest['functional_status'] = campaign_status(
                [{'status': row.get('functional_status', row['status'])} for row in runtime.manifest['results']])
            runtime.manifest['status'] = campaign_status(runtime.manifest['results'])
            if runtime.manifest.get('cleanup_blockers'):
                runtime.manifest['status'] = 'incomplete'
            if tier == 'full' and runtime.manifest['status'] == 'passed':
                runtime.manifest.update(status='incomplete', awaiting_handset_confirmation=True)
        except BaseException:
            runtime.manifest['status'] = 'incomplete'
            raise
        finally:
            runtime.stop()
            retain_effects(runtime)
            runtime.manifest['unsettled_usage'] = any(e.get('unsettled') and e['run_id'] == runtime.run_id for e in ledger['entries'])
            runtime.save()
            write_report(runtime)
    return runtime.manifest


def cleanup(runtime, *, live=False):
    """Idempotent cleanup never infers provider ownership from a title or phone."""
    with campaign_lock(runtime.root), httpx.Client(timeout=30, trust_env=False) as client:
        if runtime.manifest['cleanup'].get('database') != 'removed':
            collect_events(runtime)
        if runtime.manifest.get('agent_create_pending'):
            raise SimulationError('Agent creation was ambiguous; resolve its ownership before cleanup')
        if runtime.manifest.get('test_create_pending'):
            raise SimulationError('Test creation was ambiguous; resolve its ownership before cleanup')
        if runtime.manifest['calendar_events'] or runtime.manifest['provider_tests'] or runtime.manifest.get('campaign_agent_id'):
            if not live:
                raise SimulationError('Recorded provider resources require cleanup --live; local state retained')
            provider = ElevenLabs(secret(runtime.config, 'elevenlabs_key'))
            for invocation in runtime.manifest['invocations']:
                result = provider.get(invocation)
                if any(r.get('status') == 'pending' for r in result.get('test_runs', [])):
                    provider.cancel(invocation)
                    raise SimulationError('Cancellation requested; retry cleanup once pending execution settles')
            remove_events(runtime, client)
            removed = runtime.manifest['cleanup'].setdefault('provider_tests', [])
            for test_id in runtime.manifest['provider_tests']:
                if test_id not in removed:
                    provider.delete_test(test_id)
                    removed.append(test_id)
                    runtime.save()
            agent_id = runtime.manifest.get('campaign_agent_id')
            if agent_id and not runtime.manifest['cleanup'].get('agent_removed'):
                owned = provider.agent(agent_id, missing_ok=True)
                if owned and (owned.get('name') != 'Live simulation ' + runtime.run_id or runtime.run_id not in owned.get('tags', [])):
                    raise SimulationError('Remote agent ownership no longer matches the manifest')
                if owned:
                    provider.delete_agent(agent_id)
                runtime.manifest['cleanup']['agent_removed'] = True
                runtime.save()
        if runtime.manifest['cleanup'].get('database') != 'removed':
            runtime.drop_database()
        runtime.manifest['cleanup']['status'] = 'complete'
        runtime.save()
        write_report(runtime)


def reconcile(runtime):
    """Read provider billing; never repeat a paid request to recover its identity."""
    with campaign_lock(runtime.root):
        path = runtime.root / 'usage-ledger.json'
        ledger = json.loads(path.read_text())
        provider = ElevenLabs(secret(runtime.config, 'elevenlabs_key'))
        for entry in ledger['entries']:
            if entry.get('run_id') != runtime.run_id or not entry.get('unsettled'):
                continue
            if entry.get('resource_type') == 'conversation':
                # Native-session accounting has a distinct provider identity and
                # credit-unit contract; generic agent-test discovery cannot infer it.
                continue
            invocation = entry.get('invocation_id')
            if not invocation:
                result = provider.request('GET', '/v1/convai/test-invocations?test_id=' + quote(entry['test_id'], safe=''))
                matches = result.get('results', [])
                if result.get('has_more') or len(matches) != 1:
                    raise SimulationError('Ambiguous invocation cannot yet be reconciled; do not resubmit it')
                invocation = matches[0]['id']
                entry['invocation_id'] = invocation
                if invocation not in runtime.manifest['invocations']:
                    runtime.manifest['invocations'].append(invocation)
                    runtime.save()
            result = provider.get(invocation)
            if any(r.get('status') == 'pending' for r in result.get('test_runs', [])):
                raise SimulationError('Invocation is still pending')
            credits = provider.credits(result)
            if credits is None:
                raise SimulationError('Invocation charges are still unverified')
            entry.update(unsettled=False, credits=str(credits))
            private_json(path, ledger)
        relevant = [e for e in ledger['entries'] if e['run_id'] == runtime.run_id]
        runtime.manifest['unsettled_usage'] = any(e.get('unsettled') for e in relevant)
        runtime.manifest['spent_credits'] = str(sum((number(e['credits']) for e in relevant if not e.get('unsettled')), Decimal(0)))
        runtime.save()
        write_report(runtime)
