"""Offline fault adapter contracts; captured HTTP never admits native paid work."""
import json
from types import SimpleNamespace

import httpx
import pytest

from live_simulations import deployed_full_faults as faults
from live_simulations.core import SimulationError


def adapter(tmp_path,monkeypatch,handler):
    monkeypatch.setenv('FAULT_TEST_CRON','offline-local-cron')
    client=httpx.Client(transport=httpx.MockTransport(handler),trust_env=False,follow_redirects=False)
    value=SimpleNamespace(config={'deployed_url':'https://native.invalid','secrets':{'simulation_faults_cron_secret':'FAULT_TEST_CRON'},
        'deployed_medium':{'technician_ids':[1,2],'database_env':'TEST_DATABASE_URL'},'app_config':{'business_timezone':'America/New_York'}},
        state={'operations':[],'services':{'oil':{'id':11,'name':'owned oil'}}},
        campaign=SimpleNamespace(folder=tmp_path,root=tmp_path,manifest={'run_id':'fault-run','campaign_agent_id':'owned-clone','invocations':[],'provider_tests':[]}),
        fault_client=client,original_ids={999},owned_ids=set(),current_ids=set(),_guard=lambda:None,_save=lambda:None)
    return value


def test_arrangement_keeps_auth_and_token_private_and_descriptor_has_actual_values(tmp_path,monkeypatch):
    requests=[]
    def response(request):
        requests.append(request)
        if request.method=='GET': return httpx.Response(200,json=capability())
        assert request.headers['authorization']=='Bearer offline-local-cron'
        return httpx.Response(201,json={'success':True,'handle':'00000000-0000-4000-8000-000000000001',
            'lease_token':'private-lease-token','service_id':51,'service_name':'owned fault service','technician_id':1,'mode':'calendar_once'})
    value=adapter(tmp_path,monkeypatch,response)
    values={'customer_phone':'+14242704893','appointment_time':'2030-01-02T10:00:00-05:00'}
    arranged=faults.arrange(value,'C35',values)
    assert arranged['service_name']=='owned fault service'
    target=faults.tool_target_descriptor(value,'C35')
    assert target['url'].endswith('/00000000-0000-4000-8000-000000000001/tool')
    assert target['immutable_arguments']['booking_time']==values['appointment_time']
    assert target['immutable_arguments']['phone']==values['customer_phone']
    assert target['credential_bindings']['authorization_env']=='FAULT_TEST_CRON'
    state=json.dumps(value.state)
    assert 'private-lease-token' not in state and 'offline-local-cron' not in state
    assert (tmp_path/'c35-fault-lease.json').stat().st_mode & 0o777 == 0o600
    with pytest.raises(SimulationError,match='replay|existing|arranged'):
        faults.arrange(value,'C35',values)
    assert len([r for r in requests if r.method=='POST'])==1
    value.fault_client.close()


def test_unknown_creation_is_durably_blocked_and_never_replayed(tmp_path,monkeypatch):
    def lost(request):
        if request.method=='GET': return httpx.Response(200,json=capability())
        raise httpx.ReadTimeout('synthetic lost response')
    value=adapter(tmp_path,monkeypatch,lost)
    values={'customer_phone':'+14242704893','appointment_time':'2030-01-02T10:00:00-05:00'}
    with pytest.raises(SimulationError): faults.arrange(value,'C36',values)
    assert value.state['blocked'] is True
    assert value.state['operations'][0]['status']=='unknown'
    with pytest.raises(SimulationError): faults.arrange(value,'C36',values)
    assert len(value.state['operations'])==1
    value.fault_client.close()


def capability():
    import hashlib
    return {'success':True,'capability':'owned-faults-v1','enabled':True,
        'schema_ready':True,'modes':['calendar_once','response_loss_once'],
        'allowlisted_technician_ids':[1,2],
        'allowlisted_phone_fingerprints':[hashlib.sha256(b'+14242704893').hexdigest()]}


