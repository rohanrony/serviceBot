import pytest
import time
import zoneinfo
import serviceBot.services.google_calendar as google_calendar
from datetime import datetime
from unittest.mock import patch, MagicMock
from serviceBot.services.google_calendar import (
    get_user_google_credentials,
    is_agent_free,
    create_agent_calendar_event,
    delete_agent_calendar_event,
    fetch_agent_events,
    list_upcoming_events,
    parse_google_datetime,
)
from serviceBot.db.connection import get_db_connection
from serviceBot.services.encryption import encrypt_key

@patch("serviceBot.services.google_calendar.load_config")
@patch("serviceBot.services.google_calendar.get_db_connection")
def test_get_user_google_credentials_not_connected(mock_db, mock_load):
    """Verify get_user_google_credentials raises GoogleAuthException if no account connected."""
    mock_load.return_value = {
        "gmail_client_id": encrypt_key("dummy_id"),
        "gmail_client_secret": encrypt_key("dummy_secret")
    }
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = None
    mock_conn.__enter__.return_value = mock_conn
    mock_cursor.__enter__.return_value = mock_cursor
    mock_db.return_value = mock_conn
    
    with patch("serviceBot.db.connection.dict_cursor", return_value=mock_cursor):
        with pytest.raises(google_calendar.GoogleAuthException) as excinfo:
            get_user_google_credentials(999)
        assert "not connected" in str(excinfo.value)

@patch("serviceBot.services.google_calendar.load_config")
@patch("serviceBot.services.google_calendar.get_db_connection")
@patch("httpx.post")
def test_get_user_google_credentials_expired_refresh(mock_post, mock_db, mock_load):
    """Verify get_user_google_credentials auto-refreshes using refresh token if expired."""
    mock_load.return_value = {
        "gmail_client_id": encrypt_key("dummy_id"),
        "gmail_client_secret": encrypt_key("dummy_secret")
    }
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = {
        "access_token": encrypt_key("old_access_token"),
        "refresh_token": encrypt_key("my_refresh_token"),
        "expires_at": time.time() - 100,
        "granted_scopes": "https://www.googleapis.com/auth/calendar.events",
        "email": "agent@test.com",
        "google_account_id": "google_123"
    }
    mock_conn.__enter__.return_value = mock_conn
    mock_cursor.__enter__.return_value = mock_cursor
    mock_db.return_value = mock_conn
    
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "access_token": "brand_new_access_token",
        "expires_in": 3600
    }
    mock_post.return_value = mock_response
    
    with patch("serviceBot.db.connection.dict_cursor", return_value=mock_cursor):
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

@patch("serviceBot.services.google_calendar.load_config")
@patch("serviceBot.services.google_calendar.get_user_google_credentials")
@patch("httpx.post")
def test_create_agent_calendar_event(mock_post, mock_creds, mock_load):
    """Verify create_agent_calendar_event constructs body payload with business branding."""
    mock_load.return_value = {"business_name": "Davidson CarCare"}
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
    assert json_data["summary"] == "Davidson CarCare Appointment - John Doe"
    assert json_data["extendedProperties"]["private"]["serviceBotManagedEvent"] == (
        "agent_booking"
    )
    assert "BayFull" not in json_data["summary"]
    assert "serviceBot" not in json_data["summary"]
    assert "AC Repair" in json_data["description"]
    assert "Blowing warm air" in json_data["description"]
    assert "Davidson CarCare" in json_data["description"]
    assert "BayFull" not in json_data["description"]
    assert "serviceBot" not in json_data["description"]
    assert json_data["start"]["dateTime"] == "2026-06-25T10:00:00-04:00"


@patch("serviceBot.services.google_calendar.load_config")
@patch("serviceBot.services.google_calendar.get_user_google_credentials")
@patch("httpx.post")
def test_create_agent_calendar_event_callback(mock_post, mock_creds, mock_load):
    """Verify create_agent_calendar_event builds branded summary and description for callbacks."""
    mock_load.return_value = {"business_name": "Davidson CarCare"}
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
        customer_name="Jane Doe",
        service_type="Brake Check",
        issue_description="Squeaking noise",
        slot_datetime_str="2026-06-25 10:00:00",
        duration_minutes=30,
        booking_type="callback"
    )

    assert res is True
    assert mock_post.called

    _, kwargs = mock_post.call_args
    json_data = kwargs.get("json", {})
    assert json_data["summary"] == "Davidson CarCare Callback - Jane Doe (Brake Check)"
    assert json_data["extendedProperties"]["private"]["serviceBotManagedEvent"] == (
        "agent_booking"
    )
    assert "BayFull" not in json_data["summary"]
    assert "serviceBot" not in json_data["summary"]
    assert "Davidson CarCare" in json_data["description"]
    assert "BayFull" not in json_data["description"]
    assert "serviceBot" not in json_data["description"]


