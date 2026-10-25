import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
from serviceBot.db.connection import get_db_connection, dict_cursor
from serviceBot.db.seed import seed_db
from serviceBot.db.queries import (
    set_service_agents,
    check_availability,
    book_appointment,
)
from serviceBot.services.booking import BookingService, BookingConflictError
from serviceBot.services import timezone_service
from serviceBot.services.google_calendar import create_multi_service_calendar_events


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

    # The approved grouping contract has one appointment for this technician.
    assert len(receipts) == 1
    assert receipts[0]["staff_agent_id"] == a1
    assert receipts[0]["booking_time"] == target_dt_str
    assert receipts[0]["duration_minutes"] == 120
    assert receipts[0]["service_components"] == [
        {"name": "Brake Service Test", "duration_minutes": 60},
        {"name": "Transmission Flush Test", "duration_minutes": 60},
    ]
    assert receipts[0]["visit_group_id"] is not None
    with get_db_connection() as conn, dict_cursor(conn) as cursor:
        cursor.execute("SELECT r.ends_at-r.starts_at AS span, (SELECT count(*) FROM appointment_reservation_segments s WHERE s.reservation_id=r.id) AS segments FROM appointment_reservations r WHERE r.service_request_id=%s AND r.status='ACTIVE'", (receipts[0]["service_request_id"],))
        reservations = cursor.fetchall()
        assert len(reservations) == 1
        assert reservations[0]["span"] == timedelta(minutes=120)
        assert reservations[0]["segments"] == 8
        cursor.execute("SELECT count(*) AS count FROM outbox_notifications WHERE request_id=%s AND event_type='calendar_projection'", (receipts[0]["service_request_id"],))
        assert cursor.fetchone()["count"] == 1


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


def test_greedy_partitioning_three_plus_services():
    """T024: Verify greedy partitioning for 3+ services maximizes contiguous blocks with first technician."""
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("SELECT id FROM staff_agents ORDER BY id ASC LIMIT 3;")
            agents = [r["id"] for r in cursor.fetchall()]
            assert len(agents) >= 3, "Need at least 3 staff agents for 3+ services test"
            a1, a2, a3 = agents[0], agents[1], agents[2]

            # Create 3 test services
            for name in ["Greedy Svc 1", "Greedy Svc 2", "Greedy Svc 3"]:
                cursor.execute(
                    "INSERT INTO services (name, description, duration_minutes) VALUES (%s, %s, %s) "
                    "ON CONFLICT DO NOTHING;",
                    (name, "Greedy test", 30)
                )

            cursor.execute("SELECT id, name FROM services WHERE name IN ('Greedy Svc 1', 'Greedy Svc 2', 'Greedy Svc 3');")
            s_map = {r["name"]: r["id"] for r in cursor.fetchall()}
            cursor.execute("SELECT id FROM customers LIMIT 1;")
            c_id = cursor.fetchone()["id"]

    # Tagging: a1 can do S1 and S2; a2 can do S3; a3 can do S3
    set_service_agents(s_map["Greedy Svc 1"], [a1])
    set_service_agents(s_map["Greedy Svc 2"], [a1])
    set_service_agents(s_map["Greedy Svc 3"], [a2, a3])

    tomorrow = timezone_service.now_in_business_tz() + timedelta(days=2)
    while tomorrow.weekday() > 4:
        tomorrow += timedelta(days=1)
    target_dt_str = tomorrow.strftime("%Y-%m-%d 10:00:00")

    bs = BookingService()
    receipts = bs.reserve_multi_service_appointment(
        customer_id=c_id,
        services=["Greedy Svc 1", "Greedy Svc 2", "Greedy Svc 3"],
        appointment_datetime=target_dt_str,
    )

    assert len(receipts) == 2
    # Greedy grouping combines the first two services into a single a1 block.
    assert receipts[0]["staff_agent_id"] == a1
    assert receipts[1]["staff_agent_id"] in (a2, a3)
    assert receipts[0]["duration_minutes"] == 60
    assert receipts[1]["duration_minutes"] == 30
    assert receipts[0]["service_components"] == [
        {"name": "Greedy Svc 1", "duration_minutes": 30},
        {"name": "Greedy Svc 2", "duration_minutes": 30},
    ]
    assert receipts[1]["service_components"] == [{"name": "Greedy Svc 3", "duration_minutes": 30}]
    assert sum(row["duration_minutes"] for row in receipts) == 90
    assert receipts[0]["booking_time"] == target_dt_str
    assert receipts[1]["booking_time"] == (tomorrow.replace(hour=11, minute=0, second=0)).strftime("%Y-%m-%d %H:%M:%S")
    assert receipts[0]["visit_group_id"] == receipts[1]["visit_group_id"]
    assert receipts[0]["linked_appointment_id"] == receipts[1]["service_request_id"]


