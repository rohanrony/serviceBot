"""Persisted Google credentials and real mail encoding with a captured HTTP edge."""

import base64
import json
from email import message_from_bytes, policy
from unittest.mock import MagicMock

import httpx
import pytest


@pytest.mark.parametrize("system_connected", [True, False])
@pytest.mark.parametrize("provider_status", [200, 403])
def test_legacy_admin_delivery_uses_persisted_google_accounts(
    db, monkeypatch, system_connected, provider_status
):
    from serviceBot.api import portal
    from serviceBot.services.encryption import encrypt_key
    from serviceBot.services.gmail import send_admin_notification

    config = portal.load_config()
    config.update(
        gmail_enabled=True,
        gmail_routine_admin_copies_enabled=True,
        gmail_auth_type="app_password",
        gmail_password=encrypt_key("obsolete-password"),
        gmail_sender="sender@example.test",
        gmail_recipient="admin@example.test",
        gmail_client_id=encrypt_key("test-client-id"),
        gmail_client_secret=encrypt_key("test-client-secret"),
        gmail_refresh_token=encrypt_key("system-refresh") if system_connected else "",
        gmail_access_token=encrypt_key("system-access") if system_connected else "",
        gmail_token_expires_at=4102444800,
    )
    portal.save_config(config)
    db(
        """INSERT INTO user_google_accounts
           (agent_id, provider, email, refresh_token, access_token, granted_scopes, expires_at)
           VALUES (1, 'google', 'staff@example.test', %s, %s, %s, %s)""",
        (
            encrypt_key("staff-refresh"),
            encrypt_key("staff-access"),
            "https://www.googleapis.com/auth/gmail.send",
            4102444800,
        ),
    )
    smtp = MagicMock()
    monkeypatch.setattr("smtplib.SMTP", smtp)
    transport = httpx.Client._send_single_request
    sent = []

    def google_transport(self, request):
        if request.url.host != "gmail.googleapis.com":
            return transport(self, request)
        sent.append(request)
        return httpx.Response(
            provider_status,
            json={"id": "accepted"}
            if provider_status == 200
            else {"error": "permission denied"},
            request=request,
        )

    monkeypatch.setattr(httpx.Client, "_send_single_request", google_transport)
    before = db("SELECT * FROM user_google_accounts WHERE agent_id = 1")
    success = send_admin_notification(
        "appointment",
        {"customer_name": "Mail Test Customer", "service_type": "Inspection"},
        agent_name="Mail Test Staff",
    )
    assert success is (provider_status == 200)
    expected_accounts = ["system-access"] if system_connected else ["staff-access"]
    if system_connected and provider_status != 200:
        expected_accounts.append("staff-access")
    assert [r.headers["Authorization"] for r in sent] == [
        "Bearer " + access for access in expected_accounts
    ]
    for request in sent:
        assert request.method == "POST"
        assert request.url.path == "/gmail/v1/users/me/messages/send"
        raw = json.loads(request.content)["raw"]
        mail = message_from_bytes(base64.urlsafe_b64decode(raw), policy=policy.default)
        assert mail["To"] == "admin@example.test"
        expected_sender = (
            "sender@example.test"
            if request.headers["Authorization"] == "Bearer system-access"
            else "staff@example.test"
        )
        assert mail["From"].addresses[0].addr_spec == expected_sender
        assert "New Appointment Scheduled" in mail["Subject"]
        assert (
            "Mail Test Customer"
            in mail.get_body(preferencelist=("html",)).get_content()
        )
    assert db("SELECT * FROM user_google_accounts WHERE agent_id = 1") == before
    assert portal.load_config() == config
    smtp.assert_not_called()


def test_routine_admin_copy_is_suppressed_while_calendar_invitation_remains(
    db, monkeypatch
):
    from serviceBot.api import portal
    from serviceBot.services import gmail, outbox_worker

    config = portal.load_config()
    config.update(
        gmail_enabled=True,
        gmail_routine_admin_copies_enabled=False,
        gmail_sender="sender@example.test",
        gmail_recipient="admin@example.test",
    )
    portal.save_config(config)

    monkeypatch.setattr(gmail, "get_gmail_access_token", lambda: "calendar-access")
    monkeypatch.setattr(
        outbox_worker, "delete_admin_calendar_event", lambda *_args, **_kwargs: True
    )
    calendar_calls = []

    def capture_calendar_event(url, **kwargs):
        calendar_calls.append((url, kwargs))
        return httpx.Response(
            201,
            json={"id": "captured-admin-calendar-event"},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(gmail.httpx, "post", capture_calendar_event)
    send_admin_mail = MagicMock(return_value=True)
    monkeypatch.setattr(gmail, "send_gmail_api_email", send_admin_mail)

    outbox_worker._dispatch_outbox_event(
        "booking_notification",
        request_id=None,
        payload={
            "booking_type": "appointment",
            "notification_event": "BOOKING",
            "details": {
                "customer_name": "Calendar Test Customer",
                "service_type": "Inspection",
                "issue": "Captured provider test",
            },
            "agent_name": "Test Agent",
            "agent_email": None,
            "agent_phone": None,
            "booking_time_str": "2026-11-23 10:00:00",
        },
    )

    send_admin_mail.assert_not_called()
    assert len(calendar_calls) == 1
    url, kwargs = calendar_calls[0]
    assert url.endswith("/calendars/primary/events")
    assert kwargs["params"] == {"sendUpdates": "all"}
    assert kwargs["json"]["attendees"] == [{"email": "admin@example.test"}]
