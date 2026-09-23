"""Contracts for provider authentication and durable webhook replay protection."""

import hashlib
import hmac
import time
import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from twilio.request_validator import RequestValidator

from serviceBot.db.connection import dict_cursor, get_db_connection
from serviceBot.main import app
from serviceBot.services import webhook_security
from serviceBot.services.webhook_security import (
    WebhookEventStore,
    WebhookReplayConflictError,
    WebhookVerificationError,
)


client = TestClient(app)


def _elevenlabs_signature(secret: str, raw_body: bytes, timestamp: int) -> str:
    digest = hmac.new(
        secret.encode("utf-8"),
        str(timestamp).encode("utf-8") + b"." + raw_body,
        hashlib.sha256,
    ).hexdigest()
    return f"t={timestamp},v0={digest}"


def test_elevenlabs_signature_requires_valid_fresh_hmac(monkeypatch):
    raw_body = b'{"type":"post_call_transcription"}'
    secret = "elevenlabs-contract-secret"
    now = int(time.time())
    monkeypatch.setenv("ELEVENLABS_WEBHOOK_SECRET", secret)
    monkeypatch.setattr(webhook_security, "is_test_environment", lambda: False)

    webhook_security.verify_elevenlabs_request(raw_body, _elevenlabs_signature(secret, raw_body, now))

    with pytest.raises(WebhookVerificationError):
        webhook_security.verify_elevenlabs_request(raw_body + b"x", _elevenlabs_signature(secret, raw_body, now))
    with pytest.raises(WebhookVerificationError):
        webhook_security.verify_elevenlabs_request(raw_body, _elevenlabs_signature(secret, raw_body, now - 3600))


def test_twilio_signature_uses_explicit_public_webhook_url(monkeypatch):
    token = "twilio-contract-token"
    public_base = "https://voice.example.test"
    path = "/api/v1/telephony/sms/inbound"
    form_data = {"From": "+15550120000", "Body": "Hello", "MessageSid": "SM-contract"}
    signed_url = f"{public_base}{path}"
    signature = RequestValidator(token).compute_signature(signed_url, form_data)
    request = SimpleNamespace(
        url=SimpleNamespace(path=path, query=""),
        headers={"X-Twilio-Signature": signature},
    )
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", token)
    monkeypatch.setenv("TWILIO_WEBHOOK_BASE_URL", public_base)
    monkeypatch.setattr(webhook_security, "is_test_environment", lambda: False)

    webhook_security.verify_twilio_request(request, form_data)

    request.headers["X-Twilio-Signature"] = "invalid"
    with pytest.raises(WebhookVerificationError):
        webhook_security.verify_twilio_request(request, form_data)


def test_event_store_rejects_conflicting_replays_and_accepts_identical_retries():
    provider = "contract"
    event_id = f"event-{uuid.uuid4()}"
    store = WebhookEventStore()
    try:
        assert store.begin(provider, event_id, {"value": 1}) is True
        store.complete(provider, event_id)
        assert store.begin(provider, event_id, {"value": 1}) is False
        with pytest.raises(WebhookReplayConflictError):
            store.begin(provider, event_id, {"value": 2})
    finally:
        with get_db_connection() as conn:
            with dict_cursor(conn) as cursor:
                cursor.execute(
                    "DELETE FROM webhook_events WHERE provider = %s AND event_id = %s;",
                    (provider, event_id),
                )


@patch("serviceBot.api.telephony.extract_callback_from_transcript", return_value=None)
@patch("serviceBot.api.telephony.generate_service_summary", return_value="Contract call summary.")
def test_post_call_webhook_is_idempotent(mock_summary, _mock_callback):
    conversation_id = f"conv-contract-{uuid.uuid4()}"
    phone = f"+1555{str(uuid.uuid4().int)[-7:]}"
    payload = {
        "type": "post_call_transcription",
        "data": {
            "conversation_id": conversation_id,
            "metadata": {"from_number": phone},
            "transcript": [{"role": "user", "message": "Please inspect my brakes."}],
        },
    }
    try:
        first = client.post("/api/v1/telephony/webhook", json=payload)
        duplicate = client.post("/api/v1/telephony/webhook", json=payload)
        assert first.status_code == 200
        assert first.json() == {"success": True}
        assert duplicate.status_code == 200
        assert duplicate.json() == {"success": True, "duplicate": True}
        with get_db_connection() as conn:
            with dict_cursor(conn) as cursor:
                cursor.execute("SELECT COUNT(*) AS total FROM crm_notes WHERE call_id = %s;", (conversation_id,))
                assert cursor.fetchone()["total"] == 1
    finally:
        with get_db_connection() as conn:
            with dict_cursor(conn) as cursor:
                cursor.execute("DELETE FROM crm_notes WHERE call_id = %s;", (conversation_id,))
                cursor.execute("DELETE FROM customers WHERE phone = %s;", (phone,))
                cursor.execute(
                    "DELETE FROM webhook_events WHERE provider = 'elevenlabs' AND event_id = %s;",
                    (conversation_id,),
                )


def test_inbound_sms_webhook_ignores_identical_retry():
    message_sid = f"SM-contract-{uuid.uuid4()}"
    form = {"From": "+15550124444", "Body": "Need help", "MessageSid": message_sid}
    try:
        with patch("serviceBot.services.sms_classifier.process_inbound_sms") as process_inbound:
            first = client.post("/api/v1/telephony/sms/inbound", data=form)
            duplicate = client.post("/api/v1/telephony/sms/inbound", data=form)
        assert first.status_code == 200
        assert duplicate.status_code == 200
        process_inbound.assert_called_once()
    finally:
        with get_db_connection() as conn:
            with dict_cursor(conn) as cursor:
                cursor.execute(
                    "DELETE FROM webhook_events WHERE provider = 'twilio_sms_inbound' AND event_id = %s;",
                    (message_sid,),
                )


def test_inbound_sms_rejects_unsigned_production_request(monkeypatch):
    monkeypatch.setattr(webhook_security, "is_test_environment", lambda: False)
    monkeypatch.delenv("TWILIO_AUTH_TOKEN", raising=False)
    response = client.post(
        "/api/v1/telephony/sms/inbound",
        data={"From": "+15550125555", "Body": "Hello", "MessageSid": f"SM-{uuid.uuid4()}"},
    )
    assert response.status_code == 403
