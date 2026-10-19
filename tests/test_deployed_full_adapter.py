"""Offline full-native arrangement and persisted outcome contracts."""
from copy import deepcopy
from datetime import datetime
from types import SimpleNamespace

import httpx
import pytest

from live_simulations import deployed_full_adapter as full
from live_simulations import deployed_medium as medium
from live_simulations.core import SimulationError, load_catalog


def case(cid):
    return deepcopy(next(c for c in load_catalog() if c['id'] == cid))


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    services = {k: {'name': 'owner-full-test '+k, 'duration_minutes': d, 'price_range': '$'+str(d)}
                for k, d in [('oil', 60), ('second', 30), ('split', 60)]}
    config = {'deployed_url': 'https://native.test', 'app_config': {'business_timezone': 'America/New_York'},
              'variables': {'customer_name': 'Owned', 'customer_phone': '4242704893'},
              'allowlisted_phone_numbers': ['+14242704893'], 'allowlisted_emails': ['owned@example.test'],
              'deployed_medium': {'ownership_id': 'owner-full-test', 'technician_ids': [7, 12], 'services': services}}
    manifest = {'run_id': 'r'*32, 'stage_authorization': {'id': 'claim'}, 'baseline': []}
    campaign = SimpleNamespace(config=config, manifest=manifest, folder=tmp_path, save=lambda: None)
    catalog, calls = [], []
    native_config = {'business_timezone': 'America/New_York', 'business_days': [0,1,2,3,4],
                     'business_hours_start': 7, 'business_hours_end': 18,
                     'min_booking_buffer_hours': 4, 'min_callback_buffer_hours': 2}
    def transport(request):
        import json
        body = json.loads(request.content) if request.content else None
        calls.append((request.method, request.url.path, body))
        if request.method == 'GET':
            if request.url.path.endswith('/config'): return httpx.Response(200, json=native_config)
            if request.url.path.endswith('/agents'): return httpx.Response(200, json=[{'id': 7, 'email': 'owned@example.test', 'phone_number': '+14242704893', 'is_connected': True}])
            return httpx.Response(200, json=catalog)
        if request.method == 'POST' and request.url.path.endswith('/services'):
            row = dict(body, id=100+len(catalog), assigned_agent_ids=body['agent_ids'])
            catalog.append(row)
            return httpx.Response(201, json={'success': True, 'id': row['id']})
        if request.method == 'PUT':
            row = next(r for r in catalog if r['id'] == int(request.url.path.split('/')[-1]))
            row.update(body, assigned_agent_ids=body['agent_ids'])
        return httpx.Response(200, json={'success': True})
    client = httpx.Client(transport=httpx.MockTransport(transport))
    monkeypatch.setattr(medium, '_now', lambda config: datetime.fromisoformat('2026-11-09T10:00:00-05:00'))
    monkeypatch.setattr(medium, '_request_rows', lambda config, ids: [])
    monkeypatch.setattr(medium, '_read', lambda config, statement, params=(): [] if 'FROM customers' in statement else [{'id':7,'email':'owned@example.test','google_email':'owned@example.test','phone_number':'+14242704893'}])
    adapter = full.Adapter(campaign, client)
    values = {'customer_name': 'Owned', 'customer_phone': '4242704893', 'appointment_time': '2026-11-10T10:00:00',
              'new_time': '2026-11-11T10:00:00', 'callback_time': '2026-11-10T14:00:00', 'appointment_date': '2026-11-10'}
    return adapter, values, calls, catalog, native_config


def test_full_catalog_owns_exact_durations_and_uses_native_transport(fixture):
    adapter, _, calls, catalog, _ = fixture
    adapter.prepare_catalog()
    assert [x['duration_minutes'] for x in catalog] == [60,30,60]
    assert all(x['name'].startswith('owner-full-test ') for x in catalog)
    assert len([c for c in calls if c[0]=='POST']) == 3
    assert all(o['status']=='observed' for o in adapter.state['operations'])


