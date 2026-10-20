"""Offline full-stage admission and dispatch; no credentials or live clients."""
from types import SimpleNamespace

import pytest

from live_simulations import deployed_full_execution as execution
from live_simulations.core import SimulationError


@pytest.fixture
def setup_and_cleanup_test_db():
    yield


def test_configuration_ready_flags_never_replace_compiled_native_observer():
    with pytest.raises(SimulationError,match='observer'):
        execution.prerequisites({'ready':True},None,[],[],SimpleNamespace())


def test_observer_requires_every_case_and_no_false_or_unknown_checks():
    cases=[{'id':cid} for cid in execution.FULL_IDS]
    module=SimpleNamespace(SUPPORTED_CASE_IDS=execution.FULL_IDS,native_prerequisites=lambda *args:{cid:[{'name':'permission','passed':True}] for cid in execution.FULL_IDS})
    assert execution.prerequisites({},None,cases,[],module)==[]
    module.native_prerequisites=lambda *args:{cid:[{'name':'permission','passed':True}] for cid in execution.FULL_IDS[:-1]}
    assert execution.prerequisites({},None,cases,[],module)


def test_c48_reserve_is_positive_and_included_before_first_case():
    assert execution.total_estimate({'budget':{'c48_recovery_upper_estimate':4}},[2,3])==9
    with pytest.raises(SimulationError):execution.total_estimate({'budget':{}},[2])


def test_bound_invocation_hook_never_uses_configuration_receipt():
    calls=[]
    adapter=SimpleNamespace(bind_invocation=lambda case,**kw:calls.append((case,kw)))
    execution.bind_invocation(adapter,{'id':'C50'},'inv','test')
    assert calls==[({'id':'C50'},{'invocation_id':'inv','test_id':'test'})]


def test_explicit_owned_scope_allows_coordinator_but_blocks_other_owner(tmp_path):
    import threading

    from live_simulations.runner import campaign_lock, owned_campaign_scope
    observed=[]
    def contender():
        try:
            with campaign_lock(tmp_path):observed.append('unsafe')
        except SimulationError:observed.append('blocked')
    with campaign_lock(tmp_path):
        with pytest.raises(SimulationError), campaign_lock(tmp_path):pass
        with owned_campaign_scope(tmp_path), campaign_lock(tmp_path):
            thread=threading.Thread(target=contender);thread.start();thread.join(timeout=2)
            assert not thread.is_alive()
    assert observed==['blocked']


def test_full_live_requires_native_observer_before_campaign_or_paid_effects(monkeypatch):
    from live_simulations import deployed, deployed_full_adapter
    config={'target':'deployed','environment':'STAGING','deployed_url':'https://offline.test',
        'email_receipt_mode':'operator','variables':{'customer_phone':'4242704893','customer_name':'Owner','customer_email':'owner@example.test'},
        'stage_authorization':{'tier':'full','case_ids':list(execution.FULL_IDS),'authorization_id':'offline-full','credit_ceiling':1000},
        'deployed_medium':{'browser_readback':True},
        'budget':{'verified_credit_units':True,'monthly_credits':10000,'remaining_credits':1000,'case_upper_estimate':1,'c48_recovery_upper_estimate':2}}
    monkeypatch.setattr(deployed,'deployment_readiness',lambda *a:([],[]))
    monkeypatch.setattr(deployed,'preserved_customer_name',lambda *a:None)
    monkeypatch.setattr(deployed.deployed_medium,'readiness',lambda *a:[])
    monkeypatch.setattr(deployed_full_adapter,'native_prerequisites',lambda *a:{},raising=False)
    def forbidden(*args,**kwargs):pytest.fail('No Campaign or provider resource allowed before native prerequisites')
    monkeypatch.setattr(deployed,'Campaign',forbidden)
    monkeypatch.setattr(deployed,'provider_readiness',lambda *a:({},[]))
    with pytest.raises(SimulationError,match='prerequisites'):
        deployed.execute(config,'full',live=True,requested=list(execution.FULL_IDS))


def test_c50_never_falls_back_to_agent_testing_when_native_session_executor_missing():
    from live_simulations.core import Budget
    campaign=SimpleNamespace(config={},run_id='r')
    with pytest.raises(SimulationError,match='native session executor'):
        execution.run_c50(SimpleNamespace(),provider=object(),budget=Budget(1000,'full',1000),
            ledger={'entries':[]},campaign=campaign,estimate=1)


