"""Actual full Adapter, native HTTP, and read-only PostgreSQL observer contracts.

Only disposable E2E fixture setup/corruption uses SQL writes. Adapter observation
uses its unmodified read-only helper; provider writes are captured at transport.
"""
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace

import pytest

from e2e.test_voice_and_reporting import voice
from live_simulations import deployed_medium as medium
from live_simulations.core import load_catalog
from live_simulations.deployed_full_adapter import Adapter

CASES = {c['id']: c for c in load_catalog()}


@pytest.fixture
def native_full(api, live_server, db, scenario, tmp_path, freeze_business_clock, monkeypatch):
    from serviceBot.db.connection import get_db_connection
    from serviceBot.services import outbox_worker

    now = freeze_business_clock(scenario['start'] - timedelta(days=2))
    monkeypatch.setattr(medium, '_now', lambda config: now)
    with get_db_connection() as conn:
        monkeypatch.setenv('FULL_E2E_OBSERVER_DSN', conn.dsn)
    assert db('SELECT current_database() AS name')[0]['name'].startswith('voice_e2e_')
    db("UPDATE service_requests SET status='cancelled' WHERE id=1")
    db("INSERT INTO user_google_accounts(agent_id,email,granted_scopes) VALUES(1,'taylor@example.test','https://www.googleapis.com/auth/calendar'),(2,'morgan@example.test','https://www.googleapis.com/auth/calendar')")
    for agent in (1, 2):
        for minutes in range(0, 360, 15):
            db('INSERT INTO mock_calendar_slots(staff_agent_id,slot_datetime) VALUES(%s,%s) ON CONFLICT DO NOTHING',
               (agent, scenario['start'] + timedelta(minutes=minutes)))
    policy = api.get('/api/v1/portal/config').json()
    config = {'deployed_url': live_server, 'app_config': {'business_timezone': policy['business_timezone']},
              'evidence_timeout_seconds': 3,
              'variables': {'customer_name': 'Full Native E2E', 'customer_phone': '+15550100008'},
              'allowlisted_emails': ['taylor@example.test', 'morgan@example.test'],
              'allowlisted_phone_numbers': ['+15550100003', '+15550100004', '+15550100008'],
              'deployed_medium': {'ownership_id': 'full-native-e2e-owner', 'technician_ids': [1, 2],
                                  'database_env': 'FULL_E2E_OBSERVER_DSN',
                                  'services': {key: {'name': 'full-native-e2e-owner '+key,
                                                    'duration_minutes': duration, 'price_range': '$'+str(duration)}
                                               for key,duration in [('oil',60),('second',30),('split',60)]}}}
    manifest = {'run_id': 'e'*32, 'stage_authorization': {'id':'full-native-offline'},
                'baseline': medium._request_rows(config, [1])}
    adapter = Adapter(SimpleNamespace(config=config,manifest=manifest,folder=tmp_path,save=lambda: None), api)
    events, effects = {}, []
    def create(**payload):
        events[payload['external_event_id']] = payload
        return True
    def delete(**payload):
        events.pop(payload['event_id'], None)
        return True
    monkeypatch.setattr(outbox_worker, 'create_agent_calendar_event', create)
    monkeypatch.setattr(outbox_worker, 'delete_agent_calendar_event_by_id', delete)
    dispatch = outbox_worker._dispatch_outbox_event
    def captured(event_type, request_id, payload):
        if event_type == 'calendar_projection':
            return dispatch(event_type,request_id,payload)
        effects.append((event_type,request_id,payload))
    monkeypatch.setattr(outbox_worker, '_dispatch_outbox_event', captured)
    def drain():
        for _ in range(10):
            if not outbox_worker.process_outbox_batch(100): break
        assert not db("SELECT id FROM outbox_notifications WHERE event_type='calendar_projection' AND status<>'DELIVERED'")
    monkeypatch.setattr(medium, '_sleep', lambda seconds: drain())
    adapter.prepare_catalog()
    values = dict(config['variables'], appointment_time=scenario['start'].isoformat(),
                  appointment_date=scenario['date'],new_time=(scenario['start']+timedelta(hours=3)).isoformat(),
                  callback_time=(scenario['start']+timedelta(hours=4)).isoformat())
    def rows():
        ids = [r['id'] for r in db('SELECT id FROM service_requests WHERE id<>1 ORDER BY id')]
        return medium._request_rows(config, ids)
    def create_request(keys, *, when=None, callback=False, call='full-native-primary'):
        names = [adapter.state['services'][key]['name'] for key in keys] if keys else [adapter.state['full_callback_issue']]
        args = {'customer_name': values['customer_name'], 'phone':values['customer_phone'],
                'make':'Toyota','model':'Camry','year':2021,'service_type':' and '.join(names),
                'issue_description':' and '.join(names),'booking_type':'callback' if callback else 'appointment',
                'booking_time':when or values['appointment_time'],'call_sid':call}
        if len(names)>1: args['services']=names
        result=voice(api,'create_service_request',args)
        assert result['success'],result
        return result
    return SimpleNamespace(adapter=adapter,values=values,db=db,api=api,rows=rows,drain=drain,
                           create=create_request,events=events,effects=effects)


