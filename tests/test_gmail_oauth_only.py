"""Observable admin-mail contracts when upgrading legacy configuration."""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from serviceBot.api import portal
from serviceBot.main import app
from serviceBot.services import gmail
from serviceBot.services.encryption import encrypt_key
from serviceBot.services.gmail import send_booking_notification

client = TestClient(app)
LEGACY_KEYS = {"gmail_password", "gmail_smtp_server", "gmail_smtp_port"}


@pytest.fixture
def mail_config():
    original = portal.load_config()
    config = dict(original)
    config.update(
        gmail_enabled=True,
        gmail_sender="sender@example.test",
        gmail_recipient="admin@example.test",
        gmail_auth_type="app_password",
        gmail_password="obsolete-encrypted-password",
        gmail_smtp_server="smtp.example.test",
        gmail_smtp_port=587,
        gmail_refresh_token="preserved-encrypted-refresh",
        gmail_access_token="preserved-encrypted-access",
        gmail_token_expires_at=12345,
        gmail_client_id=encrypt_key("preserved-client-id"),
        gmail_client_secret=encrypt_key("preserved-client-secret"),
    )
    portal.save_config(config)
    yield config
    portal.save_config(original)


def payload(**changes):
    return {
        "gmail_enabled": True,
        "gmail_sender": "",
        "gmail_recipient": "new-admin@example.test",
        "enable_agent_selection": True,
        **changes,
    }


def test_legacy_read_exposes_only_google_and_never_password(mail_config):
    response = client.get("/api/v1/portal/gmail-config")
    assert response.status_code == 200
    data = response.json()
    assert data["gmail_auth_type"] == "oauth2"
    assert data["is_connected"] is True
    assert not (LEGACY_KEYS | {"has_password"}) & data.keys()
    assert "obsolete-encrypted-password" not in response.text


def test_save_defaults_to_google_removes_smtp_and_preserves_tokens(mail_config):
    response = client.post("/api/v1/portal/gmail-config", json=payload())
    assert response.status_code == 200
    saved = portal.load_config()
    assert saved["gmail_auth_type"] == "oauth2"
    assert not LEGACY_KEYS & saved.keys()
    assert saved["gmail_sender"] == mail_config["gmail_sender"]
    assert saved["gmail_recipient"] == "new-admin@example.test"
    assert saved["enable_agent_selection"] is True
    for key in (
        "gmail_refresh_token",
        "gmail_access_token",
        "gmail_token_expires_at",
        "gmail_client_id",
        "gmail_client_secret",
        "business_timezone",
    ):
        assert saved[key] == mail_config[key]


@pytest.mark.parametrize("endpoint", ["gmail-config", "gmail-config/test"])
@pytest.mark.parametrize(
    "changes",
    [
        {"gmail_auth_type": "app_password"},
        {"gmail_auth_type": "unknown"},
        {"gmail_auth_type": "oauth2", "gmail_password": "obsolete"},
        {"gmail_auth_type": "oauth2", "gmail_smtp_server": "smtp.example.test"},
        {"gmail_auth_type": "oauth2", "gmail_smtp_port": 587},
    ],
)
def test_unsupported_requests_have_no_writes_or_sends(
    mail_config, monkeypatch, endpoint, changes
):
    smtp = MagicMock()
    send = MagicMock(return_value=True)
    monkeypatch.setattr("smtplib.SMTP", smtp)
    monkeypatch.setattr(gmail, "send_gmail_api_email", send)
    before = portal.load_config()
    response = client.post(f"/api/v1/portal/{endpoint}", json=payload(**changes))
    assert response.status_code == 422
    assert portal.load_config() == before
    smtp.assert_not_called()
    send.assert_not_called()


@pytest.mark.parametrize("result", [False, RuntimeError("Google unavailable")])
def test_booking_google_failure_never_reports_success_or_uses_smtp(
    mail_config, monkeypatch, result
):
    monkeypatch.setattr(gmail, "load_config", lambda: mail_config)
    send = MagicMock(return_value=False)
    if isinstance(result, Exception):
        send.side_effect = result
    smtp = MagicMock()
    monkeypatch.setattr(gmail, "send_gmail_api_email", send)
    monkeypatch.setattr("smtplib.SMTP", smtp)
    if isinstance(result, Exception):
        with pytest.raises(RuntimeError, match="Google unavailable"):
            send_booking_notification("appointment", {})
    else:
        assert send_booking_notification("appointment", {}) is False
    send.assert_called_once()
    smtp.assert_not_called()


@pytest.mark.parametrize(
    "connected,result,status",
    [
        (True, True, 200),
        (True, False, 500),
        (True, RuntimeError("provider unavailable"), 500),
        (False, True, 400),
    ],
)
def test_connection_test_uses_google_and_reports_result(
    mail_config, monkeypatch, connected, result, status
):
    if not connected:
        mail_config["gmail_refresh_token"] = ""
        portal.save_config(mail_config)
    smtp = MagicMock()
    send = MagicMock(return_value=result if isinstance(result, bool) else None)
    if isinstance(result, Exception):
        send.side_effect = result
    monkeypatch.setattr("smtplib.SMTP", smtp)
    monkeypatch.setattr(gmail, "send_gmail_api_email", send)
    response = client.post("/api/v1/portal/gmail-config/test", json=payload())
    assert response.status_code == status
    smtp.assert_not_called()
    if connected:
        send.assert_called_once()
        assert send.call_args.kwargs["sender"] == mail_config["gmail_sender"]
        assert send.call_args.kwargs["recipient"] == "new-admin@example.test"
    else:
        send.assert_not_called()
        assert "Connect Gmail Account" in response.json()["detail"]


