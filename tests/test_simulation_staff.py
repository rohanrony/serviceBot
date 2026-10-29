"""Owned C23 lifecycle contracts; synthetic credentials and disposable PostgreSQL."""
import pytest
from psycopg2.extensions import cursor as tuple_cursor

from serviceBot.services import simulation_staff as staff


def test_disabled_missing_secret_and_bad_auth_fail_closed(monkeypatch):
    monkeypatch.delenv('SIMULATION_STAFF_ENABLED', raising=False)
    monkeypatch.setenv('CRON_SECRET', 'synthetic-cron')
    with pytest.raises(staff.LifecycleDenied):
        staff.authorize('Bearer synthetic-cron')
    monkeypatch.setenv('SIMULATION_STAFF_ENABLED', 'true')
    monkeypatch.delenv('CRON_SECRET')
    with pytest.raises(staff.LifecycleDenied):
        staff.authorize('Bearer ')
    monkeypatch.setenv('CRON_SECRET', 'synthetic-cron')
    with pytest.raises(staff.LifecycleDenied):
        staff.authorize('Bearer wrong')
    assert staff.authorize('Bearer synthetic-cron') == 'synthetic-cron'


def test_receipt_cannot_be_modified_or_used_with_other_secret():
    record = {'run_id': 'run-one', 'nonce': 'a' * 32, 'staff_id': 12, 'service_id': 24,
              'staff_snapshot': 'b' * 64, 'service_snapshot': 'c' * 64}
    receipt = staff.sign_receipt(record, 'synthetic-secret')
    assert staff.verify_receipt(receipt, 'synthetic-secret') == record
    with pytest.raises(staff.LifecycleDenied):
        staff.verify_receipt(receipt, 'other-secret')
    with pytest.raises(staff.LifecycleDenied):
        staff.verify_receipt(receipt + '0', 'synthetic-secret')


