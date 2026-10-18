import pytest
from live_simulations.core import SimulationError, private_json
from live_simulations.runtime import database_params, owned_manifest, snapshot_source


@pytest.mark.parametrize('dsn', ['postgresql://remote.invalid/app', 'postgresql://localhost/app?hostaddr=8.8.8.8', 'service=production'])
def test_database_rejects_remote_or_service_redirection(dsn):
    with pytest.raises(SimulationError):
        database_params(dsn)


def test_database_pins_loopback_and_never_uses_supplied_name_as_reset_target():
    params = database_params('postgresql://localhost/configuration_test')
    assert params['hostaddr'] == '127.0.0.1'
    assert params['dbname'] == 'postgres'


def test_cleanup_rejects_forged_manifest_and_traversal(tmp_path):
    for run_id in ('../other', 'not-a-uuid'):
        with pytest.raises(SimulationError):
            owned_manifest(tmp_path, run_id)
    run_id = 'a' * 32
    path = tmp_path / run_id
    private_json(path / 'manifest.json', {'run_id': run_id, 'database': 'production'})
    with pytest.raises(SimulationError):
        owned_manifest(tmp_path, run_id)


def test_snapshot_never_copies_workspace_secrets_or_runtime_config(tmp_path):
    source = tmp_path / 'source'; source.mkdir()
    (source / 'serviceBot').mkdir()
    (source / 'serviceBot' / 'main.py').write_text('app = None')
    (source / 'serviceBot' / 'config.json').write_text('{"secret":"private"}')
    (source / '.env').write_text('DO_NOT_COPY=secret')
    target = tmp_path / 'runtime'
    snapshot_source(source, target)
    assert (target / 'serviceBot' / 'main.py').exists()
    assert not (target / '.env').exists()
    assert not (target / 'serviceBot' / 'config.json').exists()


def test_prepare_creates_marked_disposable_database_and_cleanup_is_idempotent(tmp_path, monkeypatch):
    import os
    from live_simulations.runtime import Runtime
    monkeypatch.setenv('SIMULATION_OFFLINE_DB', os.environ['TEST_DATABASE_URL'])
    config = {'artifact_root': str(tmp_path), 'database_admin_env': 'SIMULATION_OFFLINE_DB',
              'app_port': 18201, 'gateway_port': 18202, 'app_environment': {}}
    runtime = Runtime.prepare(config)
    try:
        runtime.verify_ownership()
        assert runtime.rows('SELECT count(*) FROM service_requests')[0]['count'] == 0
        assert (runtime.folder / 'app/serviceBot/config.json').exists()
        assert runtime.manifest['source_fingerprint']
        assert runtime.manifest['id_base'] >= 8192
        with runtime.connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT nextval('appointment_reservations_id_seq') AS value")
            assert cur.fetchone()['value'] == runtime.manifest['id_base']
    finally:
        runtime.drop_database()
    assert runtime.manifest['cleanup']['database'] == 'removed'


def test_isolated_application_and_gateway_start_without_provider_credentials(tmp_path, monkeypatch):
    import json
    import os
    import socket
    import httpx
    from live_simulations.runtime import Runtime
    monkeypatch.setenv('SIMULATION_OFFLINE_DB', os.environ['TEST_DATABASE_URL'])
    sockets = [socket.socket(), socket.socket()]
    for listener in sockets: listener.bind(('127.0.0.1', 0))
    ports = [listener.getsockname()[1] for listener in sockets]
    for listener in sockets: listener.close()
    runtime = Runtime.prepare({'artifact_root': str(tmp_path), 'database_admin_env': 'SIMULATION_OFFLINE_DB',
                               'app_port': ports[0], 'gateway_port': ports[1], 'app_environment': {}})
    try:
        runtime.start()
        runtime.start_gateway()
        with httpx.Client(trust_env=False) as client:
            assert client.get(runtime.url + '/health').status_code == 200
            response = client.get(runtime.url + '/api/v1/portal/service-requests')
            assert response.status_code == 200
            assert response.json() == []
            assert client.get(runtime.gateway_url + '/api/v1/requests').status_code == 404
            token = json.loads((runtime.folder / 'gateway.json').read_text())['token']
            response = client.get(runtime.gateway_url + '/__simulation__/health',
                                  headers={'X-Live-Simulation-Token': token})
            assert response.json()['run_folder'] == runtime.run_id
        assert runtime.environment()['ELEVENLABS_AGENT_ID'] == ''
        assert 'ELEVENLABS_API_KEY' not in runtime.environment()
    finally:
        runtime.stop()
        runtime.drop_database()


def test_application_database_url_preserves_escaped_credentials_and_pinned_address():
    from psycopg2.extensions import parse_dsn
    from live_simulations.runtime import application_database_url
    params = {'user': 'test user', 'password': 'synthetic@:/?pass', 'host': '::1',
              'hostaddr': '::1', 'port': '5432', 'dbname': 'voice_live_owned_test', 'connect_timeout': '3'}
    value = application_database_url(params)
    assert value.startswith('postgresql://')
    assert parse_dsn(value) == params
