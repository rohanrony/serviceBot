import pytest
import time
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

from serviceBot.main import app
from serviceBot.db.connection import get_db_connection
from serviceBot.db.queries import check_availability, book_appointment
from serviceBot.services.google_calendar import is_agent_free, create_agent_calendar_event

client = TestClient(app)

@pytest.fixture(autouse=True)
def clean_db_agent():
    from serviceBot.services.encryption import encrypt_key
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM staff_agents WHERE id = 100;")
        cursor.execute("DELETE FROM user_google_accounts WHERE agent_id = 100;")
        cursor.execute("DELETE FROM service_requests WHERE staff_agent_id = 100;")
        
        # Insert a test agent
        cursor.execute(
            "INSERT INTO staff_agents (id, name, role, email) VALUES (100, 'Test Agent', 'Tester', 'test.agent@example.com');"
        )
        # Also insert a connected google account for the test agent so tests can mock calls!
        cursor.execute(
            "INSERT INTO user_google_accounts (agent_id, provider, email, refresh_token, access_token, granted_scopes, expires_at) "
            "VALUES (100, 'google', 'test.agent@example.com', ?, ?, ?, ?);",
            (encrypt_key("dummy_refresh_token"), encrypt_key("dummy_access_token"), "https://www.googleapis.com/auth/calendar.events", time.time() + 3600)
        )
        cursor.execute(
            "INSERT OR IGNORE INTO mock_calendar_slots (slot_datetime, is_booked, staff_agent_id) "
            "VALUES ('2026-06-25 11:00:00', 0, 100);"
        )
        conn.commit()
    yield
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM staff_agents WHERE id = 100;")
        cursor.execute("DELETE FROM user_google_accounts WHERE agent_id = 100;")
        cursor.execute("DELETE FROM service_requests WHERE staff_agent_id = 100;")
        conn.commit()


def test_portal_get_agents_includes_new_fields():
    response = client.get("/api/v1/portal/agents")
    assert response.status_code == 200
    agents = response.json()
    assert isinstance(agents, list)
    
    # Check that our test agent has is_connected and email
    test_agent = next((a for a in agents if a["id"] == 100), None)
    assert test_agent is not None
    assert test_agent["email"] == "test.agent@example.com"
    assert test_agent["is_connected"] is True

def test_portal_get_agent_oauth_url():
    # Configure mock Client ID first
    with patch("serviceBot.api.portal.load_config") as mock_load:
        # Client ID encrypted
        from serviceBot.services.encryption import encrypt_key
        mock_load.return_value = {
            "gmail_client_id": encrypt_key("dummy_client_id"),
            "gmail_client_secret": encrypt_key("dummy_secret")
        }
        
        response = client.get("/api/v1/portal/agents/100/oauth-url")
        assert response.status_code == 200
        data = response.json()
        assert "auth_url" in data
        assert "state=" in data["auth_url"]
        assert "scope=" in data["auth_url"]

def test_portal_agent_disconnect():
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO user_google_accounts (agent_id, provider, email, refresh_token) VALUES (100, 'google', 'test.agent@example.com', 'dummy_refresh_token');"
        )
        conn.commit()

    response = client.post("/api/v1/portal/agents/100/disconnect")
    assert response.status_code == 200
    assert response.json()["success"] is True
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM user_google_accounts WHERE agent_id = 100;")
        count = cursor.fetchone()[0]
        assert count == 0

