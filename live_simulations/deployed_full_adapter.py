"""Bounded full fixtures over native APIs; observer SQL is SELECT-only.

The inherited ``deployed_medium`` journal/database binding is deliberately reused.
A full_adapter marker prevents adopting a medium catalog as a new full fixture.
No readiness or spending authorization is implied by SUPPORTED_CASE_IDS.
"""
from __future__ import annotations

import copy
import json
import math
import re
import time
from datetime import timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from . import deployed_full_causal as causal
from . import deployed_full_conditions as conditions
from . import deployed_full_faults as faults
from . import deployed_full_native as native
from . import deployed_full_negative as negative
from . import deployed_full_provenance as provenance
from . import deployed_full_recovery as recovery
from . import deployed_full_session as session
from . import deployed_full_visits as visits
from . import deployed_medium as medium
from .core import SimulationError, load_catalog, number, secret
from .evidence import check

SUPPORTED_CASE_IDS = frozenset({'C17', 'C18', 'C19', 'C20', 'C21', 'C22', 'C23', 'C24', 'C25',
                                'C26', 'C27', 'C28', 'C29', 'C30', 'C31', 'C32', 'C34', 'C46', 'C47', 'C49'})
SUPPORTED_CASE_IDS = SUPPORTED_CASE_IDS | faults.SUPPORTED_CASE_IDS | conditions.CASES | {'C48','C50'}