@pytest.mark.parametrize('cid', ['C23','C33','C35','C47'])
def test_unsupported_never_arranges_or_mutates(fixture, cid):
    adapter, values, calls, _, _ = fixture
    with pytest.raises(SimulationError, match='unsupported'):
        adapter.arrange(case(cid), values)
    assert calls == []


@pytest.mark.parametrize('cid', ['C17','C18','C19','C20','C46','C49'])
def test_negative_arrangements_are_readonly_and_assert_zero_new_ids(fixture, cid):
    adapter, values, calls, _, _ = fixture
    adapter.prepare_catalog(); calls.clear()
    adapted, ids = adapter.arrange(case(cid), values)
    assert ids == []
    assert all(method == 'GET' for method, _, _ in calls)
    assert all(c['passed'] for c in adapter.checks(case(cid), values, [], []))
    with pytest.raises(SimulationError):
        adapter.checks(case(cid), values, [], [{'id': 999}])
    assert 'owner-full-test oil' in adapted['scenario']


@pytest.mark.parametrize('cid', ['C17','C18'])
def test_lead_time_cases_block_outside_live_business_window(fixture, monkeypatch, cid):
    adapter, values, calls, _, _ = fixture
    adapter.prepare_catalog(); calls.clear()
    monkeypatch.setattr(medium, '_now', lambda config: datetime.fromisoformat('2026-11-08T22:00:00-05:00'))
    with pytest.raises(SimulationError, match='business window'):
        adapter.arrange(case(cid), values)
    assert all(method == 'GET' for method, _, _ in calls)


def row(adapter, *, key='oil', identifier=1, start='2026-11-10T10:00:00', duration=None, staff=7):
    from datetime import timedelta
    service = adapter.state['services'][key]
    duration = duration or service['duration_minutes']; stamp=datetime.fromisoformat(start)
    return {'id': identifier, 'customer_id': 5, 'customer_phone': '4242704893', 'customer_name': 'Owned',
            'make':'Toyota','model':'Camry','year':2021,'status':'pending','booking_type':'appointment',
            'booking_time':start,'starts_at':start,'ends_at':(stamp+timedelta(minutes=duration)).isoformat(),
            'service_type':service['name'],'duration_minutes':duration,'staff_agent_id':staff,
            'reservation_id':identifier+1000,'reservation_status':'ACTIVE','qualified':True,
            'segment_count':duration//15,'reservation_segments':[stamp+timedelta(minutes=i) for i in range(0,duration,15)],
            'qualified_service_names':[s['name'] for s in adapter.state['services'].values()],
            'calendar_integration_status':'CREATED','request_calendar_status':'CREATED','calendar_event_id':'owned-event',
            'visit_group_id':'owned-visit'}


@pytest.mark.parametrize('defect', ['none','time','duration','identity','staff'])
def test_fresh_owned_booking_predicates_reject_concrete_wrong_state(fixture, monkeypatch, defect):
    adapter, values, _, _, _ = fixture; adapter.prepare_catalog()
    adapter.arrange(case('C34'), values)
    observed=row(adapter)
    if defect=='time': observed['booking_time']='2026-11-10T11:00:00'
    if defect=='duration': observed['duration_minutes']=15
    if defect=='identity': observed['customer_phone']='5550100002'
    if defect=='staff': observed['staff_agent_id']=99
    monkeypatch.setattr(medium, '_request_rows', lambda config, ids:[observed] if ids else [])
    if defect=='identity':
        with pytest.raises(SimulationError): adapter.checks(case('C34'), values, [], [observed])
    else:
        checks=adapter.checks(case('C34'), values, [], [observed])
        assert all(c['passed'] for c in checks) is (defect=='none')