def all_passed(native, cid):
    result = native.adapter.checks(CASES[cid], native.values, [], native.rows())
    assert all(c['passed'] for c in result),result


def cleanup(native):
    native.adapter.cleanup_case()
    assert not native.db("SELECT id FROM appointment_reservations WHERE status='ACTIVE'")
    assert not native.db('SELECT reservation_id FROM appointment_reservation_segments')
    assert native.db('SELECT status FROM service_requests WHERE id=1') == [{'status':'cancelled'}]
    assert native.db('SELECT name FROM customers WHERE id=1') == [{'name':'Alex E2E'}]
    assert native.db('SELECT year FROM vehicles WHERE customer_id=1') == [{'year':2020}]
    native.adapter.cleanup_catalog()
    assert not native.db('SELECT id FROM services WHERE name LIKE %s', ('full-native-e2e-owner %',))
    assert native.events == {}


def test_c25_native_two_technician_blocks_reject_gap_and_duplicate(native_full):
    n=native_full;n.adapter.arrange(CASES['C25'],n.values)
    n.create(['oil','second','split']);n.drain();all_passed(n,'C25')
    rows=n.rows()
    assert next(c['expect'] for c in CASES['C25']['checks'] if c['name']=='active request count')==2
    assert len(rows)==2 and sum(r['duration_minutes'] for r in rows)==150
    assert [r['duration_minutes'] for r in rows]==[90,60]
    assert len({r['staff_agent_id'] for r in rows})==2
    assert len({r['visit_group_id'] for r in rows})==1
    last=rows[-1]
    n.db("UPDATE appointment_reservations SET starts_at=starts_at+INTERVAL '15 minutes',ends_at=ends_at+INTERVAL '15 minutes' WHERE id=%s",(last['reservation_id'],))
    assert not all(c['passed'] for c in n.adapter.checks(CASES['C25'],n.values,[],n.rows()))
    n.db('UPDATE appointment_reservations SET starts_at=%s,ends_at=%s WHERE id=%s',(last['starts_at'],last['ends_at'],last['reservation_id']))
    n.create(['oil'],when=n.values['callback_time'],call='full-native-extra');n.drain()
    assert not all(c['passed'] for c in n.adapter.checks(CASES['C25'],n.values,[],n.rows()))
    cleanup(n)


def test_c28_real_consolidation_preserves_id_start_and_exact_ninety_minutes(native_full):
    n=native_full; _,ids=n.adapter.arrange(CASES['C28'],n.values)
    original=deepcopy(n.rows()[0])
    result=voice(n.api,'consolidate_appointment_service',{'phone':n.values['customer_phone'],'appointment_id':str(ids[0]),
                 'additional_service_type':n.adapter.state['services']['second']['name'],
                 'additional_issue':'Tire rotation','additional_duration_minutes':30})
    assert result['success'],result
    n.drain();all_passed(n,'C28')
    current=n.rows()[0]
    assert current['id']==original['id'] and current['booking_time']==original['booking_time']
    assert current['duration_minutes']==90 and current['segment_count']==6
    cleanup(n)


def test_c29_real_block_preserves_original_and_restores_exact_slots(native_full):
    n=native_full
    original_slots=n.db('SELECT id,is_booked,reservation_status,service_request_id FROM mock_calendar_slots WHERE staff_agent_id=1 AND slot_datetime>=%s AND slot_datetime<%s ORDER BY id',
                        (n.values['appointment_time'],n.values['callback_time']))
    _,ids=n.adapter.arrange(CASES['C29'],n.values)
    original=deepcopy(n.rows()[0])
    result=voice(n.api,'consolidate_appointment_service',{'phone':n.values['customer_phone'],'appointment_id':str(ids[0]),
                 'additional_service_type':n.adapter.state['services']['second']['name'],
                 'additional_issue':'Tire rotation','additional_duration_minutes':30})
    assert result['success'] is False and result.get('capacity_blocked') is True
    n.drain();all_passed(n,'C29')
    current=n.rows()[0]
    assert (current['id'],current['duration_minutes'],current['reservation_id'])==(original['id'],60,original['reservation_id'])
    cleanup(n)
    restored=n.db('SELECT id,is_booked,reservation_status,service_request_id FROM mock_calendar_slots WHERE staff_agent_id=1 AND slot_datetime>=%s AND slot_datetime<%s ORDER BY id',
                  (n.values['appointment_time'],n.values['callback_time']))
    assert restored==original_slots


