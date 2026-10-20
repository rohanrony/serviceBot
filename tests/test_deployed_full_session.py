"""Captured REST/socket tests; synthetic HMAC and receipts are not live evidence."""
import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from live_simulations import deployed_full_session as session
from live_simulations.core import Budget, SimulationError


@pytest.fixture
def setup_and_cleanup_test_db():
    yield

@pytest.fixture
def fixture(tmp_path,monkeypatch):
    auth={'tier':'full','case_ids':[f'C{i:02}' for i in range(17,51)],'authorization_id':'offline-test','credit_ceiling':1000}
    manifest={'run_id':'a'*32,'campaign_agent_id':'agent-owned','stage_authorization':auth}
    folder=tmp_path/manifest['run_id'];folder.mkdir()
    campaign=SimpleNamespace(root=tmp_path,folder=folder,run_id=manifest['run_id'],manifest=manifest,
        config={},save=lambda:None)
    adapter=SimpleNamespace(campaign=campaign,config={'budget':{'native_session_credit_units_verified':True, 'verified_credit_units':True,
            'native_session_credit_subscription_tier':'legacy-test', 'monthly_credits':1000, 'reset_unix':4000000000}},
        state={'full_history':{'run_id':manifest['run_id'],'case_id':'C50','agent_id':'agent-owned','customer_id':7,
            'baseline_note_ids':[],'baseline_event_ids':[],'customer_phone':'+15550100001','customer_name':'Owner'}},_guard=lambda:None,_save=lambda:None)
    (tmp_path/'usage-ledger.json').write_text(json.dumps({'entries':[],'stage_authorizations':[{**auth,'run_id':manifest['run_id']}]}))
    events=[{'type':'conversation_initiation_metadata','conversation_initiation_metadata_event':{'conversation_id':'actual-session'}},
        {'type':'ping','ping_event':{'event_id':42}},{'type':'agent_response','agent_response_event':{'agent_response':'Hello'}}]
    sent=[];closed=[];requests=[];quota_reads=[]
    subscription={'tier':'legacy-test','status':'active','character_count':0,'character_limit':1000,
        'character_refresh_period':'monthly_period','next_character_count_reset_unix':4000000000}
    class Socket:
        def send(self,value):sent.append(json.loads(value))
        def recv(self,timeout):return json.dumps(events.pop(0))
        def close(self):closed.append(True)
    detail={'conversation_id':'actual-session','agent_id':'agent-owned','status':'done','transcript':[{'role':'user','message':'hello'}],
        'user_id':'+15550100001','conversation_initiation_client_data':{'dynamic_variables':{},'user_id':'+15550100001'},'metadata':{'cost':3}}
    class Provider:
        def subscription(self):
            quota_reads.append(True)
            return deepcopy(subscription)
        def request(self,method,path):
            requests.append((method,path))
            if 'get-signed-url' in path:return {'signed_url':'wss://api.elevenlabs.io/v1/convai/conversation?signature=must-stay-secret','conversation_id':'actual-session'}
            detail['conversation_initiation_client_data']['dynamic_variables']=deepcopy(sent[0]['dynamic_variables'])
            return deepcopy(detail)
    monkeypatch.setattr(session.causal.medium,'_read',lambda *args:[{'id':7,'name':'Owner','phone':'+15550100001'}])
    monkeypatch.setattr(session.causal,'observe_history',lambda *a,**kw:{'synthetic':True})
    monkeypatch.setattr(session.causal,'verify_native_history',lambda observation,provider,**kw:provider['conversation_id']=='actual-session')
    return SimpleNamespace(adapter=adapter,provider=Provider(),socket_factory=lambda url:Socket(),events=events,
        sent=sent,closed=closed,requests=requests,detail=detail,tmp=tmp_path,
        quota_reads=quota_reads,subscription=subscription)


def run(f):
    return session.execute(f.adapter,provider=f.provider,socket_factory=f.socket_factory,
        credit_reader=lambda detail:detail['metadata']['cost'],budget=Budget(1000,'full',1000,credit_ceiling=1000),estimate=10,script=['hello'],max_events=5,max_polls=2)


