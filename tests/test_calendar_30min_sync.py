import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, date
from serviceBot.services.calendar_sync import (
    _generate_slot_strings,
    _check_busy_via_calendar,
    sync_agent_slots,
    get_configured_business_hours,
)
from serviceBot.db.queries import _generate_dynamic_slots
from serviceBot.db.seed import seed_db
from serviceBot.db.connection import get_db_connection, dict_cursor

def test_generate_slot_strings_has_30min_intervals():
    """Verify that _generate_slot_strings generates slots on minute marks."""
    slots = _generate_slot_strings(days=7)
    assert len(slots) > 0
    
    minute_marks = set()
    for slot in slots:
        dt = datetime.strptime(slot, "%Y-%m-%d %H:%M:%S")
        assert dt.minute in (0, 15, 30, 45)
        minute_marks.add(dt.minute)
    
    # Assert both 0 and 30 minute slots are generated
    assert 0 in minute_marks
    assert 30 in minute_marks

def test_generate_dynamic_slots_has_30min_intervals():
    """Verify that _generate_dynamic_slots includes 30-minute slots."""
    today_str = date.today().strftime("%Y-%m-%d")
    slots = _generate_dynamic_slots(today_str, duration_minutes=30)
    assert len(slots) > 0
    
    minute_marks = set()
    for slot in slots:
        dt = datetime.strptime(slot, "%Y-%m-%d %H:%M:%S")
        assert dt.minute in (0, 30)
        minute_marks.add(dt.minute)
        
    assert 0 in minute_marks
    assert 30 in minute_marks

@patch("serviceBot.services.google_calendar.fetch_agent_events")
def test_check_busy_via_calendar_30min_event(mock_fetch):
    """Verify check_busy_via_calendar correctly flags 30-minute slots overlapping with Google Calendar events."""
    mock_fetch.return_value = [
        {
            "id": "e1",
            "status": "confirmed",
            "start": {"dateTime": "2026-06-25T11:30:00-04:00"},
            "end": {"dateTime": "2026-06-25T12:00:00-04:00"}
        }
    ]
    
    test_slots = [
        "2026-06-25 11:00:00",
        "2026-06-25 11:30:00",
        "2026-06-25 12:00:00",
    ]
    
    busy_map = _check_busy_via_calendar(100, test_slots, duration_minutes=30)
    
    # 11:00 slot (11:00 to 11:30) does NOT overlap 11:30-12:00
    assert busy_map.get("2026-06-25 11:00:00") is None or busy_map.get("2026-06-25 11:00:00") is False
    # 11:30 slot (11:30 to 12:00) overlaps e1
    assert busy_map.get("2026-06-25 11:30:00") is True
    # 12:00 slot (12:00 to 12:30) does NOT overlap 11:30-12:00
    assert busy_map.get("2026-06-25 12:00:00") is None or busy_map.get("2026-06-25 12:00:00") is False

def test_seed_database_creates_30min_slots():
    """Verify seed_db creates mock_calendar_slots with 30-minute resolution."""
    seed_db()
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("SELECT slot_datetime FROM mock_calendar_slots;")
            rows = cursor.fetchall()
            assert len(rows) > 0
            minutes = set()
            for r in rows:
                val = r["slot_datetime"]
                dt_val = datetime.strptime(val, "%Y-%m-%d %H:%M:%S") if isinstance(val, str) else val
                minutes.add(dt_val.minute)
            assert 0 in minutes
            assert 30 in minutes

if __name__ == "__main__":
    print("Running test_generate_slot_strings_has_30min_intervals...")
    test_generate_slot_strings_has_30min_intervals()
    print("Running test_generate_dynamic_slots_has_30min_intervals...")
    test_generate_dynamic_slots_has_30min_intervals()
    print("Running test_check_busy_via_calendar_30min_event...")
    test_check_busy_via_calendar_30min_event()
    print("Running test_seed_database_creates_30min_slots...")
    test_seed_database_creates_30min_slots()
    print("ALL 30-MINUTE CALENDAR SYNC TESTS PASSED SUCCESSFULLY!")