def test_c26_real_untagged_service_assigns_active_staff_and_restores_mapping(native_full):
    n=native_full; n.adapter.arrange(CASES['C26'],n.values)
    service=n.adapter.state['services']['second']
    assert not n.db('SELECT staff_agent_id FROM service_staff_agents WHERE service_id=%s',(service['id'],))
    n.create(['second']);n.drain();all_passed(n,'C26')
    assert n.rows()[0]['staff_agent_id'] in {1,2}
    n.adapter.cleanup_case()
    assert n.db('SELECT staff_agent_id FROM service_staff_agents WHERE service_id=%s',(service['id'],))==[{'staff_agent_id':1}]
    n.adapter.cleanup_catalog();assert n.events=={}


def test_c27_real_owned_inactive_staff_is_hidden_from_active_api_and_retained(native_full):
    n=native_full;n.adapter.arrange(CASES['C27'],n.values)
    staff=n.adapter.state['full_inactive_staff']
    assert staff['id'] not in {a['id'] for a in n.api.get('/api/v1/portal/agents').json()}
    assert n.db('SELECT is_active FROM staff_agents WHERE id=%s',(staff['id'],))==[{'is_active':False}]
    n.create(['oil']);n.drain();all_passed(n,'C27')
    assert n.rows()[0]['staff_agent_id']==1
    cleanup(n)
    assert 'retained' in staff['cleanup_receipt']
    assert n.db('SELECT is_active FROM staff_agents WHERE id=%s',(staff['id'],))==[{'is_active':False}]


def test_c32_real_appointment_and_fifteen_minute_callback_are_independent(native_full):
    n=native_full;n.adapter.arrange(CASES['C32'],n.values)
    n.create(['oil']);n.create([],when=n.values['callback_time'],callback=True,call='full-native-callback')
    n.drain();all_passed(n,'C32')
    appointment,callback=sorted(n.rows(),key=lambda r:r['booking_type'])
    assert appointment['booking_type']=='appointment' and callback['booking_type']=='callback'
    assert appointment['id']!=callback['id'] and callback['duration_minutes']==15
    assert callback['segment_count']==1 and callback['reservation_id']!=appointment['reservation_id']
    cleanup(n)


def test_c26_real_third_allowlisted_active_assignee_is_eligible(native_full):
    n=native_full
    result=n.api.post('/api/v1/portal/agents',json={'name':'Third owned E2E','email':'third@example.test','phone_number':'+15550100007','role':'Technician'})
    assert result.status_code==201,result.text
    third=result.json()['id']
    n.db("INSERT INTO user_google_accounts(agent_id,email,granted_scopes) VALUES(%s,'third@example.test','https://www.googleapis.com/auth/calendar')",(third,))
    for minutes in (0,15):
        from datetime import datetime
        n.db('INSERT INTO mock_calendar_slots(staff_agent_id,slot_datetime) VALUES(%s,%s)',
             (third,datetime.fromisoformat(n.values['appointment_time'])+timedelta(minutes=minutes)))
    n.adapter.config['allowlisted_emails'].append('third@example.test')
    n.adapter.config['allowlisted_phone_numbers'].append('+15550100007')
    # Disposable setup blocks designated technicians, making the third assignee observable.
    n.db("UPDATE mock_calendar_slots SET is_booked=TRUE,reservation_status='BLOCKED' WHERE staff_agent_id IN (1,2) AND slot_datetime>=%s AND slot_datetime<%s",
         (n.values['appointment_time'],(datetime.fromisoformat(n.values['appointment_time'])+timedelta(minutes=30)).isoformat()))
    n.adapter.arrange(CASES['C26'],n.values)
    n.create(['second']);n.drain();all_passed(n,'C26')
    assert n.rows()[0]['staff_agent_id']==third
    cleanup(n)


def test_existing_vehicle_conflict_blocks_before_native_fixture_creation(native_full):
    from live_simulations.core import SimulationError
    n=native_full
    values=dict(n.values,customer_phone='+15550100001',customer_name='Alex E2E')
    before=n.db('SELECT row_to_json(s) AS value FROM service_requests s ORDER BY id')
    operations=len(n.adapter.state['operations'])
    with pytest.raises(SimulationError,match='existing vehicle'):
        n.adapter.arrange(CASES['C28'],values)
    assert n.db('SELECT row_to_json(s) AS value FROM service_requests s ORDER BY id')==before
    assert len(n.adapter.state['operations'])==operations
    assert n.db('SELECT year FROM vehicles WHERE customer_id=1')==[{'year':2020}]
    assert medium._read(n.adapter.config,"SELECT current_setting('transaction_read_only') AS readonly")==[{'readonly':'on'}]
    n.adapter.cleanup_catalog()