def test_real_session_api_shape_handshake_ledger_and_secret_hygiene(fixture):
    f=fixture
    result=run(f)
    assert result['history_verified'] is True and result['native_acceptance']=='unverified'
    assert f.requests[0]==('GET','/v1/convai/conversation/get-signed-url?agent_id=agent-owned&include_conversation_id=true')
    assert f.requests[1]==('GET','/v1/convai/conversations/actual-session')
    assert f.sent[0]['type']=='conversation_initiation_client_data'
    assert f.sent[0]['user_id']=='+15550100001'
    assert not any(k.startswith('system__') for k in f.sent[0]['dynamic_variables'])
    assert f.sent[1]=={'type':'user_message','text':'hello'}
    assert f.sent[2]=={'type':'pong','event_id':42}
    assert f.closed==[True]
    retained=''.join(p.read_text() for p in f.tmp.rglob('*.json'))
    assert 'must-stay-secret' not in retained and 'signed_url' not in retained
    entry=json.loads((f.tmp/'usage-ledger.json').read_text())['entries'][0]
    assert entry['billing_id']=='conversation:actual-session' and entry['unsettled'] is False
    assert 'invocation_id' not in entry


def test_unverified_units_stop_before_signed_url_or_socket(fixture):
    fixture.adapter.config['budget']['native_session_credit_units_verified']=False
    with pytest.raises(SimulationError,match='credit units'):run(fixture)
    assert fixture.requests==[] and fixture.sent==[]


def test_no_conversation_id_cannot_fallback_to_test_id_or_reconnect(fixture):
    f=fixture
    f.provider.request=lambda *args:{'signed_url':'wss://api.elevenlabs.io/v1/convai/conversation?signature=secret','test_run_id':'not-a-session'}
    result=run(f)
    assert result['global_stop'] is True and not f.sent
    with pytest.raises(SimulationError,match='already attempted'):run(f)
    entry=json.loads((f.tmp/'usage-ledger.json').read_text())['entries'][0]
    assert entry['unsettled'] is True and 'provider_conversation_id' not in entry


def test_foreign_handshake_closes_owned_socket_and_never_claims_history(fixture):
    f=fixture;f.events[0]['conversation_initiation_metadata_event']['conversation_id']='foreign'
    result=run(f)
    assert result['global_stop'] is True and result['history_verified'] is False
    assert f.closed==[True]
    assert len(f.requests)==1


def test_intent_and_unknown_charge_precede_signed_url_and_cid_precedes_connect(fixture):
    f=fixture;actual_request=f.provider.request;actual_factory=f.socket_factory
    def request(method,path):
        ledger=json.loads((f.tmp/'usage-ledger.json').read_text())
        assert len(ledger['entries'])==1 and ledger['entries'][0]['unsettled'] is True
        assert (f.adapter.campaign.folder/'C50-native-session-intent.json').exists()
        return actual_request(method,path)
    def factory(url):
        entry=json.loads((f.tmp/'usage-ledger.json').read_text())['entries'][0]
        assert entry['provider_conversation_id']=='actual-session'
        assert entry['billing_id']=='conversation:actual-session'
        return actual_factory(url)
    f.provider.request=request;f.socket_factory=factory
    assert run(f)['history_verified']


def test_unknown_native_credits_stay_unsettled_and_reconcile_get_only(fixture):
    f=fixture;f.detail['metadata']['cost']=None
    assert run(f)['status']=='unknown_actual_credits'
    entry=json.loads((f.tmp/'usage-ledger.json').read_text())['entries'][0]
    assert entry['unsettled'] is True and 'credits' not in entry
    f.detail['metadata']['cost']=4
    before=len(f.requests)
    result=session.reconcile(f.adapter,provider=f.provider,credit_reader=lambda detail:detail['metadata']['cost'])
    assert result['history_verified'] is True
    assert all(path=='/v1/convai/conversations/actual-session' for _,path in f.requests[before:])
    assert len(f.closed)==1


def test_cross_run_dynamic_variables_cannot_create_history_provenance(fixture):
    f=fixture;actual=f.provider.request
    def request(method,path):
        value=actual(method,path)
        if 'get-signed-url' not in path:
            value['conversation_initiation_client_data']['dynamic_variables']['run_id']='foreign'
        return value
    f.provider.request=request
    result=run(f)
    assert result['history_verified'] is False and result['global_stop'] is True
    assert json.loads((f.tmp/'usage-ledger.json').read_text())['entries'][0]['unsettled'] is True


