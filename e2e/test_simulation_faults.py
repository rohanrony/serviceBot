"""Actual local native HTTP/worker failures with disposable PostgreSQL."""
import httpx
import pytest

BASE='/api/v1/portal/internal/simulation-faults'


def prepare(api,scenario,monkeypatch,mode,booking_time=None):
    from serviceBot.api import portal
    monkeypatch.setenv('SIMULATION_FAULTS_ENABLED','true')
    monkeypatch.setenv('SIMULATION_FAULT_TECHNICIAN_IDS','1')
    monkeypatch.setenv('SIMULATION_FAULT_PHONE_NUMBERS','+15550100001')
    monkeypatch.setenv('CRON_SECRET','e2e-only-cron-secret')
    monkeypatch.setattr(portal,'sync_services_to_kb',lambda:None)
    auth={'Authorization':'Bearer e2e-only-cron-secret'}
    response=api.post(BASE,headers=auth,json={'run_id':'fault-http','mode':mode,
        'technician_id':1,'phone':'+15550100001','booking_time':booking_time or scenario['start'].isoformat()})
    assert response.status_code==201,response.text
    owned=response.json()
    auth['X-Simulation-Lease']=owned['lease_token']
    return owned,auth,BASE+'/'+owned['handle']


def test_fixture_creation_rejects_ambiguous_native_customer_before_catalog_write(api,db,scenario,monkeypatch):
    prepare(api,scenario,monkeypatch,'calendar_once')
    db('INSERT INTO customers(name,phone) VALUES (%s,%s)',('Ambiguous designated identity','5550100001'))
    before=db('SELECT id FROM services ORDER BY id')
    response=api.post(BASE,headers={'Authorization':'Bearer e2e-only-cron-secret'},json={
        'run_id':'ambiguous-customer','mode':'response_loss_once','technician_id':1,
        'phone':'+15550100001','booking_time':scenario['start'].isoformat()})
    assert response.status_code==409,response.text
    assert db('SELECT id FROM services ORDER BY id')==before
    assert db("SELECT handle FROM simulation_fault_leases WHERE run_id='ambiguous-customer'")==[]


def test_native_worker_fails_once_then_projects_exact_owned_booking(api,db,scenario,monkeypatch):
    from serviceBot.services import outbox_worker
    owned,headers,path=prepare(api,scenario,monkeypatch,'calendar_once')
    response=api.post(path+'/execute',headers=headers)
    assert response.status_code==200,response.text
    state=api.get(path,headers=headers).json()
    assert state['phase']=='committed'
    assert 'booking_bound_in_transaction' in state['journal']
    request_id=state['request_id']
    projected=[]
    monkeypatch.setattr(outbox_worker,'create_agent_calendar_event',lambda **kw: projected.append(kw) or True)
    # Test only the exact calendar item, keeping messaging out of this offline scope.
    db("UPDATE outbox_notifications SET next_retry_at=CURRENT_TIMESTAMP+INTERVAL '1 day' WHERE id<>%s",(state['outbox_id'],))
    assert outbox_worker.process_outbox_batch()==1
    assert projected==[]
    failed=api.get(path,headers=headers).json()
    assert failed['fault_consumed'] is True
    assert failed['evidence']['calendar_integration_status']=='FAILED'
    assert failed['evidence']['outbox_status']=='PENDING'
    assert failed['evidence']['attempts']==1
    # Offline retry scheduling; live native elapsed backoff remains separately evidenced.
    db('UPDATE outbox_notifications SET next_retry_at=CURRENT_TIMESTAMP WHERE id=%s',(state['outbox_id'],))
    assert outbox_worker.process_outbox_batch()==1
    recovered=api.get(path,headers=headers).json()
    assert recovered['evidence']['calendar_integration_status']=='CREATED'
    assert recovered['evidence']['outbox_status']=='DELIVERED'
    assert recovered['journal'].count('controlled_calendar_failure_consumed')==1
    assert len(projected)==1
    assert projected[0]['agent_id']==1
    assert projected[0]['service_type']==owned['service_name']
    assert db('SELECT id FROM service_requests WHERE service_type=%s',(owned['service_name'],))==[{'id':request_id}]