@pytest.mark.parametrize('defect',['none','missing_component','wrong_snapshot_duration','qualification','gap','grid','duplicate','projection','extra_projection','off_grid_start'])
def test_c25_two_grouped_rows_use_exact_component_snapshots(fixture,monkeypatch,defect):
    adapter,values,_,_,_=fixture;adapter.prepare_catalog();adapter.arrange(case('C25'),values)
    first=row(adapter,duration=90)
    first.update(service_type=adapter.state['services']['oil']['name']+', '+adapter.state['services']['second']['name'],qualified=False)
    second=row(adapter,key='split',identifier=2,start='2026-11-10T11:30:00',staff=12)
    second['calendar_event_id']='other-owned-event'
    rows=[first,second]
    snapshots={1:[{'name':adapter.state['services'][k]['name'],'duration_minutes':adapter.state['services'][k]['duration_minutes']} for k in ['oil','second']],
               2:[{'name':adapter.state['services']['split']['name'],'duration_minutes':60}]}
    if defect=='missing_component':snapshots[1].pop()
    if defect=='wrong_snapshot_duration':snapshots[1][1]['duration_minutes']=15
    if defect=='qualification':first['qualified_service_names']=[adapter.state['services']['oil']['name']]
    if defect=='gap':second['starts_at']='2026-11-10T11:45:00'
    if defect=='grid':first['reservation_segments'][1]=datetime(2026,11,10,10,7)
    if defect=='duplicate':rows.append(row(adapter,identifier=3,start='2026-11-10T14:00:00'));snapshots[3]=snapshots[2]
    if defect=='projection':second['calendar_event_id']=first['calendar_event_id']
    if defect=='off_grid_start':
        from datetime import timedelta
        values['appointment_time']='2026-11-10T10:07:00'
        for item in rows:
            for field in ('booking_time','starts_at','ends_at'):
                item[field]=(datetime.fromisoformat(item[field])+timedelta(minutes=7)).isoformat()
            item['reservation_segments']=[v+timedelta(minutes=7) for v in item['reservation_segments']]
    monkeypatch.setattr(medium,'_request_rows',lambda config,ids:[r for r in rows if r['id'] in ids])
    monkeypatch.setattr(medium,'_read',lambda config,statement,params=():[{'id':i,'service_components':snapshots[i]} for i in params[0]])
    monkeypatch.setattr(medium,'_effect_rows',lambda config,ids:[{'id':i,'projection_statuses':['DELIVERED','DELIVERED'] if defect=='extra_projection' else ['DELIVERED']} for i in ids])
    checks=adapter.checks(case('C25'),values,[],rows)
    assert all(c['passed'] for c in checks) is (defect=='none'),checks


def test_untagged_catalog_is_restored_and_unallowlisted_agents_block(fixture):
    adapter, values, calls, catalog, _ = fixture; adapter.prepare_catalog()
    adapter.arrange(case('C26'), values)
    assert catalog[1]['assigned_agent_ids']==[]
    adapter.cleanup_case()
    assert catalog[1]['assigned_agent_ids']==[7]
    adapter.config['allowlisted_emails']=[]
    calls.clear()
    with pytest.raises(SimulationError, match='recipient'):
        adapter.arrange(case('C26'), values)
    assert all(method=='GET' for method,_,_ in calls)


