"""Journaled native medium fixtures with a read-only reservation observer.

No isolated runtime, database mutation, global reset, or arbitrary fixture actions
are available here. The deployed campaign owns admission and provider settlement.
"""
from __future__ import annotations

import copy
import os
import re
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

from .core import SimulationError
from .evidence import check
from .fixtures import variables

_sleep = time.sleep
_monotonic = time.monotonic

KEYS = ('oil', 'second', 'split')
MEDIUM_IDS = {f'C{i:02}' for i in range(7, 17)}


def _read(config, statement, params=()):
    """Only internal fixed SELECT statements use this read-only connection."""
    import psycopg2
    from psycopg2.extras import RealDictCursor
    name = config.get('deployed_medium', {}).get('database_env', '')
    if not name or not os.environ.get(name):
        raise SimulationError('Deployed medium read-only database binding is missing')
    try:
        with psycopg2.connect(os.environ[name], connect_timeout=10) as conn:
            conn.set_session(readonly=True)
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT current_setting('transaction_read_only') AS readonly")
                if cur.fetchone()['readonly'] != 'on':
                    raise SimulationError('Deployed medium observer must be read-only')
                cur.execute(statement, params)
                return [dict(row) for row in cur.fetchall()]
    except SimulationError:
        raise
    except Exception:  # noqa: BLE001 - fail closed without exposing native connection details
        raise SimulationError('Deployed medium read-only observation failed') from None


def _request_rows(config, ids):
    return _read(config, """SELECT s.id,s.service_type,s.issue_description,s.status,s.booking_type,s.booking_time,
        s.duration_minutes,s.staff_agent_id,s.visit_group_id,c.id AS customer_id,c.phone AS customer_phone,
        c.name AS customer_name,v.make,v.model,v.year,r.id AS reservation_id,r.status AS reservation_status,
        r.starts_at,r.ends_at,r.calendar_event_id,r.calendar_integration_status,
        s.calendar_integration_status AS request_calendar_status,
        (SELECT count(*) FROM appointment_reservation_segments p WHERE p.reservation_id=r.id) AS segment_count,
        ARRAY(SELECT p.segment_start FROM appointment_reservation_segments p WHERE p.reservation_id=r.id ORDER BY p.segment_start) AS reservation_segments,
        EXISTS(SELECT 1 FROM service_staff_agents sa JOIN services svc ON svc.id=sa.service_id
          WHERE sa.staff_agent_id=s.staff_agent_id AND svc.name=s.service_type) AS qualified,
        ARRAY(SELECT svc.name FROM service_staff_agents sa JOIN services svc ON svc.id=sa.service_id
          WHERE sa.staff_agent_id=s.staff_agent_id ORDER BY svc.name) AS qualified_service_names
        FROM service_requests s JOIN customers c ON c.id=s.customer_id
        LEFT JOIN vehicles v ON v.id=s.vehicle_id
        LEFT JOIN appointment_reservations r ON r.service_request_id=s.id AND r.status='ACTIVE'
        WHERE s.id=ANY(%s) ORDER BY r.starts_at NULLS LAST,s.id""", (list(ids),)) if ids else []


def _callback_browser_matches(row, rendered_text, badge_text):
    """Match callback identity as app.js formatIssueDescription renders it."""
    raw = row.get('issue_description')
    if (row.get('booking_type') != 'callback' or not isinstance(raw, str) or not raw.strip()
            or not isinstance(badge_text, str) or badge_text.casefold() != 'callback'
            or not isinstance(rendered_text, str)):
        return False
    # Keep this bounded display normalization aligned with app.js:780-789.
    issue = re.sub(r'^(Appointment booked|Callback requested):\s*', '', raw, flags=re.IGNORECASE)
    issue = re.sub(r'\.?\s*Preferred time:.*$', '', issue, flags=re.IGNORECASE)
    issue = re.sub(r'\s*scheduled for.*$', '', issue, flags=re.IGNORECASE)
    issue = re.sub(r'\s*\(\d{4}\s+[a-zA-Z0-9\s-]+\)', '', issue)
    issue = re.sub(r'\s+for\s+\d{4}\s+[a-zA-Z0-9\s-]+$', '', issue, flags=re.IGNORECASE)
    issue = ' '.join(issue.split())
    if not issue or issue.lower() in ('repair', 'callback', 'callback requested', 'appointment booked', 'n/a', 'unknown'):
        return False
    text = rendered_text.strip()
    # innerText applies the portal badge's CSS uppercase transform.
    return text[:len('Callback')].casefold() == 'callback' and ' '.join(text[len('Callback'):].split()) == issue


def _effect_rows(config, ids):
    return _read(config, """SELECT s.id,s.calendar_integration_status AS request_calendar_status,
        EXISTS(SELECT 1 FROM appointment_reservations r WHERE r.service_request_id=s.id AND r.calendar_event_id IS NOT NULL) AS has_event,
        (SELECT count(*) FROM appointment_reservations r WHERE r.service_request_id=s.id AND r.status='ACTIVE') AS active_count,
        (SELECT count(*) FROM appointment_reservation_segments p JOIN appointment_reservations r ON r.id=p.reservation_id WHERE r.service_request_id=s.id) AS segment_count,
        ARRAY(SELECT r.calendar_integration_status FROM appointment_reservations r WHERE r.service_request_id=s.id) AS reservation_calendar_statuses,
        ARRAY(SELECT o.status FROM outbox_notifications o WHERE o.request_id=s.id AND o.event_type='calendar_projection') AS projection_statuses
        FROM service_requests s WHERE s.id=ANY(%s)""", (list(ids),)) if ids else []


