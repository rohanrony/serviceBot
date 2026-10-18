"""Launch the unchanged app with observational HTTP tracing for owned Google effects.

No response is mocked or rewritten. The observer records IDs returned by actual
calendar mutations, including admin events that the application does not persist.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import unquote

import httpx


def calendar_write(request):
    return (request.url.host in ('www.googleapis.com', 'calendar.googleapis.com')
            and '/calendar/v3/calendars/' in request.url.path
            and request.method in ('POST', 'PATCH', 'PUT', 'DELETE'))


def record_calendar(request, response, folder, identify, *, stage='finished', operation_id=None):
    if not calendar_write(request):
        return
    token = request.headers.get('authorization', '').removeprefix('Bearer ')
    owner = identify(token)
    suffix = request.url.path.split('/calendar/v3/calendars/', 1)[1]
    calendar_id = unquote(suffix.split('/events', 1)[0])
    event_id = suffix.split('/events/', 1)[1] if '/events/' in suffix else None
    if response is not None and response.content:
        try:
            event_id = response.json().get('id', event_id)
        except ValueError:
            pass
    if event_id is None:
        try:
            event_id = json.loads(request.content).get('id')
        except (ValueError, TypeError):
            pass
    try:
        case_id = json.loads((Path(folder) / 'active-case.json').read_text()).get('case_id')
    except (OSError, ValueError):
        case_id = None
    rejected = response is not None and 400 <= response.status_code < 500
    record = {'at': time.time(), 'stage': stage, 'operation_id': operation_id,
              'case_id': case_id, 'owner': owner, 'event_id': event_id, 'calendar_id': calendar_id,
              'method': request.method, 'rejected': rejected,
              'ambiguous': stage == 'finished' and (response is None or response.status_code >= 500),
              'request_fingerprint': hashlib.sha256(request.content).hexdigest()}
    fd = os.open(Path(folder) / 'calendar-effects.jsonl', os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
    try:
        os.write(fd, (json.dumps(record) + '\n').encode())
    finally:
        os.close(fd)


def install_observer(folder, identify):
    original_sync = httpx.Client._send_single_request
    original_async = httpx.AsyncClient._send_single_request

    def observe(request, response, stage, operation_id):
        try:
            record_calendar(request, response, folder, identify, stage=stage, operation_id=operation_id)
        except Exception:
            # Observation failure is durable and makes cleanup/evidence incomplete;
            # it must not change the application's actual provider behavior.
            (Path(folder) / 'calendar-observer-failed').touch(mode=0o600)

    def sync(self, request):
        operation = uuid.uuid4().hex if calendar_write(request) else None
        if operation:
            observe(request, None, 'started', operation)
        try:
            response = original_sync(self, request)
            if calendar_write(request):
                response.read()
        except httpx.TransportError:
            if operation:
                observe(request, None, 'finished', operation)
            raise
        if operation:
            observe(request, response, 'finished', operation)
        return response

    async def asynchronous(self, request):
        operation = uuid.uuid4().hex if calendar_write(request) else None
        if operation:
            observe(request, None, 'started', operation)
        try:
            response = await original_async(self, request)
            if calendar_write(request):
                await response.aread()
        except httpx.TransportError:
            if operation:
                observe(request, None, 'finished', operation)
            raise
        if operation:
            observe(request, response, 'finished', operation)
        return response

    httpx.Client._send_single_request = sync
    httpx.AsyncClient._send_single_request = asynchronous


def main():
    folder = Path(sys.argv[1])
    listener_fd = int(sys.argv[2])
    # The app's legacy argv heuristics must not mistake a harness artifact path
    # (for example pytest-of-user) for a request to use another test database.
    sys.argv = ['live-simulation-app']
    from serviceBot.main import app
    from serviceBot.db.connection import get_db_connection
    from serviceBot.api.portal import load_config
    from serviceBot.services.encryption import decrypt_key

    def identify(token):
        with get_db_connection() as conn, conn.cursor() as cur:
            cur.execute('SELECT agent_id,access_token FROM user_google_accounts')
            for staff, encrypted in cur.fetchall():
                if token and decrypt_key(encrypted) == token:
                    return 'staff:' + str(staff)
        if token and decrypt_key(load_config().get('gmail_access_token', '')) == token:
            return 'system_gmail'
        return 'unknown'

    install_observer(folder, identify)
    import uvicorn
    uvicorn.run(app, fd=listener_fd, access_log=False)


if __name__ == '__main__':
    main()
