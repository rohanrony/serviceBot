"""Offline shared full Adapter dispatch, never provider or production evidence."""
from types import SimpleNamespace

import pytest

from live_simulations import deployed_full_adapter as full
from live_simulations import deployed_full_faults as faults
from live_simulations.core import SimulationError


@pytest.fixture
def setup_and_cleanup_test_db():
    yield

@pytest.fixture
def adapter(tmp_path,monkeypatch):
    value=full.Adapter.__new__(full.Adapter)
    value.config={'deployed_url':'https://offline.test','deployed_medium':{'technician_ids':[7,12]},'variables':{'customer_phone':'+15550100001'}}
    value.campaign=SimpleNamespace(root=tmp_path,folder=tmp_path/('a'*32),manifest={'run_id':'a'*32,'baseline':[]})
    value.state={'full_adapter':True,'services':{key:{'id':idx,'name':key,'price_range':'$1','duration_minutes':30,'assigned_agent_ids':[7]}
        for idx,key in enumerate(('oil','second','split'),1)},'blocks':[],'operations':[]}
    value.current_ids=set();value.original_ids=set();value.owned_ids=set();value.current_case=None
    value._guard=lambda:None;value._save=lambda:None;value._catalog_readback=lambda:None
    value._intake_precondition=lambda values:None
    monkeypatch.setattr(full.medium,'_request_rows',lambda *args:[])
    return value


def test_fault_arrangement_uses_owned_lease_service_without_mapping_original_catalog(adapter,monkeypatch):
    calls=[]
    monkeypatch.setattr(faults,'arrange',lambda *args:calls.append(args) or {'service_name': 'owned-fault-service','service_id': 100})
    case={'id':'C35','scenario':'Book Oil Change','success_conditions':[],'expected_tools':[]}
    adapted,ids=adapter.arrange(case,{'customer_phone':'+15550100001','appointment_time':'2027-01-01T10:00:00'})
    assert calls and ids==[]
    assert 'owned-fault-service' in adapted['scenario']
    assert adapter.state['services']['oil']['assigned_agent_ids']==[7]


def test_fault_poll_preserves_transition_and_explicitly_reconciles_lost_response(adapter,monkeypatch):
    calls=[];adapter.current_case='C36'
    monkeypatch.setattr(faults,'observe',lambda *args:calls.append('observe') or ({'response_loss_consumed_at':'native-time'},{}))
    monkeypatch.setattr(faults,'reconcile',lambda *args:calls.append('reconcile'))
    adapter.poll_during_call({'id':'C36'},{},None)
    assert calls==['observe','reconcile']


def test_c50_without_compiled_socket_or_credit_reader_stops_before_driver_effect(adapter,monkeypatch):
    with pytest.raises(SimulationError,match='native session'):
        adapter.execute_c50(provider=object(),budget=object(),ledger={'entries':[]},campaign=adapter.campaign)


def test_condition_checks_require_fresh_native_report_and_preserve_originals(adapter,monkeypatch):
    adapter.current_case='C37';adapter.state['full_baseline']=[]
    seen=[]
    adapter._discover_condition_rows=lambda values:seen.append('native rows')
    adapter.native_bridge=SimpleNamespace(observe_conditions=lambda cid,values:seen.append('fresh observe') or {'evidence_complete':False,'blockers':['actual provider rejection unavailable']})
    checks=adapter.execution_checks({'id':'C37'},{},[],[],provider=object())
    assert seen==['native rows','fresh observe']
    assert checks[0]['passed'] is True and checks[1]['passed'] is False


def test_fault_cleanup_precedes_catalog_owned_request_cleanup(adapter,monkeypatch):
    from live_simulations import deployed_full_negative as negative
    events=[];adapter.current_case='C35'
    monkeypatch.setattr(faults,'cleanup',lambda *args:events.append('owned fault retirement'))
    monkeypatch.setattr(full.medium.Adapter,'cleanup_case',lambda self:events.append('owned request cleanup'))
    monkeypatch.setattr(negative,'before_cleanup',lambda *args:None)
    monkeypatch.setattr(negative,'cleanup',lambda *args:None)
    adapter.cleanup_case()
    assert events==['owned fault retirement','owned request cleanup']


