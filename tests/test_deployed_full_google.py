"""Offline Google busy ownership, uncertainty, and conditional cleanup contracts."""
import json
from copy import deepcopy
from datetime import datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest

from live_simulations import deployed_full_google as google
from live_simulations import deployed_medium as medium
from live_simulations.core import SimulationError


@pytest.fixture
def fixture(monkeypatch):
    monkeypatch.setattr(medium,'_now',lambda config:datetime.fromisoformat('2026-11-09T10:00:00-05:00'))
    monkeypatch.setenv('BUSY_TEST_TOKEN', 'do-not-persist-this-token')
    config={'deployed_medium':{'ownership_id':'owned-google-fixture','technician_ids':[7,12]},
            'deployed_full_google':{'technician_id':7,'access_token_env':'BUSY_TEST_TOKEN',
                                    'account_email':'owned@example.test','calendar_id':'owned@example.test'},
            'allowlisted_emails':['owned@example.test'],'app_config':{'business_timezone':'America/New_York'}}
    saves=[]
    adapter=SimpleNamespace(config=config,state={},campaign=SimpleNamespace(manifest={'run_id':'a'*32}))
    adapter._save=lambda:saves.append(deepcopy(adapter.state))
    def guard():
        if adapter.state.get('blocked'):raise SimulationError('blocked')
    adapter._guard=guard
    monkeypatch.setattr(medium,'_read',lambda config,statement,params: [{'id':7,'email':'owned@example.test',
        'google_email':'owned@example.test','granted_scopes':'https://www.googleapis.com/auth/calendar','is_active':True}])
    event, calls, behavior={},[],{}
    def transport(request):
        body=json.loads(request.content) if request.content else None
        calls.append((request.method,str(request.url),body,dict(request.headers)))
        if request.url.path.endswith('/userinfo'):
            if behavior.get('expired'):return httpx.Response(401)
            return httpx.Response(200,json={'email':behavior.get('email','owned@example.test'),'email_verified':True})
        if '/calendarList/' in request.url.path:
            return httpx.Response(200,json={'id':'owned@example.test','primary':True,'accessRole':'owner'})
        if request.method=='GET':
            if behavior.get('lost_get'):raise httpx.ReadTimeout('do-not-persist-this-token',request=request)
            if behavior.get('preexisting') and not event:return httpx.Response(200,json={'id':'collision'})
            return httpx.Response(200,json=event) if event else httpx.Response(404)
        if request.method=='POST':
            assert saves[-1]['full_google_busy']['operations'][-1]['status']=='intent'
            event.update(body,etag='"version1"')
            if behavior.get('wrong_body'):event['summary']='another owner'
            if behavior.get('lost_post'):raise httpx.ReadTimeout('do-not-persist-this-token',request=request)
            return httpx.Response(200,json=event)
        if behavior.get('lost_delete'):raise httpx.ReadTimeout('do-not-persist-this-token',request=request)
        if behavior.get('precondition_failure'):return httpx.Response(412)
        assert request.headers['if-match']=='"version1"'
        event.clear();return httpx.Response(204)
    busy=google.GoogleBusy(adapter,httpx.Client(transport=httpx.MockTransport(transport)))
    start=datetime.fromisoformat('2026-11-10T10:00:00-05:00')
    return busy,adapter,start,event,calls,behavior,saves


def create(fixture):
    busy,_,start,*_=fixture
    busy.prepare(start,start+timedelta(hours=1))


def test_exact_owned_busy_creation_and_conditional_idempotent_cleanup(fixture):
    busy,adapter,_,event,calls,_,_=fixture;create(fixture)
    assert event['transparency']=='opaque' and not event.get('attendees')
    assert event['id']==busy.event_id and len(busy.event_id)==40
    assert all(c in '0123456789abcdef' for c in busy.event_id)
    assert 'sendUpdates=none' in next(url for method,url,_,_ in calls if method=='POST')
    busy.cleanup();busy.cleanup()
    assert not event
    assert len([c for c in calls if c[0]=='DELETE'])==1
    assert adapter.state['full_google_busy']['status']=='deleted'
    assert 'do-not-persist-this-token' not in json.dumps(adapter.state)


