"""Synthetic provider webhook traverses real HTTP signature and disposable DB."""
import hashlib
import hmac
import json
import time

from live_simulations import deployed_full_causal as causal
from live_simulations import deployed_medium as medium
from serviceBot.api import telephony
from serviceBot.services import webhook_security as security


def test_signed_callback_audit_crm_join_replay_and_rejection(api,db,monkeypatch):
    monkeypatch.setattr(security,'is_test_environment',lambda:False)
    monkeypatch.setattr(security,'_elevenlabs_secret',lambda:'synthetic-offline-secret')
    monkeypatch.setattr(telephony,'generate_service_summary',lambda text:'Synthetic offline summary')
    payload={'type':'post_call_transcription','data':{'conversation_id':'conv_owned',
        'agent_id':'agent_owned','metadata':{'from_number':'+15550100001'},
        'analysis':{'summary':'Synthetic offline conversation'},'transcript':[{'role':'user','message':'Synthetic offline conversation'}]}}
    body=json.dumps(payload).encode(); stamp=str(int(time.time()))
    digest=hmac.new(b'synthetic-offline-secret',stamp.encode()+b'.'+body,hashlib.sha256).hexdigest()
    headers={'ElevenLabs-Signature':f't={stamp},v0={digest}','Content-Type':'application/json'}
    assert api.post('/api/v1/telephony/webhook',content=body,headers={'Content-Type':'application/json'}).status_code==401
    assert db('SELECT * FROM authenticated_webhook_ingress')==[]
    assert api.post('/api/v1/telephony/webhook',content=body,headers=headers).status_code==200
    first=db('SELECT * FROM authenticated_webhook_ingress')[0]
    assert first['payload_hash']==hashlib.sha256(body).hexdigest()
    assert api.post('/api/v1/telephony/webhook',content=body,headers=headers).json()['duplicate'] is True
    assert db('SELECT * FROM authenticated_webhook_ingress')==[first]
    assert len(db("SELECT * FROM crm_notes WHERE call_id='conv_owned'"))==1
    changed=json.dumps(dict(payload,event_timestamp=1)).encode()
    changed_digest=hmac.new(b'synthetic-offline-secret',stamp.encode()+b'.'+changed,hashlib.sha256).hexdigest()
    assert api.post('/api/v1/telephony/webhook',content=changed,headers=dict(headers,**{'ElevenLabs-Signature':f't={stamp},v0={changed_digest}'})).status_code==409
    assert db('SELECT * FROM authenticated_webhook_ingress')==[first]

    observation=medium._serial({'notes':db("SELECT * FROM crm_notes WHERE call_id='conv_owned'"),
        'events':db("SELECT id,provider,event_id,payload_hash,status,completed_at AT TIME ZONE current_setting('TimeZone') AS completed_at FROM webhook_events WHERE provider='elevenlabs' AND event_id='conv_owned'"),
        'audit':db("SELECT * FROM authenticated_webhook_ingress WHERE event_id='conv_owned'")})
    provider={'conversation_id':'conv_owned','agent_id':'agent_owned','status':'done',
        'transcript':payload['data']['transcript']}
    binding={'customer_id': 1,'conversation_id': 'conv_owned','agent_id': 'agent_owned','baseline_note_ids': [],'baseline_event_ids': []}
    assert causal.verify_history(observation,provider,**binding)
    assert not causal.verify_history(dict(observation,audit=[]),provider,**binding)
