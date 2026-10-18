"""Synthetic baseline and declarative per-case arrangements in the owned database."""
from __future__ import annotations

import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

from .core import SimulationError, private_json, render


def variables(config):
    values = dict(config.get('variables', {}))
    required = ('customer_name', 'customer_phone', 'customer_email')
    if any(not values.get(k) for k in required):
        raise SimulationError('Synthetic customer name, phone and receiving email are required')
    import re
    digits = re.sub(r'\D', '', values['customer_phone'])
    if len(digits) == 11 and digits.startswith('1'):
        digits = digits[1:]
    if len(digits) != 10:
        raise SimulationError('The current product requires a 10-digit North American customer phone')
    values['customer_phone'] = digits
    zone = config.get('app_config', {}).get('business_timezone', 'America/New_York')
    day = datetime.now(ZoneInfo(zone)).replace(tzinfo=None) + timedelta(days=7)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    day = day.replace(hour=10, minute=0, second=0, microsecond=0)
    changed = day + timedelta(days=1)
    while changed.weekday() >= 5:
        changed += timedelta(days=1)
    saturday = day + timedelta(days=(5 - day.weekday()) % 7)
    defaults = {'appointment_time': day.isoformat(' '), 'new_time': changed.isoformat(' '),
                'callback_time': day.replace(hour=14).isoformat(' '),
                'new_callback_time': changed.replace(hour=14).isoformat(' '),
                'appointment_date': day.date().isoformat(), 'closed_date': saturday.date().isoformat(),
                'closing_time': day.replace(hour=17).isoformat(' '), 'business_timezone': zone}
    return {**defaults, **values}


def seed(runtime, values):
    """Called with the application stopped, after external effects were settled."""
    runtime.verify_ownership()
    staff = runtime.config.get('staff', [])
    if not staff:
        raise SimulationError('At least one designated test technician is required')
    with runtime.connection() as conn, conn.cursor() as cur:
        # All these rows are run-owned. Staff OAuth bindings and portal configuration
        # intentionally survive between case baselines in this same owned database.
        cur.execute('TRUNCATE customers, service_requests, mock_calendar_slots, outbox_notifications, crm_notes CASCADE')
        cur.execute('UPDATE staff_agents SET is_active=FALSE')
        for index, member in enumerate(staff, 1):
            cur.execute('''INSERT INTO staff_agents(id,name,role,email,phone_number,is_active)
                VALUES (%s,%s,'Technician',%s,%s,TRUE) ON CONFLICT(id) DO UPDATE
                SET name=EXCLUDED.name,email=EXCLUDED.email,phone_number=EXCLUDED.phone_number,is_active=TRUE''',
                        (index, member['name'], member['email'], member['phone']))
        cur.execute('TRUNCATE services RESTART IDENTITY CASCADE')
        for name, duration, price in [('Oil Change', 60, '$80-$120'), ('Tire Rotation', 30, '$30-$50'), ('Brake Inspection', 60, '$50-$90')]:
            cur.execute('''INSERT INTO services(name,description,price_range,duration_minutes,req_location)
                           VALUES (%s,%s,%s,%s,FALSE)''', (name, name, price, duration))
        cur.execute('INSERT INTO service_staff_agents(service_id,staff_agent_id) VALUES (1,1),(2,1)')
        cur.execute('INSERT INTO service_staff_agents(service_id,staff_agent_id) VALUES (3,%s)', (min(2, len(staff)),))
        for field in ('appointment_time', 'new_time'):
            day = datetime.fromisoformat(values[field]).replace(hour=7)
            for member in range(1, len(staff) + 1):
                for offset in range(44):
                    cur.execute('''INSERT INTO mock_calendar_slots(staff_agent_id,slot_datetime)
                                   VALUES (%s,%s) ON CONFLICT DO NOTHING''',
                                (member, day + timedelta(minutes=15 * offset)))
        cur.execute("UPDATE sms_config SET environment='STAGING',quiet_hours_enabled=FALSE")
        cur.execute("UPDATE sms_matrix_rules SET enabled=(channel='WHATSAPP')")
        for phone in runtime.config.get('allowlisted_phone_numbers', []):
            cur.execute('''INSERT INTO sms_whitelist(phone_number,friendly_name,twilio_verified,whatsapp_onboarded)
                VALUES (%s,'Simulation receiver',TRUE,%s) ON CONFLICT(phone_number)
                DO UPDATE SET whatsapp_onboarded=EXCLUDED.whatsapp_onboarded''',
                        (phone, bool(runtime.config.get('whatsapp_ready'))))


