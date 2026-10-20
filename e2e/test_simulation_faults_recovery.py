"""Committed native control responses lost at the HTTP transport boundary."""
import json
from types import SimpleNamespace

import httpx
import pytest

from live_simulations import deployed_full_faults as adapter_faults
from live_simulations.core import SimulationError

BASE=adapter_faults.BASE


def control_adapter(api,db,scenario,tmp_path,monkeypatch):
    from serviceBot.api import portal
    monkeypatch.setenv('SIMULATION_FAULTS_ENABLED','true')
    monkeypatch.setenv('SIMULATION_FAULT_TECHNICIAN_IDS','1')
    monkeypatch.setenv('SIMULATION_FAULT_PHONE_NUMBERS','+15550100001')
    monkeypatch.setenv('CRON_SECRET','e2e-only-cron-secret')
    monkeypatch.setenv('FAULT_RECOVERY_AUTH','e2e-only-cron-secret')
    monkeypatch.setattr(portal,'sync_services_to_kb',lambda:None)
    monkeypatch.setattr(adapter_faults.medium,'_read',lambda config,query,params=():db(query,params))
    calls=[];lose=set()
    def request(request):
        calls.append((request.method,request.url.path))
        response=api.request(request.method,request.url.raw_path.decode(),headers=dict(request.headers),content=request.content)
        if (request.method,request.url.path) in lose:
            lose.remove((request.method,request.url.path))
            assert response.is_success,response.text
            raise httpx.ReadTimeout('committed private lost response')
        return httpx.Response(response.status_code,content=response.content,headers={'content-type':'application/json'})
    value=SimpleNamespace(config={'deployed_url':str(api.base_url).rstrip('/'),
        'secrets':{'simulation_faults_cron_secret':'FAULT_RECOVERY_AUTH'},
        'deployed_medium':{'technician_ids':[1]},'app_config':{'business_timezone':'America/New_York'}},
        state={'operations':[],'services':{}},campaign=SimpleNamespace(folder=tmp_path,root=tmp_path,
            manifest={'run_id':'recovery-run','stage_authorization':{'tier':'full'}}),
        original_ids=set(),owned_ids=set(),current_ids=set(),_save=lambda:None)
    def guard():
        if value.state.get('blocked'):raise SimulationError('Fixture mutations blocked')
    value._guard=guard
    value.fault_client=httpx.Client(transport=httpx.MockTransport(request),trust_env=False,follow_redirects=False)
    variables={'customer_phone':'+15550100001','appointment_time':scenario['start'].isoformat()}
    return value,variables,calls,lose


@pytest.mark.parametrize('action',['create','disarm','cleanup'])
def test_committed_control_timeout_recovers_by_authenticated_get_only(api,db,scenario,tmp_path,monkeypatch,action):
    value,variables,calls,lose=control_adapter(api,db,scenario,tmp_path,monkeypatch)
    if action=='create':lose.add(('POST',BASE))
    if action=='create':
        with pytest.raises(SimulationError):adapter_faults.arrange(value,'C35',variables)
    else:
        adapter_faults.arrange(value,'C35',variables)
        handle=value.state['full_faults']['C35']['handle']
        lose.add(('POST',BASE+'/'+handle+'/'+action))
        with pytest.raises(SimulationError):
            adapter_faults._request(value,'C35','POST','/'+handle+'/'+action,body={},action=action)
    assert value.state['blocked'] is True
    before=len(calls)
    result=adapter_faults.reconcile(value,'C35')
    assert result['recovered'] is True and result['case_verified'] is False
    assert all(method=='GET' for method,_ in calls[before:])
    assert value.state['operations'][-1]['status']=='observed'
    assert value.state['blocked'] is False
    assert adapter_faults.recover_control(value,'C35')['recovered'] is True
    assert len([1 for method,path in calls if method=='POST' and path==BASE])==1
    assert 'lease_token' not in json.dumps(value.state)
    assert 'e2e-only-cron-secret' not in json.dumps(value.state)
    assert (tmp_path/'c35-fault-lease.json').stat().st_mode & 0o777==0o600
    assert adapter_faults.cleanup(value,'C35')['cleanup_complete'] is True
    value.fault_client.close()


@pytest.mark.parametrize('change',['unauthorized','wrong_nonce','wrong_run','wrong_mode','wrong_technician',
    'wrong_phone','wrong_time','changed_service','changed_qualification','changed_arguments'])
