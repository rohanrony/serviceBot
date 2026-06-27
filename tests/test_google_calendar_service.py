import pytest
import time
import zoneinfo
from datetime import datetime
from unittest.mock import patch, MagicMock
from serviceBot.services.google_calendar import (
    get_user_google_credentials,
    is_agent_free,
    create_agent_calendar_event,
    fetch_agent_events,
    list_upcoming_events,
    parse_google_datetime,
    GoogleAuthException
)
from serviceBot.db.connection import get_db_connection
from serviceBot.services.encryption import encrypt_key

@patch("serviceBot.services.google_calendar.load_config")
def test_get_user_google_credentials_not_connected(mock_load):
    """Verify get_user_google_credentials raises GoogleAuthException if no account connected."""
    mock_load.return_value = {
        "gmail_client_id": encrypt_key("dummy_id"),
        "gmail_client_secret": encrypt_key("dummy_secret")
    }
    
    # Run in clean DB context (no user google account)
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM user_google_accounts WHERE agent_id = 999;")
        conn.commit()
        
    with pytest.raises(GoogleAuthException) as excinfo:
        get_user_google_credentials(999)
    assert "not connected" in str(excinfo.value)

@patch("serviceBot.services.google_calendar.load_config")
@patch("httpx.post")
def test_get_user_google_credentials_expired_refresh(mock_post, mock_load):
    """Verify get_user_google_credentials auto-refreshes using refresh token if expired."""
    mock_load.return_value = {
        "gmail_client_id": encrypt_key("dummy_id"),
        "gmail_client_secret": encrypt_key("dummy_secret")
    }
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        # Seed the foreign key reference staff_agent ID 999 first
        cursor.execute("INSERT OR IGNORE INTO staff_agents (id, name, role, email) VALUES (999, 'Test Agent 999', 'Advisor', 'agent@test.com');")
        cursor.execute("DELETE FROM user_google_accounts WHERE agent_id = 999;")
        cursor.execute(
            "INSERT INTO user_google_accounts (agent_id, provider, email, refresh_token, access_token, expires_at) "
            "VALUES (999, 'google', 'agent@test.com', ?, ?, ?);",
            (encrypt_key("my_refresh_token"), encrypt_key("old_access_token"), time.time() - 100) # already expired
        )
        conn.commit()
        
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "access_token": "brand_new_access_token",
        "expires_in": 3600
    }
    mock_post.return_value = mock_response
    
    creds = get_user_google_credentials(999)
    assert creds["access_token"] == "brand_new_access_token"

@patch("serviceBot.services.google_calendar.get_user_google_credentials")
@patch("httpx.get")
def test_is_agent_free(mock_get, mock_creds):
    """Verify is_agent_free parses Live Google Calendar response correctly."""
    mock_creds.return_value = {
        "access_token": "dummy",
        "granted_scopes": {"https://www.googleapis.com/auth/calendar.events"} # include required key
    }
    
    mock_response = MagicMock()
    mock_response.status_code = 200
    # Setup some overlapping event (busy)
    mock_response.json.return_value = {
        "items": [
            {
                "id": "event_123",
                "status": "confirmed",
                "start": {"dateTime": "2026-06-25T10:00:00-04:00"},
                "end": {"dateTime": "2026-06-25T11:00:00-04:00"}
            }
        ]
    }
    mock_get.return_value = mock_response
    
    # 2026-06-25 10:15:00 falls inside 10:00-11:00 event range -> busy
    free = is_agent_free(999, "2026-06-25 10:15:00", duration_minutes=30)
    assert free is False

@patch("serviceBot.services.google_calendar.get_user_google_credentials")
@patch("httpx.post")
def test_create_agent_calendar_event(mock_post, mock_creds):
    """Verify create_agent_calendar_event constructs body payload correctly."""
    mock_creds.return_value = {
        "access_token": "dummy", 
        "email": "agent@test.com",
        "granted_scopes": {"https://www.googleapis.com/auth/calendar.events"}
    }
    
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"id": "event_created_999"}
    mock_post.return_value = mock_response
    
    res = create_agent_calendar_event(
        agent_id=999,
        customer_name="John Doe",
        service_type="AC Repair",
        issue_description="Blowing warm air",
        slot_datetime_str="2026-06-25 10:00:00",
        duration_minutes=45
    )
    
    assert res is True
    assert mock_post.called
    
    # Check payload parameters
    _, kwargs = mock_post.call_args
    json_data = kwargs.get("json", {})
    assert json_data["summary"] == "serviceBot Appointment - John Doe"
    assert "AC Repair" in json_data["description"]
    assert "Blowing warm air" in json_data["description"]
    assert json_data["start"]["dateTime"] == "2026-06-25T10:00:00-04:00"

def test_parse_google_datetime():
    """Verify parsing of start/end Google structures (both dateTime and date)."""
    tz = zoneinfo.ZoneInfo("America/New_York")
    
    # 1. dateTime with offset
    res = parse_google_datetime({"dateTime": "2026-06-25T10:00:00-04:00"}, tz)
    assert res is not None
    assert res.year == 2026
    assert res.hour == 10
    
    # 2. All day date
    res = parse_google_datetime({"date": "2026-06-25"}, tz)
    assert res is not None
    assert res.year == 2026
    assert res.hour == 0
    
    # 3. None handling
    assert parse_google_datetime(None, tz) is None