@pytest.fixture
def native_case(fixture, monkeypatch):
    adapter, values, _calls, _catalog, _policy = fixture
    adapter.prepare_catalog()
    requests, slots, staff = {}, [], {}
    original = adapter.client
    def transport(request):
        import json
        body=json.loads(request.content) if request.content else {}
        if request.url.path.endswith('/voice/tools'):
            args=body['arguments']
            if body['name']=='create_service_request':
                from datetime import timedelta
                names=args.get('services') or [args['service_type']]
                created=[];start=datetime.fromisoformat(args['booking_time'])
                for name in names:
                    identifier=50+len(requests)
                    key=next(k for k,s in adapter.state['services'].items() if s['name']==name)
                    requests[identifier]=row(adapter,key=key,identifier=identifier,start=start.isoformat(),staff=12 if key=='split' else 7)
                    requests[identifier]['calendar_event_id']=f'owned-event-{identifier}'
                    requests[identifier]['service_components']=[{'name':name,'duration_minutes':requests[identifier]['duration_minutes']}]
                    created.append({'service_request_id':identifier})
                    start+=timedelta(minutes=requests[identifier]['duration_minutes'])
                return httpx.Response(200,json={'result':{'success':True,'service_request_id':created[0]['service_request_id'],'appointments':created}})
            requests[args['appointment_id']].update(status='cancelled',reservation_id=None)
            return httpx.Response(200,json={'result':{'success':True}})
        if '/calendar/' in request.url.path:
            slot=next(s for s in slots if s['id']==int(request.url.path.split('/')[-1]))
            slot.update(is_booked=body['is_booked'],reservation_status='BLOCKED' if body['is_booked'] else 'AVAILABLE')
            return httpx.Response(200,json={'success':True})
        if request.method=='POST' and request.url.path.endswith('/agents'):
            staff.update(body,id=88,is_active=True,requests=0,oauth=0)
            return httpx.Response(201,json={'success':True,'id':88})
        if request.method=='DELETE' and request.url.path.endswith('/agents/88'):
            staff['is_active']=False
            return httpx.Response(200,json={'success':True})
        return original.request(request.method,str(request.url),json=body if request.content else None)
    adapter.client=httpx.Client(transport=httpx.MockTransport(transport))
    monkeypatch.setattr(medium,'_request_rows',lambda config,ids:[deepcopy(requests[i]) for i in sorted(ids) if i in requests])
    monkeypatch.setattr(medium,'_slots',lambda config,agent,start,end:[deepcopy(s) for s in slots if s['staff_agent_id']==agent and start<=datetime.fromisoformat(s['slot_datetime'])<end])
    monkeypatch.setattr(medium,'_effect_rows',lambda config,ids:[{'id':i,'projection_statuses':['DELIVERED'],
        'has_event':False,'active_count':0,'segment_count':0,'request_calendar_status':'DELETED','reservation_calendar_statuses':[]} for i in ids])
    def read(config,statement,params=()):
        if 'SELECT id,service_components' in statement:
            return [{'id':i,'service_components':requests[i]['service_components']} for i in params[0]]
        if 'FROM customers' in statement: return []
        if 'WHERE name=' in statement: return []
        if 'WHERE sa.id=' in statement: return [deepcopy(staff)]
        return [{'id':7,'email':'owned@example.test','google_email':'owned@example.test','phone_number':'+14242704893'}]
    monkeypatch.setattr(medium,'_read',read)
    return adapter,values,requests,slots,staff


def add_slots(slots,agent,minutes):
    from datetime import timedelta
    for i in range(0,minutes,15):
        slots.append({'id':700+len(slots),'staff_agent_id':agent,'slot_datetime':(datetime(2026,11,10,11)+timedelta(minutes=i)).isoformat(),
                      'is_booked':False,'reservation_status':'AVAILABLE','service_request_id':None,'active_reservation':False,'updated_at':'same'})


@pytest.mark.parametrize('cid,agent,duration',[('C24',12,60),('C29',7,30)])
def test_native_block_arrangement_and_exact_cleanup_restoration(native_case,cid,agent,duration):
    adapter,values,requests,slots,_=native_case
    add_slots(slots,agent,duration); original=deepcopy(slots)
    _,ids=adapter.arrange(case(cid),values)
    assert ids==([] if cid=='C24' else [50])
    assert all(s['is_booked'] for s in slots)
    assert all(b['owned'] and not b['restored'] for b in adapter.state['blocks'])
    assert all(c['passed'] for c in adapter.checks(case(cid),values,[],list(requests.values())))
    adapter.cleanup_case()
    assert slots==original
    assert all(b['restored'] for b in adapter.state['blocks'])
    assert all(r['status']=='cancelled' for r in requests.values())


