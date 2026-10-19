"""Native startup path with real HTTP/PostgreSQL and captured embeddings."""
import socket
import threading
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest
import uvicorn

from serviceBot import main
from serviceBot.api import portal
from serviceBot.services.rag import FAQService


@pytest.fixture
def native_catalog_startup(scenario, monkeypatch, db):
    monkeypatch.setattr(main, '_isolated_startup', lambda: False)
    workers = []
    for module, name in (
        ('outbox_worker', 'start_outbox_worker'),
        ('quiet_hours', 'start_quiet_hours_queue_worker'),
        ('sms_reminders', 'start_reminder_polling_worker'),
        ('call_sync', 'start_call_sync_worker'),
    ):
        worker = Mock()
        monkeypatch.setattr(f'serviceBot.services.{module}.{name}', worker)
        workers.append(worker)
    monkeypatch.setattr('serviceBot.services.call_sync.stop_call_sync_worker', lambda: None)
    monkeypatch.delenv('ELEVENLABS_API_KEY', raising=False)
    directory = Path(portal.KB_DIR)
    directory.mkdir(parents=True, exist_ok=True)
    generated = directory / 'auto_services_catalog.txt'
    generated.write_text('STALE EPHEMERAL CATALOG', encoding='utf-8')
    authored = directory / 'authored_policy.txt'
    authored.write_text('Authored warranty policy remains exact.', encoding='utf-8')
    FAQService().index_text(generated.read_text(), generated.name)
    FAQService().index_text(authored.read_text(), authored.name)
    collection = scenario['collection']
    before = dict(collection.entries)
    # Populate enough catalog content to require replacement across many chunks.
    for index in range(45):
        db('INSERT INTO services (name,description,price_range,duration_minutes) VALUES (%s,%s,%s,%s)',
           (f'Restored Service {index:02}', f'Native PostgreSQL description {index}',
            f'${index + 20}-${index + 40}', 15 * (index % 4 + 1)))
    rows = db('SELECT name,description,price_range,duration_minutes FROM services')
    return {'generated': generated, 'authored': authored, 'before': before,
            'collection': collection, 'workers': workers, 'rows': rows}


def test_startup_rebuilds_complete_pg_catalog_before_http_ready(native_catalog_startup, request):
    state = native_catalog_startup
    url = request.getfixturevalue('live_server')
    with httpx.Client(base_url=url, timeout=10, trust_env=False) as client:
        response = client.get('/health')
    assert response.status_code == 200
    assert response.json() == {'status': 'healthy'}
    text = state['generated'].read_text(encoding='utf-8')
    assert 'STALE EPHEMERAL CATALOG' not in text
    assert len(state['rows']) == 46
    for row in state['rows']:
        assert f"## {row['name']}\nDescription: {row['description']}\nPrice Range: {row['price_range']}\nDuration: {row['duration_minutes']} minutes" in text
    entries = state['collection'].entries
    generated_chunks = [doc for doc, metadata in entries.values()
                        if metadata['filename'] == state['generated'].name]
    assert len(generated_chunks) > 1
    indexed = ' '.join(generated_chunks)
    for row in state['rows']:
        assert row['name'] in indexed
        assert row['price_range'] in indexed
        assert f"Duration: {row['duration_minutes']} minutes" in indexed
    assert 'STALE EPHEMERAL CATALOG' not in indexed
    assert state['authored'].read_text() == 'Authored warranty policy remains exact.'
    old_authored = {key: value for key, value in state['before'].items()
                    if value[1]['filename'] == state['authored'].name}
    assert old_authored
    assert {key: entries[key] for key in old_authored} == old_authored
    for worker in state['workers'][:3]:
        worker.assert_called_once()


def test_index_failure_retains_old_artifacts_and_refuses_http_readiness(native_catalog_startup, monkeypatch):
    state = native_catalog_startup
    collection = state['collection']
    add = collection.add
    def failed_embedding(**kwargs):
        add(**kwargs)
        raise RuntimeError('secret embedding provider diagnostic')
    monkeypatch.setattr(collection, 'add', failed_embedding)
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(main.app, host='127.0.0.1', port=port,
                                          log_level='critical', access_log=False))
    startup_exits = []
    def run_server():
        try:
            server.run()
        except SystemExit as error:
            startup_exits.append(error.code)
    thread = threading.Thread(target=run_server, daemon=True)
    thread.start()
    thread.join(timeout=10)
    try:
        assert not thread.is_alive()
        assert not server.started
        assert startup_exits == [3]
        with httpx.Client(timeout=2, trust_env=False) as client, pytest.raises(httpx.ConnectError):
            client.get(f'http://127.0.0.1:{port}/health')
        assert state['generated'].read_text() == 'STALE EPHEMERAL CATALOG'
        assert state['authored'].read_text() == 'Authored warranty policy remains exact.'
        assert collection.entries == state['before']
        assert not list(state['generated'].parent.glob('.auto-services-*.tmp'))
        for worker in state['workers']:
            worker.assert_not_called()
    finally:
        server.should_exit = True
        thread.join(timeout=10)