def test_response_is_truncated_only_after_real_booking_commit_and_reconciles(api,db,scenario,monkeypatch):
    owned,headers,path=prepare(api,scenario,monkeypatch,'response_loss_once')
    with pytest.raises(httpx.RemoteProtocolError):
        api.post(path+'/execute',headers=headers)
    state=api.get(path,headers=headers).json()
    assert state['phase']=='committed'
    assert state['response_loss_consumed'] is True
    assert state['result']['result']['success'] is True
    assert state['evidence']['reservation_status']=='ACTIVE'
    assert state['journal'].count('response_loss_committed')==1
    retry=api.post(path+'/execute',headers=headers)
    assert retry.status_code==200,retry.text
    result=retry.json()
    assert result['lease_reconciliation'] is True
    assert result['core_generic_retry_proven'] is False
    assert result['request_id']==state['request_id']
    assert db('SELECT id FROM service_requests WHERE service_type=%s',(owned['service_name'],))==[{'id':state['request_id']}]
    assert db('SELECT id FROM appointment_reservations WHERE service_request_id=%s',(state['request_id'],))==[{'id':state['reservation_id']}]


def test_owned_service_cleanup_requires_terminal_domain_and_provider_retirement(api,db,scenario,monkeypatch):
    from serviceBot.services import outbox_worker
    from serviceBot.services.booking import BookingService
    owned,headers,path=prepare(api,scenario,monkeypatch,'calendar_once')
    assert api.post(path+'/execute',headers=headers).status_code==200
    state=api.get(path,headers=headers).json()
    response=api.post(path+'/cleanup',headers=headers)
    assert response.status_code==409,response.text
    assert db('SELECT id FROM services WHERE id=%s',(owned['service_id'],))
    BookingService().cancel(request_id=state['request_id'],customer_consent_obtained=True,triggered_by='customer')
    monkeypatch.setattr(outbox_worker,'delete_agent_calendar_event_by_id',lambda **kwargs:True)
    # Exact deletion projection goes through the existing projection owner.
    deletion=db("SELECT payload FROM outbox_notifications WHERE request_id=%s AND event_type='calendar_projection' AND payload->>'action'='delete'",(state['request_id'],))[0]
    outbox_worker._dispatch_outbox_event('calendar_projection',state['request_id'],deletion['payload'])
    from serviceBot.services.sms_router import SMSNotificationRouter
    monkeypatch.setattr(SMSNotificationRouter,'process_event',lambda self,**kw:{'dispatches':[{'status':'SENT','success':True}]})
    for boundary in ('send_booking_notification','send_admin_notification','create_admin_calendar_event','delete_admin_calendar_event'):
        monkeypatch.setattr(outbox_worker,boundary,lambda *a,**kw:True)
    assert outbox_worker.process_outbox_batch()>=1
    response=api.post(path+'/cleanup',headers=headers)
    assert response.status_code==200,response.text
    assert response.json()['cleanup_complete'] is True
    assert db('SELECT id FROM services WHERE id=%s',(owned['service_id'],))==[]
    assert db('SELECT id,is_active FROM staff_agents WHERE id=1')==[{'id':1,'is_active':True}]
    assert db('SELECT id FROM service_requests WHERE id=%s',(state['request_id'],))==[{'id':state['request_id']}]
    assert api.get(path,headers=headers).json()['phase']=='cleaned'
    binding=db('SELECT request_id,reservation_id,outbox_id,retired_binding FROM simulation_fault_leases WHERE handle=%s',(owned['handle'],))[0]
    assert binding['request_id'] is None and binding['reservation_id'] is None and binding['outbox_id'] is None
    assert binding['retired_binding']['request_id']==state['request_id']


