"""Admin email saves survive an overlapping Google token refresh."""

import json
import inspect
from contextlib import contextmanager

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


@pytest.mark.test_layer("http")
def test_admin_config_save_uses_sync_fastapi_dispatch():
    """Synchronous persistence runs in FastAPI's worker pool, not the event loop."""
    assert not inspect.iscoroutinefunction(portal.update_gmail_config)


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
def test_admin_config_save_uses_one_database_checkout(monkeypatch, tmp_path):
    """A warm save should perform its phone and email writes on one checkout."""
    monkeypatch.setattr(portal, "CONFIG_PATH", str(tmp_path / "config.json"))
    monkeypatch.setattr(portal, "SYSTEM_PROMPT_PATH", str(tmp_path / "system_prompt.txt"))
    from serviceBot.db import queries

    real_get_db_connection = queries.get_db_connection
    checkouts = []

    @contextmanager
    def counted_get_db_connection():
        checkouts.append("checkout")
        with real_get_db_connection() as conn:
            yield conn

    monkeypatch.setattr(queries, "get_db_connection", counted_get_db_connection)
    response = TestClient(app).post(
        "/api/v1/portal/gmail-config",
        json={
            "gmail_enabled": False,
            "gmail_sender": "sender@example.test",
            "gmail_recipient": "checkout-budget@example.test",
            "admin_phone_number": "+15550109991",
        },
    )

    assert response.status_code == 200
    assert len(checkouts) <= 1

    # Keep the request budget scoped to the route itself. These reads must use
    # fresh database checkouts so the test proves all three writes persisted.
    monkeypatch.setattr(queries, "get_db_connection", real_get_db_connection)
    sms_config = queries.get_sms_config()
    whitelist = queries.get_sms_whitelist()
    persisted_recipient = queries.get_admin_notification_email()

    assert sms_config["admin_phone_number"] == "+15550109991"
    admin_contact = next(
        entry
        for entry in whitelist
        if entry["phone_number"] == "+15550109991"
    )
    assert admin_contact["friendly_name"] == "Admin Notification Contact"
    assert admin_contact["recipient_role"] == "ADMIN"
    assert admin_contact["twilio_verified"] is True
    assert persisted_recipient == "checkout-budget@example.test"


