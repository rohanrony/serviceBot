"""C23 original-intent recovery after a real local HTTP commit loses its response."""
import json
from types import SimpleNamespace

import httpx
import pytest

from live_simulations import deployed_full_negative as negative
from live_simulations.core import SimulationError

BASE='/api/v1/portal/internal/simulation-staff'


def configured(monkeypatch):
    from serviceBot.api import portal
    monkeypatch.setenv('SIMULATION_STAFF_ENABLED','true')
    monkeypatch.setenv('CRON_SECRET','e2e-only-cron-secret')
    monkeypatch.setenv('RECOVERY_TEST_CRON','e2e-only-cron-secret')
    monkeypatch.setattr(portal,'sync_services_to_kb',lambda:None)
    return {'Authorization':'Bearer e2e-only-cron-secret'}


def test_real_committed_create_lost_response_recovers_original_receipt_then_cleans(api,db,tmp_path,monkeypatch):
    configured(monkeypatch)
    requests=[]
    original=[]
    snapshots=[]
    def transport(request):
        path=request.url.path
        requests.append((request.method,path))
        response=api.request(request.method,path,params=request.url.params,content=request.content,
            headers={'Authorization':request.headers['Authorization'],'Content-Type':'application/json'})
        if request.method=='POST' and path==BASE:
            assert response.status_code==201,response.text
            original.append(response.json())
            raise httpx.ReadTimeout('synthetic response lost after actual server commit')
        return httpx.Response(response.status_code,content=response.content)
    state={'operations':[],'blocked':False}
    def guard():
        if state['blocked']: raise SimulationError('Blocked unknown effect')
    with httpx.Client(transport=httpx.MockTransport(transport),trust_env=False,follow_redirects=False) as client:
        adapter=SimpleNamespace(config={'deployed_url':str(api.base_url).rstrip('/'),
            'secrets':{'simulation_staff_cron_secret':'RECOVERY_TEST_CRON'}},state=state,
            campaign=SimpleNamespace(folder=tmp_path,manifest={'run_id':'recovery-run'}),
            simulation_staff_client=client,_guard=guard,_save=lambda:snapshots.append(json.dumps(state)))
        with pytest.raises(SimulationError): negative.create_owned_staff(adapter)
        assert state['blocked'] is True
        assert db('SELECT id FROM staff_agents WHERE id=%s',(original[0]['staff_id'],))==[{'id':original[0]['staff_id']}]
        recovered=negative.recover_owned_staff(adapter)
        assert recovered['id']==original[0]['staff_id'] and recovered['service_id']==original[0]['service_id']
        assert state['blocked'] is False
        artifact=tmp_path/'c23-owned-staff-receipt.json'
        assert json.loads(artifact.read_text())['receipt']==original[0]['receipt']
        assert artifact.stat().st_mode & 0o777==0o600
        assert all(original[0]['receipt'] not in snapshot and 'e2e-only-cron-secret' not in snapshot for snapshot in snapshots)
        assert negative.cleanup_owned_staff(adapter)['success'] is True
    assert len([r for r in requests if r==('POST',BASE)])==1
    assert any(method=='GET' and '/recover/' in path for method,path in requests)
    assert db('SELECT id FROM staff_agents WHERE id=%s',(original[0]['staff_id'],))==[]
    assert db('SELECT id FROM services WHERE id=%s',(original[0]['service_id'],))==[]


def test_original_intent_recovery_auth_cross_run_drift_and_replay(api, db, monkeypatch):
    configured(monkeypatch)
    headers = {'Authorization': 'Bearer e2e-only-cron-secret'}
    intent = 'a' * 32
    body = {'run_id': 'recovery-negative', 'intent_id': intent}
    original = api.post(BASE, json=body, headers=headers).json()
    path = BASE + '/recover/' + body['run_id']
    assert api.get(path, params={'intent_id': intent}).status_code == 403
    assert api.get(path, params={'intent_id': 'b' * 32}, headers=headers).status_code == 409
    assert api.get(BASE + '/recover/foreign', params={'intent_id': intent}, headers=headers).status_code == 409
    assert api.get(path, params={'intent_id': intent}, headers=headers).json() == original
    assert api.get(path, params={'intent_id': intent}, headers=headers).json() == original
    assert api.post(BASE, json=body, headers=headers).status_code == 409
    assert api.post(BASE, json={**body, 'intent_id': 'c' * 32}, headers=headers).status_code == 409
    db('UPDATE staff_agents SET role=%s WHERE id=%s', ('Admin', original['staff_id']))
    assert api.get(path, params={'intent_id': intent}, headers=headers).status_code == 409
    db('UPDATE staff_agents SET role=%s WHERE id=%s', ('Technician', original['staff_id']))
    assert api.post(BASE + '/cleanup', json={'receipt': original['receipt']}, headers=headers).status_code == 200
    assert api.post(BASE, json=body, headers=headers).status_code == 409


def test_real_cleanup_commit_response_loss_recovers_without_repeat(api, db, tmp_path, monkeypatch):
    configured(monkeypatch)
    writes = []
    def transport(request):
        response = api.request(request.method, request.url.path, params=request.url.params,
            content=request.content, headers={'Authorization': request.headers['Authorization'], 'Content-Type': 'application/json'})
        if request.method == 'POST':
            writes.append(request.url.path)
        if request.url.path.endswith('/cleanup'):
            assert response.status_code == 200
            raise httpx.ReadError('synthetic cleanup response loss after native commit')
        return httpx.Response(response.status_code, content=response.content)
    with httpx.Client(transport=httpx.MockTransport(transport), trust_env=False, follow_redirects=False) as client:
        state = {'operations': [], 'blocked': False}
        def guard():
            if state['blocked']:
                raise SimulationError('blocked')
        adapter = SimpleNamespace(config={'deployed_url': str(api.base_url).rstrip('/'),
            'secrets': {'simulation_staff_cron_secret': 'RECOVERY_TEST_CRON'}}, state=state,
            campaign=SimpleNamespace(folder=tmp_path, manifest={'run_id': 'cleanup-recovery'}),
            simulation_staff_client=client, _guard=guard, _save=lambda: None)
        owned = negative.create_owned_staff(adapter)
        with pytest.raises(SimulationError):
            negative.cleanup_owned_staff(adapter)
        assert state['blocked']
        recovered = negative.recover_owned_staff(adapter)
        assert recovered['cleanup_complete'] is True
        assert state['blocked'] is False
        assert db('SELECT id FROM staff_agents WHERE id=%s', (owned['id'],)) == []
        assert writes == [BASE, BASE + '/cleanup']