def test_worker_refuses_changed_bound_payload_without_consuming_fault(api,db,scenario,monkeypatch):
    from serviceBot.services import simulation_faults as faults
    _owned,headers,path=prepare(api,scenario,monkeypatch,'calendar_once')
    assert api.post(path+'/execute',headers=headers).status_code==200
    state=api.get(path,headers=headers).json()
    payload=db('SELECT payload FROM outbox_notifications WHERE id=%s',(state['outbox_id'],))[0]['payload']
    payload['duration_minutes']=120
    with pytest.raises(faults.FaultDenied,match='payload'):
        faults.before_calendar_dispatch(state['outbox_id'],state['request_id'],payload)
    assert api.get(path,headers=headers).json()['fault_consumed'] is False


def test_expired_fixture_blocks_execution_without_booking_and_can_clean_catalog(api,db,scenario,monkeypatch):
    owned,headers,path=prepare(api,scenario,monkeypatch,'calendar_once')
    db("UPDATE simulation_fault_leases SET expires_at=CURRENT_TIMESTAMP-INTERVAL '1 second' WHERE handle=%s",(owned['handle'],))
    assert api.post(path+'/execute',headers=headers).status_code==409
    assert db('SELECT id FROM service_requests WHERE service_type=%s',(owned['service_name'],))==[]
    assert api.post(path+'/cleanup',headers=headers).json()['cleanup_complete'] is True


def test_fault_consumption_is_one_shot_under_concurrent_claims(api,db,scenario,monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    from serviceBot.services import simulation_faults as faults
    _owned,headers,path=prepare(api,scenario,monkeypatch,'calendar_once')
    assert api.post(path+'/execute',headers=headers).status_code==200
    state=api.get(path,headers=headers).json()
    payload=db('SELECT payload FROM outbox_notifications WHERE id=%s',(state['outbox_id'],))[0]['payload']
    def consume(_):
        try:
            faults.before_calendar_dispatch(state['outbox_id'],state['request_id'],payload)
            return 'normal'
        except faults.ControlledCalendarFailure:
            return 'controlled_failure'
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(consume,range(2)))==['controlled_failure','normal']
    assert api.get(path,headers=headers).json()['journal'].count('controlled_calendar_failure_consumed')==1


def test_interrupted_native_execute_never_replays_unbound_intent(api,db,scenario,monkeypatch):
    from serviceBot.api import telephony
    owned,headers,path=prepare(api,scenario,monkeypatch,'calendar_once')
    calls=[]
    async def interrupted(*args,**kwargs):
        calls.append(1)
        raise RuntimeError('synthetic process interruption before booking')
    monkeypatch.setattr(telephony,'voice_tools',interrupted)
    assert api.post(path+'/execute',headers=headers).status_code==409
    assert api.post(path+'/execute',headers=headers).status_code==409
    assert len(calls)==1
    assert api.get(path,headers=headers).json()['phase']=='unknown'
    assert api.post(path+'/cleanup',headers=headers).status_code==409
    assert db('SELECT id FROM services WHERE id=%s',(owned['service_id'],))


def test_transaction_bound_booking_survives_missing_http_result_without_rebooking(api,db,scenario,monkeypatch):
    from serviceBot.services import simulation_faults as faults
    owned,headers,path=prepare(api,scenario,monkeypatch,'response_loss_once')
    monkeypatch.setattr(faults,'finish_execute',lambda *a: (_ for _ in ()).throw(RuntimeError('synthetic crash after commit')))
    assert api.post(path+'/execute',headers=headers).status_code==409
    state=api.get(path,headers=headers).json()
    assert state['phase']=='bound' and state['evidence']['reservation_status']=='ACTIVE'
    replay=api.post(path+'/execute',headers=headers).json()
    assert replay['lease_reconciliation'] is True and replay['result'] is None
    assert replay['core_generic_retry_proven'] is False
    assert db('SELECT id FROM service_requests WHERE service_type=%s',(owned['service_name'],))==[{'id':state['request_id']}]


def test_owned_service_drift_blocks_cleanup_and_preserves_mapping(api,db,scenario,monkeypatch):
    owned,headers,path=prepare(api,scenario,monkeypatch,'calendar_once')
    db("UPDATE services SET price_range='Changed original fixture' WHERE id=%s",(owned['service_id'],))
    assert api.post(path+'/cleanup',headers=headers).status_code==409
    assert db('SELECT staff_agent_id FROM service_staff_agents WHERE service_id=%s',(owned['service_id'],))==[{'staff_agent_id':1}]