def test_duplicate_provider_cid_cannot_adopt_other_run_or_open_socket(fixture):
    f=fixture
    path=f.tmp/'usage-ledger.json'
    ledger=json.loads(path.read_text())
    ledger['entries']=[{'run_id': 'other-run','case_id': 'C50','unsettled': False,'resource_type': 'conversation',
        'provider_conversation_id': 'actual-session','billing_id': 'conversation:actual-session','credits': 1}]
    path.write_text(json.dumps(ledger))
    result=run(f)
    assert result['global_stop'] is True and f.sent==[]
    assert len(json.loads(path.read_text())['entries'])==2


def test_unknown_close_keeps_charge_unknown_until_get_reconciliation(fixture):
    f=fixture;factory=f.socket_factory
    def socket_factory(url):
        socket=factory(url)
        def close():raise RuntimeError('signature=must-stay-secret')
        socket.close=close
        return socket
    f.socket_factory=socket_factory
    result=run(f)
    assert result['global_stop'] and result['status']=='native_session_effect_unknown'
    assert len(f.requests)==1
    assert 'must-stay-secret' not in ''.join(p.read_text() for p in f.tmp.rglob('*.json'))
    assert session.reconcile(f.adapter,provider=f.provider,credit_reader=lambda detail:detail['metadata']['cost'])['history_verified']


@pytest.mark.parametrize('event',[[],{'type':'agent_response','agent_response_event':{'agent_response':'before handshake'}},
    {'type':'conversation_initiation_metadata','conversation_initiation_metadata_event':{'conversation_id':True}},
    {'type':'ping','ping_event':{'event_id':False}}])
def test_malformed_or_unpaired_events_fail_without_polling_or_secret_diagnostics(fixture,event):
    f=fixture;f.events[:]=[event]
    result=run(f)
    assert not result['history_verified'] and result['global_stop']
    assert f.closed==[True] and len(f.requests)==1


def test_native_budget_gate_precedes_all_provider_effects(fixture):
    f=fixture
    with pytest.raises(SimulationError,match='budget'):
        session.execute(f.adapter,provider=f.provider,socket_factory=f.socket_factory,
            credit_reader=lambda detail:3,budget=Budget(100,'full',0),estimate=1,script=['hello'])
    assert f.requests==[] and f.sent==[]


def test_native_phone_drift_blocks_before_signed_url_or_socket(fixture,monkeypatch):
    f=fixture
    monkeypatch.setattr(session.causal.medium,'_read',lambda *args:[{'id':7,'name':'Owner','phone':'+15550100002'}])
    with pytest.raises(SimulationError,match='phone or name changed'):run(f)
    assert f.requests==[] and f.sent==[]


def test_provider_user_identity_must_match_native_customer(fixture):
    f=fixture;actual=f.provider.request
    def request(method,path):
        value=actual(method,path)
        if 'get-signed-url' not in path:value['user_id']='+15550100002'
        return value
    f.provider.request=request
    assert run(f)['history_verified'] is False


def test_unknown_credit_reader_exception_diagnostics_are_never_retained(fixture):
    f=fixture
    def credits(detail):raise RuntimeError('Bearer must-stay-secret')
    result=session.execute(f.adapter,provider=f.provider,socket_factory=f.socket_factory,credit_reader=credits,
        budget=Budget(1000,'full',1000,credit_ceiling=1000),estimate=10,script=['hello'])
    assert result['global_stop'] is True
    assert 'must-stay-secret' not in ''.join(p.read_text() for p in f.tmp.rglob('*.json'))


def test_missing_or_foreign_stage_claim_cannot_open_native_session(fixture):
    f=fixture;path=f.tmp/'usage-ledger.json';ledger=json.loads(path.read_text())
    ledger['stage_authorizations'][0]['run_id']='foreign';path.write_text(json.dumps(ledger))
    with pytest.raises(SimulationError,match='claim identity'):run(f)
    assert f.requests==[] and f.sent==[]