def test_cancel_multi_service_visit():
    """T034: Full visit cancellation cancels all linked segments and releases slots."""
    data = _setup_two_services_and_agents()
    a1, a2 = data["agent_1"], data["agent_2"]
    set_service_agents(data["service_1_id"], [a1])
    set_service_agents(data["service_2_id"], [a2])

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
    v_group_id = receipts[0]["visit_group_id"]
    sr_ids = [r["service_request_id"] for r in receipts]

    # Cancel entire visit
    res = bs.cancel_multi_service_visit(v_group_id)
    assert res["success"] is True
    assert set(res["cancelled_ids"]) == set(sr_ids)

    # Verify database status
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("SELECT status FROM service_requests WHERE id = ANY(%s);", (sr_ids,))
            statuses = [r["status"] for r in cursor.fetchall()]
            assert all(s == "cancelled" for s in statuses)

            # Slots released
            cursor.execute(
                "SELECT is_booked, reservation_status FROM mock_calendar_slots WHERE staff_agent_id = %s AND slot_datetime = %s;",
                (a1, datetime.strptime(target_dt_str, "%Y-%m-%d %H:%M:%S"))
            )
            slot = cursor.fetchone()
            if slot:
                assert slot["is_booked"] is False or slot["reservation_status"] == "AVAILABLE"


def test_revise_multi_service_visit():
    """T035: Single-service revision preserves companion appointment at original slot."""
    data = _setup_two_services_and_agents()
    a1, a2 = data["agent_1"], data["agent_2"]
    set_service_agents(data["service_1_id"], [a1])
    set_service_agents(data["service_2_id"], [a2])

    tomorrow = timezone_service.now_in_business_tz() + timedelta(days=2)
    while tomorrow.weekday() > 4:
        tomorrow += timedelta(days=1)
    target_dt_str = tomorrow.strftime("%Y-%m-%d 10:00:00")
    s2_time = (tomorrow.replace(hour=11, minute=0, second=0)).strftime("%Y-%m-%d %H:%M:%S")

    bs = BookingService()
    receipts = bs.reserve_multi_service_appointment(
        customer_id=data["customer_id"],
        services=["Brake Service Test", "Transmission Flush Test"],
        appointment_datetime=target_dt_str,
    )
    sr1_id = receipts[0]["service_request_id"]
    sr2_id = receipts[1]["service_request_id"]

    # Customer drops Service 1
    rev_res = bs.revise_multi_service_visit(sr1_id)
    assert rev_res["success"] is True
    assert rev_res["cancelled_id"] == sr1_id
    assert sr2_id in rev_res["preserved_ids"]

    # Verify Service 1 cancelled, Service 2 preserved at 11:00 AM
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("SELECT status, booking_time FROM service_requests WHERE id = %s;", (sr1_id,))
            r1 = cursor.fetchone()
            assert r1["status"] == "cancelled"

            cursor.execute("SELECT status, booking_time FROM service_requests WHERE id = %s;", (sr2_id,))
            r2 = cursor.fetchone()
            assert r2["status"] != "cancelled"
            assert str(r2["booking_time"])[:19] == s2_time


def test_technician_sms_decline_auto_reassignment():
    """T036: Technician decline auto-reassigns to next available qualified technician."""
    data = _setup_two_services_and_agents()
    a1, a2 = data["agent_1"], data["agent_2"]

    # Both a1 and a2 qualified for Service 1
    set_service_agents(data["service_1_id"], [a1, a2])

    tomorrow = timezone_service.now_in_business_tz() + timedelta(days=2)
    while tomorrow.weekday() > 4:
        tomorrow += timedelta(days=1)
    target_dt_str = tomorrow.strftime("%Y-%m-%d 10:00:00")

    # Book with a1
    bs = BookingService()
    receipts = bs.reserve_multi_service_appointment(
        customer_id=data["customer_id"],
        services=["Brake Service Test"],
        appointment_datetime=target_dt_str,
    )
    sr_id = receipts[0]["service_request_id"]

    # Simulate a1 declining -> auto-reassign to a2
    reassign_res = bs.reassign_declined_technician_segment(sr_id)
    assert reassign_res["success"] is True
    assert reassign_res["reassigned"] is True
    assert reassign_res["new_agent_id"] == a2

    # Verify in DB
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("SELECT staff_agent_id, escalation_status FROM service_requests WHERE id = %s;", (sr_id,))
            row = cursor.fetchone()
            assert row["staff_agent_id"] == a2
            assert row["escalation_status"] == "reassigned"