def test_prepare_restore_owned_clone_and_secret_variables_dispatch(adapter,monkeypatch):
    events=[];provider=object();case={'id':'C35'}
    monkeypatch.setattr(faults,'prepare_case_agent',lambda *args:{'actual':'scoped descriptor'})
    monkeypatch.setattr(full.provenance,'prepare_owned_case_agent',lambda *args:events.append('owned clone prepare'))
    monkeypatch.setattr(full.provenance,'case_dynamic_variables',lambda *args:{'secret__simulation_fault_lease':'memory-only'})
    monkeypatch.setattr(full.provenance,'restore_owned_case_agent',lambda *args:events.append('owned clone restore'))
    adapter.prepare_case_agent(case,provider)
    assert adapter.case_dynamic_variables(case)=={'secret__simulation_fault_lease':'memory-only'}
    adapter.restore_case_agent(case,provider)
    assert events==['owned clone prepare','owned clone restore']
    assert 'secret__simulation_fault_lease' not in adapter.state


def test_final_negative_checks_keep_actual_provider_proof_instead_of_readding_unverified(adapter,monkeypatch):
    adapter.current_case='C47';adapter.state['full_baseline']=[];provider=object();adapter._full_provider=provider
    adapter._register=lambda *args:[]
    seen=[]
    monkeypatch.setattr(full.negative,'checks',lambda a,cid,*,provider=None:seen.append(provider) or [full.check('actual provider correlation',provider is not None)])
    checks=adapter.final_checks({'id':'C47'},{},[])
    assert seen==[provider]
    assert all(c['passed'] for c in checks)


def test_c48_adapter_expected_slot_is_accepted_by_actual_source_coordinator(adapter,tmp_path):
    from live_simulations.core import private_json
    from live_simulations.deployed_full_recovery import prepare_source
    adapter.config['app_config']={'business_timezone':'America/New_York'}
    adapter.config['existing_customer_identity']={'id':7,'name':'Owner'}
    adapter.state['services']['oil']['duration_minutes']=60
    expected=adapter._c48_expected_booking({'appointment_time':'2026-11-11T10:00:00'})
    run='a'*32;folder=tmp_path/run;folder.mkdir()
    private_json(tmp_path/'usage-ledger.json',{'entries':[]})
    private_json(folder/'manifest.json',{'run_id':run,'campaign_agent_id':'agent','provider_tests':['test']})
    pre=prepare_source(tmp_path,identity={'run_id':run,'case_id':'C48','attempt':1,'agent_id':'agent','test_id':'test'},
        expected_booking=expected,test_definition={'id':'test','type':'simulation','tool_mock_config':{'mocking_strategy':'none','fallback_strategy':'call_real_tool','mocked_tool_ids':[]}},
        tool_url='https://offline.test/api/v1/voice/tools?name=book_appointment',
        budget={'source_estimate':10,'recovery_estimate':20,'credit_ceiling':100,'remaining':100},
        observe_baseline=lambda:{'source':'native_postgresql','customer_id':7,'observed_at_unix':100,
            'active_request_ids':[],'request_ids':[],'reservation_ids':[]})
    assert pre['expected_booking']['starts_at']=='2026-11-11T10:00:00-05:00'
    assert pre['expected_booking']['ends_at']=='2026-11-11T11:00:00-05:00'


@pytest.mark.parametrize('stamp',['2026-11-01T01:30:00','2026-03-08T02:30:00','2026-03-08T01:30:00'])
def test_c48_dst_ambiguous_or_nonexistent_native_wall_slot_is_rejected(adapter,stamp):
    adapter.config['app_config']={'business_timezone':'America/New_York'}
    adapter.config['existing_customer_identity']={'id':7,'name':'Owner'}
    with pytest.raises(SimulationError,match='unambiguous'):
        adapter._c48_expected_booking({'appointment_time':stamp})