def actions(runtime, items, values):
    """Explicit local-only fixture bindings. Never accepts a remote destination."""
    for action in render(items, values):
        if action['kind'] == 'sql':
            runtime.verify_ownership()
            with runtime.connection() as conn, conn.cursor() as cur:
                cur.execute(action['query'], action.get('params', []))
        elif action['kind'] == 'http':
            path = action['path']
            if not path.startswith('/api/v1/') or '?' in path or '..' in path or '#' in path:
                raise SimulationError('Fixture HTTP actions require an explicit local API path')
            with httpx.Client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = client.request(action.get('method', 'POST'), runtime.url + path,
                                          json=action.get('json', {}), params=action.get('params', {}))
                response.raise_for_status()
                data = response.json()
                if isinstance(data, dict) and data.get('result', data).get('success') is False:
                    raise SimulationError('Fixture tool did not succeed')
        elif action['kind'] == 'restart':
            runtime.stop()
            runtime.start()
            runtime.start_gateway()
        elif action['kind'] == 'wait_sql':
            from .evidence import compare
            limit = float(action.get('timeout_seconds', 90))
            if not 0 < limit <= 3600:
                raise SimulationError('Invalid fixture wait timeout')
            deadline = time.monotonic() + limit
            while time.monotonic() < deadline:
                rows = runtime.rows(action['query'], action.get('params', []))
                observed = next(iter(rows[0].values())) if rows else None
                if compare(observed, action['expect'], action.get('op', 'eq')):
                    break
                time.sleep(.5)
            else:
                raise SimulationError('Fixture wait did not reach its required state')
        else:
            raise SimulationError('Unsupported fixture action')


def validate_setup(config, cases):
    """Validate every selected case's designated local specialist bindings."""
    for case in cases:
        if case['setup'] not in ('split', 'linked', 'split_unavailable', 'three_services', 'inactive'):
            continue
        if len(config.get('staff', [])) < 2:
            raise SimulationError('Scenario requires two designated test specialists: ' + case['id'])
        calendars = config.get('calendar_ids', {})
        if any(not isinstance(calendars.get(str(i)), str) or not calendars[str(i)].strip() for i in (1, 2)):
            raise SimulationError('Scenario requires two designated specialist calendar bindings: ' + case['id'])


def arrange(runtime, case, values):
    validate_setup(runtime.config, [case])
    profile = case['setup']
    binding = runtime.config.get('case_bindings', {}).get(case['id'], {})
    if case.get('requires_binding') and not binding.get('ready'):
        raise SimulationError('Scenario requires its documented external/setup binding: ' + case['id'])
    if profile in ('split', 'linked', 'split_unavailable', 'three_services') and len(runtime.config['staff']) < 2:
        raise SimulationError('Scenario requires two designated test specialists')
    if profile == 'single_multi':
        actions(runtime, [{'kind': 'sql', 'query': 'INSERT INTO service_staff_agents VALUES (3,1,now()) ON CONFLICT DO NOTHING'}], values)
    if profile == 'untagged':
        actions(runtime, [{'kind': 'sql', 'query': 'DELETE FROM service_staff_agents WHERE service_id=2'}], values)
    if profile == 'inactive':
        if len(runtime.config['staff']) < 2:
            raise SimulationError('Inactive-technician scenario needs a second test technician')
        actions(runtime, [
            {'kind': 'sql', 'query': 'INSERT INTO service_staff_agents VALUES (1,2,now()) ON CONFLICT DO NOTHING'},
            {'kind': 'sql', 'query': 'UPDATE staff_agents SET is_active=FALSE WHERE id=1'}], values)
    if profile in ('occupied', 'consolidation_blocked', 'split_unavailable'):
        when = values['appointment_time']
        if profile == 'consolidation_blocked':
            when = (datetime.fromisoformat(when) + timedelta(hours=1)).isoformat(' ')
        if profile == 'split_unavailable':
            when = (datetime.fromisoformat(when) + timedelta(hours=1)).isoformat(' ')
        actions(runtime, [{'kind': 'sql', 'query': "UPDATE mock_calendar_slots SET reservation_status='BLOCKED' WHERE slot_datetime>=%s::timestamp AND slot_datetime<%s::timestamp+INTERVAL '1 hour' AND staff_agent_id=%s", 'params': [when, when, 2 if profile == 'split_unavailable' else 1]}], values)
    if profile in ('appointment', 'multiple', 'linked', 'consolidation_blocked'):
        payload = {'name': 'create_service_request', 'arguments': {
            'customer_name': values['customer_name'], 'phone': values['customer_phone'],
            'make': 'Toyota', 'model': 'Camry', 'year': 2021, 'service_type': 'Oil Change',
            'issue_description': 'Oil Change', 'booking_type': 'appointment',
            'booking_time': values['appointment_time']}}
        if profile == 'linked':
            payload['arguments'].update(services=['Oil Change', 'Brake Inspection'],
                                        service_type='Oil Change and Brake Inspection', issue_description='Oil Change and Brake Inspection')
        actions(runtime, [{'kind': 'http', 'path': '/api/v1/voice/tools', 'json': payload}], values)
        if profile == 'multiple':
            payload['arguments'].update(booking_time=values['callback_time'], service_type='Tire Rotation',
                                        issue_description='Tire Rotation', call_sid='fixture-second-booking')
            actions(runtime, [{'kind': 'http', 'path': '/api/v1/voice/tools', 'json': payload}], values)
    if profile in ('appointment', 'multiple', 'linked', 'consolidation_blocked'):
        expected = 2 if profile in ('multiple', 'linked') else 1
        rows = runtime.rows('SELECT count(*) AS count FROM service_requests')
        if not rows or rows[0]['count'] != expected:
            raise SimulationError('Returning-customer fixture did not create its required bookings')
    actions(runtime, binding.get('before', []), values)
    active = {'case_id': case['id'], **binding.get('gateway_fault', {})}
    if profile == 'calendar_unknown':
        active['fail_before'] = 'check_availability'
    if profile == 'lost_response':
        active['lose_after'] = ['create_service_request', 'book_appointment']
    private_json(runtime.folder / 'active-case.json', active)
    return binding
