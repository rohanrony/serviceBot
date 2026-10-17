import pytest
from datetime import datetime, timedelta
from serviceBot.db.connection import get_db_connection, dict_cursor
from serviceBot.db.seed import seed_db
from serviceBot.db.queries import (
    set_service_agents,
    check_availability,
    book_appointment,
)
from serviceBot.services.booking import BookingService, BookingConflictError
from serviceBot.services import timezone_service


@pytest.fixture(autouse=True)
def clean_database():
    seed_db(force=True)
    yield


def _setup_two_services_and_agents():
    """Helper to set up two distinct services and agents."""
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            # Ensure at least 2 staff agents exist
            cursor.execute("SELECT id, name FROM staff_agents ORDER BY id ASC LIMIT 3;")
            agents = cursor.fetchall()
            a1_id, a2_id = agents[0]["id"], agents[1]["id"]

            # Service 1: Brake Service (60 min)
            cursor.execute(
                """
                INSERT INTO services (name, description, price_range, duration_minutes)
                VALUES ('Brake Service Test', 'Brake pads & rotors', '$200', 60)
                ON CONFLICT DO NOTHING RETURNING id;
                """
            )
            r1 = cursor.fetchone()
            if not r1:
                cursor.execute("SELECT id FROM services WHERE name = 'Brake Service Test';")
                r1 = cursor.fetchone()
            s1_id = r1["id"]

            # Service 2: Transmission Service (60 min)
            cursor.execute(
                """
                INSERT INTO services (name, description, price_range, duration_minutes)
                VALUES ('Transmission Flush Test', 'Fluid exchange', '$250', 60)
                ON CONFLICT DO NOTHING RETURNING id;
                """
            )
            r2 = cursor.fetchone()
            if not r2:
                cursor.execute("SELECT id FROM services WHERE name = 'Transmission Flush Test';")
                r2 = cursor.fetchone()
            s2_id = r2["id"]

            # Customer
            cursor.execute("SELECT id FROM customers LIMIT 1;")
            c_row = cursor.fetchone()
            customer_id = c_row["id"]

    return {
        "agent_1": a1_id,
        "agent_2": a2_id,
        "service_1_id": s1_id,
        "service_2_id": s2_id,
        "customer_id": customer_id,
    }


def test_single_agent_priority_at_preferred_slot():
    """If Agent 1 is qualified for both services and is free at the preferred slot, assign Agent 1 for full combined duration."""
    data = _setup_two_services_and_agents()
    a1 = data["agent_1"]
    s1_id, s2_id = data["service_1_id"], data["service_2_id"]

    # Tag Agent 1 to BOTH services
    set_service_agents(s1_id, [a1])
    set_service_agents(s2_id, [a1])

    # Next business day at 10:00 AM
    tz = timezone_service.get_business_zoneinfo()
    tomorrow = timezone_service.now_in_business_tz() + timedelta(days=2)
    # Ensure weekday
    while tomorrow.weekday() > 4:
        tomorrow += timedelta(days=1)
    target_dt_str = tomorrow.strftime("%Y-%m-%d 10:00:00")

    bs = BookingService()
    receipts = bs.reserve_multi_service_appointment(
        customer_id=data["customer_id"],
        services=["Brake Service Test", "Transmission Flush Test"],
        appointment_datetime=target_dt_str,
    )

    # Should allocate both services to Agent 1
    assert len(receipts) == 2
    assert receipts[0]["staff_agent_id"] == a1
    assert receipts[1]["staff_agent_id"] == a1
    # Check consecutive times: Service 1 @ 10:00 (60 min) -> Service 2 @ 11:00 (60 min)
    assert receipts[0]["booking_time"] == target_dt_str
    assert receipts[1]["booking_time"] == (tomorrow.replace(hour=11, minute=0, second=0)).strftime("%Y-%m-%d %H:%M:%S")

    # Verify visit_group_id is shared
    assert receipts[0]["visit_group_id"] is not None
    assert receipts[0]["visit_group_id"] == receipts[1]["visit_group_id"]
    assert receipts[0]["linked_appointment_id"] == receipts[1]["service_request_id"]