def test_reconcile_settled_charge_conflict_is_not_silently_overwritten(fixture):
    f=fixture;assert run(f)['history_verified']
    f.detail['metadata']['cost']=5
    with pytest.raises(SimulationError,match='credits conflict'):
        session.reconcile(f.adapter,provider=f.provider,credit_reader=lambda detail:detail['metadata']['cost'])
    assert json.loads((f.tmp/'usage-ledger.json').read_text())['entries'][0]['credits']=='3'


def test_compiled_socket_factory_is_bounded_and_never_uses_proxy_or_global_logger(monkeypatch):
    import websockets.sync.client
    calls=[];owned=object()
    monkeypatch.setattr(websockets.sync.client,'connect',lambda url,**kw:calls.append((url,kw)) or owned)
    assert session.native_socket_factory('wss://api.elevenlabs.io/v1/convai/conversation?signature=private') is owned
    assert calls[0][1]['proxy'] is None and calls[0][1]['open_timeout']==10 and calls[0][1]['close_timeout']==5
    assert calls[0][1]['max_size']==1000000
    assert calls[0][1]['logger'].isEnabledFor(50) is False


def test_compiled_reader_settles_and_reconciles_exact_charge(fixture):
    f = fixture
    result = session.execute(f.adapter, provider=f.provider, socket_factory=f.socket_factory,
        credit_reader=session.native_credit_reader,
        budget=Budget(1000, 'full', 1000, credit_ceiling=1000), estimate=10, script=['hello'])
    assert result['history_verified'] is True
    first = json.loads((f.tmp/'usage-ledger.json').read_text())['entries'][0]
    assert first['credits'] == '3' and first['unsettled'] is False
    assert first['credit_source'] == 'conversation.metadata.cost' and first['credit_units'] == 'credits'
    intent = json.loads((f.adapter.campaign.folder/'C50-native-session-intent.json').read_text())
    assert intent['credit_contract']['subscription_tier'] == 'legacy-test'
    assert session.reconcile(f.adapter, provider=f.provider,
        credit_reader=session.native_credit_reader)['history_verified'] is True
    assert json.loads((f.tmp/'usage-ledger.json').read_text())['entries'][0] == first
    assert len(f.quota_reads) == 1
    assert sum('get-signed-url' in path for _, path in f.requests) == 1


@pytest.mark.parametrize('change', ['headroom', 'tier', 'reset', 'unknown'])
def test_fresh_quota_denies_before_intent_signed_url_or_socket(fixture, change):
    f = fixture
    if change == 'headroom': f.subscription['character_count'] = 995
    elif change == 'tier': f.subscription['tier'] = 'other-plan'
    elif change == 'reset': f.subscription['next_character_count_reset_unix'] += 1
    else:
        def failed(): raise RuntimeError('private-provider-text')
        f.provider.subscription = failed
    with pytest.raises(SimulationError): run(f)
    assert f.requests == [] and f.sent == []
    assert not (f.adapter.campaign.folder/'C50-native-session-intent.json').exists()
    assert json.loads((f.tmp/'usage-ledger.json').read_text())['entries'] == []


@pytest.mark.parametrize('remaining,used,expected', [(1000, 500, 500), (100, 0, 100)])
def test_fresh_quota_never_replenishes_known_budget(fixture, remaining, used, expected):
    f = fixture
    f.subscription['character_count'] = used
    budget = Budget(1000, 'full', remaining, credit_ceiling=1000)
    session.execute(f.adapter, provider=f.provider, socket_factory=f.socket_factory,
        credit_reader=session.native_credit_reader, budget=budget, estimate=10, script=['hello'])
    assert budget.remaining == expected


@pytest.mark.parametrize('amount', [None, 0, True, '3', 3.1])
def test_compiled_totals_preserve_unknown_and_explicit_zero(fixture, amount):
    f = fixture; f.detail['metadata']['cost'] = amount
    result = session.execute(f.adapter, provider=f.provider, socket_factory=f.socket_factory,
        credit_reader=session.native_credit_reader,
        budget=Budget(1000, 'full', 1000, credit_ceiling=1000), estimate=10, script=['hello'])
    entry = json.loads((f.tmp/'usage-ledger.json').read_text())['entries'][0]
    if amount == 0 and type(amount) is int:
        assert entry['credits'] == '0' and entry['unsettled'] is False
    else:
        assert entry['unsettled'] is True and 'credits' not in entry
        assert result['global_stop'] is True and result['status'] == 'unknown_actual_credits'


