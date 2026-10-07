"""Provider contracts and worker effects using synthetic payloads and storage."""

import hashlib
import hmac
import json
import time
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from twilio.request_validator import RequestValidator

PORTAL = "/api/v1/portal"


def test_inbound_sms_retry_does_not_duplicate_messages(api):
    form = {
        "From": "+15550100001",
        "Body": "Please check my brakes",
        "MessageSid": "SM-e2e-inbound",
    }
    for _ in range(2):
        response = api.post("/sms/inbound", data=form)
        assert response.status_code == 200
        assert "<Response>" in response.text
    messages = api.get(f"{PORTAL}/sms/conversations/1/messages").json()
    assert (
        len([m for m in messages if m["twilio_message_sid"] == form["MessageSid"]]) == 1
    )
    form["Body"] = "Conflicting retry"
    assert api.post("/sms/inbound", data=form).status_code == 409


def test_sms_stop_start_updates_opt_in_and_help_logs_reply(api, db):
    for index, (body, opted_in) in enumerate(
        (("STOP", False), ("START", True), ("HELP", True))
    ):
        response = api.post(
            "/sms/inbound",
            data={
                "From": "+15550100001",
                "Body": body,
                "MessageSid": f"SM-e2e-{index}",
            },
        )
        assert response.status_code == 200, response.text
        assert (
            db("SELECT sms_opt_in FROM customers WHERE id = 1")[0]["sms_opt_in"]
            is opted_in
        )
    messages = api.get(f"{PORTAL}/sms/conversations/1/messages").json()
    assert messages[-1]["direction"] == "outbound"
    assert "+15550100005" in messages[-1]["body"]


def test_agent_confirmation_via_sms_visible_in_portal(api, db):
    db("UPDATE service_requests SET staff_agent_id = 1 WHERE id = 1")
    response = api.post(
        "/sms/inbound",
        data={"From": "+15550100003", "Body": "CONFIRM", "MessageSid": "SM-e2e-agent"},
    )
    assert response.status_code == 200, response.text
    row = api.get(f"{PORTAL}/service-requests").json()[0]
    assert row["status"] == "confirmed"
    assert row["confirmation_status"] == "confirmed"
    assert row["confirmed_at"]


@pytest.mark.parametrize(
    "provider_status,expected",
    [("delivered", "DELIVERED"), ("undelivered", "FAILED"), ("read", "DELIVERED")],
)
def test_delivery_status_callback_updates_portal_logs(
    api, db, provider_status, expected
):
    db(
        "INSERT INTO sms_log (appointment_id, recipient_type, recipient_phone, template_type, status, twilio_message_sid, body) VALUES (1, 'customer', '+15550100001', 'booking', 'SENT', 'SM-e2e-delivery', 'Your appointment details')"
    )
    form = {"MessageSid": "SM-e2e-delivery", "MessageStatus": provider_status}
    response = api.post("/sms/status", data=form)
    assert response.status_code == 200
    assert api.post("/sms/status", data=form).json()["duplicate"] is True
    logs = api.get(f"{PORTAL}/sms/logs/appointment/1").json()["logs"]
    assert len(logs) == 1
    assert logs[0]["status"] == expected


def test_twilio_signed_request_accepted_and_tampering_rejected(api, monkeypatch):
    from serviceBot.services import webhook_security

    monkeypatch.setattr(webhook_security, "is_test_environment", lambda: False)
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "e2e-signature-token")
    monkeypatch.setenv("TWILIO_WEBHOOK_BASE_URL", "https://voice.example.test")
    form = {"From": "+15550100001", "Body": "Hello", "MessageSid": "SM-e2e-signed"}
    signature = RequestValidator("e2e-signature-token").compute_signature(
        "https://voice.example.test/sms/inbound", form
    )
    headers = {"X-Twilio-Signature": signature}
    assert api.post("/sms/inbound", data=form, headers=headers).status_code == 200
    form["Body"] = "Tampered"
    assert api.post("/sms/inbound", data=form, headers=headers).status_code == 403