def test_portal_lifecycle_is_unavailable_without_explicit_auth(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from serviceBot.api.portal import internal_simulation_router, router
    app = FastAPI()
    app.include_router(router)
    app.include_router(internal_simulation_router)
    monkeypatch.setenv('SIMULATION_STAFF_ENABLED', 'true')
    monkeypatch.setenv('CRON_SECRET', 'synthetic-cron')
    with TestClient(app) as client:
        response = client.post('/api/v1/portal/internal/simulation-staff', json={'run_id': 'test-run'})
    assert response.status_code == 403


@pytest.fixture
def db():
    from serviceBot.db.connection import get_db_connection
    with get_db_connection() as conn:
        yield conn


def test_owned_fixture_roundtrip_does_not_adopt_shared_staff(db):
    with db.cursor(cursor_factory=tuple_cursor) as cur:
        cur.execute('SELECT id,name,is_active FROM staff_agents ORDER BY id')
        before = cur.fetchall()
    owned = staff.create(db, 'roundtrip', 'synthetic-secret')
    with db.cursor(cursor_factory=tuple_cursor) as cur:
        cur.execute('SELECT is_active,email,phone_number,google_access_token,google_refresh_token FROM staff_agents WHERE id=%s', (owned['staff_id'],))
        assert cur.fetchone() == (True, None, None, None, None)
        cur.execute('SELECT service_id FROM service_staff_agents WHERE staff_agent_id=%s', (owned['staff_id'],))
        assert cur.fetchall() == [(owned['service_id'],)]
    staff.cleanup(db, owned['receipt'], 'synthetic-secret')
    with db.cursor(cursor_factory=tuple_cursor) as cur:
        cur.execute('SELECT id,name,is_active FROM staff_agents ORDER BY id')
        assert cur.fetchall() == before
        cur.execute('SELECT 1 FROM services WHERE id=%s', (owned['service_id'],))
        assert cur.fetchone() is None


@pytest.mark.parametrize('attachment', ['oauth', 'oauth_state', 'slot', 'other_mapping', 'inline_token', 'future_fk'])
def test_cleanup_refuses_attachments_without_cascading_or_partial_changes(db, attachment):
    owned = staff.create(db, 'refusal-' + attachment, 'synthetic-secret')
    with db.cursor(cursor_factory=tuple_cursor) as cur:
        if attachment == 'oauth':
            cur.execute("INSERT INTO user_google_accounts(agent_id,provider) VALUES (%s,'google')", (owned['staff_id'],))
        elif attachment == 'oauth_state':
            cur.execute("INSERT INTO oauth_states(state,agent_id,action_type) VALUES (%s,%s,'test')", (owned['nonce'], owned['staff_id']))
        elif attachment == 'slot':
            cur.execute("INSERT INTO mock_calendar_slots(staff_agent_id,slot_datetime) VALUES (%s,'2030-01-01 10:00')", (owned['staff_id'],))
        elif attachment == 'other_mapping':
            cur.execute("INSERT INTO services(name) VALUES (%s) RETURNING id", ('other-' + owned['nonce'],))
            cur.execute('INSERT INTO service_staff_agents(service_id,staff_agent_id) VALUES (%s,%s)', (cur.fetchone()[0], owned['staff_id']))
        elif attachment == 'inline_token':
            cur.execute("UPDATE staff_agents SET google_access_token='synthetic' WHERE id=%s", (owned['staff_id'],))
        else:
            cur.execute('CREATE TABLE future_attachment (owner INTEGER REFERENCES staff_agents(id) ON DELETE CASCADE)')
            cur.execute('INSERT INTO future_attachment VALUES (%s)', (owned['staff_id'],))
    db.commit()
    with pytest.raises(staff.LifecycleDenied):
        staff.cleanup(db, owned['receipt'], 'synthetic-secret')
    with db.cursor(cursor_factory=tuple_cursor) as cur:
        cur.execute('SELECT is_active FROM staff_agents WHERE id=%s', (owned['staff_id'],))
        assert cur.fetchone() == (True,)
        cur.execute('SELECT 1 FROM service_staff_agents WHERE service_id=%s AND staff_agent_id=%s', (owned['service_id'], owned['staff_id']))
        assert cur.fetchone() == (1,)
        if attachment == 'future_fk':
            cur.execute('SELECT owner FROM future_attachment')
            assert cur.fetchall() == [(owned['staff_id'],)]
            cur.execute('DROP TABLE future_attachment')
    db.commit()


def test_concurrent_attachment_commits_before_cleanup_check_and_blocks_deletion(db):
    import os
    import threading

    import psycopg2
    owned = staff.create(db, 'race', 'synthetic-secret')
    attached = threading.Event()
    release = threading.Event()
    errors = []

    def attach():
        try:
            with psycopg2.connect(os.environ['TEST_DATABASE_URL']) as other:
                with other.cursor() as cur:
                    cur.execute("INSERT INTO oauth_states(state,agent_id,action_type) VALUES (%s,%s,'test')", (owned['nonce'], owned['staff_id']))
                attached.set()
                assert release.wait(3)
        except Exception as exc:  # noqa: BLE001 - collect every background-thread failure
            errors.append(exc)

    thread = threading.Thread(target=attach)
    thread.start()
    assert attached.wait(3)
    timer = threading.Timer(0.1, release.set)
    timer.start()
    try:
        with pytest.raises(staff.LifecycleDenied):
            staff.cleanup(db, owned['receipt'], 'synthetic-secret')
    finally:
        release.set()
        thread.join(3)
        timer.cancel()
    assert not errors and not thread.is_alive()
    with db.cursor(cursor_factory=tuple_cursor) as cur:
        cur.execute('SELECT agent_id FROM oauth_states WHERE state=%s', (owned['nonce'],))
        assert cur.fetchone() == (owned['staff_id'],)
        cur.execute('SELECT 1 FROM staff_agents WHERE id=%s', (owned['staff_id'],))
        assert cur.fetchone() == (1,)


def test_cleanup_failure_rolls_back_mapping_deletion(db):
    import psycopg2
    owned = staff.create(db, 'rollback', 'synthetic-secret')
    with db.cursor() as cur:
        cur.execute("""CREATE FUNCTION reject_owned_delete() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'synthetic deletion rejection'; END $$""")
        cur.execute('CREATE TRIGGER reject_owned_delete BEFORE DELETE ON staff_agents FOR EACH ROW EXECUTE FUNCTION reject_owned_delete()')
    db.commit()
    try:
        with pytest.raises(psycopg2.Error):
            staff.cleanup(db, owned['receipt'], 'synthetic-secret')
        with db.cursor(cursor_factory=tuple_cursor) as cur:
            cur.execute('SELECT 1 FROM service_staff_agents WHERE service_id=%s AND staff_agent_id=%s', (owned['service_id'], owned['staff_id']))
            assert cur.fetchone() == (1,)
    finally:
        with db.cursor() as cur:
            cur.execute('DROP TRIGGER reject_owned_delete ON staff_agents')
            cur.execute('DROP FUNCTION reject_owned_delete()')
        db.commit()


def test_adapter_lifecycle_journal_excludes_bearer_and_receipt(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace

    import httpx

    from live_simulations import deployed_full_negative as negative
    monkeypatch.setenv('C23_TEST_CRON', 'offline-local-cron-key')
    captured = []
    def respond(request):
        captured.append(request)
        assert request.headers['authorization'] == 'Bearer offline-local-cron-key'
        if request.url.path.endswith('/cleanup'):
            return httpx.Response(200, json={'success': True, 'staff_id': 41, 'service_id': 51})
        return httpx.Response(201, json={'success': True, 'run_id': 'run-test', 'intent_id': json.loads(request.content)['intent_id'], 'nonce': 'a'*32,
            'staff_id': 41, 'service_id': 51, 'name': 'owned-staff', 'service_name': 'owned-service', 'receipt': 'private-receipt'})
    with httpx.Client(transport=httpx.MockTransport(respond), trust_env=False, follow_redirects=False) as client:
        adapter = SimpleNamespace(config={'deployed_url':'https://local.invalid', 'secrets':{'simulation_staff_cron_secret':'C23_TEST_CRON'}},
            state={'operations':[]}, campaign=SimpleNamespace(folder=tmp_path,manifest={'run_id':'run-test'}),
            simulation_staff_client=client, _guard=lambda: None, _save=lambda: None)
        owned = negative.create_owned_staff(adapter)
        assert owned['id'] == 41 and owned['service_id'] == 51
        assert 'private-receipt' not in json.dumps(adapter.state)
        assert 'offline-local-cron-key' not in json.dumps(adapter.state)
        assert negative.cleanup_owned_staff(adapter)['success'] is True
        assert len(captured) == 2
        assert (tmp_path/'c23-owned-staff-receipt.json').stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize('barrier', ['foreign_owner', 'other_unknown', 'no_owner'])
def test_staff_recovery_never_clears_unrelated_barriers(tmp_path, monkeypatch, barrier):
    import json
    from types import SimpleNamespace

    import httpx

    from live_simulations import deployed_full_negative as negative
    from live_simulations.core import fingerprint
    monkeypatch.setenv('C23_RECOVERY_SECRET', 'offline-local-key')
    body = {'run_id': 'blocked-run', 'intent_id': 'a' * 32}
    operation = {'owned_staff_action': 'create', 'status': 'unknown', **body, 'body_fingerprint': fingerprint(body)}
    state = {'operations': [operation], 'blocked': True}
    if barrier != 'no_owner':
        state['blocked_operation_owner'] = negative._staff_owner(operation)
    if barrier == 'foreign_owner':
        state['blocked_operation_owner'] = {'kind': 'fault'}
    if barrier == 'other_unknown':
        state['operations'].append({'action': 'other', 'status': 'unknown'})
    def respond(request):
        assert request.method == 'GET'
        return httpx.Response(200, json={'success': True, **body, 'staff_id': 41, 'service_id': 51,
            'name': 'owned', 'service_name': 'owned-service', 'receipt': 'private-original'})
    with httpx.Client(transport=httpx.MockTransport(respond), trust_env=False, follow_redirects=False) as client:
        adapter = SimpleNamespace(config={'deployed_url': 'https://local.invalid',
            'secrets': {'simulation_staff_cron_secret': 'C23_RECOVERY_SECRET'}}, state=state,
            campaign=SimpleNamespace(folder=tmp_path, manifest={'run_id': body['run_id']}),
            simulation_staff_client=client, _save=lambda: None)
        negative.recover_owned_staff(adapter)
        assert state['blocked'] is True
        assert 'private-original' not in json.dumps(state)
        assert 'synthetic-key' not in json.dumps(state)
        assert operation['status'] == 'observed'


def test_staff_intent_migration_immutable_claims_and_safe_rollback(db):
    import json
    import uuid
    from pathlib import Path

    import psycopg2
    from psycopg2 import sql
    root = Path(__file__).resolve().parents[1] / 'serviceBot' / 'db'
    schema = 'staff_migration_' + uuid.uuid4().hex
    with db.cursor() as cur:
        cur.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
        cur.execute(sql.SQL('SET LOCAL search_path TO {}').format(sql.Identifier(schema)))
        cur.execute('CREATE TABLE staff_agents(id integer PRIMARY KEY); CREATE TABLE services(id integer PRIMARY KEY)')
        cur.execute((root / 'migrations/0011_simulation_staff_intents.sql').read_text())
        response = {'run_id': 'migration', 'intent_id': 'a' * 32, 'staff_id': 1, 'service_id': 2, 'receipt': 'original'}
        cur.execute('INSERT INTO staff_agents VALUES(1); INSERT INTO services VALUES(2)')
        cur.execute('INSERT INTO simulation_staff_intents(run_id,intent_id,original_response,mapping_snapshot) VALUES(%s,%s,%s,%s)',
                    ('migration', 'a' * 32, json.dumps(response), 'b' * 64))
        for statement in ["UPDATE simulation_staff_intents SET original_response='{}'", 'DELETE FROM simulation_staff_intents',
                          (root / 'migrations/0011_simulation_staff_intents.down.sql').read_text()]:
            cur.execute('SAVEPOINT refusal')
            with pytest.raises(psycopg2.Error):
                cur.execute(statement)
            cur.execute('ROLLBACK TO SAVEPOINT refusal')
        cur.execute('DELETE FROM staff_agents; DELETE FROM services')
        cur.execute('UPDATE simulation_staff_intents SET cleanup_complete=TRUE')
        cur.execute((root / 'migration_verification/0011_simulation_staff_intents.sql').read_text())
        assert cur.fetchall() == []
        cur.execute('SAVEPOINT missing_trigger')
        cur.execute('DROP TRIGGER simulation_staff_intents_immutable ON simulation_staff_intents')
        cur.execute((root / 'migration_verification/0011_simulation_staff_intents.sql').read_text())
        assert cur.fetchall(), 'Missing required ownership immutability trigger must fail verification'
        cur.execute('ROLLBACK TO SAVEPOINT missing_trigger')
        cur.execute((root / 'migrations/0011_simulation_staff_intents.down.sql').read_text())
        cur.execute((root / 'migrations/0011_simulation_staff_intents.sql').read_text())
        cur.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
    db.rollback()


@pytest.mark.parametrize('owner_change,expected', [({}, True), ({'kind': 'fault'}, False),
    ({'body_fingerprint': 'foreign'}, False), ({'intent_id': 'b' * 32}, False)])
def test_observed_staff_recovery_pending_requires_exact_block_owner(owner_change, expected):
    from types import SimpleNamespace
    from live_simulations import deployed_full_negative as negative
    operation = {'owned_staff_action': 'create', 'status': 'observed', 'run_id': 'run',
                 'intent_id': 'a' * 32, 'body_fingerprint': 'original'}
    owner = {**negative._staff_owner(operation), **owner_change}
    adapter = SimpleNamespace(state={'operations': [operation], 'blocked': True,
                                     'blocked_operation_owner': owner})
    assert negative.pending_owned_staff_recovery(adapter) is expected


def test_cleanup_refuses_mapping_edit_after_recovery(db):
    owned = staff.create(db, 'mapping-edit-recovery', 'synthetic-secret')
    assert staff.recover(db, owned['run_id'], owned['intent_id'], 'synthetic-secret') == owned
    with db.cursor() as cur:
        cur.execute("UPDATE service_staff_agents SET created_at=created_at+interval '1 second' WHERE service_id=%s", (owned['service_id'],))
    db.commit()
    with pytest.raises(staff.LifecycleDenied):
        staff.cleanup(db, owned['receipt'], 'synthetic-secret')
    with db.cursor() as cur:
        cur.execute('SELECT 1 FROM service_staff_agents WHERE service_id=%s AND staff_agent_id=%s', (owned['service_id'], owned['staff_id']))
        assert cur.fetchone() is not None