def _slots(config, staff, start, end):
    return _read(config, """SELECT m.id,m.staff_agent_id,m.slot_datetime,m.is_booked,
        m.reservation_status,m.service_request_id,m.updated_at,
        EXISTS(SELECT 1 FROM appointment_reservations r WHERE r.staff_agent_id=m.staff_agent_id
          AND r.status='ACTIVE' AND r.starts_at<m.slot_datetime+INTERVAL '15 minutes'
          AND r.ends_at>m.slot_datetime) AS active_reservation
        FROM mock_calendar_slots m WHERE m.staff_agent_id=%s
          AND m.slot_datetime>=%s AND m.slot_datetime<%s ORDER BY m.slot_datetime""", (staff, start, end))


def _now(config):
    zone = config.get('app_config', {}).get('business_timezone', 'America/New_York')
    return datetime.now(ZoneInfo(zone))


def _occupied_slots(config, values, duration):
    staff = config['deployed_medium']['technician_ids'][0]
    start = _dt(values['appointment_time'], config)
    if start <= _dt(_now(config), config):
        raise SimulationError('Occupied fixture requires an appointment strictly in the future')
    end = start + timedelta(minutes=duration)
    rows = _slots(config, staff, start, end)
    expected = {start + timedelta(minutes=i) for i in range(0, duration, 15)}
    if {_dt(r['slot_datetime'], config) for r in rows} != expected or any(r['is_booked'] or r['reservation_status'] != 'AVAILABLE' or r['service_request_id'] or r['active_reservation'] for r in rows):
        raise SimulationError('Occupied fixture requires existing available unreserved designated slots')
    return rows


def _identity_id(config):
    binding = config.get('existing_customer_identity')
    if binding is None:
        return None
    if not isinstance(binding, dict) or type(binding.get('id')) is not int or binding['id'] <= 0 or not isinstance(binding.get('name'), str) or not binding['name'].strip():
        raise SimulationError('The explicit existing customer identity is invalid')
    return binding['id']


def _verify_identity(config, client):
    identity = _identity_id(config)
    if identity is None:
        return
    binding = config['existing_customer_identity']
    observed = _read(config, 'SELECT id,name,phone FROM customers WHERE id=%s', (identity,))
    if (len(observed) != 1 or observed[0]['name'] != binding['name']
            or _digits(observed[0]['phone']) != _digits(config['variables']['customer_phone'])):
        raise SimulationError('Observer customer identity differs from the explicit native binding')
    response = client.post(config['deployed_url'].rstrip('/') + '/api/v1/voice/tools', json={
        'name':'verify_caller_identity', 'arguments':{'phone':config['variables']['customer_phone'],
        'claimed_name':binding['name'], 'read_only':True}})
    response.raise_for_status()
    result = response.json().get('result', {})
    if not (result.get('success') is True and result.get('read_only') is True
            and result.get('is_existing_customer') is True and result.get('is_verified_existing_customer') is True
            and result.get('customer_id') == identity and result.get('customer_name') == binding['name']):
        raise SimulationError('Native customer identity differs from the explicit observer binding')


def _validate_original_dates(config, cases, baseline):
    identity = _identity_id(config)
    dates = set()
    for case in cases:
        values = variables(config)
        values.update(config.get('case_bindings', {}).get(case['id'], {}).get('variables', {}))
        dates.update(_dt(values[field], config).date() for field in ('appointment_time', 'new_time', 'callback_time'))
    for row in baseline:
        if identity is not None:
            if type(row.get('customer_id')) is not int:
                raise SimulationError('The original booking customer identity cannot be classified safely')
            if row['customer_id'] != identity:
                continue
        if row.get('status') in ('cancelled', 'cancelled_by_customer', 'completed', 'done'):
            continue
        when = row.get('booking_time')
        if not when or _dt(when, config).date() in dates:
            raise SimulationError('An original active or undated booking could be touched by native consolidation; choose other test dates')


def _validate_selected_slots(config, cases):
    for case in cases:
        if case['id'] == 'C08':
            values = variables(config)
            values.update(config.get('case_bindings', {}).get(case['id'], {}).get('variables', {}))
            _occupied_slots(config, values, config['deployed_medium']['services']['oil']['duration_minutes'])


def _digits(value):
    return re.sub(r'\D', '', str(value or ''))[-10:]


def _dt(value, config):
    stamp = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if stamp.tzinfo:
        stamp = stamp.astimezone(ZoneInfo(config.get('app_config', {}).get('business_timezone', 'America/New_York'))).replace(tzinfo=None)
    return stamp


def _get(client, config, path):
    response = client.get(config['deployed_url'].rstrip('/') + path)
    response.raise_for_status()
    return response.json()


def _definitions(config):
    medium = config.get('deployed_medium', {})
    owner, services, staff = medium.get('ownership_id'), medium.get('services', {}), medium.get('technician_ids', [])
    if (not isinstance(owner, str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,80}', owner)
            or len(staff) != 2 or any(type(i) is not int or i <= 0 for i in staff) or len(set(staff)) != 2
            or set(services) != set(KEYS)):
        raise SimulationError('Deployed medium requires unique ownership, three services and two designated technicians')
    for item in services.values():
        if (item.get('id') is not None or not isinstance(item.get('name'), str)
                or not (item['name'].startswith(owner + ' ') or item['name'].startswith('LIVE TEST ' + owner[:8] + ' ')) or type(item.get('duration_minutes')) is not int
                or item['duration_minutes'] <= 0 or item['duration_minutes'] % 15
                or not isinstance(item.get('price_range'), str) or not item['price_range'].strip()):
            raise SimulationError('Deployed medium services require new owned names, prices and quarter-hour durations')
    if len({s['name'] for s in services.values()}) != 3:
        raise SimulationError('Deployed medium catalog names must be distinct')
    return medium


