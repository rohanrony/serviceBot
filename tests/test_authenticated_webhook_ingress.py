"""Offline real Request handling: no provider, DB or paid effects."""
import asyncio
import hashlib
import json
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from serviceBot.api import telephony
from serviceBot.services import webhook_security as security


@pytest.fixture
def setup_and_cleanup_test_db():
    yield

@pytest.fixture
def harness(monkeypatch):
    store=Mock(); store.begin.return_value=False
    monkeypatch.setattr(security,'WebhookEventStore',lambda:store)
    monkeypatch.setattr(security,'verify_elevenlabs_request',lambda *args:True)
    return store

def request(body):
    async def receive():return {'type':'http.request','body':body,'more_body':False}
    return Request({'type':'http','method':'POST','path':'/','headers':[]},receive)

def test_signed_duplicate_still_records_ingress_before_duplicate_return(harness):
    body=json.dumps({'type':'post_call_transcription','data':{'conversation_id':'owned'}}).encode()
    assert asyncio.run(telephony.post_call_webhook(request(body)))=={'success':True,'duplicate':True}
    harness.record_authenticated_ingress.assert_called_once_with('owned',body)
    assert [call[0] for call in harness.method_calls]==['record_authenticated_ingress','begin']

def test_direct_payload_never_records_authenticated_ingress(harness):
    asyncio.run(telephony.post_call_webhook(payload={'type':'post_call_transcription','data':{'conversation_id':'owned'}}))
    harness.record_authenticated_ingress.assert_not_called()

def test_invalid_signature_cannot_record_or_claim(harness,monkeypatch):
    def reject(*args):raise security.WebhookVerificationError('invalid')
    monkeypatch.setattr(security,'verify_elevenlabs_request',reject)
    with pytest.raises(HTTPException):asyncio.run(telephony.post_call_webhook(request(b'{}')))
    assert harness.method_calls==[]

@pytest.mark.parametrize('identity',[True,23,[],None,''])
def test_malformed_identity_never_records(harness,identity):
    body=json.dumps({'type':'post_call_transcription','data':{'conversation_id':identity}}).encode()
    with pytest.raises(HTTPException):asyncio.run(telephony.post_call_webhook(request(body)))
    assert harness.method_calls==[]

@pytest.mark.parametrize('matching',[True,False])
def test_audit_is_insert_only_and_conflicting_raw_payload_is_rejected(matching):
    from contextlib import contextmanager
    body=b'actual verified bytes'
    cursor=Mock()
    cursor.fetchone.return_value={'conversation_id':'owned','payload_hash':hashlib.sha256(body).hexdigest() if matching else 'f'*64}
    conn=Mock()
    @contextmanager
    def connection():yield conn
    @contextmanager
    def cursors(_):yield cursor
    store=security.WebhookEventStore(connection,cursors)
    if matching:
        store.record_authenticated_ingress('owned',body)
        conn.commit.assert_called_once()
    else:
        with pytest.raises(security.WebhookReplayConflictError):store.record_authenticated_ingress('owned',body)
        conn.commit.assert_not_called()
    statements=[call.args[0] for call in cursor.execute.call_args_list]
    assert len(statements)==2 and statements[0].lstrip().startswith('INSERT')
    assert 'DO NOTHING' in statements[0] and statements[1].lstrip().startswith('SELECT')


def test_test_environment_auth_bypass_does_not_create_audit(harness,monkeypatch):
    monkeypatch.setattr(security,'verify_elevenlabs_request',lambda *args:False)
    body=json.dumps({'type':'post_call_transcription','data':{'conversation_id':'owned'}}).encode()
    asyncio.run(telephony.post_call_webhook(request(body)))
    harness.record_authenticated_ingress.assert_not_called()