def test_multi_service_google_calendar_sync():
    """T042/T043: Verify multi-service Google Calendar event creation and fallback."""
    from unittest.mock import patch, MagicMock
    from serviceBot.services.google_calendar import create_multi_service_calendar_events

    segments = [
        {
            "staff_agent_id": 1,
            "staff_agent_name": "John Doe",
            "service_name": "Oil Change",
            "booking_time": "2026-10-20 10:00:00",
            "duration_minutes": 30,
        },
        {
            "staff_agent_id": 2,
            "staff_agent_name": "Sarah Jenkins",
            "service_name": "Brake Replacement",
            "booking_time": "2026-10-20 10:30:00",
            "duration_minutes": 60,
        }
    ]

    with patch("serviceBot.services.google_calendar.httpx.post") as mock_post, \
         patch("serviceBot.services.google_calendar.load_config") as mock_load, \
         patch("serviceBot.services.google_calendar.get_user_google_credentials") as mock_creds:
        mock_load.return_value = {"business_name": "Davidson CarCare"}
        mock_creds.return_value = {"access_token": "mock_tok_123"}
        mock_post.return_value = MagicMock(status_code=201, text="{}")

        res = create_multi_service_calendar_events(
            customer_name="Alice Smith",
            segments=segments,
            issue_description="Regular maintenance",
        )

        assert res["success"] is True
        assert res["event_mode"] == "unified"
        assert res["summary"] == "Davidson CarCare Appointment - Alice Smith"
        # Check payload
        _, kwargs = mock_post.call_args
        json_data = kwargs.get("json", {})
        assert json_data["summary"] == "Davidson CarCare Appointment - Alice Smith"
        assert "BayFull" not in json_data["summary"]
        assert "serviceBot" not in json_data["summary"]
        assert "Oil Change" in json_data["description"]
        assert "Brake Replacement" in json_data["description"]
        assert "John Doe" in json_data["description"]
        assert "Sarah Jenkins" in json_data["description"]
        assert "Davidson CarCare" in json_data["description"]
        assert "BayFull" not in json_data["description"]
        assert "serviceBot" not in json_data["description"]


def test_multi_service_google_calendar_sync_fallback():
    """Verify fallback per-segment calendar event copy delegates when unified fails."""
    segments = [
        {
            "staff_agent_id": 1,
            "staff_agent_name": "John Doe",
            "service_name": "Oil Change",
            "booking_time": "2026-07-20 10:00:00",
            "duration_minutes": 60,
        },
        {
            "staff_agent_id": 2,
            "staff_agent_name": "Sarah Jenkins",
            "service_name": "Brake Replacement",
            "booking_time": "2026-07-20 11:00:00",
            "duration_minutes": 90,
        },
    ]

    with patch("serviceBot.services.google_calendar.httpx.post") as mock_post, \
         patch("serviceBot.services.google_calendar.load_config") as mock_load, \
         patch("serviceBot.services.google_calendar.get_user_google_credentials") as mock_creds, \
         patch("serviceBot.services.google_calendar.create_agent_calendar_event") as mock_agent_event:
        mock_load.return_value = {"business_name": "Davidson CarCare"}
        mock_creds.return_value = {"access_token": "mock_tok_123", "granted_scopes": {"https://www.googleapis.com/auth/calendar.events"}}
        mock_post.return_value = MagicMock(status_code=500, text="Internal Error") # unified fail
        mock_agent_event.return_value = True

        res = create_multi_service_calendar_events(
            customer_name="Alice Smith",
            segments=segments,
            issue_description="Regular maintenance",
        )

        assert res["success"] is True
        assert res["event_mode"] == "fallback_split"
        assert res["segments_count"] == 2
        assert mock_agent_event.call_count == 2
        call1 = mock_agent_event.call_args_list[0].kwargs
        assert call1["agent_id"] == 1
        assert call1["customer_name"] == "Alice Smith"
        assert call1["service_type"] == "Oil Change"
        assert call1["issue_description"] == "Regular maintenance"
        call2 = mock_agent_event.call_args_list[1].kwargs
        assert call2["agent_id"] == 2
        assert call2["customer_name"] == "Alice Smith"
        assert call2["service_type"] == "Brake Replacement"
        assert call2["issue_description"] == "Regular maintenance"