def test_back_to_back_split_when_no_single_agent():
    """When Agent 1 only does Service 1 and Agent 2 only does Service 2, allocate back-to-back with 0-minute buffer."""
    data = _setup_two_services_and_agents()
    a1, a2 = data["agent_1"], data["agent_2"]
    s1_id, s2_id = data["service_1_id"], data["service_2_id"]

    # Agent 1 ONLY does Service 1, Agent 2 ONLY does Service 2
    set_service_agents(s1_id, [a1])
    set_service_agents(s2_id, [a2])

    tomorrow = timezone_service.now_in_business_tz() + timedelta(days=2)
    while tomorrow.weekday() > 4:
        tomorrow += timedelta(days=1)
    target_dt_str = tomorrow.strftime("%Y-%m-%d 10:00:00")

    bs = BookingService()
    receipts = bs.reserve_multi_service_appointment(
        customer_id=data["customer_id"],
        services=["Brake Service Test", "Transmission Flush Test"],
        appointment_datetime=target_dt_str,
    )

    assert len(receipts) == 2
    assert receipts[0]["staff_agent_id"] == a1
    assert receipts[1]["staff_agent_id"] == a2

    # Verify 0-minute handoff buffer
    # Service 1: 10:00 - 11:00
    # Service 2: 11:00 - 12:00
    assert receipts[0]["booking_time"] == target_dt_str
    expected_s2_time = (tomorrow.replace(hour=11, minute=0, second=0)).strftime("%Y-%m-%d %H:%M:%S")
    assert receipts[1]["booking_time"] == expected_s2_time
    assert receipts[0]["visit_group_id"] == receipts[1]["visit_group_id"]


def test_atomic_reservation_rollback_on_conflict():
    """If Agent 1 is free but Agent 2 has a conflict at the consecutive slot, the entire reservation rolls back atomically."""
    data = _setup_two_services_and_agents()
    a1, a2 = data["agent_1"], data["agent_2"]
    s1_id, s2_id = data["service_1_id"], data["service_2_id"]

    set_service_agents(s1_id, [a1])
    set_service_agents(s2_id, [a2])

    tomorrow = timezone_service.now_in_business_tz() + timedelta(days=2)
    while tomorrow.weekday() > 4:
        tomorrow += timedelta(days=1)
    target_dt_str = tomorrow.strftime("%Y-%m-%d 10:00:00")
    s2_time_str = (tomorrow.replace(hour=11, minute=0, second=0)).strftime("%Y-%m-%d %H:%M:%S")

    # Block Agent 2 at 11:00 AM on mock_calendar_slots
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                """
                INSERT INTO mock_calendar_slots (staff_agent_id, slot_datetime, is_booked, reservation_status)
                VALUES (%s, %s, TRUE, 'RESERVED')
                ON CONFLICT (slot_datetime, staff_agent_id) DO UPDATE
                SET is_booked = TRUE, reservation_status = 'RESERVED';
                """,
                (a2, datetime.strptime(s2_time_str, "%Y-%m-%d %H:%M:%S")),
            )

    bs = BookingService()
    with pytest.raises(BookingConflictError):
        bs.reserve_multi_service_appointment(
            customer_id=data["customer_id"],
            services=["Brake Service Test", "Transmission Flush Test"],
            appointment_datetime=target_dt_str,
        )

    # Verify Agent 1 at 10:00 was NOT left reserved
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                "SELECT reservation_status, is_booked FROM mock_calendar_slots WHERE staff_agent_id = %s AND slot_datetime = %s;",
                (a1, datetime.strptime(target_dt_str, "%Y-%m-%d %H:%M:%S")),
            )
            row = cursor.fetchone()
            if row:
                assert row["is_booked"] is False or row["reservation_status"] not in ("RESERVED", "BLOCKED")