def test_special_session_unknown_charge_reloads_ledger_and_blocks_budget(tmp_path):
    import json

    from live_simulations.core import Budget
    path=tmp_path/'usage-ledger.json'
    path.write_text(json.dumps({'entries':[]}))
    campaign=SimpleNamespace(config={},run_id='run',root=tmp_path)
    ledger={'entries':[]};budget=Budget(1000,'full',1000)
    def native(**kwargs):
        path.write_text(json.dumps({'entries':[{'run_id': 'run','case_id': 'C50','unsettled': True,'session_id': 'genuine-session'}]}))
        raise SimulationError('session transport unavailable')
    from live_simulations.runner import campaign_lock
    with campaign_lock(tmp_path), pytest.raises(SimulationError):
        execution.run_c50(SimpleNamespace(execute_c50=native),provider=None,budget=budget,ledger=ledger,campaign=campaign,estimate=1)
    assert budget.unknown is True
    assert ledger['entries'][0]['session_id']=='genuine-session'


def test_owned_scope_requires_real_owner_and_restores_after_exception(tmp_path):
    from live_simulations.runner import campaign_lock, owned_campaign_scope
    with pytest.raises(SimulationError), owned_campaign_scope(tmp_path):pass
    with campaign_lock(tmp_path):
        with pytest.raises(ValueError), owned_campaign_scope(tmp_path):raise ValueError('offline')
        with pytest.raises(SimulationError), campaign_lock(tmp_path):pass


def test_native_session_settles_distinct_billing_identity_without_fake_invocation(tmp_path):
    import json

    from live_simulations.core import Budget
    from live_simulations.runner import campaign_lock
    campaign=SimpleNamespace(config={},run_id='run',root=tmp_path)
    ledger={'entries':[]};budget=Budget(1000,'full',1000)
    def native(**kwargs):
        (tmp_path/'usage-ledger.json').write_text(json.dumps({'entries':[{'run_id': 'run','case_id': 'C50','resource_type': 'conversation',
            'provider_conversation_id': 'actual-cid','billing_id': 'conversation:actual-cid','unsettled': False,'credits': '3'}]}))
        return {'history_verified':True,'global_stop':False}
    with campaign_lock(tmp_path):
        execution.run_c50(SimpleNamespace(execute_c50=native),provider=None,budget=budget,ledger=ledger,campaign=campaign,estimate=5)
    assert budget.spent==3 and budget.unknown is False
    assert budget.settled=={'conversation:actual-cid'}
    assert 'invocation_id' not in ledger['entries'][0]


def test_generic_reconcile_preserves_unknown_native_session_without_agent_test_get(tmp_path,monkeypatch):
    import json

    from live_simulations import runner
    entry={'run_id': 'run','case_id': 'C50','resource_type': 'conversation','provider_conversation_id': 'real-cid','billing_id': 'conversation:real-cid','unsettled': True}
    path=tmp_path/'usage-ledger.json';path.write_text(json.dumps({'entries':[entry]}))
    runtime=SimpleNamespace(root=tmp_path,run_id='run',config={},manifest={'invocations':[]},save=lambda:None)
    class ReadForbidden:
        def __init__(self,*args):pass
        def get(self,*args):pytest.fail('Native conversation cannot use agent-test GET')
        def request(self,*args):pytest.fail('Native conversation cannot use agent-test discovery')
    monkeypatch.setattr(runner,'ElevenLabs',ReadForbidden)
    monkeypatch.setattr(runner,'secret',lambda *args:'offline-only')
    monkeypatch.setattr(runner,'write_report',lambda runtime:None)
    runner.reconcile(runtime)
    assert json.loads(path.read_text())['entries']==[entry]
    assert runtime.manifest['unsettled_usage'] is True


def test_special_cases_retain_actual_provider_checks_and_receiving_inbox_gate():
    from live_simulations.core import Budget
    from live_simulations.runner import functional_checks
    native={'name':'actual Google and Twilio GET proof','passed':True}
    checks=execution.special_checks({'id':'C50','required_evidence':['portal','calendar','whatsapp','email']},
        {'checks':[native]},True,Budget(1000,'full',1000))
    assert native in checks
    inbox=[c for c in checks if c['name']=='receiving inbox contains expected content']
    assert len(inbox)==1 and inbox[0]['passed'] is False and inbox[0]['status']=='unverified'
    assert all(c['passed'] for c in functional_checks(checks,'operator'))
    assert not all(c['passed'] for c in functional_checks(checks,'native'))