@pytest.mark.parametrize(
    "kind,expected",
    [("valid", 200), ("invalid", 401), ("stale", 401), ("unconfigured", 503)],
)
def test_elevenlabs_signature_verification_is_not_bypassed(
    api, monkeypatch, kind, expected
):
    from serviceBot.services import webhook_security

    monkeypatch.setattr(webhook_security, "is_test_environment", lambda: False)
    secret = "e2e-elevenlabs-secret"
    if kind != "unconfigured":
        monkeypatch.setenv("ELEVENLABS_WEBHOOK_SECRET", secret)
    payload = {
        "type": "post_call_transcription",
        "data": {
            "conversation_id": "conv-e2e-signed",
            "metadata": {"from_number": "+15550100001"},
            "transcript": [],
        },
    }
    raw = json.dumps(payload).encode()
    timestamp = int(time.time()) - (3600 if kind == "stale" else 0)
    digest = hmac.new(
        secret.encode(), str(timestamp).encode() + b"." + raw, hashlib.sha256
    ).hexdigest()
    signature = f"t={timestamp},v0={digest if kind != 'invalid' else 'invalid'}"
    response = api.post(
        "/api/v1/telephony/webhook",
        content=raw,
        headers={"ElevenLabs-Signature": signature, "Content-Type": "application/json"},
    )
    assert response.status_code == expected
    assert len(api.get(f"{PORTAL}/calls").json()) == (1 if kind == "valid" else 0)


def test_missing_calls_recovered_across_provider_pages_once(api, monkeypatch):
    from serviceBot.services.call_sync import sync_recent_elevenlabs_calls

    monkeypatch.setenv("ELEVENLABS_API_KEY", "e2e-only-key")
    monkeypatch.setenv("ELEVENLABS_AGENT_ID", "e2e-only-agent")
    original = httpx.Client._send_single_request
    pages = []

    def provider(self, request):
        if request.url.host != "api.elevenlabs.io":
            return original(self, request)
        if request.url.path.endswith("/conversations"):
            cursor = request.url.params.get("cursor")
            pages.append(cursor)
            assert request.url.params["agent_id"] == "e2e-only-agent"
            if cursor is None:
                body = {
                    "conversations": [
                        {"conversation_id": "recovery-1", "status": "done"},
                        {"conversation_id": "unfinished", "status": "processing"},
                    ],
                    "has_more": True,
                    "next_cursor": "second",
                }
            else:
                assert cursor == "second"
                body = {
                    "conversations": [
                        {"conversation_id": "recovery-2", "status": "done"}
                    ],
                    "has_more": False,
                }
        else:
            assert request.url.path.split("/")[-1] in {"recovery-1", "recovery-2"}
            body = {
                "status": "done",
                "metadata": {"from_number": "+15550100001"},
                "transcript": [],
                "analysis": {"summary": "Recovered oil change call"},
            }
        return httpx.Response(200, json=body, request=request)

    monkeypatch.setattr(httpx.Client, "_send_single_request", provider)
    assert sync_recent_elevenlabs_calls(limit=1) == 2
    assert sync_recent_elevenlabs_calls(limit=1) == 0
    assert pages == [None, "second", None, "second"]
    assert {row["call_id"] for row in api.get(f"{PORTAL}/calls").json()} == {
        "recovery-1",
        "recovery-2",
    }