def test_migration_rollback_refuses_unresolved_lease_then_reapplies(api,db,scenario,monkeypatch):
    from serviceBot.db.connection import get_db_connection
    from serviceBot.db.migrations import apply_migrations, rollback_migration
    _owned,headers,path=prepare(api,scenario,monkeypatch,'calendar_once')
    with pytest.raises(Exception,match='require owned cleanup'), get_db_connection() as conn:
        rollback_migration(conn,'0009_simulation_fault_leases')
    assert api.post(path+'/cleanup',headers=headers).status_code==200
    with get_db_connection() as conn:
        rollback_migration(conn,'0009_simulation_fault_leases')
    assert db("SELECT to_regclass('simulation_fault_leases') AS relation")==[{'relation':None}]
    with get_db_connection() as conn:
        assert '0009_simulation_fault_leases' in apply_migrations(conn)
    assert db("SELECT count(*) AS rows FROM simulation_fault_leases")==[{'rows':0}]


def test_cleanup_refuses_unconstrained_service_reference(api,db,scenario,monkeypatch):
    owned,headers,path=prepare(api,scenario,monkeypatch,'calendar_once')
    db('CREATE TABLE simulation_test_legacy_reference(service_id INTEGER)')
    try:
        db('INSERT INTO simulation_test_legacy_reference VALUES (%s)',(owned['service_id'],))
        assert api.post(path+'/cleanup',headers=headers).status_code==409
        assert db('SELECT id FROM services WHERE id=%s',(owned['service_id'],))
    finally:
        db('DROP TABLE simulation_test_legacy_reference')


@pytest.mark.parametrize('change',[
    {'customer_consent_obtained':False},{'customer_consent_obtained':None},
    {'phone':'+15550100002'},{'service_type':'Oil Change'},
    {'booking_time':'2030-01-01T11:00:00'},{'booking_type':'callback'},
    {'phone':'+445550100001'},
])
def test_actual_model_tool_payload_rejected_before_native_intent(api,db,scenario,monkeypatch,change):
    owned,headers,path=prepare(api,scenario,monkeypatch,'calendar_once')
    arguments={'phone':'+15550100001','service_type':owned['service_name'],
        'booking_time':scenario['start'].isoformat(),'booking_type':'appointment',
        'customer_consent_obtained':True}
    arguments.update(change)
    response=api.post(path+'/tool',headers=headers,json={'name':'create_service_request','arguments':arguments})
    assert response.status_code==409,response.text
    state=api.get(path,headers=headers).json()
    assert state['phase']=='prepared'
    assert 'execution_intent' not in state['journal']
    assert db('SELECT id FROM service_requests WHERE service_type=%s',(owned['service_name'],))==[]


def test_model_tool_payload_records_native_agent_origin_and_commit(api,db,scenario,monkeypatch):
    owned,headers,path=prepare(api,scenario,monkeypatch,'calendar_once')
    arguments={'phone':'+15550100001','service_type':owned['service_name'],
        'booking_time':scenario['start'].isoformat(),'booking_type':'appointment',
        'customer_consent_obtained':True}
    response=api.post(path+'/tool',headers=headers,json=arguments)
    assert response.status_code==200,response.text
    state=api.get(path,headers=headers).json()
    assert state['agent_tool_verified'] is True
    assert state['tool_payload_hash']
    assert 'agent_payload_validated' in state['journal']


def test_capability_probe_is_authenticated_read_only_and_hashes_recipients(api,db,scenario,monkeypatch):
    import hashlib
    monkeypatch.setenv('SIMULATION_FAULTS_ENABLED','true')
    monkeypatch.setenv('SIMULATION_FAULT_TECHNICIAN_IDS','1,2')
    monkeypatch.setenv('SIMULATION_FAULT_PHONE_NUMBERS','+15550100001')
    headers={'Authorization':'Bearer e2e-only-cron-secret'}
    assert api.get(BASE).status_code==403
    before=db('SELECT count(*) AS rows FROM simulation_fault_leases')
    response=api.get(BASE,headers=headers)
    assert response.status_code==200,response.text
    result=response.json()
    assert result['capability']=='owned-faults-v1' and result['schema_ready'] is True
    assert result['modes']==['calendar_once','response_loss_once']
    assert result['allowlisted_technician_ids']==[1,2]
    assert result['allowlisted_phone_fingerprints']==[hashlib.sha256(b'+15550100001').hexdigest()]
    assert '+15550100001' not in response.text and 'e2e-only-cron-secret' not in response.text
    assert db('SELECT count(*) AS rows FROM simulation_fault_leases')==before