def test_dynamic_business_hours_closing_boundary_rejected():
    """Verify that multi-service appointments that would run past the configured business closing hour are rejected."""
    data = _setup_two_services_and_agents()
    tomorrow = timezone_service.now_in_business_tz() + timedelta(days=2)
    while tomorrow.weekday() > 4:
        tomorrow += timedelta(days=1)

    from serviceBot.services.calendar_sync import get_configured_business_hours
    closing_hour = max(get_configured_business_hours()) + 1  # e.g., 18 for 6:00 PM

    # Attempt to book a 2-hour multi-service appointment at 1 hour before closing
    # E.g. at 17:00 (5:00 PM) when closing is 18:00 (6:00 PM) -> ends at 19:00 -> EXCEEDS CLOSING
    invalid_start = tomorrow.replace(hour=closing_hour - 1, minute=0, second=0).strftime("%Y-%m-%d %H:%M:%S")

    bs = BookingService()
    with pytest.raises(ValueError) as excinfo:
        bs.reserve_multi_service_appointment(
            customer_id=data["customer_id"],
            services=["Brake Service Test", "Transmission Flush Test"],
            appointment_datetime=invalid_start,
        )
    assert "conclude" in str(excinfo.value).lower() or "business hours" in str(excinfo.value).lower()


def test_dual_callbacks_non_overlapping():
    """Verify dual callbacks are scheduled in distinct non-overlapping windows."""
    data = _setup_two_services_and_agents()
    a1, a2 = data["agent_1"], data["agent_2"]
    s1_id, s2_id = data["service_1_id"], data["service_2_id"]

    set_service_agents(s1_id, [a1])
    set_service_agents(s2_id, [a2])

    tomorrow = timezone_service.now_in_business_tz() + timedelta(days=2)
    while tomorrow.weekday() > 4:
        tomorrow += timedelta(days=1)
    target_dt_str = tomorrow.strftime("%Y-%m-%d 10:00:00")

    bs = BookingService()
    receipts = bs.reserve_multi_service_appointment(
        customer_id=data["customer_id"],
        services=["Brake Service Test", "Transmission Flush Test"],
        appointment_datetime=target_dt_str,
        booking_type="callback",
    )

    assert len(receipts) == 2
    # Ensure they do NOT have the exact same start time (minimum 30 min window separation per spec US4)
    assert receipts[0]["booking_time"] != receipts[1]["booking_time"]
    t0 = datetime.strptime(receipts[0]["booking_time"], "%Y-%m-%d %H:%M:%S")
    t1 = datetime.strptime(receipts[1]["booking_time"], "%Y-%m-%d %H:%M:%S")
    assert abs((t1 - t0).total_seconds()) >= 30 * 60


def test_telephony_book_appointment_multi_service():
    """Verify telephony voice tool executes multi-service back-to-back reservation correctly."""
    import asyncio
    from serviceBot.api.telephony import voice_tools
    data = _setup_two_services_and_agents()
    a1, a2 = data["agent_1"], data["agent_2"]
    set_service_agents(data["service_1_id"], [a1])
    set_service_agents(data["service_2_id"], [a2])

    tomorrow = timezone_service.now_in_business_tz() + timedelta(days=2)
    while tomorrow.weekday() > 4:
        tomorrow += timedelta(days=1)
    target_dt_str = tomorrow.strftime("%Y-%m-%d 10:00:00")

    payload = {
        "name": "book_appointment",
        "tool_call_id": "test_multi_call_1",
        "arguments": {
            "phone": "5551234567",
            "name": "Jane Doe",
            "appointment_datetime": target_dt_str,
            "service_type": "Brake Service Test, Transmission Flush Test",
            "make": "Toyota",
            "model": "Camry",
            "year": 2022
        }
    }
    tool_res = asyncio.run(voice_tools(payload))

    res_data = tool_res["result"]
    assert res_data["success"] is True
    assert res_data["visit_group_id"] is not None
    assert len(res_data["appointments"]) == 2
    assert "back-to-back" in res_data["message"].lower() or "confirmed" in res_data["message"].lower()