def validate_retained_catalog(config, client, services):
    """Read back exact journaled definitions and qualifications without adopting IDs."""
    binding = _definitions(config)
    if not isinstance(services, dict) or set(services) != set(KEYS):
        raise SimulationError('Retained catalog identities are incomplete')
    ids = [services[key].get('id') for key in KEYS]
    if any(type(value) is not int or value <= 0 for value in ids) or len(set(ids)) != 3:
        raise SimulationError('Retained catalog identities are invalid')
    native = {row['id']: row for row in _get(client, config, '/api/v1/portal/services')}
    for key in KEYS:
        item, expected = services[key], binding['services'][key]
        agents = [binding['technician_ids'][1 if key == 'split' else 0]]
        if (any(item.get(field) != value for field, value in expected.items())
                or item.get('assigned_agent_ids') != agents
                or any(native.get(item['id'], {}).get(field) != item.get(field)
                       for field in ('name', 'duration_minutes', 'price_range', 'assigned_agent_ids'))):
            raise SimulationError('Retained native catalog definitions or qualifications differ')
    observed = _read(config, 'SELECT id,name,duration_minutes,price_range FROM services WHERE id=ANY(%s)', (ids,))
    indexed = {row['id']: row for row in observed}
    if set(indexed) != set(ids) or any(any(indexed[item['id']].get(field) != item.get(field)
            for field in ('name', 'duration_minutes', 'price_range')) for item in services.values()):
        raise SimulationError('Retained observer catalog definitions differ')
    qualified = _read(config, 'SELECT service_id,staff_agent_id FROM service_staff_agents WHERE service_id=ANY(%s)', (ids,))
    expected_pairs = {(item['id'], agent) for item in services.values() for agent in item['assigned_agent_ids']}
    if {(row['service_id'], row['staff_agent_id']) for row in qualified} != expected_pairs:
        raise SimulationError('Retained observer qualifications differ')


def _native_mutation_timeout(config):
    # Native fixture writes may outlast the provider client's independent 30s bound.
    timeout = config.get('native_mutation_timeout_seconds', 120)
    if type(timeout) not in (int, float) or not 0 < timeout <= 120:
        raise SimulationError('Native mutation timeout must be a finite number above 0 and at most 120 seconds')
    return timeout