def test_missing_native_capability_blocks_before_any_fixture_mutation(tmp_path,monkeypatch):
    requests=[]
    def unavailable(request):
        requests.append(request)
        if request.method=='GET': return httpx.Response(403,json={'detail':'disabled'})
        return httpx.Response(201,json={'success':True})
    value=adapter(tmp_path,monkeypatch,unavailable)
    with pytest.raises(SimulationError):
        faults.arrange(value,'C35',{'customer_phone':'+14242704893','appointment_time':'2030-01-02T10:00:00-05:00'})
    assert not any(request.method=='POST' for request in requests)
    value.fault_client.close()


def bound_fixture(tmp_path,monkeypatch,cid='C35'):
    row={}
    def respond(request):
        if request.method=='GET' and request.url.path.endswith('/simulation-faults'):
            return httpx.Response(200,json=capability())
        if request.method=='POST':
            return httpx.Response(201,json={'success':True,'handle':'00000000-0000-4000-8000-000000000001',
                'lease_token':'private-lease-token','service_id':51,'service_name':'owned fault service',
                'technician_id':1,'mode':faults.MODES[cid]})
        return httpx.Response(200,json={'success':True,**{key:row[key] for key in ('request_id','reservation_id','outbox_id','tool_payload_hash')},
            'agent_tool_verified':row['tool_payload_hash'] is not None,'lease_reconciliation':True,'core_generic_retry_proven':False})
    value=adapter(tmp_path,monkeypatch,respond)
    variables={'customer_phone':'+14242704893','appointment_time':'2030-01-02T10:00:00-05:00'}
    faults.arrange(value,cid,variables)
    arguments={'phone':variables['customer_phone'],'service_type':'owned fault service',
        'booking_time':variables['appointment_time'],'booking_type':'appointment','customer_consent_obtained':True}
    payload_hash=faults._native_payload_hash({'name':'create_service_request','arguments':arguments})
    row.update(phase='committed',request_id=41,reservation_id=42,outbox_id=43,request_count=1,
        projection_status='FAILED' if cid=='C35' else 'PENDING_CALENDAR',outbox_status='PENDING',attempts=1,
        fault_consumed_at='2030-01-02T15:00:01+00:00' if cid=='C35' else None,
        response_loss_consumed_at='2030-01-02T15:00:01+00:00' if cid=='C36' else None,
        tool_payload_hash=payload_hash,request_status='pending',unsettled_outbox=1)
    monkeypatch.setattr(faults,'_database',lambda *a:dict(row))
    value.campaign.manifest['invocations']=['inv-1']
    value.campaign.manifest['provider_tests']=['test-1']
    (tmp_path/'usage-ledger.json').write_text(json.dumps({'entries':[{'run_id':'fault-run','case_id':cid,
        'invocation_id':'inv-1','test_id':'test-1'}]}))
    faults.bind(value,cid,invocation_id='inv-1',test_id='test-1')
    url=faults.tool_target_descriptor(value,cid)['url']
    call={'tool_name':'create_service_request','type':'webhook','tool_has_been_called':True,
        'request_id':'provider-request-1','params_as_json':json.dumps(arguments),
        'tool_details':{'type':'webhook','method':'POST','url':url}}
    result={'tool_name':'create_service_request','request_id':'provider-request-1','is_error':cid=='C36',
        'result_value':json.dumps({'result':{'success':True,'service_request_id':41}})}
    run={'test_id':'test-1','test_invocation_id':'inv-1','status':'passed',
        'agent_responses':[{'tool_calls':[call],'tool_results':[result]}]}
    observation={'id':'inv-1','agent_id':'owned-clone','cancelled':False,'test_runs':[run]}
    provider=SimpleNamespace(get=lambda invocation:observation,observation=observation)
    return value,row,provider,call


def test_worker_acceptance_requires_actual_failed_then_created_same_binding(tmp_path,monkeypatch):
    value,row,provider,call=bound_fixture(tmp_path,monkeypatch)
    faults.observe(value,'C35')
    assert value.owned_ids=={41} and value.current_ids=={41}
    row.update(projection_status='CREATED',outbox_status='DELIVERED',unsettled_outbox=0)
    assert all(check['passed'] for check in faults.checks(value,'C35',provider=provider))
    call['tool_details']['url']='https://native.invalid/api/v1/voice/tools'
    assert faults.checks(value,'C35',provider=provider)[0]['passed'] is False
    value.fault_client.close()