def test_discovery_excludes_original_and_previous_case_rows_but_keeps_new_cancelled_request(adapter,monkeypatch):
    adapter.config['existing_customer_identity']={'id':7,'name':'Owner'}
    adapter.original_ids={1}
    adapter.state['full_case_request_baseline_ids']=[1,2]
    registered=[]
    monkeypatch.setattr(full.medium,'_read',lambda *args:[{'id':1},{'id':2},{'id':3}])
    adapter._register=lambda ids,values:registered.append(ids)
    adapter._discover_condition_rows({'customer_phone':'+15550100001'})
    assert registered==[{3}]


def test_c50_history_and_booking_flags_cannot_replace_actual_provider_delivery(adapter,monkeypatch):
    adapter.config.update(variables={'customer_name':'Owner','customer_phone':'+15550100001','appointment_time':'2026-11-11T10:00:00'},
        budget={'native_session_credit_units_verified':True,'case_upper_estimate':10})
    adapter.native_session_socket_factory=lambda url:None
    adapter.native_session_credit_reader=lambda detail:3
    adapter.arrange=lambda *args:None
    adapter._discover_condition_rows=lambda *args:None
    adapter._c48_expected_booking=lambda values:{'exact':'expected'}
    adapter.current_ids={50}
    adapter.checks=lambda *args:[full.check('native booking flags',True)]
    monkeypatch.setattr(full.medium,'_read',lambda *args:[{'make':'Toyota','model':'Camry','year':2021}])
    monkeypatch.setattr(full.medium,'_request_rows',lambda *args:[{'id':50}])
    monkeypatch.setattr(full.medium.Adapter,'final_checks',lambda *args:[full.check('reloaded browser owned row 50',True)])
    monkeypatch.setattr(full.session,'execute',lambda *args,**kwargs:{'history_verified':True,'global_stop':False,'provider_conversation_id':'real-session'})
    observed=[]
    def delivery(**kwargs):
        observed.append(kwargs)
        return {'evidence_complete':False,'checks':[full.check('actual provider WhatsApp delivery',False)]}
    adapter.native_bridge=SimpleNamespace(c50_delivery=delivery)
    result=adapter.execute_c50(provider=object(),budget=object(),ledger={'entries':[]},campaign=adapter.campaign)
    assert result['full_case_verified'] is False and result['global_stop'] is True
    assert observed==[{'expected_booking':{'exact':'expected'},'request_id':50,'conversation_id':'real-session'}]
    assert any(c['name']=='actual provider WhatsApp delivery' and c['passed'] is False for c in result['checks'])


def test_c50_default_reader_is_compiled_without_runtime_attribute_injection(adapter,monkeypatch):
    adapter.config.update(variables={'customer_name':'Owner','customer_phone':'+15550100001','appointment_time':'2026-11-11T10:00:00'},
        budget={'native_session_credit_units_verified':True,'case_upper_estimate':10})
    adapter.arrange=lambda *args:None
    adapter._discover_condition_rows=lambda *args:None
    adapter._c48_expected_booking=lambda values:{'exact':'expected'}
    adapter.current_ids={50}
    adapter.checks=lambda *args:[full.check('native booking flags',True)]
    monkeypatch.setattr(full.medium,'_read',lambda *args:[{'make':'Toyota','model':'Camry','year':2021}])
    monkeypatch.setattr(full.medium,'_request_rows',lambda *args:[{'id':50}])
    monkeypatch.setattr(full.medium.Adapter,'final_checks',lambda *args:[full.check('reloaded browser owned row 50',True)])
    observed=[]
    def execute(*args,**kwargs):
        observed.append(kwargs['credit_reader'])
        return {'history_verified':True,'global_stop':False,'provider_conversation_id':'real-session'}
    monkeypatch.setattr(full.session,'execute',execute)
    adapter.native_bridge=SimpleNamespace(c50_delivery=lambda **kwargs:{'evidence_complete':True,'checks':[full.check('actual provider WhatsApp delivery',True)]})
    assert adapter.execute_c50(provider=object(),budget=object(),ledger={'entries':[]},campaign=adapter.campaign)['full_case_verified']
    assert observed == [full.session.native_credit_reader]
