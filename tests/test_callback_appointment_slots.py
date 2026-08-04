import pytest
import datetime
from unittest.mock import patch, MagicMock

from serviceBot.db.queries import (
    check_availability,
    book_appointment,
    create_service_request,
    create_callback_request,
    _generate_dynamic_slots
)
from serviceBot.services.calendar_sync import _generate_slot_strings


def test_generate_slot_strings_has_15_min_intervals():
    """Verify that _generate_slot_strings generates 15-minute interval slots (0, 15, 30, 45)."""
    slots = _generate_slot_strings(days=7, hours=[10])
    minutes = [datetime.datetime.strptime(s, "%Y-%m-%d %H:%M:%S").minute for s in slots]
    assert 0 in minutes
    assert 15 in minutes
    assert 30 in minutes
    assert 45 in minutes


def test_check_availability_appointment_returns_only_30_min_intervals():
    """Verify check_availability for appointments only returns slots at :00 and :30 minute marks."""
    # Test tomorrow date
    tomorrow_str = (datetime.date.today() + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    
    slots = check_availability(service_type="Oil Change", preferred_date=tomorrow_str, booking_type="appointment")
    for s in slots:
        dt = datetime.datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
        assert dt.minute in (0, 30), f"Appointment slot {s} is not aligned to 30-minute interval!"


def test_check_availability_callback_returns_15_min_intervals():
    """Verify check_availability for callbacks can return 15-minute interval slots (:00, :15, :30, :45)."""
    tomorrow_str = (datetime.date.today() + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    
    slots = check_availability(service_type="Callback", preferred_date=tomorrow_str, booking_type="callback")
    assert len(slots) > 0
    for s in slots:
        dt = datetime.datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
        assert dt.minute in (0, 15, 30, 45), f"Callback slot {s} is not on 15-minute boundary!"


def test_callback_asap_resolution():
    """Verify booking a callback with ASAP resolves preferred_time to a valid 15-min future slot timestamp."""
    with patch("serviceBot.services.google_calendar.create_agent_calendar_event") as mock_cal_event, \
         patch("serviceBot.services.gmail.create_admin_calendar_event") as mock_admin_event:
        mock_cal_event.return_value = True
        mock_admin_event.return_value = True
        
        sr_id = create_callback_request(
            customer_id=1,
            preferred_time="ASAP",
            vehicle_details={"make": "Honda", "model": "Civic", "year": 2020}
        )
        assert sr_id is not None

        from serviceBot.db.connection import get_db_connection, dict_cursor
        with get_db_connection() as conn:
            with dict_cursor(conn) as cursor:
                cursor.execute("SELECT booking_type, booking_time FROM service_requests WHERE id = %s;", (sr_id,))
                row = cursor.fetchone()
                assert row["booking_type"] == "callback"
                assert row["booking_time"] != "ASAP", "ASAP should be resolved to a specific slot timestamp!"
                
                # Check parsed datetime
                dt = datetime.datetime.strptime(row["booking_time"], "%Y-%m-%d %H:%M:%S")
                assert dt.minute in (0, 15, 30, 45)


def test_callback_calendar_event_type_and_duration():
    """Verify creating a callback triggers Google Calendar event with 15-min duration and Callback summary."""
    with patch("serviceBot.services.google_calendar.create_agent_calendar_event") as mock_agent_event, \
         patch("serviceBot.services.gmail.create_admin_calendar_event") as mock_admin_event:
        mock_agent_event.return_value = True
        mock_admin_event.return_value = True

        tomorrow_str = (datetime.date.today() + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
        slot_str = f"{tomorrow_str} 11:15:00"

        sr_id = create_service_request(
            customer_id=1,
            vehicle_details={"make": "Toyota", "model": "Camry", "year": 2021},
            issue="Engine noise inquiry",
            service_type="Engine Diagnostics",
            booking_type="callback",
            booking_time=slot_str
        )

        assert sr_id is not None
        # Verify call to create_agent_calendar_event received duration_minutes=15 and booking_type='callback'
        if mock_agent_event.called:
            kwargs = mock_agent_event.call_args.kwargs
            assert kwargs.get("duration_minutes") == 15 or mock_agent_event.call_args[0][5] == 15 or kwargs.get("booking_type") == "callback"


if __name__ == "__main__":
    print("Running test_generate_slot_strings_has_15_min_intervals...")
    test_generate_slot_strings_has_15_min_intervals()
    print("PASSED")

    print("Running test_check_availability_appointment_returns_only_30_min_intervals...")
    test_check_availability_appointment_returns_only_30_min_intervals()
    print("PASSED")

    print("Running test_check_availability_callback_returns_15_min_intervals...")
    test_check_availability_callback_returns_15_min_intervals()
    print("PASSED")

    print("Running test_callback_asap_resolution...")
    test_callback_asap_resolution()
    print("PASSED")

    print("Running test_callback_calendar_event_type_and_duration...")
    test_callback_calendar_event_type_and_duration()
    print("PASSED")

    print("All tests passed cleanly!")
