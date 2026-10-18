"""Observable checks; provider evaluation alone is never an acceptance result."""
from __future__ import annotations

import base64
import operator
import re
from urllib.parse import quote

from .core import SimulationError, render


def compare(observed, expected, op='eq'):
    operators = {'eq': operator.eq, 'ne': operator.ne, 'gt': operator.gt,
                 'ge': operator.ge, 'contains': lambda a, b: b in a}
    if op not in operators:
        raise SimulationError('Unknown evidence comparison')
    if observed is None:
        return False
    try:
        return bool(operators[op](observed, expected))
    except (TypeError, ValueError):
        return False


def check(name, passed, observed=None):
    return {'name': name, 'passed': bool(passed), 'observed': observed}


def verify_tools(case, trace):
    successful = set()
    names = {entry.get('name') for entry in trace}
    for entry in trace:
        response = entry.get('response', {})
        result = response.get('result', response) if isinstance(response, dict) else {}
        if isinstance(result, dict) and result.get('success') is True:
            successful.add(entry.get('name'))
    return ([check('required tool: ' + name, name in successful) for name in case.get('expected_tools', [])]
            + [check('forbidden tool: ' + name, name not in names) for name in case.get('forbidden_tools', [])])


def sql_checks(runtime, checks, variables):
    results = []
    for item in render(checks, variables):
        if item['kind'] != 'sql':
            raise SimulationError('Only read-only SQL is accepted for state checks')
        rows = runtime.rows(item['query'], item.get('params', []))
        observed = next(iter(rows[0].values())) if rows else None
        results.append(check(item['name'], compare(observed, item['expect'], item.get('op', 'eq')), observed))
    return results


def local_invariants(runtime):
    """Cross-case guarantees about authoritative state, independent of dialogue scoring."""
    checks = [
        {'name': 'no orphan active reservation', 'kind': 'sql', 'query': "SELECT count(*) FROM appointment_reservations r JOIN service_requests s ON s.id=r.service_request_id WHERE r.status='ACTIVE' AND s.status='cancelled'", 'expect': 0},
        {'name': 'booked requests have reservations', 'kind': 'sql', 'query': "SELECT count(*) FROM service_requests s LEFT JOIN appointment_reservations r ON r.service_request_id=s.id AND r.status='ACTIVE' WHERE s.status<>'cancelled' AND s.booking_time IS NOT NULL AND r.id IS NULL", 'expect': 0},
        {'name': 'reservation segments cover duration', 'kind': 'sql', 'query': "SELECT count(*) FROM appointment_reservations r WHERE r.status='ACTIVE' AND (SELECT count(*) FROM appointment_reservation_segments p WHERE p.reservation_id=r.id) <> ceil(EXTRACT(EPOCH FROM (r.ends_at-r.starts_at))/900)", 'expect': 0},
        {'name': 'inactive technicians never assigned', 'kind': 'sql', 'query': "SELECT count(*) FROM appointment_reservations r JOIN staff_agents a ON a.id=r.staff_agent_id WHERE r.status='ACTIVE' AND NOT a.is_active", 'expect': 0},
    ]
    return sql_checks(runtime, checks, {})


def browser_readback(page, url, rows):
    page.goto(url + '/portal/')
    page.reload()
    page.wait_for_selector('#service-requests-list', state='attached', timeout=15000)
    results = []
    observed = page.request.get(url + '/api/v1/portal/service-requests').json()
    indexed = {r['id']: r for r in observed} if isinstance(observed, list) else {}
    results.append(check('fresh portal API agrees with database IDs', set(indexed) == {r['id'] for r in rows}))
    for row in rows:
        page.wait_for_selector(f'.edit-sr-btn[data-id="{int(row["id"])}"]', state='attached', timeout=15000)
        locator = page.locator(f'.edit-sr-btn[data-id="{int(row["id"])}"]').locator('xpath=ancestor::tr')
        exists = locator.count() == 1
        content = locator.inner_text() if exists else ''
        detail = row.get('issue_description') or row['service_type']
        results.append(check(f'portal row {row["id"]}', exists and detail in content, content))
        status = page.locator(f'.status-select-badge[data-id="{int(row["id"])}"]').input_value()
        expected_status = 'pending' if row['status'] == 'rescheduled' else row['status']
        results.append(check('visible persisted status', status == expected_status, status))
        data = indexed.get(row['id'], {})
        for field in ('service_type', 'status', 'issue_description', 'booking_time'):
            if field in row:
                results.append(check('portal API ' + field, data.get(field) == row[field], data.get(field)))
    # An empty-booking case still verifies a real loaded portal rather than
    # returning a vacuous all([]) success.
    if not rows:
        results.append(check('portal loaded after reload', True))
    return results