_NEGATIVE = frozenset({'C17', 'C18', 'C19', 'C20', 'C22', 'C23', 'C24', 'C46', 'C47', 'C49'})
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
        self.state['full_case_values'] = copy.deepcopy(values)
        if cid in conditions.CASES or cid in {'C48','C50'}:
            previous=medium._read(self.config,'SELECT id FROM service_requests WHERE service_type=ANY(%s) ORDER BY id',
                ([item['name'] for item in self.state['services'].values()],))
            if any(type(row.get('id')) is not int or row['id']<=0 for row in previous):
                raise SimulationError('Full case request baseline contains unknown identities')
            self.state['full_case_request_baseline_ids']=[row['id'] for row in previous]
        self._save()
        if cid in faults.SUPPORTED_CASE_IDS:
            owned = faults.arrange(self,cid,values)
            adapted['scenario'] = adapted['scenario'].replace(names['Oil Change'],owned['service_name'])
            adapted['success_conditions'].append('Use only the exact owned service '+owned['service_name']+'. Obtain explicit consent before the native booking tool.')
            return adapted,[]
        if cid in conditions.CASES:
            self._bridge().arrange_conditions(cid,values)
            return adapted,[]
        if cid == 'C50':
            causal.arrange(self,cid,values)
            return adapted,[]
        if cid == 'C23':
            negative.arrange(self, cid, values)
            owned_name = self.state['full_unconnected_staff']['service_name']
            adapted = {**adapted, 'scenario': adapted['scenario'].replace(names['Oil Change'], owned_name)}
            adapted['success_conditions'].append('Use only the exact owned unavailable service ' + owned_name + '; never book from unknown availability.')
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

    def _bridge(self,provider=None):
        if provider is not None:
            self._full_provider=provider
        bridge=getattr(self,'native_bridge',None)
        if bridge is not None:
            return bridge
        provider=getattr(self,'_full_provider',None)
        if provider is None:
            raise SimulationError('Full native provider reader must be attached before fixture setup')
        options={'google_client':self.client}
        try:
            options['capability_headers']={'Authorization':'Bearer '+secret(self.config,'simulation_staff_cron_secret')}
        except SimulationError:
            pass
        try:
            sid,token=secret(self.config,'twilio_sid'),secret(self.config,'twilio_token')
            options.update(twilio_client=self.client,twilio_account_sid=sid,twilio_auth=(sid,token))
        except SimulationError:
            pass
        self.native_bridge=native.NativeBridge(self,provider,**options)
        return self.native_bridge

    def attach_provider(self,provider):
        self._full_provider=provider

    def bind_invocation(self,case,*,invocation_id,test_id):
        cid=case['id']
        if cid in faults.SUPPORTED_CASE_IDS:
            faults.bind(self,cid,invocation_id=invocation_id,test_id=test_id)
        elif cid in {'C23','C47'}:
            provenance.bind_negative_invocation(self,cid,invocation_id,test_id,self._full_provider)
        else:
            manifest=self.campaign.manifest
            ledger=json.loads((Path(self.campaign.root)/'usage-ledger.json').read_text())
            rows=[e for e in ledger['entries'] if e.get('invocation_id')==invocation_id]
            expected={'run_id':manifest['run_id'],'case_id':cid,'invocation_id':invocation_id,'test_id':test_id}
            if (len(rows)!=1 or any(rows[0].get(k)!=v for k,v in expected.items())
                    or invocation_id not in manifest.get('invocations',[]) or test_id not in manifest.get('provider_tests',[])):
                raise SimulationError('Full invocation must already have exact common ledger ownership')
            saved=self.state.setdefault('full_invocation_bindings',{})
            if saved.get(cid) not in (None,expected):
                raise SimulationError('Full case invocation cannot be rebound')
            saved[cid]=expected
            self._save()

    def prepare_case_agent(self,case,provider):
        self.attach_provider(provider)
        if case['id'] in faults.SUPPORTED_CASE_IDS:
            return provenance.prepare_owned_case_agent(self,case['id'],faults.prepare_case_agent(self,case['id']),provider)
        return None

    def case_dynamic_variables(self,case):
        return provenance.case_dynamic_variables(self,case['id']) if case['id'] in faults.SUPPORTED_CASE_IDS else {}

    def restore_case_agent(self,case,provider):
        if case['id'] in faults.SUPPORTED_CASE_IDS:
            return provenance.restore_owned_case_agent(self,provider)
        return None

    def poll_during_call(self,case,values,provider):
        cid=case['id']
        if cid in faults.SUPPORTED_CASE_IDS:
            row,_=faults.observe(self,cid)
            if cid=='C36' and row.get('response_loss_consumed_at') and not self.state.get('full_faults',{}).get(cid,{}).get('reconciliation'):
                faults.reconcile(self,cid)
        elif cid in conditions.CASES:
            self._discover_condition_rows(values)
            return self._bridge(provider).poll_conditions(cid,values)

    def _discover_condition_rows(self,values):
        identity=medium._identity_id(self.config)
        rows=medium._read(self.config,'SELECT id FROM service_requests WHERE customer_id=%s AND service_type=%s ORDER BY id',
            (identity,self.state['services']['oil']['name']))
        prior=self.state.get('full_case_request_baseline_ids')
        if not isinstance(prior,list):
            raise SimulationError('New owned request discovery requires a pre-submission case baseline')
        ids={r['id'] for r in rows if type(r.get('id')) is int and r['id'] not in self.original_ids and r['id'] not in prior}
        if ids:
            self._register(ids,values)

    def execution_checks(self,case,values,before,after,*,provider):
        cid=case['id']
        self.attach_provider(provider)
        if self.current_case!=cid:
            raise SimulationError('Full case was not arranged')
        original=medium._serial(medium._request_rows(self.config,self.original_ids))
        checks=[check('original native bookings preserved',original==self.state['full_baseline'])]
        if cid in faults.SUPPORTED_CASE_IDS:
            return checks+faults.checks(self,cid,values,before,after,provider=provider)
        if cid in conditions.CASES:
            self._discover_condition_rows(values)
            report=self._bridge(provider).observe_conditions(cid,values)
            return checks+[check('actual native operational condition',report.get('evidence_complete') is True,
                                 report.get('blockers',[]))]
        if cid in {'C23','C47'}:
            ids={r['id'] for r in after}
            rows=self._register(ids,values)
            return checks+[check('zero new native requests or reservations',not rows and not ids)]+negative.checks(self,cid,provider=provider)
        return self.checks(case,values,before,after)

    def execute_c50(self,*,provider,budget,ledger,campaign):
        factory=getattr(self,'native_session_socket_factory',session.native_socket_factory)
        reader=getattr(self,'native_session_credit_reader',session.native_credit_reader)
        if (not callable(factory) or not callable(reader)
                or self.config.get('budget',{}).get('native_session_credit_units_verified') is not True
                or reader is session.unknown_credit_reader):
            raise SimulationError('C50 genuine native session socket or verified credit reader unavailable')
        self.attach_provider(provider)
        values=copy.deepcopy(self.config['variables'])
        values.update(self.state.get('full_case_values',{}))
        case=copy.deepcopy(next(c for c in load_catalog() if c['id']=='C50'))
        self.arrange(case,values)
        estimate=number(self.config['budget'].get('case_estimates',{}).get('C50',self.config['budget'].get('case_upper_estimate')),positive=True)
        when=values.get('appointment_time') or self.config.get('case_bindings',{}).get('C50',{}).get('variables',{}).get('appointment_time')
        if not when:
            raise SimulationError('C50 requires exact intended appointment time before session')
        profiles=medium._read(self.config,'SELECT make,model,year FROM vehicles WHERE customer_id=%s ORDER BY id',
            (medium._identity_id(self.config),))
        matching=[p for p in profiles if p.get('make')=='Toyota' and p.get('model')=='Camry' and p.get('year')==2021]
        if not matching:
            raise SimulationError('C50 actual native fixture vehicle is unavailable; do not invent intake')
        profile=matching[0]
        script=['My name is '+values['customer_name']+'. I am calling from '+values['customer_phone']+'.',
                'Please book '+self.state['services']['oil']['name']+' at '+when+'. My vehicle is a '+str(profile['year'])+' '+profile['make']+' '+profile['model']+'.',
                'I confirm this exact appointment and consent to booking it. Please confirm the saved appointment, then end the conversation.']
        report=session.execute(self,provider=provider,socket_factory=factory,credit_reader=reader,budget=budget,estimate=estimate,script=script)
        self._discover_condition_rows(values)
        rows=medium._request_rows(self.config,self.current_ids)
        expected=self._c48_expected_booking(values)
        conversation=report.get('provider_conversation_id')
        delivery=self._bridge(provider).c50_delivery(expected_booking=expected,
            request_id=rows[0]['id'] if len(rows)==1 else None,conversation_id=conversation)
        booking_checks=self.checks(case,values,[],rows)+super().final_checks(case,values,rows)
        booking_checks.append(check('required native portal readback',any(c.get('name','').startswith('reloaded browser owned row ') and c.get('passed') is True for c in booking_checks)))
        booking_checks.extend(delivery.get('checks',[]))
        full_verified=(report.get('history_verified') is True and delivery.get('evidence_complete') is True
            and all(c['passed'] for c in booking_checks))
        report.update(full_case_verified=full_verified,global_stop=report.get('global_stop') is not False or not full_verified,
                      booking_checks=booking_checks,checks=booking_checks,native_inbox_receiving='unverified')
        self.state['full_c50_report']=report
        self._save()
        return report

    def _owned_test(self,provider,case,values,phase):
        from .deployed import deployed_scenario
        manifest=self.campaign.manifest
        if manifest.get('test_create_pending'):
            raise SimulationError('Previous provider test creation remains unresolved')
        manifest['test_create_pending']='C48:'+phase
        intent={'case_id':'C48','phase':phase,'attempt':1,'repeat':1,'status':'intent'}
        manifest.setdefault('test_creation_intents',[]).append(intent)
        self.campaign.save()
        dynamic={'caller_phone':values['customer_phone'],'customer_phone':values['customer_phone'],'customer_name':values['customer_name'],
                 'run_id':manifest['run_id'],'case_id':'C48'}
        test_id=provider.create(deployed_scenario(case,values),manifest['run_id'],dynamic,self.config['environment'])
        if not isinstance(test_id,str) or not test_id:
            raise SimulationError('C48 provider test identity is unknown')
        intent.update(status='observed',test_id=test_id)
        manifest.setdefault('provider_tests',[]).append(test_id)
        manifest['test_create_pending']=None
        self.campaign.save()
        return {'id':test_id,'type':'simulation','tool_mock_config':{'mocking_strategy':'none','fallback_strategy':'call_real_tool','mocked_tool_ids':[]}}

    def _c48_expected_booking(self,values):
        identity=medium._identity_id(self.config)
        local_start=medium._dt(values['appointment_time'],self.config)
        zone=ZoneInfo(self.config['app_config']['business_timezone'])
        def aware(local):
            first=local.replace(tzinfo=zone,fold=0)
            second=local.replace(tzinfo=zone,fold=1)
            if (first.utcoffset()!=second.utcoffset()
                    or first.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None)!=local):
                raise SimulationError('C48 requires an unambiguous existing business-time slot')
            return first
        start=aware(local_start)
        end=aware(local_start+timedelta(minutes=60))
        if end.astimezone(timezone.utc)-start.astimezone(timezone.utc)!=timedelta(minutes=60):
            raise SimulationError('C48 requires an unambiguous one-hour elapsed business-time slot')
        expected={'customer_id':identity,'staff_agent_id':self.config['deployed_medium']['technician_ids'][0],
            'starts_at':start.isoformat(),'ends_at':end.isoformat(),
            'service_type':self.state['services']['oil']['name'],'duration_minutes':60}
        return expected

    def execute_c48(self,*,provider,budget,ledger,campaign):
        from .deployed import current_remaining
        self.attach_provider(provider)
        values=copy.deepcopy(self.state.get('full_case_values') or self.config['variables'])
        case=copy.deepcopy(next(c for c in load_catalog() if c['id']=='C48'))
        self.arrange(case,values)
        identity=medium._identity_id(self.config)
        if identity is None:
            raise SimulationError('C48 requires independently resolved native customer identity')
        expected=self._c48_expected_booking(values)
        actual=provenance._owned(self,provider)
        resolved=provider.resolve_reference(actual)
        tools=resolved.get('conversation_config',{}).get('agent',{}).get('prompt',{}).get('tools',[])
        bookings=[t for t in tools if t.get('name')=='book_appointment' and t.get('type')=='webhook']
        if len(bookings)!=1 or bookings[0].get('api_schema',{}).get('method')!='POST':
            raise SimulationError('C48 actual owned clone booking tool is unavailable')
        tool_url=bookings[0].get('api_schema',{}).get('url','')
        target,origin=urlsplit(tool_url),urlsplit(self.config['deployed_url'])
        if (target.scheme,target.netloc)!=(origin.scheme,origin.netloc) or target.path!='/api/v1/voice/tools':
            raise SimulationError('C48 actual native booking tool origin differs')
        source_case=copy.deepcopy(case)
        source_case['scenario']='Book '+expected['service_type']+' at {{appointment_time}}. Provide the fixture identity and explicit booking consent. Ask the agent to confirm the saved appointment.'
        source_case['expected_tools']=['book_appointment']
        source_case['success_conditions']=['The exact native appointment is booked after explicit consent.']
        recovery_case=copy.deepcopy(case)
        recovery_case['scenario']='Ask whether the previously interrupted '+expected['service_type']+' at {{appointment_time}} exists. Require a lookup of existing appointments. Do not authorize a new booking or any mutation.'
        source_definition=self._owned_test(provider,source_case,values,'source')
        recovery_definition=self._owned_test(provider,recovery_case,values,'recovery')
        base={'run_id':campaign.manifest['run_id'],'case_id':'C48','attempt':1,'agent_id':campaign.manifest['campaign_agent_id']}
        source_identity=dict(base,test_id=source_definition['id'])
        recovery_identity=dict(base,test_id=recovery_definition['id'])
        hooks=self._bridge(provider).c48_observers(identity=source_identity,expected_booking=expected)
        source_estimate=number(self.config['budget'].get('case_estimates',{}).get('C48',self.config['budget'].get('case_upper_estimate')),positive=True)
        retained={'source_estimate':str(source_estimate),'recovery_estimate':str(number(self.config['budget']['c48_recovery_upper_estimate'],positive=True)),
            'credit_ceiling':str(budget.cap),'remaining':str(current_remaining(self.config,provider))}
        submit=lambda request:provider.run(base['agent_id'],request['tests'][0]['test_id'])
        result=recovery.execute(campaign.root,source={'identity':source_identity,'expected_booking':expected,'test_definition':source_definition,
            'tool_url':tool_url,'budget':retained,'observe_baseline':hooks['observe_baseline'],'submit':submit,'now':time.time},
            recovery={'identity':recovery_identity,'test_definition':recovery_definition,'submit':submit},provider=hooks['provider'],
            observe_booking=hooks['observe_booking'],observe_delivery=hooks['observe_delivery'])
        retained_manifest=json.loads((Path(campaign.folder)/'manifest.json').read_text())
        for key in ('invocations','provider_tests'):
            campaign.manifest[key]=list(dict.fromkeys([*campaign.manifest.get(key,[]),*retained_manifest.get(key,[])]))
        self._discover_condition_rows(values)
        native_rows=medium._request_rows(self.config,self.current_ids)
        native_checks=self.checks(case,values,[],native_rows)+super().final_checks(case,values,native_rows)
        native_checks.append(check('required native portal readback',any(c.get('name','').startswith('reloaded browser owned row ') and c.get('passed') is True for c in native_checks)))
        native_checks.append(check('actual native Google and WhatsApp recovery delivery',result.get('recovery_verified') is True))
        result['checks']=native_checks
        result['full_case_verified']=result.get('recovery_verified') is True and all(c['passed'] for c in native_checks)
        result['global_stop']=result.get('global_stop') is not False or not result['full_case_verified']
        result['native_inbox_receiving']='unverified'
        self.state['full_c48_report']=result
        self._save()
        return result

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
                negative.checks(self, cid) if cid in {'C23', 'C47'} else [])
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
        if case['id'] in faults.SUPPORTED_CASE_IDS or case['id'] in conditions.CASES:
            return self.execution_checks(case,values,[],after,provider=self._full_provider)+super().final_checks(case,values,after)
        if case['id'] in {'C23', 'C47'}:
            provider=getattr(self,'_full_provider',None)
            checks=(self.execution_checks(case,values,[],after,provider=provider) if provider is not None
                    else self.checks(case,values,[],after))
            if self.config.get('deployed_medium', {}).get('browser_readback'):
                # A negative case has no new owned rows. Read back the actual
                # original baseline rows rather than passing an empty-row oracle.
                checks.extend(self._browser_checks(case, self.state['full_baseline']))
            return checks
        return self.checks(case, values, [], after) + super().final_checks(case, values, after)

    def _browser_checks_owned(self, case, rows):
        if case['id'] not in {'C23', 'C47'}:
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
        if self.current_case in faults.SUPPORTED_CASE_IDS:
            faults.cleanup(self,self.current_case)
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