def test_native_block_refuses_real_reserved_slot_without_mutation(native_case):
    adapter,values,_,slots,_=native_case
    add_slots(slots,12,60); slots[0]['active_reservation']=True
    with pytest.raises(SimulationError,match='reserved'):
        adapter.arrange(case('C24'),values)
    assert adapter.state['blocks']==[]


def test_block_cleanup_refuses_external_edit(native_case):
    adapter,values,_,slots,_=native_case; add_slots(slots,12,60)
    adapter.arrange(case('C24'),values); slots[0]['updated_at']='someone-else'
    with pytest.raises(SimulationError,match='changed'):
        adapter.cleanup_case()
    assert slots[0]['is_booked'] is True


@pytest.mark.parametrize('defect',['none','id','start','duration'])
def test_add_service_fixture_and_exact_consolidation_result(native_case,defect):
    from datetime import timedelta
    adapter,values,requests,_,_=native_case
    _,ids=adapter.arrange(case('C28'),values); assert ids==[50]
    result=requests[50]
    result['service_type']=adapter.state['services']['oil']['name']+', '+adapter.state['services']['second']['name']
    result.update(duration_minutes=90,segment_count=6,ends_at='2026-11-10T11:30:00',
                  reservation_segments=[datetime(2026,11,10,10)+timedelta(minutes=i) for i in range(0,90,15)])
    if defect=='id': result['id']=51; requests[51]=requests.pop(50)
    if defect=='start': result['booking_time']='2026-11-10T11:00:00'
    if defect=='duration': result['duration_minutes']=60
    assert all(c['passed'] for c in adapter.checks(case('C28'),values,[],list(requests.values()))) is (defect=='none')


@pytest.mark.parametrize('defect',['none','type','callback_time','callback_staff','callback_service','reservation'])
def test_appointment_plus_custom_callback_requires_both_owned_reservations(native_case,defect):
    adapter,values,requests,_,_=native_case; adapter.arrange(case('C32'),values)
    requests[50]=row(adapter,identifier=50)
    callback=row(adapter,identifier=51,start=values['callback_time'],duration=15)
    callback.update(service_type='Callback / Phone Consultation',booking_type='callback',issue_description=adapter.state['full_callback_issue'])
    requests[51]=callback
    if defect=='type': callback['booking_type']='appointment'
    if defect=='callback_time': callback['booking_time']='2026-11-10T15:00:00'
    if defect=='callback_staff': callback['staff_agent_id']=99
    if defect=='callback_service': callback['service_type']=adapter.state['services']['oil']['name']
    if defect=='reservation': callback['reservation_id']=None
    try:
        checks=adapter.checks(case('C32'),values,[],list(requests.values()))
    except SimulationError:
        assert defect in {'type','callback_time'}
    else:
        assert all(c['passed'] for c in checks) is (defect=='none')


def test_owned_inactive_staff_is_journaled_verified_and_retained(native_case):
    adapter,values,requests,_,staff=native_case
    adapter.arrange(case('C27'),values)
    assert staff['id']==88 and staff['is_active'] is False
    assert adapter.state['services']['oil']['assigned_agent_ids']==[7,88]
    assert [o['method'] for o in adapter.state['operations'][-3:]]==['POST','DELETE','PUT']
    requests[50]=row(adapter,identifier=50)
    assert all(c['passed'] for c in adapter.checks(case('C27'),values,[],list(requests.values())))
    adapter.cleanup_case()
    assert adapter.state['services']['oil']['assigned_agent_ids']==[7]
    assert adapter.state['full_inactive_staff']['cleanup_receipt'].startswith('owned inactive staff retained')
    assert staff['is_active'] is False


@pytest.mark.parametrize('cid', ['C17', 'C18'])
def test_nonviolating_native_buffer_refuses_lead_case(fixture, cid):
    adapter,values,_,_,policy=fixture; adapter.prepare_catalog()
    policy['min_booking_buffer_hours']=0
    policy['min_callback_buffer_hours']=0
    with pytest.raises(SimulationError,match='violating buffer'):
        adapter.arrange(case(cid),values)