def test_model_timezone_timestamp_uses_existing_domain_normalization(api,db,scenario,monkeypatch):
    from datetime import timezone
    from zoneinfo import ZoneInfo
    when=scenario['start'].replace(tzinfo=ZoneInfo('America/New_York')).astimezone(timezone.utc).isoformat()
    owned,headers,path=prepare(api,scenario,monkeypatch,'calendar_once',booking_time=when)
    response=api.post(path+'/tool',headers=headers,json={'phone':'+15550100001',
        'service_type':owned['service_name'],'booking_time':when,'booking_type':'appointment',
        'customer_consent_obtained':True})
    assert response.status_code==200,response.text
    state=api.get(path,headers=headers).json()
    assert db('SELECT starts_at FROM appointment_reservations WHERE id=%s',(state['reservation_id'],))==[{'starts_at':scenario['start']}]


def test_first_future_sequence_value_is_new_owned_request_not_original_watermark(api,db,scenario,monkeypatch):
    owned,headers,path=prepare(api,scenario,monkeypatch,'calendar_once')
    target=db('SELECT COALESCE(MAX(id),0)+100 AS next_id FROM service_requests')[0]['next_id']
    db("SELECT setval('service_requests_id_seq',%s,FALSE)",(target,))
    response=api.post(path+'/tool',headers=headers,json={'phone':'+15550100001',
        'service_type':owned['service_name'],'booking_time':scenario['start'].isoformat(),
        'booking_type':'appointment','customer_consent_obtained':True})
    assert response.status_code==200,response.text
    state=api.get(path,headers=headers).json()
    assert state['request_id']==target
    assert db('SELECT request_watermark FROM simulation_fault_leases WHERE handle=%s',(owned['handle'],))==[{'request_watermark':target-1}]


def test_cleanup_rechecks_schema_after_late_cascading_reference_before_locks(api,db,scenario,monkeypatch):
    from serviceBot.services import simulation_faults as faults
    owned,headers,path=prepare(api,scenario,monkeypatch,'calendar_once')
    scan=faults._reference_columns
    scans=[]
    def attach_after_first_scan(cursor):
        references=scan(cursor)
        scans.append(references)
        if len(scans)==1:
            # A separate committed DDL transaction wins the interval between
            # metadata discovery and cleanup's parent/reference table locks.
            db('CREATE TABLE simulation_test_late_reference(owner INTEGER REFERENCES services(id) ON DELETE CASCADE)')
            db('INSERT INTO simulation_test_late_reference VALUES (%s)',(owned['service_id'],))
        return references
    monkeypatch.setattr(faults,'_reference_columns',attach_after_first_scan)
    try:
        response=api.post(path+'/cleanup',headers=headers)
        assert response.status_code==409,response.text
        assert 'schema changed' in response.json()['detail'].lower()
        assert len(scans)==2 and scans[0]!=scans[1]
        assert db('SELECT owner FROM simulation_test_late_reference')==[{'owner':owned['service_id']}]
        assert db('SELECT id FROM services WHERE id=%s',(owned['service_id'],))==[{'id':owned['service_id']}]
        assert db('SELECT staff_agent_id FROM service_staff_agents WHERE service_id=%s',(owned['service_id'],))==[{'staff_agent_id':1}]
        assert db('SELECT service_id,phase FROM simulation_fault_leases WHERE handle=%s',(owned['handle'],))==[
            {'service_id':owned['service_id'],'phase':'disarmed'}]
    finally:
        db('DROP TABLE IF EXISTS simulation_test_late_reference')