def test_cron_requires_bearer_secret(api):
    for endpoint in ("outbox", "reminders"):
        assert api.post(f"/api/cron/{endpoint}").status_code == 401
        assert (
            api.post(
                f"/api/cron/{endpoint}", headers={"Authorization": "Bearer wrong"}
            ).status_code
            == 401
        )
        response = api.post(
            f"/api/cron/{endpoint}",
            headers={"Authorization": "Bearer e2e-only-cron-secret"},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "success"


def test_outbox_processes_notification_once_and_preserves_body(api, db):
    payload = {
        "sms_event_type": "BOOKING",
        "appointment_id": 1,
        "customer_phone": "+15550100001",
        "details": {"customer_name": "Alex E2E", "service_type": "Oil Change"},
    }
    db(
        "INSERT INTO outbox_notifications (event_type, request_id, payload) VALUES ('sms_status_change', 1, %s)",
        (json.dumps(payload),),
    )
    headers = {"Authorization": "Bearer e2e-only-cron-secret"}
    first = api.post("/api/cron/outbox", headers=headers)
    assert first.status_code == 200
    assert first.json()["processed_events"] == 1
    assert db("SELECT status FROM outbox_notifications")[0]["status"] == "DELIVERED"
    logs = api.get(f"{PORTAL}/sms/logs/appointment/1").json()["logs"]
    assert logs
    assert any(
        log["status"] == "SENT" and "Oil Change" in (log["body"] or "") for log in logs
    )
    assert api.post("/api/cron/outbox", headers=headers).json()["processed_events"] == 0
    assert len(api.get(f"{PORTAL}/sms/logs/appointment/1").json()["logs"]) == len(logs)


@pytest.mark.parametrize(
    "opted_in,expected", [(True, "SENT"), (False, "SKIPPED_OPT_OUT")]
)
def test_due_reminder_respects_opt_out_and_is_not_sent_twice(
    api, db, opted_in, expected
):
    db("UPDATE customers SET sms_opt_in = %s WHERE id = 1", (opted_in,))
    db(
        "INSERT INTO sms_reminders (appointment_id, recipient_type, recipient_phone, reminder_type, scheduled_at, attempt_kind) VALUES (1, 'customer', '+15550100001', '2h', NOW() - INTERVAL '1 day', 'final_reminder')"
    )
    headers = {"Authorization": "Bearer e2e-only-cron-secret"}
    response = api.post("/api/cron/reminders", headers=headers)
    assert response.status_code == 200
    assert db("SELECT status FROM sms_reminders")[0]["status"] == expected
    logs = api.get(f"{PORTAL}/sms/logs/appointment/1").json()["logs"]
    assert bool(logs) is opted_in
    assert (
        api.post("/api/cron/reminders", headers=headers).json()["reminders_sent"] == 0
    )


def test_quiet_hours_release_updates_original_log_once(api, db):
    from serviceBot.services.quiet_hours import run_quiet_hours_queue_worker_cycle

    db(
        "INSERT INTO sms_log (appointment_id, recipient_type, recipient_phone, template_type, status, body, channel, scheduled_send_at) VALUES (1, 'customer', '+15550100001', 'booking', 'QUEUED', 'Original queued body', 'WHATSAPP', NOW() - INTERVAL '1 day')"
    )
    assert run_quiet_hours_queue_worker_cycle() == 1
    assert run_quiet_hours_queue_worker_cycle() == 0
    logs = api.get(f"{PORTAL}/sms/logs/appointment/1").json()["logs"]
    assert len(logs) == 1
    assert logs[0]["body"] == "Original queued body"
    assert logs[0]["channel"] == "WHATSAPP"
    assert logs[0]["status"] == "SENT"


def test_secrets_set_mask_and_clear(api):
    secret = "e2e-only-fake-key-123456789"
    assert (
        api.post(f"{PORTAL}/secrets", json={"openai_api_key": secret}).status_code
        == 200
    )
    response = api.get(f"{PORTAL}/secrets")
    assert response.json()["openai"]["source"] == "custom"
    assert response.json()["openai"]["has_key"] is True
    assert secret not in response.text
    assert (
        api.post(f"{PORTAL}/secrets", json={"openai_api_key": "clear"}).status_code
        == 200
    )
    assert api.get(f"{PORTAL}/secrets").json()["openai"]["has_key"] is False


def test_google_auth_url_uses_unique_persisted_state_and_expected_scopes(
    api, db, monkeypatch
):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "e2e-google-client")
    urls = [
        api.get(f"{PORTAL}/agents/1/google/auth-url", params={"action": action})
        for action in ("calendar", "gmail")
    ]
    assert all(response.status_code == 200 for response in urls)
    states = []
    for response, scope in zip(urls, ("calendar.events", "gmail.send")):
        query = parse_qs(urlparse(response.json()["auth_url"]).query)
        assert query["client_id"] == ["e2e-google-client"]
        assert scope in query["scope"][0]
        states.append(query["state"][0])
    assert len(set(states)) == 2
    assert {row["state"] for row in db("SELECT state FROM oauth_states")} == set(states)
    invalid = api.get(
        f"{PORTAL}/gmail/oauth/callback",
        params={"code": "e2e-code", "state": "invalid-state"},
    )
    assert "Invalid or expired state" in invalid.text