def test_closed_day_requires_actual_native_closed_day(fixture):
    adapter,values,_,_,policy=fixture; adapter.prepare_catalog()
    policy['business_days']=list(range(7))
    with pytest.raises(SimulationError,match='no closed day'):
        adapter.arrange(case('C19'),values)


def test_timezone_case_requires_native_timezone_proof(fixture):
    adapter,values,_,_,policy=fixture; adapter.prepare_catalog()
    adapted,_=adapter.arrange(case('C21'),values)
    assert 'America/New_York' in adapted['scenario']
    assert values['appointment_time'] in adapted['scenario']
    policy['business_timezone']='UTC'
    with pytest.raises(SimulationError,match='timezone'):
        adapter.arrange(case('C21'),values)


def test_original_baseline_cannot_be_rebased_to_changed_current_booking(fixture,monkeypatch):
    adapter,values,calls,_,_=fixture; adapter.prepare_catalog()
    original=row(adapter,identifier=9)
    adapter.campaign.manifest['baseline']=[deepcopy(original)]
    adapter.original_ids={9}
    original['status']='cancelled'
    monkeypatch.setattr(medium,'_request_rows',lambda config,ids:[original] if ids else [])
    calls.clear()
    with pytest.raises(SimulationError,match='baseline changed'):
        adapter.arrange(case('C46'),values)
    assert all(method=='GET' for method,_,_ in calls)


def test_inactive_assignee_is_never_accepted(native_case):
    adapter,values,requests,_,_=native_case; adapter.arrange(case('C27'),values)
    requests[50]=row(adapter,identifier=50,staff=88)
    with pytest.raises(SimulationError,match='inactive staff state'):
        # Mirror the authoritative staff request count after the wrong assignment.
        native_case[-1]['requests']=1
        adapter.checks(case('C27'),values,[],list(requests.values()))


def test_blocked_addition_allows_only_async_calendar_projection_to_settle(native_case):
    adapter,values,requests,slots,_=native_case;add_slots(slots,7,30)
    adapter.arrange(case('C29'),values)
    requests[50]['calendar_integration_status']='PENDING_CALENDAR'
    requests[50]['request_calendar_status']='PENDING_CALENDAR'
    requests[50]['calendar_event_id']=None
    adapter.before_rows=deepcopy(list(requests.values()))
    requests[50].update(calendar_integration_status='CREATED',request_calendar_status='CREATED',calendar_event_id='settled-owned-event')
    assert all(c['passed'] for c in adapter.checks(case('C29'),values,[],list(requests.values())))


def test_custom_callback_without_run_issue_marker_cannot_become_owned(native_case):
    adapter,values,requests,_,_=native_case;adapter.arrange(case('C32'),values)
    requests[50]=row(adapter,identifier=50)
    callback=row(adapter,identifier=51,start=values['callback_time'],duration=15)
    callback.update(service_type='Callback / Phone Consultation',booking_type='callback',issue_description='unrelated symptom')
    requests[51]=callback
    with pytest.raises(SimulationError,match='callback issue'):
        adapter.checks(case('C32'),values,[],list(requests.values()))
    assert 51 not in adapter.owned_ids


def test_conflicting_existing_vehicle_blocks_before_any_fixture_write(fixture,monkeypatch):
    adapter,values,calls,_,_=fixture;adapter.prepare_catalog();calls.clear()
    def existing(config,statement,params=()):
        if 'FROM customers' in statement:
            return [{'id':5,'name':'Owned','make':'Toyota','model':'Camry','year':2020}]
        return []
    monkeypatch.setattr(medium,'_read',existing)
    with pytest.raises(SimulationError,match='existing vehicle'):
        adapter.arrange(case('C28'),values)
    assert all(method=='GET' for method,_,_ in calls)