def test_c22_captured_owned_google_event_causes_native_exclusion_and_safe_restoration(native_full,monkeypatch):
    import json
    from copy import deepcopy

    import httpx

    from serviceBot.services import google_calendar
    n=native_full
    monkeypatch.setenv('FULL_GOOGLE_E2E_TOKEN','synthetic-memory-only-token')
    n.adapter.config['deployed_full_google']={
        'technician_id':1,'access_token_env':'FULL_GOOGLE_E2E_TOKEN',
        'account_email':'taylor@example.test','calendar_id':'taylor@example.test',
        'availability_timeout_seconds':2}
    busy,calls={},[]
    def transport(request):
        calls.append((request.method,request.url.path))
        if request.url.path.endswith('/userinfo'):
            return httpx.Response(200,json={'email':'taylor@example.test','email_verified':True})
        if '/calendarList/' in request.url.path:
            return httpx.Response(200,json={'id':'taylor@example.test','primary':True,'accessRole':'owner'})
        if request.method=='GET':return httpx.Response(200,json=busy) if busy else httpx.Response(404)
        if request.method=='POST':
            assert n.adapter.state['full_google_busy']['operations'][-1]['status']=='intent'
            busy.update(json.loads(request.content),etag='"captured-provider-v1"')
            return httpx.Response(200,json=busy)
        assert request.method=='DELETE' and request.headers['if-match']=='"captured-provider-v1"'
        busy.clear();return httpx.Response(204)
    captured_transport=httpx.MockTransport(transport)
    class GoogleCaptureClient(httpx.Client):
        # The general E2E HTTP guard rejects every external host. This instance
        # bypasses it only to invoke the in-memory captured Google transport.
        def _send_single_request(self,request):
            response=captured_transport.handle_request(request)
            response.request=request
            return response
    n.adapter.google_client=GoogleCaptureClient(transport=captured_transport)
    monkeypatch.setattr(google_calendar,'fetch_agent_events',lambda agent,*args,**kwargs:[deepcopy(busy)] if agent==1 and busy else [])
    original=n.db('SELECT row_to_json(s) AS value FROM service_requests s ORDER BY id')
    n.adapter.arrange(CASES['C22'],n.values)
    assert busy and n.adapter.state['full_google_busy']['availability_proof']=='native_free_then_excluded'
    assert not n.rows()
    all_passed(n,'C22')
    n.adapter.cleanup_case()
    assert not busy and n.adapter.state['full_google_busy']['status']=='deleted'
    assert n.db('SELECT row_to_json(s) AS value FROM service_requests s ORDER BY id')==original
    assert [method for method,_ in calls].count('POST')==1
    assert [method for method,_ in calls].count('DELETE')==1
    assert n.adapter.state['full_google_busy']['event_id'] not in n.events
    n.adapter.cleanup_catalog()


def test_c30_native_selective_oil_removal_retires_only_selected_projection(native_full):
    n=native_full;_,ids=n.adapter.arrange(CASES['C30'],n.values)
    n.drain();before={r['service_type']:deepcopy(r) for r in n.rows()}
    oil=n.adapter.state['services']['oil']['name'];split=n.adapter.state['services']['split']['name']
    result=voice(n.api,'cancel_appointment',{'phone':n.values['customer_phone'],
        'appointment_id':str(before[oil]['id']),'service_name':oil})
    assert result['success'] and result['cancelled'],result
    n.drain();all_passed(n,'C30')
    assert set(ids)=={r['id'] for r in n.rows()}
    current={r['service_type']:r for r in n.rows()}
    assert current[oil]['status']=='cancelled' and current[oil]['reservation_id'] is None
    assert current[split]['booking_time']==before[split]['booking_time']
    assert current[split]['starts_at']==before[split]['starts_at']
    assert current[split]['ends_at']==before[split]['ends_at']
    assert before[oil]['calendar_event_id'] not in n.events
    assert before[split]['calendar_event_id'] in n.events
    cleanup(n)


def test_c31_real_two_specialist_callbacks_keep_the_gap_and_cleanup_both(native_full):
    n=native_full;adapted,ids=n.adapter.arrange(CASES['C31'],n.values)
    assert not ids and '15-minute callbacks' in adapted['scenario']
    n.create(['oil','split'],when=n.values['callback_time'],callback=True)
    n.drain();all_passed(n,'C31')
    rows=n.rows()
    assert len(rows)==2 and {r['booking_type'] for r in rows}=={'callback'}
    assert {r['staff_agent_id'] for r in rows}=={1,2}
    assert [r['duration_minutes'] for r in rows]==[15,15]
    assert rows[1]['starts_at']-rows[0]['starts_at']==timedelta(minutes=30)
    assert rows[1]['starts_at']-rows[0]['ends_at']==timedelta(minutes=15)
    assert len({r['reservation_id'] for r in rows})==len({r['calendar_event_id'] for r in rows})==2
    assert len(n.events)==2
    cleanup(n)