def test_compiled_failed_conversation_settles_cost_without_functional_success(fixture):
    f = fixture; f.detail['status'] = 'failed'
    result = session.execute(f.adapter, provider=f.provider, socket_factory=f.socket_factory,
        credit_reader=session.native_credit_reader,
        budget=Budget(1000, 'full', 1000, credit_ceiling=1000), estimate=10, script=['hello'])
    assert result['history_verified'] is False and result['global_stop'] is True
    entry = json.loads((f.tmp/'usage-ledger.json').read_text())['entries'][0]
    assert entry['credits'] == '3' and entry['unsettled'] is False


def test_compiled_reconcile_after_rollover_uses_only_existing_conversation_get(fixture):
    f = fixture; f.detail['metadata']['cost'] = None
    result = session.execute(f.adapter, provider=f.provider, socket_factory=f.socket_factory,
        credit_reader=session.native_credit_reader,
        budget=Budget(1000, 'full', 1000, credit_ceiling=1000), estimate=10, script=['hello'])
    assert result['global_stop'] is True
    requests_before = len(f.requests)
    f.detail['metadata']['cost'] = 0
    f.adapter.config['budget']['reset_unix'] = 1
    def forbidden(): raise AssertionError('Reconciliation must not fetch new admission quota')
    f.provider.subscription = forbidden
    assert session.reconcile(f.adapter, provider=f.provider,
        credit_reader=session.native_credit_reader)['history_verified'] is True
    assert f.requests[requests_before:] == [('GET', '/v1/convai/conversations/actual-session')]
    assert json.loads((f.tmp/'usage-ledger.json').read_text())['entries'][0]['credits'] == '0'


def test_compiled_native_charge_reaches_outer_budget_once(fixture):
    from live_simulations import deployed_full_execution as execution
    from live_simulations.runner import campaign_lock

    f = fixture; ledger = {'entries': []}
    budget = Budget(1000, 'full', 1000, credit_ceiling=1000)
    f.adapter.execute_c50 = lambda **kw: session.execute(f.adapter,
        provider=kw['provider'], socket_factory=f.socket_factory,
        credit_reader=session.native_credit_reader, budget=kw['budget'], estimate=10, script=['hello'])
    with campaign_lock(f.tmp):
        execution.run_c50(f.adapter, provider=f.provider, budget=budget, ledger=ledger,
            campaign=f.adapter.campaign, estimate=10)
    assert budget.spent == 3 and budget.remaining == 997 and not budget.unknown
    assert budget.settled == {'conversation:actual-session'}
    assert len(ledger['entries']) == 1 and ledger['entries'][0]['credits'] == '3'
    f.adapter.execute_c50 = lambda **kw: session.reconcile(f.adapter,
        provider=kw['provider'], credit_reader=session.native_credit_reader)
    with campaign_lock(f.tmp):
        execution.run_c50(f.adapter, provider=f.provider, budget=budget, ledger=ledger,
            campaign=f.adapter.campaign, estimate=10)
    assert budget.spent == 3 and budget.remaining == 997
    assert len(f.quota_reads) == 1 and len(ledger['entries']) == 1


def test_c50_reconciliation_uses_compiled_default_after_restart(fixture):
    f = fixture
    session.execute(f.adapter, provider=f.provider, socket_factory=f.socket_factory,
        credit_reader=session.native_credit_reader,
        budget=Budget(1000, 'full', 1000, credit_ceiling=1000), estimate=10, script=['hello'])
    assert not hasattr(f.adapter, 'native_session_credit_reader')
    requests_before = len(f.requests)
    checks = session.causal.checks(f.adapter, 'C50', {}, [], [], provider=f.provider)
    assert checks and all(check['passed'] for check in checks)
    assert len(f.quota_reads) == 1
    assert f.requests[requests_before:] == [('GET', '/v1/convai/conversations/actual-session')]


