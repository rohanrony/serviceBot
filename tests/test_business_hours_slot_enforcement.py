import pytest
import datetime as dt
from unittest.mock import patch, MagicMock

from serviceBot.db.queries import (
    _generate_dynamic_slots,
    check_availability,
    get_available_slots_for_date,
    parse_specific_time,
)
from serviceBot.services.calendar_sync import get_configured_business_hours
from serviceBot.api.telephony import voice_tools


def test_dynamic_slots_90_minute_excludes_slots_extending_past_closing():
    """Verify that a 90-minute (1.5 hr) appointment never generates 17:00 or 17:30 slots

    when business hours end at 18:00 (6:00 PM). Latest start must be 16:30 (4:30 PM).
    """
    fake_config = {
        "business_hours_start": 7,
        "business_hours_end": 18,
        "business_hours": list(range(7, 18)),
        "business_days": [0, 1, 2, 3, 4],
    }

    with patch("serviceBot.api.portal.load_config", return_value=fake_config):
        slots = _generate_dynamic_slots("tomorrow", duration_minutes=90)
        assert len(slots) > 0

        for slot_str in slots:
            slot_dt = dt.datetime.strptime(slot_str, "%Y-%m-%d %H:%M:%S")
            end_dt = slot_dt + dt.timedelta(minutes=90)
            # Closing time on that day is 18:00:00
            closing_dt = slot_dt.replace(hour=18, minute=0, second=0)
            assert end_dt <= closing_dt, f"Slot {slot_str} + 90m ends at {end_dt}, which exceeds closing time {closing_dt}"
            # 17:00 and 17:30 must never appear
            assert not (slot_dt.hour == 17 and slot_dt.minute in (0, 30)), f"Slot {slot_str} was generated but extends past 18:00"

        # Verify that 16:30:00 IS generated as the latest viable slot
        assert any(s.endswith("16:30:00") for s in slots), "Expected 16:30:00 to be generated as latest valid 90-min slot"


def test_dynamic_slots_60_minute_excludes_1730():
    """Verify that for 60-minute appointments, 17:00 is allowed (ends at 18:00)

    but 17:30 is excluded (ends at 18:30).
    """
    fake_config = {
        "business_hours_start": 7,
        "business_hours_end": 18,
        "business_hours": list(range(7, 18)),
        "business_days": [0, 1, 2, 3, 4],
    }

    with patch("serviceBot.api.portal.load_config", return_value=fake_config):
        slots = _generate_dynamic_slots("tomorrow", duration_minutes=60)
        assert len(slots) > 0

        for slot_str in slots:
            slot_dt = dt.datetime.strptime(slot_str, "%Y-%m-%d %H:%M:%S")
            end_dt = slot_dt + dt.timedelta(minutes=60)
            closing_dt = slot_dt.replace(hour=18, minute=0, second=0)
            assert end_dt <= closing_dt, f"Slot {slot_str} + 60m ends at {end_dt}, exceeding {closing_dt}"
            assert not (slot_dt.hour == 17 and slot_dt.minute == 30), f"17:30 should not be generated for 60m appointment"

        # 17:00:00 is valid for 60m because it finishes at 18:00:00
        assert any(s.endswith("17:00:00") for s in slots), "Expected 17:00:00 to be generated for 60m appointment"


def test_dynamic_slots_120_minute_excludes_after_1600():
    """Verify that for 120-minute (2-hour) appointments, latest slot is 16:00 (ends at 18:00).

    16:30, 17:00, 17:30 must be excluded.
    """
    fake_config = {
        "business_hours_start": 7,
        "business_hours_end": 18,
        "business_hours": list(range(7, 18)),
        "business_days": [0, 1, 2, 3, 4],
    }

    with patch("serviceBot.api.portal.load_config", return_value=fake_config):
        slots = _generate_dynamic_slots("tomorrow", duration_minutes=120)
        assert len(slots) > 0

        for slot_str in slots:
            slot_dt = dt.datetime.strptime(slot_str, "%Y-%m-%d %H:%M:%S")
            end_dt = slot_dt + dt.timedelta(minutes=120)
            closing_dt = slot_dt.replace(hour=18, minute=0, second=0)
            assert end_dt <= closing_dt, f"Slot {slot_str} + 120m ends at {end_dt}, exceeding {closing_dt}"

        assert any(s.endswith("16:00:00") for s in slots), "Expected 16:00:00 for 120m appointment"
        assert not any(s.endswith("16:30:00") for s in slots), "16:30:00 exceeds closing for 120m appointment"
        assert not any(s.endswith("17:00:00") for s in slots), "17:00:00 exceeds closing for 120m appointment"


def test_check_availability_with_target_time_never_returns_overrunning_slots():
    """Verify check_availability when requested at 5 PM for 90m service does NOT return 17:00."""
    fake_config = {
        "business_hours_start": 7,
        "business_hours_end": 18,
        "business_hours": list(range(7, 18)),
        "business_days": [0, 1, 2, 3, 4],
    }

    mock_db_agents = [{"id": 1, "name": "Tech 1"}]

    with patch("serviceBot.api.portal.load_config", return_value=fake_config), \
         patch("serviceBot.db.queries.get_db_connection") as mock_conn, \
         patch("serviceBot.db.queries.dict_cursor") as mock_cur_factory, \
         patch("serviceBot.db.queries.get_service_required_fields", return_value={"duration_minutes": 90}), \
         patch("serviceBot.services.google_calendar.fetch_agent_events", return_value=[]):

        mock_cur = MagicMock()
        mock_cur.fetchall.return_value = mock_db_agents
        mock_cur_factory.return_value.__enter__.return_value = mock_cur

        slots = check_availability(service_type="Routine Maintenance, Inspection", preferred_date="tomorrow at 5 PM")
        assert len(slots) > 0, "Expected available slots"

        for s in slots:
            s_dt = dt.datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
            s_end = s_dt + dt.timedelta(minutes=90)
            closing = s_dt.replace(hour=18, minute=0, second=0)
            assert s_end <= closing, f"Returned slot {s} with 90m duration ends at {s_end}, exceeding closing time {closing}"
            assert not s.endswith("17:00:00"), f"17:00:00 was returned for a 90-minute service!"


def test_system_prompt_closing_boundary_rules_present():
    """Verify serviceBot/system_prompt.txt and config.json explicitly instruct the agent

    regarding the 6:00 PM closing boundary and duration calculations.
    """
    import os
    base_dir = os.path.dirname(os.path.dirname(__file__))
    prompt_path = os.path.join(base_dir, "serviceBot", "system_prompt.txt")

    with open(prompt_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Check for closing boundary and latest start rules
    assert "6:00 PM" in content
    assert "conclude" in content.lower() or "end" in content.lower()
    assert "latest" in content.lower()
    assert "4:30" in content  # Example of 90-min service latest start time
