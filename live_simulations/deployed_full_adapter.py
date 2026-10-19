"""Bounded full fixtures over native APIs; observer SQL is SELECT-only.

The inherited ``deployed_medium`` journal/database binding is deliberately reused.
A full_adapter marker prevents adopting a medium catalog as a new full fixture.
No readiness or spending authorization is implied by SUPPORTED_CASE_IDS.
"""
from __future__ import annotations

import copy
import math
import re
from datetime import timedelta
from zoneinfo import ZoneInfo

from . import deployed_full_negative as negative
from . import deployed_full_visits as visits
from . import deployed_medium as medium
from .core import SimulationError
from .evidence import check

SUPPORTED_CASE_IDS = frozenset({'C17', 'C18', 'C19', 'C20', 'C21', 'C22', 'C24', 'C25',
                                'C26', 'C27', 'C28', 'C29', 'C30', 'C31', 'C32', 'C34', 'C46', 'C47', 'C49'})
_NEGATIVE = frozenset({'C17', 'C18', 'C19', 'C20', 'C22', 'C24', 'C46', 'C47', 'C49'})
_FIELDS = ('id', 'status', 'service_type', 'booking_type', 'booking_time',
           'duration_minutes', 'staff_agent_id', 'customer_id', 'reservation_id')


class Adapter(medium.Adapter):
    """Same public lifecycle as medium.Adapter, without medium case fallbacks."""

    def prepare_catalog(self):
        self._guard()
        binding = self.config['deployed_medium']
        owner, services, staff = binding.get('ownership_id'), binding.get('services', {}), binding.get('technician_ids', [])
        if (not isinstance(owner, str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,80}', owner)
                or set(services) != set(medium.KEYS) or len(staff) != 2
                or any(type(i) is not int or i <= 0 for i in staff) or len(set(staff)) != 2):
            raise SimulationError('Full catalog requires unique ownership and two designated technicians')
        for key, duration in (('oil', 60), ('second', 30), ('split', 60)):
            item = services[key]
            if (item.get('id') is not None or not isinstance(item.get('name'), str)
                    or not item['name'].startswith(owner + ' ')
                    or item.get('duration_minutes') != duration
                    or not isinstance(item.get('price_range'), str) or not item['price_range'].strip()):
                raise SimulationError('Full catalog requires wholly owned names and exact 60/30/60 durations')
        if len({s['name'] for s in services.values()}) != 3 or self.state['services']:
            raise SimulationError('Full catalog must be new and distinct')
        existing = medium._get(self.client, self.config, '/api/v1/portal/services')
        if {s['name'] for s in services.values()} & {s['name'] for s in existing}:
            raise SimulationError('Existing catalog cannot become full-test owned')
        self.state['full_adapter'] = True
        self._save()
        for key in medium.KEYS:
            item = services[key]
            agents = [staff[1 if key == 'split' else 0]]
            payload = {k: item[k] for k in ('name', 'duration_minutes', 'price_range')}
            payload.update(description='Owner-designated full simulation ' + owner,
                           req_location=False, agent_ids=agents)
            result = self._mutate('POST', '/api/v1/portal/services', payload)
            if type(result.get('id')) is not int:
                self.state['blocked'] = True
                self._save()
                raise SimulationError('Full catalog creation identity is unknown')
            self.state['services'][key] = dict(item, id=result['id'], assigned_agent_ids=agents)
            self._save()
        self._catalog_readback()

    def _catalog_readback(self):
        actual = {r['id']: r for r in medium._get(self.client, self.config, '/api/v1/portal/services')}
        for item in self.state['services'].values():
            observed = actual.get(item['id'], {})
            agents = observed.get('assigned_agent_ids')
            if (any(observed.get(k) != item[k] for k in ('name', 'duration_minutes', 'price_range'))
                    or not isinstance(agents, list)
                    or sorted(agents) != sorted(item['assigned_agent_ids'])):
                self.state['blocked'] = True
                self._save()
                raise SimulationError('Full catalog native read-back differs')

    def _mapping(self, key, agents):
        self._catalog_readback()
        item = self.state['services'][key]
        payload = {k: item[k] for k in ('name', 'duration_minutes', 'price_range')}
        payload.update(description='Owner-designated full simulation ' + self.config['deployed_medium']['ownership_id'],
                       req_location=False, agent_ids=agents)
        self._mutate('PUT', '/api/v1/portal/services/' + str(item['id']), payload)
        item['assigned_agent_ids'] = list(agents)
        self._save()
        self._catalog_readback()

    def _eligible_agents(self):
        """Untagging opens the service to every active staff recipient."""
        agents = medium._get(self.client, self.config, '/api/v1/portal/agents')
        observed = medium._read(self.config, '''SELECT sa.id,sa.email,sa.phone_number,
            uga.email AS google_email FROM staff_agents sa
            LEFT JOIN user_google_accounts uga ON uga.agent_id=sa.id
            WHERE sa.is_active IS NOT FALSE ORDER BY sa.id''')
        allowed_emails = {str(v).lower() for v in self.config.get('allowlisted_emails', [])}
        allowed_phones = {medium._digits(v) for v in self.config.get('allowlisted_phone_numbers', [])}
        if not agents or {a['id'] for a in agents} != {a['id'] for a in observed}:
            raise SimulationError('Every reachable untagged recipient must be verified')
        for agent in observed:
            if (medium._digits(agent.get('phone_number')) not in allowed_phones
                    or str(agent.get('email', '')).lower() not in allowed_emails
                    or str(agent.get('google_email', '')).lower() not in allowed_emails):
                raise SimulationError('Untagged service has an unallowlisted recipient')
        return sorted(a['id'] for a in observed)

    def _inactive_staff(self):
        binding = self.config['deployed_medium']
        name = binding['ownership_id'] + ' inactive ' + self.campaign.manifest['run_id']
        existing = medium._read(self.config, 'SELECT id FROM staff_agents WHERE name=%s', (name,))
        if existing or self.state.get('full_inactive_staff'):
            raise SimulationError('Existing inactive staff cannot become test-owned')
        phones, emails = self.config.get('allowlisted_phone_numbers', []), self.config.get('allowlisted_emails', [])
        if not phones or not emails:
            raise SimulationError('Inactive fixture requires designated notification destinations')
        result = self._mutate('POST', '/api/v1/portal/agents',
                              {'name': name, 'role': 'Technician', 'email': emails[0], 'phone_number': phones[0]})
        identifier = result.get('id')
        if type(identifier) is not int or identifier in binding['technician_ids']:
            self.state['blocked'] = True
            self._save()
            raise SimulationError('Owned synthetic staff identity is unknown')
        self.state['full_inactive_staff'] = {'id': identifier, 'name': name, 'inactive_verified': False}
        self._save()
        self._verify_staff(identifier, name, True)
        self._mutate('DELETE', '/api/v1/portal/agents/' + str(identifier), {})
        self._verify_staff(identifier, name, False)
        self.state['full_inactive_staff']['inactive_verified'] = True
        self._save()
        return identifier

    def _verify_staff(self, identifier, name, active):
        rows = medium._read(self.config, """SELECT sa.id,sa.name,sa.email,sa.phone_number,sa.is_active,
            (SELECT count(*) FROM service_requests r WHERE r.staff_agent_id=sa.id) AS requests,
            (SELECT count(*) FROM user_google_accounts g WHERE g.agent_id=sa.id) AS oauth
            FROM staff_agents sa WHERE sa.id=%s""", (identifier,))
        if (len(rows) != 1 or rows[0]['name'] != name or rows[0]['is_active'] is not active
                or rows[0]['requests'] or rows[0]['oauth']
                or str(rows[0]['email']).lower() not in {str(v).lower() for v in self.config['allowlisted_emails']}
                or medium._digits(rows[0]['phone_number']) not in {medium._digits(v) for v in self.config['allowlisted_phone_numbers']}):
            self.state['blocked'] = True
            self._save()
            raise SimulationError('Owned inactive staff state cannot be verified safely')

    def _intake_precondition(self, values):
        phone = medium._digits(values['customer_phone'])
        rows = medium._read(self.config, """SELECT c.id,c.name,v.make,v.model,v.year
            FROM customers c LEFT JOIN vehicles v ON v.customer_id=c.id
            WHERE regexp_replace(c.phone,'[^0-9]','','g') IN (%s,%s)""", (phone, '1' + phone))
        identity = medium._identity_id(self.config)
        for row in rows:
            if identity is not None and row['id'] != identity:
                continue
            if row.get('name') != values['customer_name']:
                raise SimulationError('Existing customer name conflicts with full fixture intake')
            if (str(row.get('make', '')).strip().lower() == 'toyota'
                    and str(row.get('model', '')).strip().lower() == 'camry'
                    and row.get('year') != 2021):
                raise SimulationError('Full fixture would mutate an existing vehicle; use a safe owned profile')

    def _policy(self):
        policy = medium._get(self.client, self.config, '/api/v1/portal/config')
        zone = policy.get('business_timezone')
        if not zone or zone != self.config.get('app_config', {}).get('business_timezone'):
            raise SimulationError('Native shop timezone must match the observed business clock')
        days = policy.get('business_days')
        if not isinstance(days, list) or not days or any(type(d) is not int or d not in range(7) for d in days):
            raise SimulationError('Native business days are unavailable')
        start, end = policy.get('business_hours_start'), policy.get('business_hours_end')
        if type(start) is not int or type(end) is not int or not 0 <= start < end <= 24:
            raise SimulationError('Native business hours are unavailable')
        return policy

    def _block_interval(self, staff, start, duration):
        end = start + timedelta(minutes=duration)
        original = medium._slots(self.config, staff, start, end)
        expected = [start + timedelta(minutes=m) for m in range(0, duration, 15)]
        if ([medium._dt(r['slot_datetime'], self.config) for r in original] != expected
                or start <= medium._dt(medium._now(self.config), self.config)):
            raise SimulationError('Full block requires exact future native quarter-hour slots')
        for row in original:
            latest = medium._slots(self.config, staff, medium._dt(row['slot_datetime'], self.config),
                                   medium._dt(row['slot_datetime'], self.config) + timedelta(minutes=15))
            if (len(latest) != 1 or medium._serial(latest[0]) != medium._serial(row)
                    or row['is_booked'] or row['reservation_status'] != 'AVAILABLE'
                    or row['service_request_id'] or row['active_reservation']):
                raise SimulationError('Full block refuses changed or reserved native slots')
            block = {'original': medium._serial(row), 'owned': None, 'restored': False}
            self.state['blocks'].append(block)
            self._save()
            self._mutate('PATCH', '/api/v1/portal/calendar/' + str(row['id']), {'is_booked': True})
            current = medium._slots(self.config, staff, medium._dt(row['slot_datetime'], self.config),
                                    medium._dt(row['slot_datetime'], self.config) + timedelta(minutes=15))
            if (len(current) != 1 or current[0]['reservation_status'] != 'BLOCKED'
                    or not current[0]['is_booked'] or current[0]['active_reservation'] or current[0]['service_request_id']):
                self.state['blocked'] = True
                self._save()
                raise SimulationError('Full native block cannot be verified')
            block['owned'] = medium._serial(current[0])
            self._save()

    def _available(self, when):
        response = self.client.post(self.config['deployed_url'].rstrip('/') + '/api/v1/voice/tools',
            json={'name': 'check_availability', 'arguments': {
                'service_type': self.state['services']['oil']['name'], 'booking_type': 'appointment',
                'preferred_date': when.date().isoformat(), 'preferred_time': when.strftime('%I:%M %p')}}, timeout=10)
        try:
            response.raise_for_status()
            result = response.json()['result']
            if result.get('success') is not True or not isinstance(result.get('available_slots'), list):
                raise ValueError
            return when in {medium._dt(v, self.config) for v in result['available_slots']}
        except (ValueError, TypeError, KeyError):
            raise SimulationError('Native Google busy availability is unknown') from None

    def _poll_available(self, when, expected):
        timeout = self.config.get('deployed_full_google', {}).get('availability_timeout_seconds', 120)
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0 < timeout <= 180:
            raise SimulationError('Google busy availability timeout must be bounded to 180 seconds')
        deadline = medium._monotonic() + timeout
        while True:
            if self._available(when) is expected:
                return
            if medium._monotonic() >= deadline:
                raise SimulationError('Native Google busy availability did not settle; no paid case permitted')
            medium._sleep(.5)

    def _google_busy_arrange(self, values):
        from .deployed_full_google import GoogleBusy
        policy = self._policy()
        when = medium._dt(values['appointment_time'], self.config)
        now = medium._dt(medium._now(self.config), self.config)
        lead = policy.get('min_booking_buffer_hours')
        opening = when.replace(hour=policy['business_hours_start'], minute=0, second=0, microsecond=0)
        closing = when.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(hours=policy['business_hours_end'])
        if (when.weekday() not in policy['business_days'] or when.minute % 15 or when.second or when.microsecond
                or not isinstance(lead, (int, float)) or isinstance(lead, bool) or lead < 0
                or when <= now or when < now + timedelta(hours=lead)
                or not opening <= when < when + timedelta(hours=1) <= closing):
            raise SimulationError('Google busy requires a future open sixty-minute interval beyond native lead time')
        if not self._available(when):
            raise SimulationError('Google busy target must be natively free before the owned event')
        zone = ZoneInfo(policy['business_timezone'])
        busy = GoogleBusy(self, getattr(self, 'google_client', self.client))
        busy.prepare(when.replace(tzinfo=zone), (when + timedelta(hours=1)).replace(tzinfo=zone))
        self.state['full_google_target'] = when.isoformat()
        self._save()
        self._poll_available(when, False)
        self.state['full_google_busy']['availability_proof'] = 'native_free_then_excluded'
        self._save()

    def _callback_visit_available(self, when):
        response = self.client.post(self.config['deployed_url'].rstrip('/') + '/api/v1/voice/tools',
            json={'name': 'check_availability', 'arguments': {
                'services': [self.state['services'][key]['name'] for key in ('oil', 'split')],
                'booking_type': 'callback', 'preferred_date': when.date().isoformat(),
                'preferred_time': when.strftime('%I:%M %p')}}, timeout=10)
        if response.status_code != 200:
            raise SimulationError('Native specialist callback availability is unknown')
        try:
            result = response.json()['result']
            if result.get('success') is not True or not isinstance(result.get('available_slots'), list):
                raise ValueError
            return when in {medium._dt(value, self.config) for value in result['available_slots']}
        except (ValueError, TypeError, KeyError):
            raise SimulationError('Native specialist callback availability is unknown') from None

    def _callback_visit_prerequisites(self, values):
        policy = self._policy()
        when = medium._dt(values['callback_time'], self.config)
        now = medium._dt(medium._now(self.config), self.config)
        lead = policy.get('min_callback_buffer_hours')
        opening = when.replace(hour=policy['business_hours_start'], minute=0, second=0, microsecond=0)
        closing = when.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(hours=policy['business_hours_end'])
        if (not isinstance(lead, (int, float)) or isinstance(lead, bool) or not math.isfinite(lead) or lead < 0
                or when.weekday() not in policy['business_days'] or when.minute % 15 or when.second or when.microsecond
                or when <= now or when < now + timedelta(hours=lead)
                or not opening <= when < when + timedelta(minutes=45) <= closing):
            raise SimulationError('Specialist callbacks require future native business hours and callback lead time')
        if not self._callback_visit_available(when):
            raise SimulationError('Both exact qualified callback slots must be natively available')
        return when

    def arrange(self, case, values):
        self._guard()
        cid = case['id']
        if cid == 'C23':
            raise SimulationError(negative.C23_SETUP_BLOCKER)
        if cid not in SUPPORTED_CASE_IDS:
            raise SimulationError('Full-native case is unsupported: ' + cid)
        if (not self.state.get('full_adapter') or set(self.state['services']) != set(medium.KEYS)
                or self.current_ids or any(not b['restored'] for b in self.state['blocks'])
                or self.state.get('mapping_restore')
                or (self.state.get('full_google_busy') and self.state['full_google_busy'].get('status') != 'deleted')):
            raise SimulationError('Full catalog must be prepared and prior case cleaned')
        self._catalog_readback()
        self.current_case = cid
        self.state['current_case'] = cid
        self.state['full_baseline'] = medium._serial(medium._request_rows(self.config, self.original_ids))
        observed_baseline = {r['id']: r for r in self.state['full_baseline']}
        if set(observed_baseline) != self.original_ids:
            raise SimulationError('Original baseline is unavailable')
        for original in self.campaign.manifest.get('baseline', []):
            if any(str(observed_baseline[original['id']].get(k)) != str(original[k])
                   for k in _FIELDS if k in original):
                raise SimulationError('Original native baseline changed before arrangement')
        if cid not in _NEGATIVE:
            self._intake_precondition(values)
        adapted = copy.deepcopy(case)
        names = {old: self.state['services'][key]['name'] for old, key in
                 [('Oil Change', 'oil'), ('Tire Rotation', 'second'), ('Brake Inspection', 'split')]}
        def replace(value):
            if isinstance(value, str):
                for old, new in names.items(): value = value.replace(old, new)
                return value
            if isinstance(value, list): return [replace(v) for v in value]
            if isinstance(value, dict): return {k: replace(v) for k, v in value.items()}
            return value
        adapted = replace(adapted)
        adapted['success_conditions'] = [v for v in adapted['success_conditions'] if not v.startswith('Before booking, quote catalog facts accurately:')]
        adapted['success_conditions'].append('Use only actual native catalog facts: ' + '; '.join(
            f"{s['name']}: {s['price_range']}, {s['duration_minutes']} minutes" for s in self.state['services'].values()))
        adapted['scenario'] += ' Use only these exact test service names: ' + '; '.join(names.values()) + '. Never modify a pre-existing booking.'
        if cid == 'C47':
            negative.arrange(self, cid, values)
            tool = self.state['full_negative_cases'][cid]['capability']['tool_name']
            adapted['expected_tools'] = list(dict.fromkeys([*adapted['expected_tools'], tool]))
            adapted['success_conditions'].append('The actual native handoff response is unavailable, no transfer completed, and callback remains declined.')
        if cid in {'C17','C18','C19','C20','C21','C46','C49'}:
            policy = self._policy()
            now = medium._dt(medium._now(self.config), self.config)
            if cid in {'C17', 'C18'}:
                target = now + timedelta(minutes=10)
                opening = now.replace(hour=policy['business_hours_start'], minute=0, second=0, microsecond=0)
                closing = opening.replace(hour=0) + timedelta(hours=policy['business_hours_end'])
                buffer = policy.get('min_callback_buffer_hours' if cid == 'C18' else 'min_booking_buffer_hours')
                if (now.weekday() not in policy['business_days'] or not opening <= now < target < closing
                        or not isinstance(buffer, (int, float)) or buffer <= 1/6):
                    raise SimulationError('Lead-time scenario requires a live business window and violating buffer')
                adapted['scenario'] += ' Request exactly ' + target.isoformat() + ' in shop timezone ' + policy['business_timezone'] + '.'
                self.state['full_temporal_target'] = target.isoformat()
            elif cid == 'C19':
                dates = [now.date()+timedelta(days=i) for i in range(1,15)
                         if (now.date()+timedelta(days=i)).weekday() not in policy['business_days']]
                if not dates: raise SimulationError('Native shop has no closed day')
                adapted['scenario'] = adapted['scenario'].replace('{{closed_date}}', dates[0].isoformat())
            elif cid in {'C20', 'C49'}:
                day = medium._dt(values['appointment_time'], self.config)
                if day.weekday() not in policy['business_days']:
                    raise SimulationError('Closing boundary requires an otherwise open date')
                closing = day.replace(hour=0, minute=0, second=0) + timedelta(hours=policy['business_hours_end'])
                target = closing - timedelta(minutes=30) if cid == 'C20' else closing + timedelta(minutes=15)
                if target <= now: raise SimulationError('Closing boundary must be in the future')
                adapted['scenario'] = adapted['scenario'].replace('{{closing_time}}', target.isoformat())
                adapted['scenario'] += ' Request ' + self.state['services']['oil']['name'] + ' and ' + self.state['services']['second']['name'] + ' at exactly ' + target.isoformat() + '.'
            elif cid == 'C46':
                adapted['success_conditions'].append('Native shop hours: weekdays ' + str(policy['business_days'])
                    + ', opening hour ' + str(policy['business_hours_start']) + ', closing hour '
                    + str(policy['business_hours_end']) + ' in ' + policy['business_timezone'] + '.')
            else:
                initial_zone = 'America/New_York' if policy['business_timezone'] == 'UTC' else 'UTC'
                adapted['scenario'] += ' Initially mention ' + initial_zone + ', then explicitly confirm ' + values['appointment_time'] + ' in ' + policy['business_timezone'] + '.'
        if cid == 'C22':
            self._google_busy_arrange(values)
        if cid == 'C31':
            callback = self._callback_visit_prerequisites(values)
            adapted['scenario'] += ' Confirm exactly two separate 15-minute callbacks: ' + self.state['services']['oil']['name'] + ' at ' + callback.isoformat() + ', then ' + self.state['services']['split']['name'] + ' at ' + (callback + timedelta(minutes=30)).isoformat() + ' in shop timezone ' + self.config['app_config']['business_timezone'] + '. Keep the 15-minute gap between callbacks; do not create an in-shop appointment.'
        if cid in {'C26', 'C32'}:
            self.state['full_eligible_agents'] = self._eligible_agents()
        if cid == 'C32':
            marker = self.config['deployed_medium']['ownership_id'] + ' custom issue ' + self.campaign.manifest['run_id']
            self.state['full_callback_issue'] = marker
            adapted['scenario'] += ' For the separate uncataloged callback, describe this exact issue verbatim: ' + marker + '. Do not describe it as a catalog service.'
        if cid == 'C26':
            self.state['mapping_restore'] = {'key': 'second', 'agents': list(self.state['services']['second']['assigned_agent_ids'])}
            self._save()
            self._mapping('second', [])
        if cid == 'C27':
            inactive = self._inactive_staff()
            self.state['mapping_restore'] = {'key': 'oil', 'agents': list(self.state['services']['oil']['assigned_agent_ids'])}
            self._save()
            self._mapping('oil', self.state['mapping_restore']['agents'] + [inactive])
        if cid == 'C30':
            rows = self._create(values, ['oil', 'split'], values['appointment_time'])
            if not medium._visit(rows, self.config, self.state['services'], ['oil', 'split'], 2):
                raise SimulationError('Selective removal requires a complete owned two-specialist visit')
            self.state['full_fixture_components'] = copy.deepcopy(visits.components(self, self.current_ids))
            for row in rows:
                key = 'oil' if row['service_type'] == self.state['services']['oil']['name'] else 'split'
                expected = [{'name': self.state['services'][key]['name'], 'duration_minutes': self.state['services'][key]['duration_minutes']}]
                if not visits.exact_reservation(row, self.state['full_fixture_components'][row['id']], expected,
                        self.config['deployed_medium']['technician_ids'][0 if key == 'oil' else 1], self.config):
                    raise SimulationError('Selective fixture component metadata is unavailable or inconsistent')
            self._settle_fixture_projections()
            oil = next(r for r in rows if r['service_type'] == self.state['services']['oil']['name'])
            adapted['scenario'] += ' Remove only the exact service ' + oil['service_type'] + ' from appointment ID ' + str(oil['id']) + ' after consent. Do not cancel the linked visit.'
        if cid in {'C28', 'C29'}:
            self._create(values, ['oil'], values['appointment_time'])
        if cid in {'C24', 'C29'}:
            start = medium._dt(values['appointment_time'], self.config) + timedelta(minutes=60)
            staff = self.config['deployed_medium']['technician_ids'][1 if cid == 'C24' else 0]
            self._block_interval(staff, start, 60 if cid == 'C24' else 30)
        self.before_rows = medium._serial(medium._request_rows(self.config, self.current_ids))
        self.state['fixture_rows'] = self.before_rows
        self._save()
        return adapted, sorted(self.current_ids)

    def _register(self, ids, values, *, callback=False, combined=False):
        if callback:
            rows = medium._request_rows(self.config, ids)
            marker = self.state.get('full_callback_issue')
            for row in rows:
                if row.get('booking_type') == 'callback' and (
                        not marker or marker not in str(row.get('issue_description', ''))):
                    raise SimulationError('The exact run-owned callback issue is required')
        return super()._register(ids, values, callback=callback, combined=combined)

    def checks(self, case, values, before, after):
        cid = case['id']
        if cid not in SUPPORTED_CASE_IDS or self.current_case != cid:
            raise SimulationError('Full-native case is unsupported or was not arranged')
        self._catalog_readback()
        ids = {r['id'] for r in after}
        rows = self._register(ids, values, callback=cid == 'C32', combined=cid in {'C25', 'C28'})
        baseline = medium._serial(medium._request_rows(self.config, self.original_ids))
        checks = [check('original native bookings preserved', baseline == self.state['full_baseline'])]
        if cid in _NEGATIVE:
            return checks + [check('zero new native requests or reservations', not rows and not ids)] + (
                negative.checks(self, cid) if cid == 'C47' else [])
        active = [r for r in rows if r['status'] != 'cancelled']
        if cid == 'C30':
            return checks + self._selective_removal_checks(values, rows)
        expected_count = 2 if cid in {'C25', 'C31', 'C32'} else 1
        checks += [check('exact owned native request count', len(rows) == expected_count and len(active) == len(rows)),
                   check('owned vehicle intake preserved', all(r.get('make') == 'Toyota' and r.get('model') == 'Camry' and r.get('year') == 2021 for r in rows))]
        appointments = [r for r in active if r['booking_type'] == 'appointment']
        if cid == 'C26':
            eligible = self._eligible_agents()
            checks.append(check('untagged active recipient qualification', len(rows) == 1 and rows[0]['staff_agent_id'] in eligible))
            qualified = copy.deepcopy(rows)
            for r in qualified: r['qualified'] = True
            # Untagged assignments may use any verified active staff, not just designated specialists.
            config = copy.deepcopy(self.config)
            config['deployed_medium']['technician_ids'] = eligible
            checks.append(check('untagged exact native reservation', all(medium._reservation(r, config, self.state['services']) for r in qualified)))
        elif cid not in {'C25', 'C31'}:
            checks.append(check('exact authoritative native reservations', all(medium._reservation(r, self.config, self.state['services'], combined=cid == 'C28') for r in appointments)))
        checks.append(check('native Google appointment projections', all(
            r.get('calendar_integration_status') == 'CREATED' and r.get('request_calendar_status') == 'CREATED'
            and bool(r.get('calendar_event_id')) for r in appointments)))
        if cid == 'C25':
            snapshots = visits.components(self, ids)
            effects = medium._effect_rows(self.config, ids)
            checks.append(check('exact two grouped technician appointments with component snapshots',
                visits.grouped_three_service_visit(rows, snapshots, self.config, self.state['services'], values['appointment_time'])))
            checks.append(check('one delivered calendar projection per grouped appointment',
                {r['id'] for r in effects} == ids and all(r['projection_statuses'] == ['DELIVERED'] for r in effects)))
        elif cid in {'C28', 'C29'}:
            checks.append(check('original request identity and start retained', len(rows) == 1 and len(self.before_rows) == 1
                                and rows[0]['id'] == self.before_rows[0]['id']
                                and medium._dt(rows[0]['booking_time'], self.config) == medium._dt(self.before_rows[0]['booking_time'], self.config)))
            if cid == 'C28':
                checks.append(check('combined requested services and duration', len(rows) == 1 and medium._combined_visit(rows[0], self.config, self.state['services'])))
            else:
                fields = _FIELDS + ('starts_at', 'ends_at', 'segment_count', 'reservation_segments', 'visit_group_id', 'issue_description')
                checks.append(check('blocked addition preserves complete original', len(rows) == len(self.before_rows) == 1
                                    and all(medium._serial(rows[0].get(k)) == medium._serial(self.before_rows[0].get(k)) for k in fields)))
        elif cid == 'C31':
            snapshots = visits.components(self, ids)
            effects = medium._effect_rows(self.config, ids)
            checks.append(check('two separate qualified fifteen-minute callbacks with the confirmed gap',
                visits.separated_specialist_callbacks(rows, snapshots, self.config, self.state['services'], values['callback_time'])))
            checks.append(check('one delivered calendar projection per specialist callback',
                {r['id'] for r in effects} == ids and all(r['projection_statuses'] == ['DELIVERED'] for r in effects)))
        elif cid == 'C32':
            eligible = self._eligible_agents()
            callbacks = [r for r in rows if r['booking_type'] == 'callback']
            checks.append(check('distinct exact appointment and custom callback', len(appointments) == len(callbacks) == 1
                                and appointments[0]['service_type'] == self.state['services']['oil']['name']
                                and medium._dt(appointments[0]['booking_time'], self.config) == medium._dt(values['appointment_time'], self.config)
                                and medium._dt(callbacks[0]['booking_time'], self.config) == medium._dt(values['callback_time'], self.config)
                                and callbacks[0]['service_type'] not in {s['name'] for s in self.state['services'].values()}
                                and callbacks[0]['staff_agent_id'] in eligible
                                and callbacks[0]['duration_minutes'] == 15
                                and callbacks[0]['reservation_status'] == 'ACTIVE' and bool(callbacks[0]['reservation_id'])
                                and callbacks[0]['segment_count'] == 1
                                and medium._dt(callbacks[0]['starts_at'], self.config) == medium._dt(values['callback_time'], self.config)
                                and medium._dt(callbacks[0]['ends_at'], self.config) - medium._dt(callbacks[0]['starts_at'], self.config) == timedelta(minutes=15)))
        else:
            if cid == 'C27':
                staff = self.state['full_inactive_staff']
                self._verify_staff(staff['id'], staff['name'], False)
                checks.append(check('inactive synthetic staff excluded', all(r['staff_agent_id'] != staff['id'] for r in rows)))
            key = 'second' if cid == 'C26' else 'oil'
            checks.append(check('exact requested native service and shop time', len(appointments) == 1
                                and appointments[0]['service_type'] == self.state['services'][key]['name']
                                and medium._dt(appointments[0]['booking_time'], self.config) == medium._dt(values['appointment_time'], self.config)))
        return checks

    def _settle_fixture_projections(self):
        timeout = self.config.get('evidence_timeout_seconds', 120)
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0 < timeout <= 3600:
            raise SimulationError('Invalid owned fixture projection timeout')
        deadline = medium._monotonic() + timeout
        while True:
            rows = medium._request_rows(self.config, self.current_ids)
            if {r['id'] for r in rows} != self.current_ids:
                raise SimulationError('Owned selective fixture identities are unavailable')
            if all(r.get('request_calendar_status') == 'CREATED' and r.get('calendar_integration_status') == 'CREATED'
                   and r.get('calendar_event_id') for r in rows):
                effects = medium._effect_rows(self.config, self.current_ids)
                if (len({r['calendar_event_id'] for r in rows}) == len(rows)
                        and {r['id'] for r in effects} == self.current_ids
                        and all(r['projection_statuses'] == ['DELIVERED'] for r in effects)):
                    return rows
            if medium._monotonic() >= deadline:
                raise SimulationError('Owned selective fixture projections must settle before a paid case')
            medium._sleep(.5)

    def _selective_removal_checks(self, values, rows):
        original = {r['service_type']: r for r in self.before_rows}
        oil, split = self.state['services']['oil']['name'], self.state['services']['split']['name']
        ids = {r['id'] for r in rows}
        expected_ids = {r['id'] for r in self.before_rows}
        snapshots = visits.components(self, ids)
        indexed = {r['id']: r for r in rows}
        expected_components = self.state['full_fixture_components']
        # JSON journal keys may become strings after resuming a saved campaign.
        expected_components = {int(key): value for key, value in expected_components.items()}
        if oil not in original or split not in original or ids != expected_ids or len(rows) != 2:
            return [check('exact original selective fixture identities', False)]
        selected, companion = indexed[original[oil]['id']], indexed[original[split]['id']]
        effects = medium._effect_rows(self.config, [selected['id']])
        stable = ('id', 'customer_id', 'customer_phone', 'customer_name', 'make', 'model', 'year',
                  'service_type', 'booking_type', 'booking_time', 'duration_minutes', 'staff_agent_id', 'visit_group_id')
        return [check('exact original selective fixture identities', True),
                check('selected canonical oil service cancelled and capacity released',
                    selected['status'] == 'cancelled' and selected['reservation_id'] is None
                    and selected['service_type'] == oil and selected['staff_agent_id'] == original[oil]['staff_agent_id']
                    and medium._dt(selected['booking_time'], self.config) == medium._dt(original[oil]['booking_time'], self.config)
                    and snapshots[selected['id']] == expected_components[selected['id']]
                    and all(medium._serial(selected.get(k)) == medium._serial(original[oil].get(k)) for k in stable)),
                check('selected projection independently retired', len(effects) == 1 and visits.retired_selected_projection(effects[0])),
                check('companion component appointment and exact original interval preserved',
                    visits.preserved_component_appointment(companion, original[split], snapshots[companion['id']],
                        expected_components[companion['id']], self.config, self.state['services'])
                    and medium._dt(companion['starts_at'], self.config) == medium._dt(values['appointment_time'], self.config) + timedelta(minutes=60)),
                check('companion Google projection remains created', companion.get('calendar_integration_status') == 'CREATED'
                    and companion.get('request_calendar_status') == 'CREATED' and bool(companion.get('calendar_event_id'))
                    and companion['calendar_event_id'] == original[split]['calendar_event_id'])]

    def final_checks(self, case, values, after):
        if case['id'] == 'C47':
            checks = self.checks(case, values, [], after)
            if self.config.get('deployed_medium', {}).get('browser_readback'):
                # A negative case has no new owned rows. Read back the actual
                # original baseline rows rather than passing an empty-row oracle.
                checks.extend(self._browser_checks(case, self.state['full_baseline']))
            return checks
        return self.checks(case, values, [], after) + super().final_checks(case, values, after)

    def _browser_checks_owned(self, case, rows):
        if case['id'] != 'C47':
            return super()._browser_checks_owned(case, rows)
        # The portal table displays issue_description, not service_type. Keep
        # actual baseline IDs/statuses and compare the actual visible field.
        if not rows or any(not isinstance(row.get('issue_description'), str)
                           or not row['issue_description'].strip() for row in rows):
            return [check('C47 nonempty original browser row descriptions', False)]
        visible_rows = copy.deepcopy(rows)
        for row in visible_rows:
            row['service_type'] = row['issue_description']
        return super()._browser_checks_owned(case, visible_rows)

    def cleanup_case(self):
        negative.before_cleanup(self)
        super().cleanup_case()
        if self.state.get('full_google_busy'):
            from .deployed_full_google import GoogleBusy
            GoogleBusy(self, getattr(self, 'google_client', self.client)).cleanup()
            self._poll_available(medium._dt(self.state['full_google_target'], self.config), True)
        restore = self.state.get('mapping_restore')
        if restore:
            self._mapping(restore['key'], restore['agents'])
            self.state.pop('mapping_restore')
            self._save()
        negative.cleanup(self)
        staff = self.state.get('full_inactive_staff')
        if staff:
            self._verify_staff(staff['id'], staff['name'], False)
            staff['cleanup_receipt'] = 'owned inactive staff retained; no requests or OAuth'
            self._save()

    def cleanup_catalog(self):
        if self.state.get('full_unconnected_staff') and not self.state['full_unconnected_staff']['cleanup_complete']:
            raise SimulationError('Owned unconnected technician must be cleaned before catalog deletion')
        if self.state.get('mapping_restore'):
            raise SimulationError('Full catalog mapping must be restored before deletion')
        if self.state.get('full_google_busy', {}).get('status') not in (None, 'deleted'):
            raise SimulationError('Owned Google busy event must be removed before catalog cleanup')
        super().cleanup_catalog()