@patch("httpx.post")
@patch("httpx.get")
def test_agent_oauth_callback(mock_get, mock_post):
    # Mock token exchange response
    mock_post_resp = MagicMock()
    mock_post_resp.status_code = 200
    mock_post_resp.json.return_value = {
        "access_token": "mock_access_token",
        "refresh_token": "mock_refresh_token",
        "expires_in": 3600,
        "scope": "openid email profile https://www.googleapis.com/auth/calendar.events"
    }
    mock_post.return_value = mock_post_resp

    # Mock userinfo response
    mock_get_resp = MagicMock()
    mock_get_resp.status_code = 200
    mock_get_resp.json.return_value = {
        "sub": "mock_google_id",
        "email": "authenticated.agent@example.com",
        "name": "Authenticated Agent"
    }
    mock_get.return_value = mock_get_resp

    # Force configurations
    with patch("serviceBot.api.portal.load_config") as mock_load:
        from serviceBot.services.encryption import encrypt_key
        mock_load.return_value = {
            "gmail_client_id": encrypt_key("dummy_client_id"),
            "gmail_client_secret": encrypt_key("dummy_secret")
        }
        
        # Insert matching state in oauth_states table
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT OR REPLACE INTO oauth_states (state, agent_id, action_type) VALUES ('agent_100', 100, 'calendar');")
            conn.commit()

        response = client.get(
            "/api/v1/portal/gmail/oauth/callback?code=mockcode&state=agent_100"
        )
        assert response.status_code == 200
        # Verify saved in user_google_accounts table and staff_agents table
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT email, refresh_token FROM user_google_accounts WHERE agent_id = 100;")
            row = cursor.fetchone()
            assert row is not None
            assert row["email"] == "authenticated.agent@example.com"
            assert row["refresh_token"] is not None

            # Verify that initial staff agent name is retained
            cursor.execute("SELECT name FROM staff_agents WHERE id = 100;")
            name_row = cursor.fetchone()
            assert name_row["name"] == "Test Agent"

@patch("serviceBot.services.google_calendar.get_user_google_credentials")
@patch("httpx.get")
def test_is_agent_free_busy(mock_get, mock_creds):
    mock_creds.return_value = {
        "access_token": "valid_token",
        "refresh_token": "dummy_refresh",
        "granted_scopes": {"https://www.googleapis.com/auth/calendar.events"},
        "email": "test.agent@example.com",
        "google_account_id": "sub_123"
    }
    
    # 1. Mock busy (returns an event)
    mock_get_resp_busy = MagicMock()
    mock_get_resp_busy.status_code = 200
    mock_get_resp_busy.json.return_value = {
        "items": [{"id": "event1", "status": "confirmed", "start": {"dateTime": "2026-06-25T10:00:00-04:00"}, "end": {"dateTime": "2026-06-25T11:00:00-04:00"}}]
    }
    mock_get.return_value = mock_get_resp_busy
    assert is_agent_free(100, "2026-06-25 10:00:00") is False

    # 2. Mock free (returns empty items list)
    mock_get_resp_free = MagicMock()
    mock_get_resp_free.status_code = 200
    mock_get_resp_free.json.return_value = {
        "items": []
    }
    mock_get.return_value = mock_get_resp_free
    assert is_agent_free(100, "2026-06-25 10:00:00") is True

@patch("serviceBot.services.google_calendar.fetch_agent_events")
def test_check_availability_filtering(mock_fetch):
    # If the agent is busy, slot should not be returned in check_availability
    mock_fetch.return_value = [{"id": "event1", "status": "confirmed", "start": {"dateTime": "2026-06-25T11:00:00-04:00"}, "end": {"dateTime": "2026-06-25T12:00:00-04:00"}}]
    slots = check_availability(preferred_date="2026-06-25 09:00:00")
    # Should not find 2026-06-25 11:00:00 because the single agent is busy
    assert "2026-06-25 11:00:00" not in slots

    # If the agent is free, slot should be returned
    mock_fetch.return_value = []
    slots = check_availability(preferred_date="2026-06-25 09:00:00")
    assert "2026-06-25 11:00:00" in slots

@patch("serviceBot.services.google_calendar.is_agent_free")
@patch("serviceBot.services.google_calendar.create_agent_calendar_event")
@patch("serviceBot.services.gmail.send_booking_notification")
def test_booking_notifications(mock_notify, mock_event, mock_free):
    mock_free.return_value = True
    mock_event.return_value = True
    
    # We must insert a mock vehicle for Sarah Johnson (id=1) as it is now required
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO vehicles (id, customer_id, make, model, year) VALUES (99, 1, 'Honda', 'Civic', 2020);")
        conn.commit()
    
    appt_id = book_appointment(
        customer_id=1,
        service_request_id=None,
        appointment_datetime="2026-06-25 11:00:00",
        service_type="Oil Change"
    )
    assert appt_id is not None
    
    # Confirm slot has been marked booked in local DB service_requests table
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT staff_agent_id, booking_time FROM service_requests WHERE id = ?;", (appt_id,))
        row = cursor.fetchone()
        assert row["staff_agent_id"] == 100
        assert row["booking_time"] == "2026-06-25 11:00:00"