def test_original_creation_recovery_rejects_adoption_and_changed_ownership(api,db,scenario,tmp_path,monkeypatch,change):
    value,variables,calls,lose=control_adapter(api,db,scenario,tmp_path,monkeypatch)
    lose.add(('POST',BASE))
    with pytest.raises(SimulationError):adapter_faults.arrange(value,'C35',variables)
    record=value.state['full_faults']['C35']
    owned=db("SELECT handle::text,service_id FROM simulation_fault_leases WHERE run_id='recovery-run'")[0]
    nonce=json.loads((tmp_path/'c35-fault-lease.json').read_text())['recovery_nonce']
    headers={'Authorization':'Bearer e2e-only-cron-secret','X-Simulation-Recovery':nonce}
    params=dict(record['expected'])
    if change=='unauthorized':headers['Authorization']='Bearer wrong'
    elif change=='wrong_nonce':headers['X-Simulation-Recovery']='a'*64
    elif change=='wrong_run':params['run_id']='foreign'
    elif change=='wrong_mode':params['mode']='response_loss_once'
    elif change=='wrong_technician':params['technician_id']=2
    elif change=='wrong_phone':params['phone']='+15550100002'
    elif change=='wrong_time':params['booking_time']='2030-01-01T00:00:00'
    elif change=='changed_service':db('UPDATE services SET duration_minutes=90 WHERE id=%s',(owned['service_id'],))
    elif change=='changed_qualification':db('DELETE FROM service_staff_agents WHERE service_id=%s',(owned['service_id'],))
    else:db("UPDATE simulation_fault_leases SET arguments=jsonb_set(arguments,'{phone}','\"+15550100002\"') WHERE handle=%s",(owned['handle'],))
    before=db('SELECT event FROM simulation_fault_journal ORDER BY id')
    response=api.get(BASE+'/recover',params=params,headers=headers)
    assert response.status_code in {403,409},response.text
    assert 'lease_token' not in response.text and nonce not in response.text
    assert db('SELECT event FROM simulation_fault_journal ORDER BY id')==before
    assert db('SELECT count(*) AS count FROM simulation_fault_leases')==[{'count':1}]
    value.fault_client.close()


@pytest.mark.parametrize('other_owner',[None,{'kind':'staff','operation_id':'foreign'}])
def test_fault_recovery_does_not_clear_an_unrelated_global_block(api,db,scenario,tmp_path,monkeypatch,other_owner):
    value,variables,calls,lose=control_adapter(api,db,scenario,tmp_path,monkeypatch)
    lose.add(('POST',BASE))
    with pytest.raises(SimulationError):adapter_faults.arrange(value,'C35',variables)
    if other_owner is None:value.state.pop('blocked_operation_owner')
    else:value.state['blocked_operation_owner']=other_owner
    assert adapter_faults.recover_control(value,'C35')['recovered'] is True
    assert value.state['blocked'] is True
    with pytest.raises(SimulationError):adapter_faults.cleanup(value,'C35')
    value.fault_client.close()


def test_fault_recovery_preserves_other_pending_operation_and_mutation_barrier(api,db,scenario,tmp_path,monkeypatch):
    value,variables,calls,lose=control_adapter(api,db,scenario,tmp_path,monkeypatch)
    lose.add(('POST',BASE))
    with pytest.raises(SimulationError):adapter_faults.arrange(value,'C35',variables)
    other={'kind':'staff','operation_id':'unrelated','status':'unknown'}
    value.state['operations'].append(other)
    assert adapter_faults.recover_control(value,'C35')['recovered'] is True
    assert value.state['operations'][0]['status']=='observed'
    assert value.state['operations'][1]==other and value.state['blocked'] is True
    with pytest.raises(SimulationError):adapter_faults.cleanup(value,'C35')
    value.fault_client.close()


def test_recovery_returns_original_private_lease_without_mutating_server_journal(api,db,scenario,tmp_path,monkeypatch):
    value,variables,calls,lose=control_adapter(api,db,scenario,tmp_path,monkeypatch)
    adapter_faults.arrange(value,'C35',variables)
    private=json.loads((tmp_path/'c35-fault-lease.json').read_text())
    record=value.state['full_faults']['C35']
    headers={'Authorization':'Bearer e2e-only-cron-secret','X-Simulation-Recovery':private['recovery_nonce']}
    before=db('SELECT event FROM simulation_fault_journal ORDER BY id')
    responses=[api.get(BASE+'/recover',params=record['expected'],headers=headers) for _ in range(2)]
    assert all(response.status_code==200 for response in responses)
    assert responses[0].json()==responses[1].json()
    assert responses[0].json()['handle']==record['handle']
    assert responses[0].json()['lease_token']==private['lease_token']
    assert db('SELECT event FROM simulation_fault_journal ORDER BY id')==before
    assert private['lease_token'] not in json.dumps(value.state)
    value.fault_client.close()


def test_uncommitted_control_timeout_stays_blocked_without_replay(api,db,scenario,tmp_path,monkeypatch):
    value,variables,calls,lose=control_adapter(api,db,scenario,tmp_path,monkeypatch)
    adapter_faults.arrange(value,'C35',variables)
    handle=value.state['full_faults']['C35']['handle']
    value.fault_client.close();requests=[]
    def no_commit(request):
        requests.append(request.method)
        if request.method=='POST':raise httpx.ReadTimeout('No response; outcome unknown')
        response=api.get(request.url.raw_path.decode(),headers=dict(request.headers))
        return httpx.Response(response.status_code,content=response.content)
    value.fault_client=httpx.Client(transport=httpx.MockTransport(no_commit),trust_env=False,follow_redirects=False)
    with pytest.raises(SimulationError):adapter_faults._request(value,'C35','POST','/'+handle+'/disarm',body={},action='disarm')
    with pytest.raises(SimulationError,match='remains unverified'):adapter_faults.reconcile(value,'C35')
    assert value.state['blocked'] is True and value.state['operations'][-1]['status']=='unknown'
    with pytest.raises(SimulationError):adapter_faults.cleanup(value,'C35')
    assert requests.count('POST')==1
    value.fault_client.close()