def test_final_created_and_consumption_journal_do_not_invent_failure_observation(tmp_path,monkeypatch):
    value,row,provider,_call=bound_fixture(tmp_path,monkeypatch)
    row.update(projection_status='CREATED',outbox_status='DELIVERED')
    checks=faults.checks(value,'C35',provider=provider)
    assert checks[-1]['passed'] is False
    value.fault_client.close()


def test_c36_recovery_is_explicit_lease_reconciliation_and_never_rebooks(tmp_path,monkeypatch):
    value,_row,provider,_call=bound_fixture(tmp_path,monkeypatch,'C36')
    assert faults.checks(value,'C36',provider=provider)[-1]['passed'] is False
    result=faults.reconcile(value,'C36')
    assert result['lease_reconciliation'] is True and result['core_generic_retry_proven'] is False
    assert all(check['passed'] for check in faults.checks(value,'C36',provider=provider))
    assert len(value.state['operations'])==1  # Creation only; reconciliation is read-only.
    value.fault_client.close()


def test_operator_execution_cannot_become_actual_model_booking_proof(tmp_path,monkeypatch):
    value,row,provider,_call=bound_fixture(tmp_path,monkeypatch)
    row['tool_payload_hash']=None
    assert faults.checks(value,'C35',provider=provider)[0]['passed'] is False
    value.fault_client.close()


def test_common_ledger_binding_cannot_be_adopted_or_rebound(tmp_path,monkeypatch):
    value,_row,_provider,_call=bound_fixture(tmp_path,monkeypatch)
    with pytest.raises(SimulationError):
        faults.bind(value,'C35',invocation_id='foreign-invocation',test_id='test-1')
    value.fault_client.close()



def test_provider_identity_must_be_the_actual_owned_clone_invocation(tmp_path,monkeypatch):
    value,row,provider,_call=bound_fixture(tmp_path,monkeypatch)
    faults.observe(value,'C35')
    row.update(projection_status='CREATED',outbox_status='DELIVERED')
    provider.observation['agent_id']='foreign-shared-agent'
    assert faults.checks(value,'C35',provider=provider)[0]['passed'] is False
    value.fault_client.close()


def test_cleanup_cancels_only_registered_owned_binding_then_waits_for_provider_retirement(tmp_path,monkeypatch):
    value,row,_provider,_call=bound_fixture(tmp_path,monkeypatch)
    row['service_id']=51
    calls=[]
    def control(request):
        calls.append((request.method,request.url.path))
        if request.method=='GET':
            return httpx.Response(200,json={'success':True,**{key:row[key] for key in ('request_id','reservation_id','outbox_id','tool_payload_hash')}})
        if request.url.path.endswith('/cleanup'):
            assert row['projection_status']=='DELETED' and row['unsettled_outbox']==0
            row.update(phase='cleaned',service_id=None)
            return httpx.Response(200,json={'success':True,'cleanup_complete':True})
        return httpx.Response(200,json={'success':True,'disarmed':True})
    value.fault_client.close()
    value.fault_client=httpx.Client(transport=httpx.MockTransport(control),trust_env=False,follow_redirects=False)
    cancellations=[]
    def cancel(method,path,body):
        cancellations.append(body)
        assert body['arguments']['appointment_id']==41
        row['request_status']='cancelled'
    def settle(ids):
        assert ids=={41}
        row.update(projection_status='DELETED',unsettled_outbox=0)
    value._mutate=cancel
    value._settle_cleanup=settle
    assert faults.cleanup(value,'C35')['cleanup_complete'] is True
    assert len(cancellations)==1 and value.current_ids==set()
    assert value.state['full_faults']['C35']['cleanup_complete'] is True
    value.fault_client.close()


def test_pending_provider_retirement_prevents_lease_catalog_cleanup(tmp_path,monkeypatch):
    value,row,_provider,_call=bound_fixture(tmp_path,monkeypatch)
    value._mutate=lambda *a:row.update(request_status='cancelled')
    value._settle_cleanup=lambda ids:None
    with pytest.raises(SimulationError,match='retirement|delivery'):
        faults.cleanup(value,'C35')
    assert not any(op.get('fault_action')=='cleanup' for op in value.state['operations'])
    value.fault_client.close()