@pytest.mark.parametrize('mode',['excluded','preblocked','unknown','timeout'])
def test_c22_requires_native_free_before_and_successful_exclusion_after(fixture,monkeypatch,mode):
    from live_simulations import deployed_full_google
    adapter,values,_,_,_=fixture;adapter.prepare_catalog()
    calls=[]
    class FakeBusy:
        def __init__(self,owner,client):self.owner=owner
        def prepare(self,start,end):
            calls.append('create');self.owner.state['full_google_busy']={'status':'observed'}
        def cleanup(self):self.owner.state['full_google_busy']['status']='deleted'
    monkeypatch.setattr(deployed_full_google,'GoogleBusy',FakeBusy)
    def available(when):
        if 'create' not in calls:return mode!='preblocked'
        if mode=='unknown':raise SimulationError('Native availability is unknown')
        return mode=='timeout'
    monkeypatch.setattr(adapter,'_available',available,raising=False)
    monkeypatch.setattr(medium,'_sleep',lambda seconds:None)
    counter=iter(range(1000))
    monkeypatch.setattr(medium,'_monotonic',lambda:next(counter))
    adapter.config['deployed_full_google']={'availability_timeout_seconds':1}
    if mode=='excluded':
        adapter.arrange(case('C22'),values)
        assert adapter.state['full_google_busy']['availability_proof']=='native_free_then_excluded'
    else:
        with pytest.raises(SimulationError):adapter.arrange(case('C22'),values)
        assert calls==([] if mode=='preblocked' else ['create'])


def test_c30_arranges_exact_owned_two_specialist_fixture(native_case):
    adapter,values,requests,_,_=native_case
    _,ids=adapter.arrange(case('C30'),values)
    assert len(ids)==2
    assert {requests[i]['staff_agent_id'] for i in ids}=={7,12}
    assert len(adapter.state['full_fixture_components'])==2


@pytest.mark.parametrize('defect',['none','whole_group','moved_companion','metadata','projection','still_active','missing_selected','selected_metadata'])
def test_c30_requires_explicit_cancelled_row_retired_projection_and_intact_companion(native_case,monkeypatch,defect):
    adapter,values,requests,_,_=native_case;adapter.arrange(case('C30'),values)
    original=deepcopy(requests)
    requests[50].update(status='cancelled',reservation_id=None,reservation_status=None,
                        starts_at=None,ends_at=None,segment_count=0,reservation_segments=[],
                        request_calendar_status='DELETED',calendar_integration_status=None,calendar_event_id=None)
    effect={'id':50,'has_event':True,'active_count':0,'segment_count':0,'request_calendar_status':'DELETED',
            'reservation_calendar_statuses':['DELETED'],'projection_statuses':['DELIVERED','DELIVERED']}
    if defect=='whole_group':requests[51]['status']='cancelled'
    if defect=='moved_companion':requests[51]['booking_time']='2026-11-10T11:15:00'
    if defect=='metadata':requests[51]['service_components'][0]['duration_minutes']=45
    if defect=='projection':effect['request_calendar_status']='PENDING_CALENDAR'
    if defect=='selected_metadata':requests[50]['service_components'][0]['duration_minutes']=30
    if defect=='still_active':requests[50]=original[50]
    if defect=='missing_selected':requests.pop(50)
    monkeypatch.setattr(medium,'_effect_rows',lambda config,ids:[effect])
    checks=adapter.checks(case('C30'),values,[],list(requests.values()))
    assert all(c['passed'] for c in checks) is (defect=='none'),checks


