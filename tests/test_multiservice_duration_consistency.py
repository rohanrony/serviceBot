import pytest
from serviceBot.db.queries import (
    get_service_required_fields,
    create_service_request,
    book_appointment,
    get_customer_appointments
)
from serviceBot.services.sms_router import SMSNotificationRouter, format_time_slot_range
from serviceBot.api.telephony import get_booking_details
from serviceBot.db.connection import get_db_connection, dict_cursor
from serviceBot.db.seed import seed_db


def test_get_service_required_fields_multi_service_sum():
    """Verify get_service_required_fields accurately calculates total multi-service duration."""
    seed_db()
    # Test case 1: Service Repair Estimates (30m) + Standard System Inspection (45m) = 75m
    res1 = get_service_required_fields("Service Repair Estimates, Standard System Inspection")
    assert res1 is not None
    assert res1["duration_minutes"] == 75

    # Test case 2: Standard System Inspection (45m) + Precision System Alignment & Calibration (60m) = 105m
    res2 = get_service_required_fields("Standard System Inspection, Precision System Alignment & Calibration")
    assert res2 is not None
    assert res2["duration_minutes"] == 105

    # Test case 3: Courtesy Inspection (20m) + Standard System Inspection (45m) = 65m
    res3 = get_service_required_fields("Courtesy Inspection, Standard System Inspection")
    assert res3 is not None
    assert res3["duration_minutes"] == 65


def test_format_time_slot_range_with_custom_duration():
    """Verify format_time_slot_range computes correct end time based on duration_minutes."""
    time_str = "2026-08-06 09:00:00"
    formatted_75m = format_time_slot_range(time_str, duration_minutes=75)
    assert "9:00 AM - 10:15 AM" in formatted_75m

    formatted_120m = format_time_slot_range(time_str, duration_minutes=120)
    assert "9:00 AM - 11:00 AM" in formatted_120m


def test_book_appointment_persists_duration_in_db():
    """Verify book_appointment stores total duration_minutes in service_requests table."""
    seed_db()
    multi_service = "Service Repair Estimates, Standard System Inspection"
    time_slot = "2026-08-06 09:00:00"

    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            # Get or create customer
            cursor.execute("SELECT id FROM customers LIMIT 1;")
            c_row = cursor.fetchone()
            cust_id = c_row["id"] if c_row else 1

            # Insert service request via create_service_request
            sr_id = create_service_request(
                customer_id=cust_id,
                vehicle_details={"make": "TestMake", "model": "TestModel", "year": 2022},
                service_type=multi_service,
                issue="Multi-service testing",
                booking_type="appointment",
                booking_time=time_slot
            )

            # Query database directly for duration_minutes
            cursor.execute("SELECT duration_minutes, service_type FROM service_requests WHERE id = %s;", (sr_id,))
            row = cursor.fetchone()
            assert row is not None
            assert row["duration_minutes"] == 75


def test_telephony_get_booking_details_includes_duration():
    """Verify get_booking_details returns accurate duration_minutes."""
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("SELECT id, customer_id FROM service_requests WHERE booking_type = 'appointment' ORDER BY id DESC LIMIT 1;")
            row = cursor.fetchone()
            if row:
                details = get_booking_details(row["customer_id"], row["id"])
                assert "duration_minutes" in details
                assert isinstance(details["duration_minutes"], int)