def test_compiled_unknown_charge_blocks_outer_budget(fixture):
    from live_simulations import deployed_full_execution as execution
    from live_simulations.runner import campaign_lock

    f = fixture; f.detail['metadata']['cost'] = None; ledger = {'entries': []}
    budget = Budget(1000, 'full', 1000, credit_ceiling=1000)
    f.adapter.execute_c50 = lambda **kw: session.execute(f.adapter,
        provider=kw['provider'], socket_factory=f.socket_factory,
        credit_reader=session.native_credit_reader, budget=kw['budget'], estimate=10, script=['hello'])
    with campaign_lock(f.tmp):
        result = execution.run_c50(f.adapter, provider=f.provider, budget=budget,
            ledger=ledger, campaign=f.adapter.campaign, estimate=10)
    assert result['global_stop'] is True and budget.unknown is True
    assert budget.spent == 0 and not budget.can_start(1)
    assert len(ledger['entries']) == 1 and ledger['entries'][0]['unsettled'] is True


def _management_fixture(f, monkeypatch):
    from live_simulations import deployed, runner
    f.detail['metadata']['cost'] = None
    session.execute(f.adapter, provider=f.provider, socket_factory=f.socket_factory,
        credit_reader=session.native_credit_reader,
        budget=Budget(1000, 'full', 1000, credit_ceiling=1000), estimate=10, script=['hello'])
    config=f.adapter.config
    config.update(artifact_root=str(f.tmp),deployed_url='https://synthetic.example')
    manifest=f.adapter.campaign.manifest
    manifest.update(target='deployed',deployed_url=config['deployed_url'],status='incomplete',
        results=[],invocations=[],deployed_medium=f.adapter.state)
    manifest['deployed_medium']['blocked']=True
    (f.adapter.campaign.folder/'manifest.json').write_text(json.dumps(manifest))
    monkeypatch.setattr(runner,'secret',lambda *a:'synthetic-key')
    monkeypatch.setattr(runner,'ElevenLabs',lambda *a:f.provider)
    f.provider.subscription=lambda:pytest.fail('Financial recovery must not fetch quota')
    f.requests.clear()
    return lambda:deployed.manage(config,manifest['run_id'],'reconcile')


def test_management_settles_native_charge_with_blocked_fixtures_and_preserves_other_entries(fixture,monkeypatch):
    f=fixture; manage=_management_fixture(f,monkeypatch)
    path=f.tmp/'usage-ledger.json'; ledger=json.loads(path.read_text())
    other={'run_id':'other','credits':'8','unsettled':False}
    ledger['entries'].append(other);path.write_text(json.dumps(ledger))
    f.detail['metadata']['cost']=0
    assert manage()==0
    assert manage()==0
    ledger=json.loads(path.read_text())
    assert ledger['entries'][0]['unsettled'] is False and ledger['entries'][0]['credits']=='0'
    assert ledger['entries'][1]==other
    manifest=json.loads((f.adapter.campaign.folder/'manifest.json').read_text())
    assert manifest['spent_credits']=='0' and manifest['unsettled_usage'] is False
    assert manifest['deployed_medium']['blocked'] is True
    assert f.requests==[('GET','/v1/convai/conversations/actual-session')]


@pytest.mark.parametrize('damage',['unknown_id','missing_units','claim_drift','malformed','provider_error'])
def test_management_native_recovery_fails_closed(fixture,monkeypatch,damage):
    f=fixture; manage=_management_fixture(f,monkeypatch)
    path=f.tmp/'usage-ledger.json';ledger=json.loads(path.read_text())
    if damage=='unknown_id': ledger['entries'][0].pop('provider_conversation_id')
    elif damage=='missing_units': f.adapter.config['budget']['verified_credit_units']=False
    elif damage=='claim_drift': ledger['stage_authorizations'][0]['run_id']='foreign'
    elif damage=='malformed': f.detail['metadata']['cost']=True
    else:
        def failed(*args): raise RuntimeError('private-provider-text')
        f.provider.request=failed
    path.write_text(json.dumps(ledger))
    with pytest.raises(SimulationError) as error: manage()
    assert 'private-provider-text' not in str(error.value)
    ledger=json.loads(path.read_text())
    assert ledger['entries'][0]['unsettled'] is True and 'credits' not in ledger['entries'][0]
    assert all(method=='GET' and url=='/v1/convai/conversations/actual-session' for method,url in f.requests)