def native_prerequisites(config,client,cases,baseline):
    """Fresh read-only mechanisms and permission checks; no fixture/claim exists.

    Post-call outcomes are deliberately absent: this probe checks whether source
    mechanisms can run now. Unobserved phone/operator/policy/unit gates fail closed.
    """
    reports={case['id']:[check('compiled full native fixture and assertion path',case['id'] in SUPPORTED_CASE_IDS)] for case in cases}
    seed=SimpleNamespace(config=config,client=client,state={'services':{},'operations':[]},_guard=lambda:None,_save=lambda:None,
        campaign=SimpleNamespace(root=Path(config.get('artifact_root','scratch/live-simulations')),
                                 manifest={'run_id':'preflight'}))
    def probe(cids,name,callback):
        try:
            observed=callback()
            good=observed is True
        except Exception:  # noqa: BLE001 - no provider/credential diagnostics cross readiness boundary
            good=False
        for cid in cids:
            if cid in reports:
                reports[cid].append(check(name,good))
    probe(reports,'independent native booking and callback audit schema',lambda:medium._read(config,
        "SELECT to_regclass('appointment_reservations') IS NOT NULL AND to_regclass('outbox_notifications') IS NOT NULL AND to_regclass('authenticated_webhook_ingress') IS NOT NULL AS ready")==[{'ready':True}])
    identity=medium._identity_id(config)
    probe(reports,'exact existing native customer identity',lambda: identity is not None and len(medium._read(config,
        'SELECT id FROM customers WHERE id=%s',(identity,)))==1)
    def staff_control():
        auth=secret(config,'simulation_staff_cron_secret')
        response=client.get(config['deployed_url'].rstrip('/')+'/api/v1/portal/internal/simulation-staff',headers={'Authorization':'Bearer '+auth})
        response.raise_for_status()
        value=response.json()
        return value.get('success') is True and value.get('enabled') is True and value.get('capability')=='owned-staff-v1'
    probe(['C23'],'authenticated deployed owned staff lifecycle capability',staff_control)
    from .deployed_full_google import GoogleBusy
    probe(['C22'],'actual designated Google account and writable calendar identity',lambda:GoogleBusy(seed,client)._identity() is None)
    values=dict(config.get('variables',{}))
    values.update(config.get('case_bindings',{}).get('C35',{}).get('variables',{}))
    for cid in faults.SUPPORTED_CASE_IDS:
        probe([cid],'authenticated deployed native scoped fault controls and allowlists',lambda cid=cid:bool(faults.prerequisites(seed,cid,values)))
    try:
        options={'google_client':client}
        try:
            options['capability_headers']={'Authorization':'Bearer '+secret(config,'simulation_staff_cron_secret')}
        except SimulationError:
            pass
        try:
            sid,token=secret(config,'twilio_sid'),secret(config,'twilio_token')
            options.update(twilio_client=client,twilio_account_sid=sid,twilio_auth=(sid,token))
        except SimulationError:
            pass
        elevenlabs=None
        if 'C50' in reports:
            try:
                from .provider import ElevenLabs
                elevenlabs=ElevenLabs(secret(config,'elevenlabs_key'),client=client)
            except SimulationError:
                pass
        bridge=native.NativeBridge(seed,elevenlabs,**options)
        conditions_report=bridge.preflight([*conditions.CASES,'C48','C50'])
        for cid,report in conditions_report.items():
            if cid in reports:
                reports[cid].append(check('independently observed native operational mechanisms',
                    report.get('source_supported') is True and not report.get('blockers'),report.get('blockers',[])))
    except Exception:  # noqa: BLE001 - fixed diagnostic protects native/provider details
        for cid in [*conditions.CASES,'C48','C50']:
            if cid in reports:
                reports[cid].append(check('native operational permission and policy mechanisms available',False))
    if 'C50' in reports:
        reports['C50'] += [check('compiled genuine provider session socket',callable(session.native_socket_factory)),
            check('native conversation credit reader compiled',callable(session.native_credit_reader))]
    if 'C47' in reports:
        probe(['C47'],'actual resolved handoff capability absence',lambda:bool(negative.handoff_capability(seed)))
    return reports