@pytest.mark.parametrize("auth", [None, "app_password", "oauth2"])
@pytest.mark.parametrize(
    "notify", [send_booking_notification, gmail.send_admin_notification]
)
def test_notifications_use_google_even_with_old_or_missing_selector(
    mail_config, monkeypatch, auth, notify
):
    if auth is None:
        mail_config.pop("gmail_auth_type")
    else:
        mail_config["gmail_auth_type"] = auth
    monkeypatch.setattr(gmail, "load_config", lambda: mail_config)
    smtp = MagicMock()
    send = MagicMock(return_value=True)
    monkeypatch.setattr("smtplib.SMTP", smtp)
    monkeypatch.setattr(gmail, "send_gmail_api_email", send)
    assert notify("appointment", {"customer_name": "OAuth Customer"}) is True
    send.assert_called_once()
    assert send.call_args.kwargs["recipient"] == "admin@example.test"
    smtp.assert_not_called()


@pytest.mark.parametrize(
    "change", [{"gmail_enabled": False}, {"gmail_sender": ""}, {"gmail_recipient": ""}]
)
@pytest.mark.parametrize(
    "notify", [send_booking_notification, gmail.send_admin_notification]
)
def test_disabled_or_incomplete_mail_never_sends(
    mail_config, monkeypatch, change, notify
):
    monkeypatch.setattr(gmail, "load_config", lambda: {**mail_config, **change})
    send = MagicMock()
    monkeypatch.setattr(gmail, "send_gmail_api_email", send)
    assert notify("appointment", {}) is False
    send.assert_not_called()


@pytest.mark.parametrize("system_result", [False, RuntimeError("system disconnected")])
@pytest.mark.parametrize("staff_result", [True, False, None])
def test_admin_google_failure_retains_staff_fallback(
    mail_config, monkeypatch, system_result, staff_result
):
    monkeypatch.setattr(gmail, "load_config", lambda: mail_config)
    send = MagicMock(return_value=system_result if system_result is False else None)
    if isinstance(system_result, Exception):
        send.side_effect = system_result
    monkeypatch.setattr(gmail, "send_gmail_api_email", send)
    staff_send = MagicMock(return_value=staff_result)
    monkeypatch.setattr(gmail, "send_gmail_via_api", staff_send)
    connection = MagicMock()
    cursor = MagicMock()
    cursor.fetchone.return_value = None if staff_result is None else {"agent_id": 8}
    monkeypatch.setattr(
        "serviceBot.db.connection.get_db_connection", lambda: connection
    )
    monkeypatch.setattr("serviceBot.db.connection.dict_cursor", lambda conn: cursor)
    cursor.__enter__.return_value = cursor
    smtp = MagicMock()
    monkeypatch.setattr("smtplib.SMTP", smtp)
    assert gmail.send_admin_notification("appointment", {}) is bool(staff_result)
    send.assert_called_once()
    smtp.assert_not_called()
    if staff_result is None:
        staff_send.assert_not_called()
    else:
        staff_send.assert_called_once()
        assert staff_send.call_args.kwargs["agent_id"] == 8


@pytest.mark.parametrize("staff_result", [True, False])
def test_booking_preserves_staff_google_then_system_routing(
    mail_config, monkeypatch, staff_result
):
    monkeypatch.setattr(gmail, "load_config", lambda: mail_config)
    connection = MagicMock()
    cursor = MagicMock()
    cursor.__enter__.return_value = cursor
    cursor.fetchone.return_value = {"id": 8}
    monkeypatch.setattr(gmail, "get_db_connection", lambda: connection)
    monkeypatch.setattr("serviceBot.db.connection.dict_cursor", lambda conn: cursor)
    staff_send = MagicMock(return_value=staff_result)
    system_send = MagicMock(return_value=True)
    smtp = MagicMock()
    monkeypatch.setattr(gmail, "send_gmail_via_api", staff_send)
    monkeypatch.setattr(gmail, "send_gmail_api_email", system_send)
    monkeypatch.setattr("smtplib.SMTP", smtp)
    assert (
        send_booking_notification("appointment", {}, agent_email="staff@example.test")
        is True
    )
    staff_send.assert_called_once()
    assert staff_send.call_args.kwargs["agent_id"] == 8
    assert staff_send.call_args.kwargs["recipient"] == "staff@example.test"
    if staff_result:
        system_send.assert_not_called()
    else:
        system_send.assert_called_once()
        assert system_send.call_args.kwargs["recipient"] == "staff@example.test"
    smtp.assert_not_called()