def test_management_retains_partial_native_settlement_when_other_charge_is_pending(fixture,monkeypatch):
    f=fixture;manage=_management_fixture(f,monkeypatch)
    path=f.tmp/'usage-ledger.json';ledger=json.loads(path.read_text())
    other={'run_id':f.adapter.campaign.run_id,'case_id':'C17','unsettled':True,'invocation_id':'pending-test'}
    ledger['entries'].append(other);path.write_text(json.dumps(ledger))
    f.detail['metadata']['cost']=7
    f.provider.get=lambda invocation:{'test_runs':[{'status':'pending'}]}
    with pytest.raises(SimulationError,match='still pending'):manage()
    ledger=json.loads(path.read_text())
    assert ledger['entries'][0]['credits']=='7' and ledger['entries'][0]['unsettled'] is False
    assert ledger['entries'][1]==other
    manifest=json.loads((f.adapter.campaign.folder/'manifest.json').read_text())
    assert manifest['spent_credits']=='7' and manifest['unsettled_usage'] is True
    assert manifest['deployed_medium']['blocked'] is True


def test_management_rejects_changed_retained_intent_before_provider_get(fixture,monkeypatch):
    f=fixture;manage=_management_fixture(f,monkeypatch)
    path=f.adapter.campaign.folder/'C50-native-session-intent.json'
    intent=json.loads(path.read_text());intent['baseline']['customer_id']=99
    path.write_text(json.dumps(intent))
    with pytest.raises(SimulationError):manage()
    assert f.requests==[]
    assert json.loads((f.tmp/'usage-ledger.json').read_text())['entries'][0]['unsettled'] is True


def test_management_persists_discovered_invocation_before_pending_read(fixture,monkeypatch):
    f=fixture;manage=_management_fixture(f,monkeypatch)
    path=f.tmp/'usage-ledger.json';ledger=json.loads(path.read_text())
    ledger['entries'].append({'run_id':f.adapter.campaign.run_id,'case_id':'C17',
        'unsettled':True,'test_id':'owned-test'})
    path.write_text(json.dumps(ledger));f.detail['metadata']['cost']=3
    actual=f.provider.request;discoveries=[]
    def request(method,url):
        if 'test-invocations?' in url:
            discoveries.append(url)
            return {'results':[{'id':'discovered-invocation'}]}
        return actual(method,url)
    def get(invocation):
        assert invocation=='discovered-invocation'
        assert json.loads(path.read_text())['entries'][1]['invocation_id']==invocation
        return {'test_runs':[{'status':'pending'}]}
    f.provider.request=request;f.provider.get=get
    for _ in range(2):
        with pytest.raises(SimulationError,match='still pending'):manage()
    assert discoveries==['/v1/convai/test-invocations?test_id=owned-test']
    assert json.loads(path.read_text())['entries'][1]['invocation_id']=='discovered-invocation'


def test_management_financial_recovery_does_not_require_current_customer_database(fixture,monkeypatch):
    f=fixture;manage=_management_fixture(f,monkeypatch)
    f.detail['metadata']['cost']=4
    monkeypatch.setattr(session.causal.medium,'_read',lambda *a:pytest.fail('Financial recovery must not query current customer DB'))
    assert manage()==0
    entry=json.loads((f.tmp/'usage-ledger.json').read_text())['entries'][0]
    assert entry['unsettled'] is False and entry['credits']=='4'


@pytest.mark.parametrize('provider_phone',['+15550100001','+15550100002'])
def test_management_customer_drift_uses_original_provider_identity(fixture,monkeypatch,provider_phone):
    f=fixture;manage=_management_fixture(f,monkeypatch)
    f.detail['metadata']['cost']=4
    f.detail['user_id']=provider_phone
    monkeypatch.setattr(session.causal.medium,'_read',lambda *a:[{'id':7,'name':'Changed','phone':'+15550109999'}])
    if provider_phone=='+15550100001':
        assert manage()==0
    else:
        with pytest.raises(SimulationError,match='Native conversation charges remain unverified'):manage()
    entry=json.loads((f.tmp/'usage-ledger.json').read_text())['entries'][0]
    assert entry['unsettled'] is (provider_phone!='+15550100001')