def readiness(config, client, cases, baseline, *, retained_catalog=None):
    """Read every selected setup before the campaign claims or spends anything."""
    try:
        _native_mutation_timeout(config)
        binding = _definitions(config)
        if not cases or any(c['id'] not in MEDIUM_IDS for c in cases):
            raise SimulationError('Deployed medium supports C07-C16 only')
        catalog = _get(client, config, '/api/v1/portal/services')
        names = {row['name'] for row in catalog}
        if retained_catalog is not None:
            validate_retained_catalog(config, client, retained_catalog)
        if retained_catalog is None and any(s['name'] in names for s in binding['services'].values()):
            raise SimulationError('Planned test catalog names already exist; do not adopt existing services')
        staff = _read(config, """SELECT sa.id,sa.email,sa.phone_number,sa.is_active,
            uga.email AS google_email,uga.granted_scopes FROM staff_agents sa
            LEFT JOIN user_google_accounts uga ON uga.agent_id=sa.id WHERE sa.id=ANY(%s)""", (binding['technician_ids'],))
        allowed_emails = {str(x).lower() for x in config.get('allowlisted_emails', [])}
        allowed_phones = {_digits(x) for x in config.get('allowlisted_phone_numbers', [])}
        if len(staff) != 2 or len({str(s.get('google_email', '')).lower() for s in staff}) != 2:
            raise SimulationError('Both distinct designated Google bindings must exist on the deployment')
        for row in staff:
            if (not row.get('is_active') or str(row.get('google_email', '')).lower() not in allowed_emails
                    or str(row.get('email', '')).lower() not in allowed_emails
                    or _digits(row.get('phone_number')) not in allowed_phones
                    or 'calendar' not in str(row.get('granted_scopes', ''))):
                raise SimulationError('Designated technician binding or notification recipient is unavailable')
            native = _get(client, config, '/api/v1/portal/agents/' + str(row['id']))
            if (native.get('id') != row['id'] or str(native.get('email', '')).lower() != str(row['google_email']).lower()
                    or _digits(native.get('phone_number')) != _digits(row['phone_number']) or not native.get('is_connected')):
                raise SimulationError('Native deployment and observer technician identities differ')
        # Pin the database to native catalog and baseline facts; a local copied
        # database must not silently substitute for the deployed observer.
        observed = _read(config, 'SELECT id,name,duration_minutes FROM services ORDER BY id')
        expected = sorted((r['id'], r['name'], r['duration_minutes']) for r in catalog)
        if sorted((r['id'], r['name'], r['duration_minutes']) for r in observed) != expected:
            raise SimulationError('Native deployment and observer catalogs differ')
        original = _request_rows(config, [r['id'] for r in baseline])
        if len(original) != len(baseline) or any(_digits(r['customer_phone']) != _digits(config['variables']['customer_phone']) for r in original):
            raise SimulationError('Native deployment and observer customer baseline differ')
        indexed = {r['id']: r for r in original}
        for row in baseline:
            current = indexed[row['id']]
            if any(str(current.get(k)) != str(row.get(k)) for k in ('status', 'service_type', 'booking_type', 'booking_time', 'duration_minutes', 'staff_agent_id')):
                raise SimulationError('Native deployment and observer booking identities differ')
        _verify_identity(config, client)
        _validate_original_dates(config, cases, original)
        _validate_selected_slots(config, cases)
        return []
    except (SimulationError, httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
        return [str(exc) if isinstance(exc, SimulationError) else 'Cannot verify deployed medium native prerequisites']


class Adapter:
    def __init__(self, campaign, client):
        self.campaign, self.client, self.config = campaign, client, campaign.config
        self.state = campaign.manifest.setdefault('deployed_medium', {'services': {}, 'operations': [], 'owned_request_ids': [], 'blocks': [], 'blocked': False})
        self.owned_ids = set(self.state['owned_request_ids'])
        self.current_ids = set(self.state.get('current_request_ids', []))
        self.original_ids = {r['id'] for r in campaign.manifest.get('baseline', [])}
        self.current_case = self.state.get('current_case')
        self.before_rows = self.state.get('fixture_rows', [])

    def _save(self):
        self.state['owned_request_ids'] = sorted(self.owned_ids)
        self.state['current_request_ids'] = sorted(self.current_ids)
        self.campaign.save()

    def _guard(self):
        if self.state.get('blocked'):
            raise SimulationError('Deployed fixture state is unknown or unresolved; reconciliation is required')
        if not self.campaign.manifest.get('stage_authorization'):
            raise SimulationError('Deployed medium fixture mutation requires a durable stage claim')

    def _mutate(self, method, path, body):
        self._guard()
        timeout = _native_mutation_timeout(self.config)
        op = {'method': method, 'path': path, 'body': copy.deepcopy(body), 'status': 'intent',
              'timeout_seconds': timeout}
        self.state['operations'].append(op)
        self._save()
        stage, status_code = 'request', None
        started = _monotonic()
        try:
            response = self.client.request(method, self.config['deployed_url'].rstrip('/') + path, json=body, timeout=timeout)
            status_code = response.status_code
            stage = 'http_status'
            response.raise_for_status()
            stage = 'decode'
            data = response.json()
            stage = 'result'
            result = data.get('result', data)
            if not isinstance(result, dict) or result.get('success') is False:
                raise SimulationError('Native fixture operation was rejected')
            op['status'] = 'observed'
            # Persist bounded IDs, not arbitrary response/customer content.
            op['ids'] = self._ids(result)
            op['elapsed_seconds'] = max(0, _monotonic() - started)
            stage = 'persist'
            self._save()
            return result
        except Exception as exc:  # noqa: BLE001 - any error after sending leaves fixture outcome uncertain
            op['elapsed_seconds'] = max(0, _monotonic() - started)
            op['diagnostic'] = {
                'error_type': type(exc).__name__, 'status_code': status_code, 'stage': stage,
                'kind': ('transport' if isinstance(exc, httpx.TransportError) else
                         'rejected' if isinstance(exc, httpx.HTTPStatusError) or
                         (stage == 'result' and isinstance(exc, SimulationError)) else 'unknown'),
            }
            op['status'] = 'unknown'
            self.state['blocked'] = True
            self._save()
            raise SimulationError('Native fixture response is unknown; reconcile before further paid work') from None

    @staticmethod
    def _ids(result):
        ids = {result[k] for k in ('id', 'appointment_id', 'service_request_id') if type(result.get(k)) is int}
        for row in result.get('appointments', []):
            if type(row.get('service_request_id')) is int:
                ids.add(row['service_request_id'])
        return sorted(ids)

    def prepare_catalog(self):
        self._guard()
        binding = _definitions(self.config)
        if self.state['services']:
            raise SimulationError('Existing catalog fixture cannot be adopted or prepared twice')
        existing = _get(self.client, self.config, '/api/v1/portal/services')
        if any(s['name'] in {r['name'] for r in existing} for s in binding['services'].values()):
            raise SimulationError('Owned catalog name already exists')
        for key in KEYS:
            item = binding['services'][key]
            agents = [binding['technician_ids'][1 if key == 'split' else 0]]
            payload = {k: item[k] for k in ('name', 'duration_minutes', 'price_range')}
            payload.update(description='Owner-designated simulation ' + binding['ownership_id'], req_location=False, agent_ids=agents)
            result = self._mutate('POST', '/api/v1/portal/services', payload)
            if type(result.get('id')) is not int:
                self.state['blocked'] = True
                self._save()
                raise SimulationError('Catalog creation identity is unknown')
            self.state['services'][key] = {**item, 'id': result['id'], 'assigned_agent_ids': agents}
            self._save()
        observed = _get(self.client, self.config, '/api/v1/portal/services')
        by_id = {r['id']: r for r in observed}
        for item in self.state['services'].values():
            native = by_id.get(item['id'], {})
            if any(native.get(k) != item[k] for k in ('name', 'duration_minutes', 'price_range', 'assigned_agent_ids')):
                self.state['blocked'] = True
                self._save()
                raise SimulationError('Created test catalog bindings did not match native read-back')

    def _adapt(self, case):
        adapted = copy.deepcopy(case)
        substitutions = {'Oil Change': self.state['services']['oil']['name'], 'Tire Rotation': self.state['services']['second']['name'], 'Brake Inspection': self.state['services']['split']['name']}
        def replace(value):
            if isinstance(value, str):
                for old, new in substitutions.items(): value = value.replace(old, new)
                return value
            if isinstance(value, list): return [replace(v) for v in value]
            if isinstance(value, dict): return {k: replace(v) for k, v in value.items()}
            return value
        adapted = replace(adapted)
        # Quotes are derived from the actual deployed catalog, never fixture defaults.
        adapted['success_conditions'] = [v for v in adapted['success_conditions'] if not v.startswith('Before booking, quote catalog facts accurately:')]
        if case['id'] in {'C07', 'C08', 'C09', 'C11', 'C13', 'C14'}:
            facts = '; '.join(f"{s['name']}: {s['price_range']}, {s['duration_minutes']} minutes" for s in self.state['services'].values())
            adapted['success_conditions'].append('Before any appointment booking quote the actual requested catalog service facts and obtain consent: ' + facts)
        if case['id'] != 'C12':
            keys = ['oil', 'second'] if case['id'] in ('C10', 'C13') else ['oil', 'split'] if case['id'] in ('C14', 'C15', 'C16') else ['oil']
            names = [self.state['services'][key]['name'] for key in keys]
            if case['id'] == 'C08':
                adapted['scenario'] = adapted['scenario'].replace(
                    'Ask for the occupied', 'Ask for ' + names[0] + ' at the occupied', 1)
            adapted['scenario'] = (
                'Use these exact service names from the start of the conversation: '
                + '; '.join(names) + '. ' + adapted['scenario'])
        adapted['scenario'] += ' Identify test services by their exact full names. Do not change any pre-existing booking for another service.'
        return adapted

    def _register(self, ids, values, *, callback=False, combined=False):
        ids = set(ids)
        if ids & self.original_ids:
            raise SimulationError('Original customer bookings cannot become test-owned')
        rows = _request_rows(self.config, ids)
        if {r['id'] for r in rows} != ids:
            raise SimulationError('Native test request identities cannot be verified')
        names = {s['name'] for s in self.state['services'].values()}
        identity = _identity_id(self.config)
        for row in rows:
            unknown_callback = callback and row['booking_type'] == 'callback' and _dt(row['booking_time'], self.config) == _dt(values['callback_time'], self.config)
            if ((identity is not None and row.get('customer_id') != identity)
                    or _digits(row['customer_phone']) != _digits(values['customer_phone'])
                    or row['customer_name'] != values['customer_name']
                    or (row['service_type'] not in names and not unknown_callback
                        and not (combined and _combined_name(row['service_type'], self.state['services'])))):
                raise SimulationError('Unexpected customer/service request cannot become test-owned')
        self.owned_ids.update(ids)
        self.current_ids.update(ids)
        self._save()
        return rows

    def _create(self, values, keys, when):
        services = [self.state['services'][key]['name'] for key in keys]
        args = {'customer_name': values['customer_name'], 'phone': values['customer_phone'], 'make': 'Toyota', 'model': 'Camry', 'year': 2021,
                'service_type': ' and '.join(services), 'issue_description': ' and '.join(services), 'booking_type': 'appointment', 'booking_time': when,
                'call_sid': self.campaign.manifest['run_id'] + '-' + str(len(self.state['operations']))}
        if len(services) > 1: args['services'] = services
        result = self._mutate('POST', '/api/v1/voice/tools', {'name': 'create_service_request', 'arguments': args})
        ids = self._ids(result)
        try:
            rows = self._register(ids, values)
        except SimulationError:
            self.state['blocked'] = True
            self._save()
            raise
        if (len(rows) != len(keys) or {r['service_type'] for r in rows} != set(services)
                or any(not _reservation(r, self.config, self.state['services']) for r in rows)
                or min((_dt(r['starts_at'], self.config) for r in rows), default=None) != _dt(when, self.config)):
            self.state['blocked'] = True
            self._save()
            raise SimulationError('Native fixture did not create its required exact service requests')
        return rows

    def _block(self, values):
        staff = self.config['deployed_medium']['technician_ids'][0]
        start = _dt(values['appointment_time'], self.config)
        end = start + timedelta(minutes=self.state['services']['oil']['duration_minutes'])
        original = _occupied_slots(self.config, values, self.state['services']['oil']['duration_minutes'])
        for row in original:
            if start <= _dt(_now(self.config), self.config):
                raise SimulationError('Occupied fixture appointment is no longer in the future')
            slot_start = _dt(row['slot_datetime'], self.config)
            latest = _slots(self.config, staff, slot_start, slot_start + timedelta(minutes=15))
            if (len(latest) != 1 or _serial(latest[0]) != _serial(row)
                    or latest[0]['is_booked'] or latest[0]['reservation_status'] != 'AVAILABLE'
                    or latest[0]['active_reservation'] or latest[0]['service_request_id']):
                raise SimulationError('Occupied fixture slot changed before mutation; refuse unsafe block')
            block = {'original': _serial(row), 'owned': None, 'restored': False}
            self.state['blocks'].append(block)
            self._save()
            self._mutate('PATCH', '/api/v1/portal/calendar/' + str(row['id']), {'is_booked': True})
            updated = next((r for r in _slots(self.config, staff, start, end) if r['id'] == row['id']), None)
            if not updated or updated['reservation_status'] != 'BLOCKED' or updated['active_reservation'] or updated['service_request_id']:
                self.state['blocked'] = True
                self._save()
                raise SimulationError('Owned occupied block could not be verified')
            block['owned'] = _serial(updated)
            self._save()
        for key, unavailable in (('appointment_time', True), ('new_time', False)):
            when = _dt(values[key], self.config)
            response = self.client.post(self.config['deployed_url'].rstrip('/') + '/api/v1/voice/tools', json={'name': 'check_availability', 'arguments': {'service_type': self.state['services']['oil']['name'], 'preferred_date': when.date().isoformat(), 'preferred_time': when.strftime('%I:%M %p'), 'booking_type': 'appointment'}})
            response.raise_for_status()
            result = response.json().get('result', {})
            offered = {_dt(s, self.config) for s in result.get('available_slots', [])}
            if not result.get('success') or ((when in offered) == unavailable):
                raise SimulationError('Native occupied fixture availability precondition failed')

    def arrange(self, case, values):
        self._guard()
        if case['id'] not in MEDIUM_IDS or set(self.state['services']) != set(KEYS):
            raise SimulationError('Deployed medium catalog must be prepared before cases')
        if self.current_ids or any(not b['restored'] for b in self.state['blocks']):
            raise SimulationError('Previous case fixtures are not cleaned up')
        self.current_case = case['id']
        self.state['current_case'] = self.current_case
        self._save()
        adapted = self._adapt(case)
        if case['id'] == 'C08': self._block(values)
        if case['id'] == 'C10':
            self._create(values, ['oil'], values['appointment_time'])
            self._create(values, ['second'], values['callback_time'])
        if case['id'] in ('C15', 'C16'):
            rows = self._create(values, ['oil', 'split'], values['appointment_time'])
            if not _visit(rows, self.config, self.state['services'], ['oil', 'split'], 2):
                raise SimulationError('Native linked fixture is not a complete qualified visit')
        self.before_rows = _serial(_request_rows(self.config, self.current_ids))
        self.state['fixture_rows'] = self.before_rows
        self._save()
        return adapted, sorted(self.current_ids)

    def checks(self, case, values, before, after):
        ids = {r['id'] for r in after}
        rows = self._register(ids, values, callback=case['id'] == 'C12', combined=case['id'] == 'C13')
        active = [r for r in rows if r['status'] != 'cancelled']
        cid = case['id']
        expected_count = len(rows) in (1, 2) if cid == 'C13' else len(rows) == (0 if cid == 'C07' else 2 if cid in ('C10', 'C14', 'C15', 'C16') else 1)
        checks = [check('native request count', expected_count)]
        if cid == 'C07': return checks
        checks.append(check('preserved customer identity and vehicle intake', all(r['customer_name'] == values['customer_name'] and r.get('make') == 'Toyota' and r.get('model') == 'Camry' and r.get('year') == 2021 for r in rows)))
        if cid == 'C16':
            checks.append(check('complete linked cancellation', len(rows) == 2 and not active and all(not r['reservation_id'] for r in rows) and {r['id'] for r in rows} == {r['id'] for r in self.before_rows}))
            return checks
        checks.append(check('all expected requests remain active', len(active) == len(rows)))
        checks.append(check('native appointment calendar projection created', all(r.get('calendar_integration_status') == 'CREATED' and r.get('request_calendar_status') == 'CREATED' and bool(r.get('calendar_event_id')) for r in active if r['booking_type'] == 'appointment')))
        if cid not in ('C12',):
            checks.append(check('authoritative active reservations', all(_reservation(r, self.config, self.state['services'], combined=cid == 'C13') for r in active)))
        if cid in ('C13', 'C14', 'C15'):
            keys = ['oil', 'second' if cid == 'C13' else 'split']
            checks.append(check('qualified contiguous full visit', _visit(active, self.config, self.state['services'], keys, 1 if cid == 'C13' else 2)))
            field = 'new_time' if cid == 'C15' else 'appointment_time'
            starts = [_dt(r['starts_at'], self.config) for r in active if r['starts_at'] is not None]
            checks.append(check('exact requested visit start', bool(starts) and min(starts) == _dt(values[field], self.config)))
            if cid == 'C15': checks.append(check('linked request identities preserved', ids == {r['id'] for r in self.before_rows} if self.before_rows else ids == self.owned_ids))
        elif cid == 'C10':
            original = {r['service_type']: r for r in self.before_rows}
            oil, second = self.state['services']['oil']['name'], self.state['services']['second']['name']
            indexed = {r['service_type']: r for r in rows}
            checks.append(check('selected booking moved', oil in indexed and oil in original and indexed[oil]['id'] == original[oil]['id'] and _dt(indexed[oil]['booking_time'], self.config) == _dt(values['new_time'], self.config)))
            checks.append(check('unselected booking preserved', second in indexed and second in original and all(str(indexed[second].get(k)) == str(original[second].get(k)) for k in ('id', 'booking_time', 'staff_agent_id', 'duration_minutes', 'booking_type', 'status'))))
        else:
            field = 'callback_time' if cid == 'C12' else 'new_time' if cid in ('C08', 'C09') else 'appointment_time'
            kind = 'callback' if cid == 'C12' else 'appointment'
            if cid != 'C12':
                checks.append(check('exact requested catalog service', len(active) == 1 and active[0]['service_type'] == self.state['services']['oil']['name']))
            checks.append(check('exact requested booking time and type', len(active) == 1 and active[0]['booking_type'] == kind and _dt(active[0]['booking_time'], self.config) == _dt(values[field], self.config)))
        return checks

    def final_checks(self, case, values, after):
        """Native projection must settle; optional browser check scopes only owned rows."""
        ids = {r['id'] for r in after}
        rows = _request_rows(self.config, ids)
        appointments = [r for r in rows if r['status'] != 'cancelled' and r['booking_type'] == 'appointment']
        results = [check('native calendar projection created', {r['id'] for r in rows} == ids and all(r.get('calendar_integration_status') == 'CREATED' and r.get('request_calendar_status') == 'CREATED' and bool(r.get('calendar_event_id')) for r in appointments))]
        if self.config.get('deployed_medium', {}).get('browser_readback'):
            results.extend(self._browser_checks(case, rows))
        return results

    def _browser_checks(self, case, rows):
        # Playwright's synchronous owner cannot nest in a thread whose event
        # loop is already running (including an existing session browser).
        # Transfer only immutable observation inputs; this worker owns and
        # closes its own driver, context and browser on the same thread.
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=1, thread_name_prefix='medium-browser') as executor:
            return executor.submit(self._browser_checks_owned, copy.deepcopy(case), copy.deepcopy(rows)).result()

    def _browser_checks_owned(self, case, rows):
        from urllib.parse import urlparse

        from playwright.sync_api import sync_playwright
        url = self.config['deployed_url'].rstrip('/')
        checks = []
        stage = 'playwright_start'
        try:
            with sync_playwright() as playwright:
                stage = 'browser_launch'
                browser = playwright.chromium.launch(headless=True)
                try:
                    page = browser.new_page()
                    allowed = urlparse(url).netloc
                    page.route('**/*', lambda route: route.continue_() if urlparse(route.request.url).netloc == allowed else route.abort())
                    stage = 'portal_navigation'
                    page.goto(url + '/portal/', wait_until='domcontentloaded')
                    page.reload(wait_until='domcontentloaded')
                    page.wait_for_selector('#service-requests-list', state='attached', timeout=15000)
                    stage = 'owned_row_readback'
                    for row in rows:
                        page.wait_for_selector(f'.edit-sr-btn[data-id="{int(row["id"])}"]', state='attached', timeout=15000)
                        locator = page.locator(f'.edit-sr-btn[data-id="{int(row["id"])}"]').locator('xpath=ancestor::tr')
                        exists = locator.count() == 1
                        if exists and (case['id'] == 'C12' or row.get('booking_type') == 'callback'):
                            issue = locator.locator('.issue-desc-text')
                            badge = issue.locator('.booking-type-tag.callback')
                            matches = (issue.count() == 1 and badge.count() == 1
                                       and _callback_browser_matches(row, issue.inner_text(), badge.inner_text().strip()))
                        else:
                            matches = exists and row['service_type'] in locator.inner_text()
                        checks.append(check('reloaded browser owned row ' + str(row['id']), matches))
                        if exists:
                            status = page.locator(f'.status-select-badge[data-id="{int(row["id"])}"]').input_value()
                            expected = 'pending' if row['status'] == 'rescheduled' else row['status']
                            checks.append(check('browser owned row persisted status ' + str(row['id']), status == expected))
                    if not rows: checks.append(check('reloaded browser portal', True))
                    stage = 'screenshot'
                    sample = getattr(self, 'artifact_sample', 1)
                    if type(sample) is not int or sample < 1:
                        raise SimulationError('Browser artifact sample must be a positive integer')
                    suffix = '' if sample == 1 else '-' + str(sample)
                    page.screenshot(path=str(self.campaign.folder / (case['id'] + suffix + '-portal.png')), full_page=True)
                finally:
                    browser.close()
        except Exception as exc:  # noqa: BLE001 - browser errors are sanitized failing evidence
            reason = 'sync_api_in_active_event_loop' if 'inside the asyncio loop' in str(exc) else 'browser_failure'
            checks.append(check('reloaded browser owned scope', False, {'stage':stage, 'error_type':type(exc).__name__, 'reason':reason}))
        return checks

    def cleanup_case(self):
        self._guard()
        if self.owned_ids & self.original_ids or self.current_ids & self.original_ids:
            raise SimulationError('Original customer bookings cannot be cleaned up')
        ids = set(self.current_ids)
        rows = _request_rows(self.config, ids)
        if {r['id'] for r in rows} != ids:
            raise SimulationError('Owned cleanup request state is unavailable')
        for row in rows:
            latest = _request_rows(self.config, [row['id']])
            if len(latest) != 1:
                raise SimulationError('Owned cleanup request disappeared')
            if latest[0]['status'] != 'cancelled':
                self._mutate('POST', '/api/v1/voice/tools', {'name': 'cancel_appointment', 'arguments': {'phone': row['customer_phone'], 'appointment_id': row['id'], 'cancellation_reason': 'Owner-designated simulation cleanup'}})
        observed = _request_rows(self.config, ids)
        if any(r['status'] != 'cancelled' or r['reservation_id'] for r in observed):
            raise SimulationError('Owned booking cleanup has not released active reservations')
        self._settle_cleanup(ids)
        for block in self.state['blocks']:
            if block['restored']: continue
            original, owned = block['original'], block['owned']
            if owned is None: raise SimulationError('Occupied block ownership is unknown')
            start = _dt(original['slot_datetime'], self.config)
            current = _slots(self.config, original['staff_agent_id'], start, start + timedelta(minutes=15))
            if len(current) != 1 or _serial(current[0]) != owned or current[0]['active_reservation']:
                raise SimulationError('Occupied block changed; refuse unsafe restoration')
            self._mutate('PATCH', '/api/v1/portal/calendar/' + str(original['id']), {'is_booked': original['is_booked']})
            restored = _slots(self.config, original['staff_agent_id'], start, start + timedelta(minutes=15))
            if len(restored) != 1 or any(_serial(restored[0]).get(k) != original.get(k) for k in ('id', 'staff_agent_id', 'slot_datetime', 'is_booked', 'reservation_status', 'service_request_id', 'active_reservation')):
                raise SimulationError('Occupied block restoration did not match original state')
            block['restored'] = True
            self._save()
        self.current_ids.clear()
        self.state['fixture_rows'] = []
        self._save()

    def _settle_cleanup(self, ids):
        if not ids: return
        timeout = float(self.config.get('evidence_timeout_seconds', 120))
        if not 0 < timeout <= 3600:
            raise SimulationError('Invalid cleanup settlement timeout')
        deadline = _monotonic() + timeout
        while True:
            rows = _effect_rows(self.config, ids)
            if {r['id'] for r in rows} != set(ids):
                raise SimulationError('Owned cleanup effect identities are unavailable')
            settled = True
            for row in rows:
                statuses = row['projection_statuses']
                if any(status not in ('DELIVERED', 'PENDING', 'PROCESSING', 'RETRY', 'INFLIGHT') for status in statuses):
                    raise SimulationError('Owned cleanup calendar projection failed; reconciliation required')
                deleted = not row['has_event'] or (row['request_calendar_status'] == 'DELETED' and all(status == 'DELETED' for status in row['reservation_calendar_statuses']))
                if row['active_count'] or row['segment_count'] or not statuses or any(status != 'DELIVERED' for status in statuses) or not deleted:
                    settled = False
            if settled:
                self.state['cleanup_settlement'] = {'request_ids': sorted(ids), 'status': 'native_calendar_effects_settled', 'google_delete_verified': False}
                self._save()
                return
            if _monotonic() >= deadline:
                raise SimulationError('Owned cleanup calendar effects remain pending; stop before another paid case')
            _sleep(min(.5, max(0, deadline - _monotonic())))

    def cleanup_catalog(self):
        self._guard()
        if self.current_ids or any(not b['restored'] for b in self.state['blocks']):
            raise SimulationError('Case effects must settle before catalog cleanup')
        rows = _request_rows(self.config, self.owned_ids)
        if any(r['status'] != 'cancelled' or r['reservation_id'] for r in rows):
            raise SimulationError('Owned request effects must settle before catalog cleanup')
        self._settle_cleanup(self.owned_ids)
        catalog = {r['id']: r for r in _get(self.client, self.config, '/api/v1/portal/services')}
        for item in self.state['services'].values():
            if item.get('deleted'): continue
            current = catalog.get(item['id'], {})
            if any(current.get(k) != item[k] for k in ('name', 'duration_minutes', 'price_range', 'assigned_agent_ids')):
                raise SimulationError('Owned catalog changed; refuse deletion')
            self._mutate('DELETE', '/api/v1/portal/services/' + str(item['id']), {})
            item['deleted'] = True
            self._save()
        remaining = _get(self.client, self.config, '/api/v1/portal/services')
        if {r['id'] for r in remaining} & {s['id'] for s in self.state['services'].values()}:
            raise SimulationError('Owned catalog cleanup was not verified')


