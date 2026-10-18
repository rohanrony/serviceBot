"""Tunnel ingress: only tool calls and signed callback routes reach the real app."""
from __future__ import annotations

import hmac
import json
import os
import sys
import time
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from .core import private_json

CALLBACKS = {'/api/v1/telephony/webhook', '/api/v1/telephony/sms/status',
             '/api/v1/telephony/sms/inbound', '/sms/status', '/sms/inbound',
             '/api/v1/telephony/inbound'}
TOOLS = '/api/v1/voice/tools'


def create_app(settings, client=None):
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    folder = Path(settings['run_folder'])
    client = client or httpx.AsyncClient(timeout=35, trust_env=False, follow_redirects=False)

    def record(entry):
        fd = os.open(folder / 'trace.jsonl', os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(fd, (json.dumps(entry, default=str) + '\n').encode())
        finally:
            os.close(fd)

    @app.api_route('/{path:path}', methods=['GET', 'POST'])
    async def forward(request: Request, path: str):
        endpoint = '/' + path
        token = request.headers.get('X-Live-Simulation-Token', '')
        if endpoint == '/__simulation__/health':
            if not hmac.compare_digest(token, settings['token']):
                return Response(status_code=403)
            return {'run_folder': folder.name}
        if endpoint not in CALLBACKS and endpoint != TOOLS:
            return Response(status_code=404)
        if request.method != 'POST':
            return Response(status_code=405)
        if endpoint == TOOLS and not hmac.compare_digest(token, settings['token']):
            return Response(status_code=403)
        body = await request.body()
        if len(body) > 2_000_000:
            return Response(status_code=413)
        try:
            active = json.loads((folder / 'active-case.json').read_text())
        except (OSError, ValueError):
            active = {}
        # No tool may mutate state during a fixture transition or after abort.
        if endpoint == TOOLS and not active.get('case_id'):
            return Response(status_code=503)
        try:
            payload = json.loads(body) if endpoint == TOOLS else {}
        except ValueError:
            return Response(status_code=400)
        name = request.query_params.get('name') or payload.get('name', '')
        entry = {'at': time.time(), 'case_id': active.get('case_id'), 'path': endpoint,
                 'name': name, 'arguments': payload}
        if endpoint == TOOLS and active.get('fail_before') == name:
            result = {'result': {'success': False, 'message': 'Controlled dependency failure; do not claim success.'}}
            record({**entry, 'response': result, 'controlled_fault': 'before_tool'})
            return JSONResponse(result)
        headers = {k: v for k, v in request.headers.items()
                   if k.lower() not in ('content-length', 'connection', 'x-live-simulation-token')}
        # Preserve public Host and signed bytes for Twilio signature verification.
        headers['X-Forwarded-Proto'] = 'https'
        try:
            result = await client.request('POST', settings['app_url'] + endpoint,
                                          params=request.query_params, content=body, headers=headers)
        except httpx.TransportError:
            record({**entry, 'response': {}, 'transport_error': True})
            return Response(status_code=502)
        try:
            data = result.json()
        except ValueError:
            data = {'status_code': result.status_code}
        entry.update(response=data, status_code=result.status_code)
        if endpoint in CALLBACKS and result.is_success:
            from urllib.parse import parse_qs
            entry['callback'] = {k: v[0] for k, v in parse_qs(body.decode(errors='replace')).items()}
            if 'application/json' in request.headers.get('content-type', ''):
                try:
                    entry['callback_json'] = json.loads(body)
                except ValueError:
                    pass
        if endpoint == TOOLS and name in active.get('lose_after', []):
            active.pop('lose_after')
            private_json(folder / 'active-case.json', active)
            record({**entry, 'controlled_fault': 'lost_response'})
            return Response(status_code=504)
        record(entry)
        return Response(result.content, status_code=result.status_code,
                        media_type=result.headers.get('content-type', 'application/json'))

    return app


if __name__ == '__main__':
    import uvicorn
    settings = json.loads(Path(sys.argv[1]).read_text())
    uvicorn.run(create_app(settings), fd=int(sys.argv[2]) if len(sys.argv) > 2 else None,
                host='127.0.0.1', port=settings['port'], access_log=False)