@pytest.mark.parametrize('key,value',[('customer_phone','15550100001'),('customer_phone',True),
    ('customer_phone','+1555010000'),('customer_name','   '),('customer_name',None)])
def test_management_malformed_saved_customer_identity_stops_before_get(fixture,monkeypatch,key,value):
    f=fixture;manage=_management_fixture(f,monkeypatch)
    path=f.adapter.campaign.folder/'manifest.json'
    manifest=json.loads(path.read_text());manifest['deployed_medium']['full_history'][key]=value
    path.write_text(json.dumps(manifest))
    monkeypatch.setattr(session.causal.medium,'_read',lambda *a:pytest.fail('No customer DB needed'))
    with pytest.raises(SimulationError,match='saved customer identity'):manage()
    assert f.requests==[]


@pytest.mark.parametrize('outcome',['pending','missing_cost','provider_failure'])
def test_management_unresolved_native_charge_raises_and_persists_summary(fixture,monkeypatch,outcome):
    f=fixture;manage=_management_fixture(f,monkeypatch)
    path=f.tmp/'usage-ledger.json';ledger=json.loads(path.read_text())
    settled={'run_id':f.adapter.campaign.run_id,'case_id':'C17','unsettled':False,'credits':'9'}
    ledger['entries'].append(settled);path.write_text(json.dumps(ledger))
    if outcome=='pending':f.detail['status']='processing'
    if outcome=='provider_failure':
        def failed(*a):raise RuntimeError('private-provider-error')
        f.provider.request=failed
    with pytest.raises(SimulationError,match='Native conversation charges remain unverified') as error:manage()
    assert 'private-provider-error' not in str(error.value)
    ledger=json.loads(path.read_text())
    assert ledger['entries'][0]['unsettled'] is True and ledger['entries'][1]==settled
    manifest=json.loads((f.adapter.campaign.folder/'manifest.json').read_text())
    assert manifest['spent_credits']=='9' and manifest['unsettled_usage'] is True


def test_management_foreign_unknown_conversation_does_not_trigger_recovery(fixture,monkeypatch):
    f=fixture;manage=_management_fixture(f,monkeypatch)
    f.detail['metadata']['cost']=3
    path=f.tmp/'usage-ledger.json';ledger=json.loads(path.read_text())
    foreign={'run_id':'foreign','case_id':'C50','resource_type':'conversation','unsettled':True}
    ledger['entries'].append(foreign);path.write_text(json.dumps(ledger))
    assert manage()==0
    assert json.loads(path.read_text())['entries'][1]==foreign
    assert f.requests==[('GET','/v1/convai/conversations/actual-session')]


@pytest.mark.parametrize('damage',['missing','duplicate','identity_changed','missing_credits'])
def test_management_requires_exact_settled_native_entry_after_callback(fixture,monkeypatch,damage):
    f=fixture;manage=_management_fixture(f,monkeypatch)
    path=f.tmp/'usage-ledger.json'
    def changed(campaign,provider):
        ledger=json.loads(path.read_text());entry=ledger['entries'][0]
        entry.update(unsettled=False,credits='3')
        if damage=='missing':ledger['entries']=[]
        elif damage=='duplicate':ledger['entries'].append(deepcopy(entry))
        elif damage=='identity_changed':entry['billing_id']='conversation:foreign'
        else:entry.pop('credits')
        path.write_text(json.dumps(ledger))
        return {'status':'pretend-success'}
    monkeypatch.setattr(session,'reconcile_campaign',changed)
    with pytest.raises(SimulationError,match='Native conversation charges remain unverified'):manage()
    assert f.requests==[]
    manifest=json.loads((f.adapter.campaign.folder/'manifest.json').read_text())
    assert manifest['unsettled_usage'] is True


def test_management_only_foreign_unknown_conversation_is_skipped(fixture,monkeypatch):
    f=fixture;manage=_management_fixture(f,monkeypatch)
    path=f.tmp/'usage-ledger.json';ledger=json.loads(path.read_text())
    ledger['entries'][0]['run_id']='foreign'
    ledger['entries'][0].pop('provider_conversation_id')
    path.write_text(json.dumps(ledger));before=deepcopy(ledger)
    assert manage()==0
    assert json.loads(path.read_text())==before and f.requests==[]