def require_delivery(message, callback):
    return (message.get('status') in ('delivered', 'read') and callback
            and bool(re.fullmatch(r'(SM|MM)[0-9a-fA-F]{32}', message.get('sid', ''))))


def whatsapp_checks(client, runtime, logs, callbacks, auth, allowlist, expected_failure=False, fragments=(), expected_error=None):
    results = []
    selected = [row for row in logs if row.get('channel', 'WHATSAPP') == 'WHATSAPP']
    results.append(check('WhatsApp dispatch evidence exists', bool(selected)))
    for row in selected:
        sid = row.get('twilio_message_sid', '') or ''
        if not re.fullmatch(r'(SM|MM)[0-9a-fA-F]{32}', sid):
            if expected_failure:
                results.append(check('persisted provider rejection', row.get('status', '').upper() == 'FAILED'
                                     and bool(row.get('error_code')) and (expected_error is None or str(row['error_code']) == str(expected_error)),
                                     row.get('error_code')))
                continue
            results.append(check('non-mock WhatsApp SID', False))
            continue
        response = client.get(f'https://api.twilio.com/2010-04-01/Accounts/{auth[0]}/Messages/{sid}.json', auth=auth)
        response.raise_for_status()
        message = response.json()
        to = message.get('to', '').replace('whatsapp:', '')
        delivered_callback = any(c.get('MessageSid') == sid and c.get('MessageStatus') in ('delivered', 'read')
                                 for c in callbacks)
        results.append(check('allowlisted WhatsApp recipient', to in allowlist, to))
        results.append(check('WhatsApp content matches fixture', all(str(s) in message.get('body', '') for s in fragments)))
        if expected_failure:
            results.append(check('honest provider failure', message.get('status') in ('failed', 'undelivered')
                                 and row.get('status', '').upper() in ('FAILED', 'UNDELIVERED'), message.get('error_code')))
        else:
            results.append(check('provider and signed callback delivery', require_delivery(message, delivered_callback)
                                 and row.get('status', '').upper() in ('DELIVERED', 'READ'),
                                 {'sid': sid, 'provider': message.get('status'), 'callback': delivered_callback}))
    return results


def email_receipt(client, token, since, recipient, snippets):
    headers = {'Authorization': 'Bearer ' + token}
    result = client.get('https://gmail.googleapis.com/gmail/v1/users/me/messages', headers=headers,
                        params={'q': f'after:{int(since)} to:{recipient}', 'maxResults': 100})
    result.raise_for_status()
    messages = result.json()
    observed = []
    for item in messages.get('messages', []):
        response = client.get('https://gmail.googleapis.com/gmail/v1/users/me/messages/' + quote(item['id'], safe=''),
                              headers=headers, params={'format': 'full'})
        response.raise_for_status()
        data = response.json()
        content = [data.get('snippet', '')]
        def body(part):
            encoded = part.get('body', {}).get('data')
            if encoded:
                content.append(base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4)).decode(errors='replace'))
            for child in part.get('parts', []):
                body(child)
        body(data.get('payload', {}))
        text = '\n'.join(content)
        if all(str(fragment) in text for fragment in snippets):
            observed.append(item['id'])
    return check('receiving inbox contains expected content', bool(observed), observed)


def google_event(client, token, calendar_id, event_id, expected_start=None, cancelled=False, expected_end=None):
    response = client.get('https://www.googleapis.com/calendar/v3/calendars/' + quote(calendar_id, safe='')
                          + '/events/' + quote(event_id, safe=''), headers={'Authorization': 'Bearer ' + token})
    if cancelled and response.status_code in (404, 410):
        return check('Google event removed', True, event_id)
    response.raise_for_status()
    event = response.json()
    observed = event.get('start', {}).get('dateTime')
    if cancelled:
        return check('Google event cancelled', event.get('status') == 'cancelled', event_id)
    from datetime import datetime
    matched = bool(observed)
    if expected_start and observed:
        matched = datetime.fromisoformat(observed.replace('Z', '+00:00')) == datetime.fromisoformat(expected_start.replace('Z', '+00:00'))
    if expected_end:
        end = event.get('end', {}).get('dateTime')
        matched = matched and bool(end) and datetime.fromisoformat(end.replace('Z', '+00:00')) == datetime.fromisoformat(expected_end.replace('Z', '+00:00'))
    return check('Google event time agrees', matched, {'event_id': event_id, 'start': observed})
