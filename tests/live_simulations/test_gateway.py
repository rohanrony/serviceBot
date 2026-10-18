import httpx
from fastapi.testclient import TestClient
from live_simulations.gateway import create_app


def test_gateway_blocks_portal_and_unauthenticated_tools_and_preserves_callback_bytes(tmp_path):
    seen = []
    def forward(request):
        seen.append(request)
        return httpx.Response(200, json={'result': {'success': True}})
    client = httpx.AsyncClient(transport=httpx.MockTransport(forward))
    settings = {'token': 'synthetic-token', 'app_url': 'http://127.0.0.1:8011', 'run_folder': str(tmp_path)}
    with TestClient(create_app(settings, client)) as web:
        assert web.get('/portal/').status_code == 404
        assert web.post('/api/v1/voice/tools', json={'name': 'book_appointment'}).status_code == 403
        assert not seen
        body = b'MessageSid=SM123&MessageStatus=delivered'
        assert web.post('/sms/status', content=body, headers={'Content-Type': 'application/x-www-form-urlencoded',
                        'X-Twilio-Signature': 'provider-signature'}).status_code == 200
        assert seen[0].content == body
        assert seen[0].headers['X-Twilio-Signature'] == 'provider-signature'


def test_gateway_records_real_tool_result_before_controlled_lost_response(tmp_path):
    from live_simulations.core import private_json
    import json
    private_json(tmp_path / 'active-case.json', {'case_id': 'C36', 'lose_after': 'book_appointment'})
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={'result': {'success': True, 'service_request_id': 8}})))
    settings = {'token': 'synthetic-token', 'app_url': 'http://127.0.0.1:8011', 'run_folder': str(tmp_path)}
    with TestClient(create_app(settings, client)) as web:
        response = web.post('/api/v1/voice/tools?name=book_appointment', json={'phone': '2125551234'},
                            headers={'X-Live-Simulation-Token': 'synthetic-token'})
        assert response.status_code == 504
    trace = json.loads((tmp_path / 'trace.jsonl').read_text().splitlines()[0])
    assert trace['response']['result']['service_request_id'] == 8
    assert trace['controlled_fault'] == 'lost_response'
