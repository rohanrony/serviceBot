import json
import httpx
from live_simulations.app_server import record_calendar


def test_native_calendar_observer_records_returned_id_and_owner_without_credentials(tmp_path):
    request = httpx.Request('POST', 'https://www.googleapis.com/calendar/v3/calendars/primary/events',
                            headers={'Authorization': 'Bearer do-not-retain'}, json={'summary': 'Synthetic booking'})
    record_calendar(request, httpx.Response(200, json={'id': 'native-returned-id'}), tmp_path,
                    lambda token: 'system_gmail')
    text = (tmp_path / 'calendar-effects.jsonl').read_text()
    assert 'do-not-retain' not in text
    observed = json.loads(text)
    assert observed['event_id'] == 'native-returned-id'
    assert observed['owner'] == 'system_gmail'


def test_unidentified_calendar_write_remains_an_explicit_cleanup_blocker(tmp_path):
    request = httpx.Request('POST', 'https://www.googleapis.com/calendar/v3/calendars/primary/events', json={})
    record_calendar(request, None, tmp_path, lambda token: 'unknown')
    observed = json.loads((tmp_path / 'calendar-effects.jsonl').read_text())
    assert observed['ambiguous'] is True and observed['event_id'] is None


def test_observer_brackets_real_http_write_and_preserves_response(tmp_path, monkeypatch):
    from live_simulations.app_server import install_observer
    monkeypatch.setattr(httpx.Client, '_send_single_request', httpx.Client._send_single_request)
    monkeypatch.setattr(httpx.AsyncClient, '_send_single_request', httpx.AsyncClient._send_single_request)
    install_observer(tmp_path, lambda token: 'staff:1')
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, stream=httpx.ByteStream(b'{"id":"observed"}')))) as client:
        response = client.post('https://www.googleapis.com/calendar/v3/calendars/primary/events', json={})
    assert response.json() == {'id': 'observed'}
    records = [json.loads(line) for line in (tmp_path / 'calendar-effects.jsonl').read_text().splitlines()]
    assert [r['stage'] for r in records] == ['started', 'finished']
    assert records[0]['operation_id'] == records[1]['operation_id']
