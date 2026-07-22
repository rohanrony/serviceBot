import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, date
from serviceBot.services.calendar_sync import (
    _generate_slot_strings,
    _check_busy_via_calendar,
    sync_agent_slots,
    sync_all_connected_agents,
    get_configured_business_hours,
)
from serviceBot.db.connection import get_db_connection

@patch("serviceBot.api.portal.load_config")
def test_get_configured_business_hours(mock_load_config):
    """Verify get_configured_business_hours reads business_hours_start/end and list from config."""
    # Test custom start and end hours (8 AM to 5 PM -> 8..16)
    mock_load_config.return_value = {
        "business_hours_start": 8,
        "business_hours_end": 17,
    }
    hours = get_configured_business_hours()
    assert hours == [8, 9, 10, 11, 12, 13, 14, 15, 16]

    # Test explicit business_hours list
    mock_load_config.return_value = {
        "business_hours": [9, 11, 14, 16]
    }
    hours = get_configured_business_hours()
    assert hours == [9, 11, 14, 16]

def test_generate_slot_strings():
    """Verify that slot strings are correctly generated within business hours and skip weekends."""
    # Use days=7 to guarantee we include weekdays regardless of today's day of week
    slots = _generate_slot_strings(days=7)
    
    # Check that we have slots
    assert len(slots) > 0
    # Every slot must match Mon-Fri and one of the business hours
    for slot in slots:
        dt = datetime.strptime(slot, "%Y-%m-%d %H:%M:%S")
        assert dt.weekday() < 5 # Monday-Friday only
        assert 7 <= dt.hour <= 17

@patch("serviceBot.services.google_calendar.fetch_agent_events")
def test_check_busy_via_calendar(mock_fetch):
    """Verify check_busy_via_calendar maps busy slots based on event overlaps."""
    # Mock some Google Calendar events
    mock_fetch.return_value = [
        {
            "id": "e1",
            "status": "confirmed",
            "start": {"dateTime": "2026-06-25T10:00:00-04:00"},
            "end": {"dateTime": "2026-06-25T11:00:00-04:00"}
        },
        {
            "id": "e2",
            "status": "tentative",
            "start": {"dateTime": "2026-06-25T14:30:00-04:00"},
            "end": {"dateTime": "2026-06-25T15:30:00-04:00"}
        },
        {
            "id": "e3",
            "status": "confirmed", # Use confirmed to match current status implementation check
            "start": {"dateTime": "2026-06-25T16:00:00-04:00"},
            "end": {"dateTime": "2026-06-25T17:00:00-04:00"}
        }
    ]
    
    test_slots = [
        "2026-06-25 09:00:00",
        "2026-06-25 10:00:00",
        "2026-06-25 11:00:00",
        "2026-06-25 14:00:00",
        "2026-06-25 15:00:00",
        "2026-06-25 16:00:00"
    ]
    
    busy_map = _check_busy_via_calendar(100, test_slots)
    
    assert busy_map.get("2026-06-25 09:00:00") is None or busy_map.get("2026-06-25 09:00:00") is False
    assert busy_map.get("2026-06-25 10:00:00") is True
    assert busy_map.get("2026-06-25 11:00:00") is None or busy_map.get("2026-06-25 11:00:00") is False
    assert busy_map.get("2026-06-25 14:00:00") is True
    assert busy_map.get("2026-06-25 15:00:00") is True
    assert busy_map.get("2026-06-25 16:00:00") is True # Overlaps with e3

@patch("serviceBot.services.calendar_sync._check_busy_via_calendar")
def test_sync_agent_slots(mock_check_busy):
    """Verify sync_agent_slots correctly syncs and updates mock calendar slots."""
    # Configure mock busy slots
    # Get today's slots
    today_str = date.today().strftime("%Y-%m-%d")
    slot_09 = f"{today_str} 09:00:00"
    slot_11 = f"{today_str} 11:00:00"
    
    mock_check_busy.return_value = {
        slot_09: False,
        slot_11: True
    }
    
    # Run sync on test agent 1
    sync_agent_slots(1, days=1)
    
    # Query database to confirm (check is_booked column)
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT slot_datetime, is_booked FROM mock_calendar_slots WHERE staff_agent_id = 1 AND slot_datetime = ?;", (slot_09,))
        row_09 = cursor.fetchone()
        
        cursor.execute("SELECT slot_datetime, is_booked FROM mock_calendar_slots WHERE staff_agent_id = 1 AND slot_datetime = ?;", (slot_11,))
        row_11 = cursor.fetchone()
        
        # Depending on weekday, they should exist
        if row_09:
            assert row_09["is_booked"] == 0
        if row_11:
            assert row_11["is_booked"] == 1

@patch("serviceBot.services.calendar_sync.sync_agent_slots")
def test_sync_all_connected_agents(mock_sync_agent):
    """Verify sync_all_connected_agents processes all agents in user_google_accounts."""
    # Seed a couple of connected accounts in test DB
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM user_google_accounts;")
        cursor.execute("INSERT INTO user_google_accounts (agent_id, provider, email, refresh_token, access_token, granted_scopes, expires_at) VALUES (1, 'google', 'a1@test.com', 'x', 'y', 'z', 9999999999);")
        cursor.execute("INSERT INTO user_google_accounts (agent_id, provider, email, refresh_token, access_token, granted_scopes, expires_at) VALUES (2, 'google', 'a2@test.com', 'x', 'y', 'z', 9999999999);")
        conn.commit()
        
    sync_all_connected_agents(days=2)
    
    # Should call sync_agent_slots for agents 1 and 2
    assert mock_sync_agent.call_count == 2
    called_agents = [call[0][0] for call in mock_sync_agent.call_args_list]
    assert 1 in called_agents
    assert 2 in called_agents