def _serial(value):
    if isinstance(value, datetime): return value.isoformat(' ')
    if isinstance(value, list): return [_serial(x) for x in value]
    if isinstance(value, dict): return {k: _serial(v) for k, v in value.items()}
    return value


def _visit(rows, config, services, keys, technicians):
    try:
        if technicians == 1 and keys == ['oil', 'second'] and len(rows) == 1:
            return _combined_visit(rows[0], config, services)
        expected = {services[k]['name']: services[k]['duration_minutes'] for k in keys}
        if len(rows) != len(keys) or {r['service_type'] for r in rows} != set(expected): return False
        groups = {r['visit_group_id'] for r in rows}
        if len(groups) != 1 or not next(iter(groups)) or len({r['staff_agent_id'] for r in rows}) != technicians: return False
        ordered = sorted(rows, key=lambda r: _dt(r['starts_at'], config))
        previous = None
        for row in ordered:
            start, end = _dt(row['starts_at'], config), _dt(row['ends_at'], config)
            duration = expected[row['service_type']]
            if (not row['reservation_id'] or row['reservation_status'] != 'ACTIVE' or not row['qualified']
                    or row['staff_agent_id'] not in config['deployed_medium']['technician_ids']
                    or row['duration_minutes'] != duration or end-start != timedelta(minutes=duration)
                    or row['segment_count'] != duration // 15 or (previous is not None and start != previous)):
                return False
            previous = end
        return True
    except (KeyError, ValueError, TypeError):
        return False


def _reservation(row, config, services, *, combined=False):
    if combined and _combined_name(row.get('service_type'), services):
        return _combined_visit(row, config, services)
    try:
        expected = next(s['duration_minutes'] for s in services.values() if s['name'] == row['service_type'])
        start, end = _dt(row['starts_at'], config), _dt(row['ends_at'], config)
        return (bool(row['reservation_id']) and row['reservation_status'] == 'ACTIVE' and row['qualified']
                and row['staff_agent_id'] in config['deployed_medium']['technician_ids']
                and row['duration_minutes'] == expected and end-start == timedelta(minutes=expected)
                and start == _dt(row['booking_time'], config) and row['segment_count'] == expected // 15)
    except (KeyError, ValueError, TypeError, StopIteration):
        return False


def _combined_name(name, services):
    oil, second = services['oil']['name'], services['second']['name']
    return name in (oil + ', ' + second, second + ', ' + oil)


def _combined_visit(row, config, services):
    try:
        duration = services['oil']['duration_minutes'] + services['second']['duration_minutes']
        names = {services['oil']['name'], services['second']['name']}
        return (_combined_name(row['service_type'], services)
                and names <= set(row['qualified_service_names'])
                and row['staff_agent_id'] == config['deployed_medium']['technician_ids'][0]
                and bool(row['reservation_id']) and row['reservation_status'] == 'ACTIVE'
                and row['duration_minutes'] == duration and row['segment_count'] == duration // 15
                and [_dt(segment, config) for segment in row['reservation_segments']] == [_dt(row['starts_at'], config) + timedelta(minutes=offset) for offset in range(0, duration, 15)]
                and _dt(row['ends_at'], config) - _dt(row['starts_at'], config) == timedelta(minutes=duration)
                and _dt(row['starts_at'], config) == _dt(row['booking_time'], config))
    except (KeyError, TypeError, ValueError):
        return False
