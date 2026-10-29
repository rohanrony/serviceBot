"""Admin email saves survive an overlapping Google token refresh."""

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from serviceBot.api import portal
from serviceBot.main import app
from serviceBot.services import gmail, google_calendar
from serviceBot.services.encryption import decrypt_key, encrypt_key

_REAL_SEND_BOOKING_NOTIFICATION = gmail.send_booking_notification
_REAL_CREATE_ADMIN_CALENDAR_EVENT = gmail.create_admin_calendar_event
_REAL_CREATE_AGENT_CALENDAR_EVENT = google_calendar.create_agent_calendar_event


def _clear_saved_admin_email():
    """Keep this test independent of other settings persistence tests."""
    from serviceBot.db.connection import get_db_connection, dict_cursor

    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                "SELECT to_regclass('public.admin_notification_settings') AS table_name;"
            )
            if cursor.fetchone()["table_name"] is not None:
                cursor.execute("DELETE FROM admin_notification_settings;")


@pytest.mark.test_layer("http")
@pytest.mark.parametrize("google_status", [200, 403])
def test_admin_email_save_survives_token_refresh(monkeypatch, tmp_path, google_status):
    monkeypatch.setattr(portal, "CONFIG_PATH", str(tmp_path / "config.json"))
    monkeypatch.setattr(portal, "SYSTEM_PROMPT_PATH", str(tmp_path / "system_prompt.txt"))
    config = portal.load_config()
    config.update(
        gmail_enabled=True,
        gmail_recipient="old-admin@example.test",
        gmail_sender="sender@example.test",
        gmail_client_id=encrypt_key("synthetic-client"),
        gmail_client_secret=encrypt_key("synthetic-secret"),
        gmail_refresh_token=encrypt_key("synthetic-refresh"),
        gmail_access_token=encrypt_key("old-access"),
        gmail_token_expires_at=1,
    )
    portal.save_config(config)
    client = TestClient(app)

    def google_response(url, **kwargs):
        assert url == "https://oauth2.googleapis.com/token"
        assert kwargs["data"] == {
            "client_id": "synthetic-client",
            "client_secret": "synthetic-secret",
            "refresh_token": "synthetic-refresh",
            "grant_type": "refresh_token",
        }
        # A successful admin save occurs after refresh took its snapshot but
        # before Google responds. No threads or timing sleeps are necessary.
        response = client.post(
            "/api/v1/portal/gmail-config",
            json={
                "gmail_enabled": True,
                "gmail_sender": "sender@example.test",
                "gmail_recipient": "new-admin@example.test",
                "gmail_routine_admin_copies_enabled": True,
            },
        )
        assert response.status_code == 200
        assert portal.load_config()["gmail_recipient"] == "new-admin@example.test"
        return httpx.Response(
            google_status,
            json={"access_token": "new-access", "expires_in": 3600}
            if google_status == 200
            else {"error": "invalid_grant"},
        )

    monkeypatch.setattr(gmail.httpx, "post", google_response)
    token = gmail.refresh_gmail_token()

    with open(portal.CONFIG_PATH, encoding="utf-8") as saved_file:
        stored = json.load(saved_file)
    fresh = client.get("/api/v1/portal/gmail-config")
    assert fresh.status_code == 200
    assert fresh.json()["gmail_recipient"] == "new-admin@example.test"
    assert stored["gmail_recipient"] == "new-admin@example.test"
    assert stored["gmail_routine_admin_copies_enabled"] is True
    assert stored["gmail_refresh_token"] == config["gmail_refresh_token"]
    assert stored["business_timezone"] == config["business_timezone"]
    if google_status == 200:
        assert token == "new-access"
        assert decrypt_key(stored["gmail_access_token"]) == "new-access"
        assert stored["gmail_token_expires_at"] > 1
    else:
        assert token is None
        assert stored["gmail_access_token"] == config["gmail_access_token"]
        assert stored["gmail_token_expires_at"] == 1


@pytest.mark.test_layer("http")
def test_admin_email_save_survives_config_file_reset(monkeypatch, tmp_path):
    """A Free Render restart can reset JSON without losing the saved recipient."""
    monkeypatch.setattr(portal, "CONFIG_PATH", str(tmp_path / "config.json"))
    monkeypatch.setattr(portal, "SYSTEM_PROMPT_PATH", str(tmp_path / "system_prompt.txt"))
    _clear_saved_admin_email()

    config_before_save = portal.load_config()
    config_before_save.update(
        gmail_enabled=False,
        gmail_sender="sender@example.test",
        gmail_recipient="old-admin@example.test",
    )
    portal.save_config(config_before_save)
    client = TestClient(app)

    saved = client.post(
        "/api/v1/portal/gmail-config",
        json={
            "gmail_enabled": False,
            "gmail_sender": "sender@example.test",
            "gmail_recipient": "new-admin@example.test",
            "gmail_routine_admin_copies_enabled": False,
        },
    )
    assert saved.status_code == 200

    # Model Render's ephemeral filesystem returning to the pre-save config.
    portal.save_config(config_before_save)

    fresh = client.get("/api/v1/portal/gmail-config")
    assert fresh.status_code == 200
    assert fresh.json()["gmail_recipient"] == "new-admin@example.test"