@patch("serviceBot.services.google_calendar.load_config")
@patch("serviceBot.services.google_calendar.get_user_google_credentials")
@patch("serviceBot.services.google_calendar.fetch_agent_events")
@patch("httpx.delete")
def test_delete_agent_calendar_event_cancellation_compatibility(
    mock_delete, mock_fetch, mock_creds, mock_load
):
    """Verify delete_agent_calendar_event matches and cancels both legacy and newly branded events."""
    from serviceBot.services.google_calendar import delete_agent_calendar_event
    mock_load.return_value = {"business_name": "Davidson CarCare"}
    mock_creds.return_value = {
        "access_token": "dummy",
        "email": "agent@test.com",
        "granted_scopes": {"https://www.googleapis.com/auth/calendar.events"}
    }
    mock_fetch.return_value = [
        {"id": "ev_legacy_bayfull", "summary": "BayFull Appointment - John Doe"},
        {"id": "ev_legacy_servicebot", "summary": "serviceBot Booking - John Doe (Staff)"},
        {"id": "ev_branded_appt", "summary": "Davidson CarCare Appointment - John Doe"},
        {"id": "ev_branded_cb", "summary": "Davidson CarCare Callback - John Doe (AC Repair)"},
        {"id": "ev_unrelated_meeting", "summary": "Davidson CarCare planning meeting"},
        {"id": "ev_unrelated_appointment", "summary": "Dentist Appointment - Dr Smith"},
        {"id": "ev_unrelated_callback", "summary": "Phone Callback - Acme"},
        {"id": "ev_unrelated_booking", "summary": "Business Booking Review"},
    ]
    mock_resp = MagicMock()
    mock_resp.status_code = 204
    mock_delete.return_value = mock_resp

    res = delete_agent_calendar_event(agent_id=999, slot_datetime_str="2026-06-25 10:00:00")
    assert res is True
    assert mock_delete.call_count == 4
    deleted_urls = [call.args[0] for call in mock_delete.call_args_list]
    for unrelated_id in (
        "ev_unrelated_meeting",
        "ev_unrelated_appointment",
        "ev_unrelated_callback",
        "ev_unrelated_booking",
    ):
        assert all(unrelated_id not in url for url in deleted_urls)

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


@patch("serviceBot.services.google_calendar.get_user_google_credentials")
@patch("serviceBot.services.google_calendar.fetch_agent_events")
@patch("httpx.delete")
@patch("serviceBot.services.google_calendar.load_config")
def test_delete_agent_calendar_event_only_deletes_known_app_owned_titles(
    mock_load, mock_delete, mock_fetch, mock_credentials
):
    """Delete marked/legacy app events while preserving lookalike meetings."""
    mock_load.return_value = {"business_name": "Current Business"}
    mock_credentials.return_value = {
        "access_token": "dummy",
        "granted_scopes": {"https://www.googleapis.com/auth/calendar.events"},
    }
    mock_fetch.return_value = [
        {"id": "legacy_appointment", "summary": "BayFull Appointment - Customer"},
        {"id": "legacy_callback", "summary": "BayFull Callback - Customer"},
        {"id": "legacy_servicebot", "summary": "serviceBot Booking - Customer"},
        {
            "id": "renamed_business_event",
            "summary": "Former Business Appointment - Customer",
            "description": "Automatically booked by Former Business.",
        },
        {
            "id": "marked_event",
            "summary": "A new display title",
            "extendedProperties": {
                "private": {"serviceBotManagedEvent": "agent_booking"}
            },
        },
        {"id": "unrelated_appointment", "summary": "Dentist Appointment - Customer"},
        {"id": "unrelated_callback", "summary": "Phone Callback - Customer"},
        {"id": "unrelated_booking", "summary": "Business Booking Review"},
        {"id": "unrelated_brand", "summary": "BayFull quarterly planning meeting"},
        {
            "id": "unrelated_title_shape",
            "summary": "Project Appointment - Customer",
            "description": "Created by the calendar owner.",
        },
    ]
    mock_delete.return_value = MagicMock(status_code=204, text="")

    assert delete_agent_calendar_event(999, "2026-06-25 10:00:00") is True

    deleted_urls = [call.args[0] for call in mock_delete.call_args_list]
    assert len(deleted_urls) == 5
    for event_id in (
        "legacy_appointment",
        "legacy_callback",
        "legacy_servicebot",
        "renamed_business_event",
        "marked_event",
    ):
        assert any(event_id in url for url in deleted_urls)
    for event_id in (
        "unrelated_appointment",
        "unrelated_callback",
        "unrelated_booking",
        "unrelated_brand",
        "unrelated_title_shape",
    ):
        assert all(event_id not in url for url in deleted_urls)