def test_component_reader_never_expands_owned_scope_or_adopts_incomplete_metadata(fixture,monkeypatch):
    from live_simulations import deployed_full_visits as visits
    adapter,_,_,_,_=fixture
    adapter.owned_ids={41};adapter.original_ids={9}
    calls=[]
    def read(config,statement,params):
        calls.append((statement,params));return []
    monkeypatch.setattr(medium,'_read',read)
    for ids in ({9},{42}):
        with pytest.raises(SimulationError,match='owned request IDs'):
            visits.components(adapter,ids)
    assert not calls
    with pytest.raises(SimulationError,match='snapshots are unavailable'):
        visits.components(adapter,{41})
    assert calls==[('SELECT id,service_components FROM service_requests WHERE id=ANY(%s) ORDER BY id',([41],))]


@pytest.mark.parametrize('defect',['none','appointment','wrong_staff','duration','contiguous','gap_grid','projection','merged','metadata','duplicate_event','extra_effect'])
def test_c31_keeps_two_qualified_callback_reservations_and_intentional_gap(fixture,monkeypatch,defect):
    adapter,values,_,_,_=fixture;adapter.prepare_catalog()
    monkeypatch.setattr(adapter,'_callback_visit_available',lambda when:True,raising=False)
    adapted,_=adapter.arrange(case('C31'),values)
    assert '15-minute callbacks' in adapted['scenario']
    assert '2026-11-10T14:30:00' in adapted['scenario']
    rows=[row(adapter,identifier=1,start=values['callback_time'],duration=15),
          row(adapter,key='split',identifier=2,start='2026-11-10T14:30:00',duration=15,staff=12)]
    for i,r in enumerate(rows):r.update(booking_type='callback',calendar_event_id=f'callback-{i}')
    snapshots={1:None,2:None}
    if defect=='appointment':rows[0]['booking_type']='appointment'
    if defect=='wrong_staff':rows[1]['staff_agent_id']=7
    if defect=='duration':rows[1]['duration_minutes']=60
    if defect=='contiguous':rows[1]['starts_at']=rows[1]['booking_time']='2026-11-10T14:15:00'
    if defect=='gap_grid':rows[1]['reservation_segments']=[datetime(2026,11,10,14,15)]
    if defect=='projection':rows[1]['request_calendar_status']='PENDING_CALENDAR'
    if defect=='duplicate_event':rows[1]['calendar_event_id']=rows[0]['calendar_event_id']
    if defect=='merged':rows.pop();snapshots.pop(2)
    if defect=='metadata':snapshots[1]=[{'name':rows[0]['service_type'],'duration_minutes':60}]
    monkeypatch.setattr(medium,'_request_rows',lambda config,ids:[r for r in rows if r['id'] in ids])
    monkeypatch.setattr(medium,'_read',lambda config,statement,params=():[{'id':i,'service_components':snapshots[i]} for i in params[0]])
    monkeypatch.setattr(medium,'_effect_rows',lambda config,ids:[{'id':i,'projection_statuses':['DELIVERED','DELIVERED'] if defect=='extra_effect' else ['DELIVERED']} for i in ids])
    checks=adapter.checks(case('C31'),values,[],rows)
    assert all(c['passed'] for c in checks) is (defect=='none'),checks


@pytest.mark.parametrize('defect',['closed','lead','grid','unavailable','unknown'])
def test_c31_missing_real_callback_prerequisite_blocks_before_any_owned_booking(fixture,monkeypatch,defect):
    adapter,values,calls,_,policy=fixture;adapter.prepare_catalog();calls.clear()
    if defect=='closed':values['callback_time']='2026-11-15T14:00:00'
    if defect=='lead':values['callback_time']='2026-11-09T10:15:00'
    if defect=='grid':values['callback_time']='2026-11-10T14:07:00'
    def available(when):
        if defect=='unknown':raise SimulationError('Native specialist callback availability is unknown')
        return defect!='unavailable'
    monkeypatch.setattr(adapter,'_callback_visit_available',available)
    with pytest.raises(SimulationError):adapter.arrange(case('C31'),values)
    assert not adapter.current_ids and not adapter.owned_ids
    assert all(method=='GET' for method,_,_ in calls)
    assert policy['min_callback_buffer_hours']==2