@pytest.mark.test_layer("http")
def test_admin_email_save_does_not_report_success_when_database_write_fails(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(portal, "CONFIG_PATH", str(tmp_path / "config.json"))
    monkeypatch.setattr(portal, "SYSTEM_PROMPT_PATH", str(tmp_path / "system_prompt.txt"))
    config = portal.load_config()
    config.update(
        gmail_enabled=False,
        gmail_sender="sender@example.test",
        gmail_recipient="old-admin@example.test",
    )
    portal.save_config(config)

    from serviceBot.db import queries

    def fail_persist(email):
        raise RuntimeError("synthetic database outage")

    monkeypatch.setattr(queries, "update_admin_notification_email", fail_persist)
    response = TestClient(app).post(
        "/api/v1/portal/gmail-config",
        json={
            "gmail_enabled": False,
            "gmail_sender": "sender@example.test",
            "gmail_recipient": "new-admin@example.test",
        },
    )

    assert response.status_code == 503
    assert portal.load_config()["gmail_recipient"] == "old-admin@example.test"


@pytest.mark.test_layer("http")
def test_admin_email_read_does_not_return_stale_file_value_when_database_fails(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(portal, "CONFIG_PATH", str(tmp_path / "config.json"))
    monkeypatch.setattr(portal, "SYSTEM_PROMPT_PATH", str(tmp_path / "system_prompt.txt"))
    config = portal.load_config()
    config["gmail_recipient"] = "old-admin@example.test"
    portal.save_config(config)

    from serviceBot.db import queries

    def fail_read(default=None):
        raise RuntimeError("synthetic database outage")

    monkeypatch.setattr(queries, "get_admin_notification_email", fail_read)
    response = TestClient(app).get("/api/v1/portal/gmail-config")

    assert response.status_code == 503
    assert "gmail_recipient" not in response.json()


@pytest.mark.test_layer("provider_contract")
def test_email_and_calendar_delivery_use_saved_recipient_after_file_reset(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(portal, "CONFIG_PATH", str(tmp_path / "config.json"))
    monkeypatch.setattr(portal, "SYSTEM_PROMPT_PATH", str(tmp_path / "system_prompt.txt"))
    config_before_save = portal.load_config()
    config_before_save.update(
        gmail_enabled=True,
        gmail_routine_admin_copies_enabled=True,
        gmail_sender="sender@example.test",
        gmail_recipient="old-admin@example.test",
    )
    portal.save_config(config_before_save)
    client = TestClient(app)

    saved = client.post(
        "/api/v1/portal/gmail-config",
        json={
            "gmail_enabled": True,
            "gmail_routine_admin_copies_enabled": True,
            "gmail_sender": "sender@example.test",
            "gmail_recipient": "new-admin@example.test",
        },
    )
    assert saved.status_code == 200

    reset_config = portal.load_config()
    reset_config["gmail_recipient"] = "old-admin@example.test"
    portal.save_config(reset_config)

    email_call = {}
    monkeypatch.setattr(
        gmail,
        "send_gmail_api_email",
        lambda **kwargs: email_call.update(kwargs) or True,
    )
    assert gmail.send_admin_notification(
        "appointment",
        {"customer_name": "Test Customer", "service_type": "Inspection"},
        agent_name="Service Advisor",
    )
    assert email_call["recipient"] == "new-admin@example.test"

    email_call.clear()
    monkeypatch.setattr(
        gmail, "send_booking_notification", _REAL_SEND_BOOKING_NOTIFICATION
    )
    assert gmail.send_booking_notification(
        "appointment", {"customer_name": "Test Customer"}
    )
    assert email_call["recipient"] == "new-admin@example.test"

    calendar_call = {}
    monkeypatch.setattr(gmail, "get_gmail_access_token", lambda: "synthetic-access")
    monkeypatch.setattr(
        gmail, "create_admin_calendar_event", _REAL_CREATE_ADMIN_CALENDAR_EVENT
    )

    def record_admin_calendar_call(url, **kwargs):
        calendar_call.update(kwargs)
        return httpx.Response(201, json={"id": "admin-event"})

    monkeypatch.setattr(gmail.httpx, "post", record_admin_calendar_call)
    assert gmail.create_admin_calendar_event(
        customer_name="Test Customer",
        service_type="Inspection",
        issue_description="Routine inspection",
        slot_datetime_str="2026-10-29 10:00:00",
    )
    assert calendar_call["json"]["attendees"] == [
        {"email": "new-admin@example.test"}
    ]

    monkeypatch.setattr(
        google_calendar,
        "get_user_google_credentials",
        lambda agent_id: {
            "access_token": "synthetic-access",
            "granted_scopes": {"https://www.googleapis.com/auth/calendar.events"},
        },
    )
    monkeypatch.setattr(
        google_calendar, "create_agent_calendar_event", _REAL_CREATE_AGENT_CALENDAR_EVENT
    )
    agent_calendar_call = {}

    def record_agent_calendar_call(url, **kwargs):
        agent_calendar_call.update(kwargs)
        return httpx.Response(201, json={"id": "agent-event"})

    monkeypatch.setattr(google_calendar.httpx, "post", record_agent_calendar_call)
    assert google_calendar.create_agent_calendar_event(
        agent_id=7,
        customer_name="Test Customer",
        service_type="Inspection",
        issue_description="Routine inspection",
        slot_datetime_str="2026-10-29 10:00:00",
    )
    assert agent_calendar_call["json"]["attendees"] == [
        {"email": "new-admin@example.test"}
    ]

    multi_service_call = {}

    def record_multi_service_calendar_call(url, **kwargs):
        multi_service_call.update(kwargs)
        return httpx.Response(201, json={"id": "multi-service-event"})

    monkeypatch.setattr(
        google_calendar.httpx, "post", record_multi_service_calendar_call
    )
    multi_service_result = google_calendar.create_multi_service_calendar_events(
        customer_name="Test Customer",
        segments=[
            {
                "booking_time": "2026-10-29 10:00:00",
                "duration_minutes": 60,
                "service_name": "Inspection",
                "staff_agent_id": 7,
            }
        ],
        issue_description="Routine inspection",
    )
    assert multi_service_result["success"] is True
    assert multi_service_call["json"]["attendees"] == [
        {"email": "new-admin@example.test"}
    ]
