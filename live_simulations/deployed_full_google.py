"""Journaled owned Google busy event; tokens never enter the persisted journal.

Google API contracts: events.insert (base32hex ID, sendUpdates=none) and
version-resources (ETag with If-Match for conditional DELETE). Credentials are
provided only through an explicitly configured environment variable; no refresh
helper or shared OAuth database mutation is available here.
"""
from __future__ import annotations

import copy
import hashlib
import os
import re
from datetime import datetime
from urllib.parse import quote

from . import deployed_medium as medium
from .core import SimulationError

_ROOT = 'https://www.googleapis.com/calendar/v3/'


class GoogleBusy:
    def __init__(self, adapter, client):
        self.adapter, self.client = adapter, client
        self.config, self.state = adapter.config, adapter.state
        self.binding = self.config.get('deployed_full_google', {})
        owner = self.config.get('deployed_medium', {}).get('ownership_id', '')
        run = adapter.campaign.manifest['run_id']
        self.event_id = hashlib.sha256((owner + ':' + run + ':C22').encode()).hexdigest()[:40]

    def _fail(self, reason, *, blocked=False):
        if blocked:
            self.state['blocked'] = True
            self.adapter._save()
        raise SimulationError(reason) from None

    def _token(self):
        name = self.binding.get('access_token_env')
        if not isinstance(name, str) or not re.fullmatch(r'[A-Z][A-Z0-9_]{2,100}', name):
            self._fail('Google busy access-token environment binding is missing')
        token = os.environ.get(name)
        if not token or '\n' in token or '\r' in token:
            self._fail('Google busy access token is unavailable')
        return token

    def _request(self, method, url, *, body=None, etag=None, mutation=False):
        self.adapter._guard()
        headers = {'Authorization': 'Bearer ' + self._token()}
        if etag is not None:
            headers['If-Match'] = etag
        op = None
        if mutation:
            op = {'method': method, 'event_id': self.event_id, 'status': 'intent'}
            self.state['full_google_busy']['operations'].append(op)
            self.adapter._save()
        try:
            response = self.client.request(method, url, headers=headers, json=body,
                                           params={'sendUpdates': 'none'} if mutation else None,
                                           timeout=10)
            if mutation and response.status_code not in (200, 201, 204, 404, 410):
                raise SimulationError('Google busy mutation was not confirmed')
            if op is not None:
                op['status'] = 'observed'
                op['http_status'] = response.status_code
                self.adapter._save()
            return response
        except Exception:  # noqa: BLE001 - provider errors may contain authorization tokens
            if op is not None:
                op['status'] = 'unknown'
            self._fail('Google busy operation is uncertain; reconcile without retry', blocked=mutation)

    def _json(self, response):
        if response.status_code != 200:
            self._fail('Google busy read or account authorization failed')
        try:
            value = response.json()
            if not isinstance(value, dict): raise TypeError
            return value
        except (ValueError, TypeError):
            self._fail('Google busy read-back is invalid')

    def _url(self):
        calendar = quote(self.binding['calendar_id'], safe='')
        return _ROOT + 'calendars/' + calendar + '/events/' + self.event_id

    def _identity(self):
        binding = self.binding
        staff = self.config.get('deployed_medium', {}).get('technician_ids', [])
        email, calendar = binding.get('account_email'), binding.get('calendar_id')
        if (not staff or binding.get('technician_id') != staff[0] or not isinstance(email, str)
                or not email or not isinstance(calendar, str) or calendar.lower() != email.lower()
                or email.lower() not in {str(v).lower() for v in self.config.get('allowlisted_emails', [])}):
            self._fail('Google busy requires the first designated owned primary calendar account')
        rows = medium._read(self.config, '''SELECT sa.id,sa.email,sa.is_active,
            uga.email AS google_email,uga.granted_scopes FROM staff_agents sa
            JOIN user_google_accounts uga ON uga.agent_id=sa.id WHERE sa.id=%s''', (staff[0],))
        if (len(rows) != 1 or not rows[0]['is_active'] or rows[0]['id'] != staff[0]
                or str(rows[0].get('email', '')).lower() != email.lower()
                or str(rows[0].get('google_email', '')).lower() != email.lower()
                or not {'https://www.googleapis.com/auth/calendar', 'https://www.googleapis.com/auth/calendar.events'}
                .intersection(str(rows[0].get('granted_scopes', '')).split())):
            self._fail('Google busy native account/calendar scope is unverified')
        account = self._json(self._request('GET', 'https://openidconnect.googleapis.com/v1/userinfo'))
        if account.get('email_verified') is not True or str(account.get('email', '')).lower() != email.lower():
            self._fail('Google busy access token belongs to a different or unverified account')
        item = self._json(self._request('GET', _ROOT + 'users/me/calendarList/' + quote(calendar, safe='')))
        if item.get('id') != calendar or item.get('primary') is not True or item.get('accessRole') != 'owner':
            self._fail('Google busy token does not own the exact primary calendar')

    def _matches(self, event, expected):
        try:
            scalars = ('id', 'summary', 'description', 'transparency', 'visibility', 'status', 'extendedProperties', 'reminders')
            return (all(event.get(k) == expected[k] for k in scalars)
                    and not event.get('attendees') and not event.get('recurrence')
                    and all(datetime.fromisoformat(event[k]['dateTime']) ==
                            datetime.fromisoformat(expected[k]['dateTime'])
                            and event[k].get('timeZone') == expected[k]['timeZone'] for k in ('start', 'end')))
        except (KeyError, ValueError, TypeError):
            return False

    def prepare(self, start, end):
        self.adapter._guard()
        if self.state.get('full_google_busy'):
            self._fail('Existing Google busy fixture cannot be adopted or prepared twice')
        self._identity()
        if (not start.tzinfo or not end.tzinfo or (end-start).total_seconds() != 3600
                or medium._dt(start, self.config) <= medium._dt(medium._now(self.config), self.config)):
            self._fail('Google busy requires an exact timezone-aware sixty-minute interval')
        existing = self._request('GET', self._url())
        if existing.status_code != 404:
            self._fail('Google busy deterministic event ID already exists or cannot be verified absent')
        owner = self.config['deployed_medium']['ownership_id']
        run = self.adapter.campaign.manifest['run_id']
        zone = self.config['app_config']['business_timezone']
        body = {'id': self.event_id, 'summary': 'Owned C22 busy ' + owner,
                'description': 'Owner-designated C22 fixture ' + owner + ' run ' + run,
                'start': {'dateTime': start.isoformat(), 'timeZone': zone},
                'end': {'dateTime': end.isoformat(), 'timeZone': zone},
                'transparency': 'opaque', 'visibility': 'private', 'status': 'confirmed',
                'reminders': {'useDefault': False},
                'extendedProperties': {'private': {'owner': owner, 'run_id': run, 'case_id': 'C22'}}}
        record = {'event_id': self.event_id, 'calendar_id': self.binding['calendar_id'],
                  'account_email': self.binding['account_email'], 'technician_id': self.binding['technician_id'],
                  'expected': copy.deepcopy(body), 'operations': [], 'status': 'create_intent'}
        self.state['full_google_busy'] = record
        self.adapter._save()
        response = self._request('POST', self._url().rsplit('/', 1)[0], body=body, mutation=True)
        if response.status_code not in (200, 201):
            self._fail('Google busy creation was not confirmed', blocked=True)
        try:
            observed = self._json(self._request('GET', self._url()))
        except SimulationError:
            self._fail('Google busy creation read-back is unresolved', blocked=True)
        etag = observed.get('etag')
        if not self._matches(observed, body) or not isinstance(etag, str) or not etag.startswith('"') or not etag.endswith('"'):
            self._fail('Google busy owned event read-back differs', blocked=True)
        record.update(etag=etag, status='observed')
        self.adapter._save()

    def cleanup(self):
        self.adapter._guard()
        record = self.state.get('full_google_busy')
        if not record or record.get('status') == 'deleted':
            return
        if (record.get('status') != 'observed' or record.get('event_id') != self.event_id
                or record.get('calendar_id') != self.binding.get('calendar_id')
                or record.get('account_email') != self.binding.get('account_email')):
            self._fail('Google busy cleanup ownership is unresolved', blocked=True)
        try:
            response = self._request('GET', self._url())
        except SimulationError:
            self._fail('Google busy cleanup read is unresolved', blocked=True)
        if response.status_code in (404, 410):
            record['status'] = 'deleted'
            self.adapter._save()
            return
        try:
            current = self._json(response)
        except SimulationError:
            self._fail('Google busy cleanup read is unresolved', blocked=True)
        if not self._matches(current, record['expected']) or current.get('etag') != record['etag']:
            self._fail('Google busy event changed; refuse unsafe cleanup', blocked=True)
        self._request('DELETE', self._url(), etag=record['etag'], mutation=True)
        try:
            removed = self._request('GET', self._url())
            if removed.status_code not in (404, 410):
                value = self._json(removed)
                if value.get('id') != self.event_id or value.get('status') != 'cancelled':
                    raise SimulationError('Deletion not visible')
        except SimulationError:
            self._fail('Google busy deletion read-back is unresolved', blocked=True)
        record['status'] = 'deleted'
        self.adapter._save()
