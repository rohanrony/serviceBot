import datetime as dt_mod
from unittest.mock import patch, MagicMock
import pytest

from serviceBot.db.connection import get_db_connection, dict_cursor
from serviceBot.db.queries import (
    _generate_dynamic_slots,
    check_availability,
    set_service_agents,
    get_qualified_agent_ids,
    parse_preferred_date_and_time,
    parse_specific_time,
)
from serviceBot.services.booking import BookingService


def test_dynamic_slots_business_timezone_lead_time():
    """
    Verify that _generate_dynamic_slots uses the configured business timezone
    rather than system UTC. At 10:26 AM local time with 4h lead time,
    4:00 PM (16:00) today must be considered valid.
    """
    mock_local_now = dt_mod.datetime(2026, 10, 15, 10, 26, 0)
    with patch("serviceBot.services.timezone_service.now_in_business_tz", return_value=mock_local_now):
        slots = _generate_dynamic_slots(
            preferred_date_str="today",
            duration_minutes=30,
            interval_minutes=30,
            booking_type="appointment",
        )
        assert len(slots) > 0, "Expected dynamic slots to be generated for today"
        # 10:26 AM + 4.0 lead hours = 14:26 (2:26 PM). Slots >= 14:30 should exist.
        today_slots = [s for s in slots if s.startswith("2026-10-15")]
        assert any("16:00:00" in s for s in today_slots), (
            f"Expected 16:00:00 today slot to be available when now is 10:26 AM local. Got: {today_slots}"
        )


def test_telephony_time_match_requires_date_and_time():
    """
    Verify date-safe time matching:
    If candidate slots only contain tomorrow at 4:00 PM, a query for today at 4:00 PM
    must NOT evaluate time_match=True.
    """
    preferred_date = "today"
    preferred_time = "4:00 PM"
    tomorrow_iso = (dt_mod.date.today() + dt_mod.timedelta(days=1)).isoformat()
    slots = [f"{tomorrow_iso} 16:00:00"]  # Only tomorrow at 4 PM is available

    iso_date_target, _, _ = parse_preferred_date_and_time(preferred_date)
    requested_time_target = parse_specific_time(f"{preferred_date or ''} {preferred_time or ''}")

    time_match = False
    if requested_time_target and slots:
        time_match = any(
            (not iso_date_target or s.startswith(iso_date_target))
            and dt_mod.datetime.strptime(s, "%Y-%m-%d %H:%M:%S").time().hour == requested_time_target.hour
            and dt_mod.datetime.strptime(s, "%Y-%m-%d %H:%M:%S").time().minute == requested_time_target.minute
            for s in slots
        )

    assert not time_match, "Should not match 4:00 PM tomorrow when today 4:00 PM was requested"

    # Now verify with today's 4:00 PM in slots
    today_iso = dt_mod.date.today().isoformat()
    slots_with_today = [f"{today_iso} 16:00:00"]
    time_match_today = any(
        (not iso_date_target or s.startswith(iso_date_target))
        and dt_mod.datetime.strptime(s, "%Y-%m-%d %H:%M:%S").time().hour == requested_time_target.hour
        and dt_mod.datetime.strptime(s, "%Y-%m-%d %H:%M:%S").time().minute == requested_time_target.minute
        for s in slots_with_today
    )
    assert time_match_today, "Should match 4:00 PM today when today 4:00 PM is available"


def test_booking_service_candidate_agent_ids_qualified_filtering():
    """
    Verify that BookingService._candidate_agent_ids restricts candidate staff agents
    to only those tagged to the service.
    """
    booking_service = BookingService()

    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = [{"id": 1}, {"id": 2}, {"id": 7}, {"id": 8}]

    # When qualified_agent_ids is [7], candidate_ids must only contain [7]
    candidates = booking_service._candidate_agent_ids(
        mock_cursor,
        requested_agent_id=None,
        fallback_agent_id=None,
        qualified_agent_ids=[7],
    )
    assert candidates == [7], f"Expected only qualified agent [7], got {candidates}"

    # When no qualified agents are restricted, returns all agents
    all_candidates = booking_service._candidate_agent_ids(
        mock_cursor,
        requested_agent_id=None,
        fallback_agent_id=None,
        qualified_agent_ids=None,
    )
    assert all_candidates == [1, 2, 7, 8]


def test_check_availability_evaluates_only_qualified_agents():
    """
    Verify that check_availability only fetches calendar events and tests availability
    for agents qualified for the requested service.
    """
    fake_slots = ["2026-10-16 09:00:00", "2026-10-16 10:00:00"]
    fetched_agent_ids = []

    def fake_fetch_events(aid, start_iso, end_iso):
        fetched_agent_ids.append(aid)
        return []

    mock_db = MagicMock()
    mock_cursor = MagicMock()
    # Mock staff agents in DB as [1, 2, 7, 8]
    mock_cursor.fetchall.side_effect = [
        [{"id": 1}, {"id": 2}, {"id": 7}, {"id": 8}],  # SELECT id FROM staff_agents
        [],  # mock_calendar_slots query
        [],  # appointment_reservation_segments query
    ]
    mock_db.__enter__.return_value = mock_db
    mock_cursor.__enter__.return_value = mock_cursor

    with patch("serviceBot.db.queries.get_service_required_fields", return_value={"duration_minutes": 60}), \
         patch("serviceBot.db.queries.get_db_connection", return_value=mock_db), \
         patch("serviceBot.db.queries.dict_cursor", return_value=mock_cursor), \
         patch("serviceBot.db.queries.get_qualified_agent_ids", return_value=[7]), \
         patch("serviceBot.db.queries._generate_dynamic_slots", return_value=fake_slots), \
         patch("serviceBot.services.google_calendar.fetch_agent_events", side_effect=fake_fetch_events):

        slots = check_availability(service_type="Manufacturer Scheduled Maintenance", preferred_date="2026-10-16")
        assert len(slots) > 0
        # Only agent 7 should have been evaluated and fetched, NOT agents 1, 2, or 8!
        assert set(fetched_agent_ids) == {7}, f"Expected only agent 7 to be evaluated, but got: {fetched_agent_ids}"