@pytest.mark.parametrize('defect',['wrong_owner','preexisting','wrong_readback','missing_token'])
def test_rejected_identity_collision_or_readback_never_adopted(fixture,monkeypatch,defect):
    _busy,adapter,_,_,calls,behavior,_=fixture
    if defect=='wrong_owner':behavior['email']='other@example.test'
    if defect=='preexisting':behavior['preexisting']=True
    if defect=='wrong_readback':behavior['wrong_body']=True
    if defect=='missing_token':monkeypatch.delenv('BUSY_TEST_TOKEN')
    with pytest.raises(SimulationError):create(fixture)
    assert not any(c[0]=='DELETE' for c in calls)
    if defect!='wrong_readback':assert not any(c[0]=='POST' for c in calls)
    else:assert adapter.state['blocked']


def test_unknown_post_is_journaled_redacted_and_never_retried(fixture):
    busy,adapter,_,_,calls,behavior,_=fixture;behavior['lost_post']=True
    with pytest.raises(SimulationError) as error:create(fixture)
    assert 'do-not-persist-this-token' not in str(error.value)+json.dumps(adapter.state)
    with pytest.raises(SimulationError):create(fixture)
    assert len([c for c in calls if c[0]=='POST'])==1
    assert adapter.state['full_google_busy']['operations'][-1]['status']=='unknown'
    with pytest.raises(SimulationError):busy.cleanup()
    assert not any(c[0]=='DELETE' for c in calls)


@pytest.mark.parametrize('defect',['etag','body','412'])
def test_cleanup_refuses_external_edit_or_precondition_failure(fixture,defect):
    busy,adapter,_,event,calls,behavior,_=fixture;create(fixture)
    if defect=='etag':event['etag']='"version2"'
    if defect=='body':event['description']='edited externally'
    if defect=='412':behavior['precondition_failure']=True
    with pytest.raises(SimulationError):busy.cleanup()
    assert adapter.state['blocked']
    assert len([c for c in calls if c[0]=='DELETE'])==(1 if defect=='412' else 0)


def test_already_removed_owned_event_cleanup_accepts_404(fixture):
    busy,adapter,_,event,calls,_,_=fixture;create(fixture);event.clear()
    busy.cleanup()
    assert adapter.state['full_google_busy']['status']=='deleted'
    assert not any(c[0]=='DELETE' for c in calls)


def test_expired_token_and_missing_stage_claim_never_create(fixture):
    _busy,adapter,_,_,calls,behavior,_=fixture
    behavior['expired']=True
    with pytest.raises(SimulationError):create(fixture)
    assert not any(c[0]=='POST' for c in calls)
    calls.clear()
    def guard():raise SimulationError('durable stage claim required')
    adapter._guard=guard
    with pytest.raises(SimulationError,match='stage claim'):create(fixture)
    assert calls==[]


@pytest.mark.parametrize('kind',['lost_get','lost_delete'])
def test_uncertain_cleanup_blocks_without_leaking_token(fixture,kind):
    busy,adapter,_,_,_,behavior,_=fixture;create(fixture);behavior[kind]=True
    with pytest.raises(SimulationError) as error:busy.cleanup()
    assert adapter.state['blocked']
    assert 'do-not-persist-this-token' not in str(error.value)+json.dumps(adapter.state)


@pytest.mark.parametrize('method',['GET','POST','DELETE'])
def test_provider_failure_traceback_never_exposes_access_token(fixture,method):
    import traceback

    busy,_adapter,_,_,_,behavior,_=fixture
    if method=='DELETE':
        create(fixture)
        behavior['lost_delete']=True
        action=busy.cleanup
    else:
        behavior['lost_get' if method=='GET' else 'lost_post']=True
        action=lambda:create(fixture)
    with pytest.raises(SimulationError) as caught:
        action()
    rendered=''.join(traceback.format_exception(caught.value))
    assert 'do-not-persist-this-token' not in rendered
    assert caught.value.__suppress_context__ is True