@pytest.mark.test_layer("database")
def test_admin_notification_settings_success_avoids_savepoint_release_roundtrip(monkeypatch):
    from contextlib import contextmanager

    from serviceBot.db import queries

    executed = []

    class Cursor:
        def execute(self, sql, params=None):
            executed.append(sql.strip())

        def fetchone(self):
            return {"gmail_recipient": "admin@example.test"}

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    class Connection:
        def cursor(self):
            return Cursor()

    @contextmanager
    def fake_connection():
        yield Connection()

    @contextmanager
    def fake_dict_cursor(_conn):
        yield Cursor()

    monkeypatch.setattr(queries, "get_db_connection", fake_connection)
    monkeypatch.setattr(queries, "dict_cursor", fake_dict_cursor)
    monkeypatch.setattr(queries, "_persist_admin_phone_on_connection", lambda *_: None)

    result = queries.update_admin_notification_settings(
        "admin@example.test", admin_phone_number="+15550109991"
    )

    assert result == {"email": "admin@example.test", "phone_error": None}
    assert "SAVEPOINT admin_phone_persistence;" in executed
    assert not any(sql.startswith("RELEASE SAVEPOINT") for sql in executed)


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

    def fail_persist(email, admin_phone_number=None):
        raise RuntimeError("synthetic database outage")

    monkeypatch.setattr(queries, "update_admin_notification_settings", fail_persist)
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
def test_admin_email_save_preserves_config_updated_during_database_persistence(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(portal, "CONFIG_PATH", str(tmp_path / "config.json"))
    monkeypatch.setattr(portal, "SYSTEM_PROMPT_PATH", str(tmp_path / "system_prompt.txt"))
    config = portal.load_config()
    config.update(
        gmail_enabled=False,
        gmail_sender="sender@example.test",
        gmail_recipient="old-admin@example.test",
        business_timezone="America/New_York",
    )
    portal.save_config(config)

    from serviceBot.db import queries

    def persist_with_overlapping_update(email, admin_phone_number=None):
        # Deterministically model a concurrent /config write after Gmail's DB
        # persistence starts but before its local JSON save.
        portal.update_config_values({"business_timezone": "Europe/London"})
        return {"email": email, "phone_error": None}

    monkeypatch.setattr(
        queries, "update_admin_notification_settings", persist_with_overlapping_update
    )
    response = TestClient(app).post(
        "/api/v1/portal/gmail-config",
        json={
            "gmail_enabled": False,
            "gmail_sender": "sender@example.test",
            "gmail_recipient": "new-admin@example.test",
        },
    )

    assert response.status_code == 200
    saved = portal.load_config()
    assert saved["gmail_recipient"] == "new-admin@example.test"
    assert saved["business_timezone"] == "Europe/London"


@pytest.mark.test_layer("http")
def test_config_save_preserves_gmail_update_during_database_persistence(
    monkeypatch, tmp_path
):
    """The inverse overlap must not restore a stale Gmail snapshot."""
    monkeypatch.setattr(portal, "CONFIG_PATH", str(tmp_path / "config.json"))
    monkeypatch.setattr(portal, "SYSTEM_PROMPT_PATH", str(tmp_path / "system_prompt.txt"))
    config = portal.load_config()
    config.update(
        gmail_enabled=True,
        gmail_recipient="old-admin@example.test",
        gmail_access_token="old-access-token",
    )
    portal.save_config(config)

    from serviceBot.db import queries

    def persist_phone_with_overlapping_gmail_update(_settings):
        # Model a Gmail worker saving after /config took its initial snapshot
        # but before its synchronous support-phone database write completes.
        portal.update_config_values(
            {
                "gmail_recipient": "new-admin@example.test",
                "gmail_access_token": "refreshed-access-token",
                "system_prompt": "Concurrent prompt update.",
            }
        )

    monkeypatch.setattr(queries, "update_sms_config", persist_phone_with_overlapping_gmail_update)
    async def sync_prompt(*_args, **_kwargs):
        return {"status": "synced"}

    monkeypatch.setattr(portal, "sync_prompt_to_elevenlabs", sync_prompt)
    response = TestClient(app).post(
        "/api/v1/portal/config",
        json={"support_phone_number": "+15550109993"},
    )

    assert response.status_code == 200
    saved = portal.load_config()
    assert saved["support_phone_number"] == "+15550109993"
    assert saved["gmail_recipient"] == "new-admin@example.test"
    assert saved["gmail_access_token"] == "refreshed-access-token"
    assert "Concurrent prompt update." in saved["system_prompt"]


@pytest.mark.test_layer("http")
def test_admin_phone_persistence_failure_does_not_block_email_save(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(portal, "CONFIG_PATH", str(tmp_path / "config.json"))
    monkeypatch.setattr(portal, "SYSTEM_PROMPT_PATH", str(tmp_path / "system_prompt.txt"))
    from serviceBot.db import queries

    original_phone_number = queries.get_sms_config()["admin_phone_number"]
    update_rowcounts = []

    def fail_phone(conn, phone_number):
        # Make the first phone write on the request's transaction, then fail.
        # The SAVEPOINT must undo this write while allowing email to commit.
        with queries.dict_cursor(conn) as cursor:
            cursor.execute(
                "UPDATE sms_config SET admin_phone_number = %s "
                "WHERE id = (SELECT id FROM sms_config ORDER BY id ASC LIMIT 1);",
                (phone_number,),
            )
            update_rowcounts.append(cursor.rowcount)
        raise RuntimeError("synthetic SMS schema outage")

    monkeypatch.setattr(queries, "_persist_admin_phone_on_connection", fail_phone)
    response = TestClient(app).post(
        "/api/v1/portal/gmail-config",
        json={
            "gmail_enabled": False,
            "gmail_sender": "sender@example.test",
            "gmail_recipient": "phone-failure@example.test",
            "admin_phone_number": "+15550109992",
        },
    )

    assert response.status_code == 200
    assert update_rowcounts == [1]
    assert queries.get_admin_notification_email() == "phone-failure@example.test"
    assert portal.load_config()["gmail_recipient"] == "phone-failure@example.test"
    assert queries.get_sms_config()["admin_phone_number"] == original_phone_number


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
    assert multi_service_call["json"]["extendedProperties"]["private"][
        "serviceBotManagedEvent"
    ] == "agent_booking"
