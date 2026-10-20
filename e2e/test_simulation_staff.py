"""Real HTTP C23 lifecycle contracts with disposable PostgreSQL."""


def test_owned_simulation_staff_http_roundtrip_and_refusal(api, db, monkeypatch):
    from serviceBot.api import portal
    monkeypatch.setenv('SIMULATION_STAFF_ENABLED', 'true')
    monkeypatch.setenv('CRON_SECRET', 'e2e-only-cron-secret')
    monkeypatch.setattr(portal, 'sync_services_to_kb', lambda: None)
    path = '/api/v1/portal/internal/simulation-staff'
    headers = {'Authorization': 'Bearer e2e-only-cron-secret'}
    assert api.post(path, json={'run_id': 'http-owned'}).status_code == 403
    response = api.post(path, json={'run_id': 'http-owned'}, headers=headers)
    assert response.status_code == 201
    owned = response.json()
    assert owned['success'] is True
    assert db('SELECT is_active,email,phone_number FROM staff_agents WHERE id=%s', (owned['staff_id'],)) == [
        {'is_active': True, 'email': None, 'phone_number': None}]
    db("INSERT INTO oauth_states(state,agent_id,action_type) VALUES ('http-owned',%s,'test')", (owned['staff_id'],))
    cleanup = {'receipt': owned['receipt']}
    assert api.post(path + '/cleanup', json=cleanup, headers=headers).status_code == 409
    assert db("SELECT agent_id FROM oauth_states WHERE state='http-owned'") == [{'agent_id': owned['staff_id']}]
    db("DELETE FROM oauth_states WHERE state='http-owned'")
    assert api.post(path + '/cleanup', json=cleanup, headers=headers).status_code == 200
    assert db('SELECT id FROM staff_agents WHERE id=%s', (owned['staff_id'],)) == []
    assert db('SELECT id FROM services WHERE id=%s', (owned['service_id'],)) == []
    assert api.post(path + '/cleanup', json=cleanup, headers=headers).status_code == 409
