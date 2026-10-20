"""Synthetic observations exercise rejection rules, never claim native evidence."""
from types import SimpleNamespace

import pytest

from live_simulations import deployed_full_causal as causal
from live_simulations.core import SimulationError


@pytest.fixture
def setup_and_cleanup_test_db():
    yield

def pair():
    row = {'id': 5, 'request_id': 10, 'event_type': 'calendar_projection', 'attempts': 1,
               'status': 'PENDING', 'error_log': 'provider timeout', 'updated_at': '2026-10-19T10:00:00+00:00'}
    recovered = dict(row, status='DELIVERED', updated_at='2026-10-19T10:01:00+00:00')
    return row, recovered


def test_same_owned_row_failure_then_recovery():
    a,b=pair()
    assert causal.projection_transition(a,b,owned_request_ids={10})


@pytest.mark.parametrize('change', [{'id': 6}, {'request_id': 11}, {'attempts': True},
    {'event_type': 'booking_notification'}, {'updated_at': '2026-10-19T09:00:00+00:00'},
    {'status': 'PROCESSING'}, {'updated_at': None}])
def test_unrelated_malformed_or_nonterminal_recovery_rejected(change):
    a,b=pair(); b.update(change)
    assert not causal.projection_transition(a,b,owned_request_ids={10})


def test_ready_flags_cannot_activate_any_case():
    adapter=SimpleNamespace(_guard=lambda:None)
    for cid in causal.REQUIREMENTS:
        with pytest.raises(SimulationError, match='requires'):
            causal.arrange(adapter,cid,{'ready':True})


def test_history_reads_exact_customer_conversation_but_never_infers_auth(monkeypatch):
    calls=[]
    def read(config,sql,args):
        calls.append((sql,args)); return [{'id':1}]
    monkeypatch.setattr(causal.medium,'_read',read)
    adapter=SimpleNamespace(config={},_guard=lambda:None)
    result=causal.observe_history(adapter,customer_id=7,conversation_id='conv_own')
    assert len(calls)==3
    assert calls[0][1]==(7,'conv_own')
    assert calls[1][1]==('conv_own',)
    assert result['authenticated_callback_provenance']=='native_audit_requires_provider_join'
    assert result['case_verified'] is False


@pytest.mark.parametrize('customer,conversation',[(True,'c'),(7,''),(7,False)])
def test_history_rejects_bad_identity_before_read(customer,conversation):
    with pytest.raises(SimulationError):
        causal.observe_history(SimpleNamespace(_guard=lambda:None),customer_id=customer,conversation_id=conversation)


@pytest.mark.parametrize('tool_turn', [None, {'role': 'agent', 'message': None}, {'role': 'agent'}])
def test_history_join_rejects_sync_without_audit_and_stale_or_wrong_identity(tool_turn):
    observation={'notes':[{'id': 2,'customer_id': 7,'call_id': 'conv','transcript': 'User: hello'}],
        'events':[{'id': 3,'provider': 'elevenlabs','event_id': 'conv','status': 'COMPLETED','completed_at': '2026-10-19T10:01:00+00:00','payload_hash': 'a'*64}],
        'audit':[{'provider': 'elevenlabs','event_id': 'conv','conversation_id': 'conv','payload_hash': 'a'*64,'verified_at': '2026-10-19T10:00:00+00:00'}]}
    provider={'conversation_id': 'conv','agent_id': 'agent','status': 'done','transcript': [{'role': 'user','message': 'hello'}]}
    if tool_turn is not None:
        provider['transcript'].append(tool_turn)
        # Match the native post_call_webhook formatting owner, including tool-only turns.
        observation['notes'][0]['transcript'] += '\nAgent: ' + str(tool_turn.get('message', ''))
    kwargs={'customer_id': 7,'conversation_id': 'conv','agent_id': 'agent','baseline_note_ids': [],'baseline_event_ids': []}
    assert causal.verify_history(observation,provider,**kwargs)
    assert not causal.verify_history(dict(observation,audit=[]),provider,**kwargs)
    assert not causal.verify_history(observation,dict(provider,conversation_id='other'),**kwargs)
    assert not causal.verify_history(observation,provider,**dict(kwargs,baseline_note_ids=[2]))

@pytest.fixture
def lifecycle(tmp_path,monkeypatch):
    import json
    folder=tmp_path/'run';folder.mkdir()
    adapter=SimpleNamespace(config={'existing_customer_identity':{'id':7,'name':'Owner'},
        'variables':{'customer_phone':'+15550100001'}},state={},_guard=lambda:None,_save=lambda:None,
        campaign=SimpleNamespace(run_id='run',root=tmp_path,manifest={'run_id':'run','campaign_agent_id':'agent',
        'invocations':['inv'],'provider_tests':['test']}))
    (tmp_path/'usage-ledger.json').write_text(json.dumps({'entries':[{'run_id': 'run','case_id': 'C50','test_id': 'test','invocation_id': 'inv'}]}))
    def read(config,sql,args=()):
        if 'FROM customers' in sql:return [{'id': 7,'name': 'Owner','phone': '+15550100001'}]
        return []
    monkeypatch.setattr(causal.medium,'_read',read)
    return adapter


def test_agent_test_binding_cannot_establish_native_session(lifecycle):
    causal.arrange(lifecycle,'C50',{})
    with pytest.raises(SimulationError,match='genuine provider conversation'):
        causal.bind_invocation(lifecycle,invocation_id='inv',test_id='test')
    assert causal.checks(lifecycle,'C50',{},[],[],object())[0]['passed'] is False


def test_history_ambiguous_customer_rejected_before_save(lifecycle,monkeypatch):
    monkeypatch.setattr(causal.medium,'_read',lambda *args:[{'id': 7,'name': 'Owner','phone': '+15550100001'}]*2)
    with pytest.raises(SimulationError):causal.arrange(lifecycle,'C50',{})
    assert 'full_history' not in lifecycle.state



def test_genuine_native_history_requires_exact_get_initiation_nonce_and_case():
    observation={'notes':[{'id': 2,'customer_id': 7,'call_id': 'conv','transcript': 'User: hello'}],
        'events':[{'id': 3,'provider': 'elevenlabs','event_id': 'conv','status': 'COMPLETED','completed_at': '2026-10-19T10:01:00+00:00','payload_hash': 'a'*64}],
        'audit':[{'provider': 'elevenlabs','event_id': 'conv','conversation_id': 'conv','payload_hash': 'a'*64,'verified_at': '2026-10-19T10:00:00+00:00'}]}
    dynamic={'run_id': 'run-owned','case_id': 'C50','session_nonce': 'nonce-owned'}
    detail={'conversation_id': 'conv','agent_id': 'agent','status': 'done','transcript': [{'role': 'user','message': 'hello'}],
        'user_id': '+15550100001','conversation_initiation_client_data': {'dynamic_variables':dict(dynamic)}}
    binding={'customer_id': 7,'conversation_id': 'conv','agent_id': 'agent','baseline_note_ids': [],'baseline_event_ids': [],'dynamic_variables': dynamic,'expected_user_id': '+15550100001'}
    assert causal.verify_native_history(observation,detail,**binding)
    detail['conversation_initiation_client_data']['dynamic_variables']['session_nonce']='foreign'
    assert not causal.verify_native_history(observation,detail,**binding)
    detail.pop('conversation_initiation_client_data')
    detail['test_run_id']='nonce-owned'
    assert not causal.verify_native_history(observation,detail,**binding)
