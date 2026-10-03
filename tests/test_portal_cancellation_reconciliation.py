import pytest
from unittest.mock import patch, MagicMock
from serviceBot.db.connection import get_db_connection, dict_cursor
from serviceBot.db.queries import update_service_request_status
from serviceBot.services.sms_router import SMSNotificationRouter
from serviceBot.services.outbox_worker import _dispatch_outbox_event


import uuid


def create_cancellation_test_data(cust_phone=None, agent_phone="+15554443322"):
    import random
    rand_digits = "".join([str(random.randint(0, 9)) for _ in range(7)])
    cust_phone = cust_phone or f"+1555{rand_digits}"
    unique_email = f"advisor_{rand_digits}@example.com"
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            # 1. Staff Agent
            cursor.execute(
                """
                INSERT INTO staff_agents (name, role, email, phone_number)
                VALUES ('Alex Rivera', 'Service Advisor', %s, %s)
                RETURNING id;
                """,
                (unique_email, agent_phone)
            )
            agent_id = cursor.fetchone()["id"]

            # 2. Customer
            cursor.execute(
                """
                INSERT INTO customers (name, phone, sms_opt_in)
                VALUES ('Morgan Taylor', %s, TRUE)
                ON CONFLICT (phone) DO UPDATE SET name = EXCLUDED.name
                RETURNING id;
                """,
                (cust_phone,)
            )
            cust_id = cursor.fetchone()["id"]

            # 3. Vehicle
            cursor.execute(
                """
                INSERT INTO vehicles (customer_id, year, make, model)
                VALUES (%s, '2023', 'Toyota', 'RAV4')
                RETURNING id;
                """,
                (cust_id,)
            )
            veh_id = cursor.fetchone()["id"]

            # 4. Service Request
            cursor.execute(
                """
                INSERT INTO service_requests (
                    customer_id, vehicle_id, staff_agent_id,
                    service_type, issue_description, booking_time, status, confirmation_status
                )
                VALUES (%s, %s, %s, 'Brake Inspection', 'Squeaking brake noise', '2026-11-15 14:00:00', 'pending', 'pending')
                RETURNING id;
                """,
                (cust_id, veh_id, agent_id)
            )
            sr_id = cursor.fetchone()["id"]

            # 5. Reservation & Mock Slot
            cursor.execute(
                """
                INSERT INTO appointment_reservations (service_request_id, staff_agent_id, status, starts_at, ends_at)
                VALUES (%s, %s, 'ACTIVE', '2026-11-15 14:00:00', '2026-11-15 15:00:00')
                RETURNING id;
                """,
                (sr_id, agent_id)
            )
            res_id = cursor.fetchone()["id"]

            cursor.execute(
                """
                INSERT INTO appointment_reservation_segments (reservation_id, staff_agent_id, segment_start)
                VALUES (%s, %s, '2026-11-15 14:00:00');
                """,
                (res_id, agent_id)
            )

            cursor.execute(
                """
                INSERT INTO mock_calendar_slots (service_request_id, slot_datetime, is_booked)
                VALUES (%s, '2026-11-15 14:00:00', TRUE);
                """,
                (sr_id,)
            )

            return cust_id, veh_id, agent_id, sr_id, res_id, cust_phone, agent_phone


def test_sms_router_resolves_agent_phone_and_dispatches_cancellation():
    """Verify that SMSNotificationRouter automatically resolves the assigned agent's phone from DB and sends the cancellation alert."""
    router = SMSNotificationRouter()
    cust_id, veh_id, agent_id, sr_id, res_id, cust_phone, agent_phone = create_cancellation_test_data()

    with patch.object(router.twilio_client, "send_whatsapp") as mock_whatsapp, \
         patch("serviceBot.services.twilio_sms.is_phone_whitelisted", return_value=True), \
         patch("serviceBot.services.sms_router.get_customer_opt_in", return_value=True), \
         patch("serviceBot.services.sms_router.is_in_quiet_hours", return_value=False), \
         patch("serviceBot.services.sms_router.get_sms_matrix_rules", return_value=[
             {"event_type": "CANCELLED_BY_ADMIN", "recipient_role": "customer", "channel": "WHATSAPP", "enabled": True},
             {"event_type": "CANCELLED_BY_ADMIN", "recipient_role": "agent", "channel": "WHATSAPP", "enabled": True},
         ]):
        mock_whatsapp.return_value = {"success": True, "sid": "SMmock_cancel_123"}

        # Call process_event without passing customer_phone or agent_phone explicitly
        res = router.process_event(
            event_type="CANCELLED_BY_ADMIN",
            appointment_id=sr_id,
        )

        assert res["event_type"] == "CANCELLED_BY_ADMIN"
        dispatches = res["dispatches"]
        recipients = [d["recipient"] for d in dispatches if d.get("success")]
        assert "customer" in recipients
        assert "agent" in recipients

        # Verify WhatsApp calls
        assert mock_whatsapp.call_count == 2
        calls = mock_whatsapp.call_args_list

        to_numbers = [c.kwargs.get("to") for c in calls]
        bodies = [c.kwargs.get("body") for c in calls]

        # Check customer received cancellation notification
        assert any(cust_phone in to for to in to_numbers)
        # Check advisor received cancellation notification
        assert any(agent_phone in to for to in to_numbers)

        agent_call = next(c for c in calls if agent_phone in c.kwargs.get("to"))
        agent_body = agent_call.kwargs.get("body")
        assert "❌ [APPOINTMENT CANCELLED]" in agent_body
        assert f"Appt #{sr_id}" in agent_body
        assert "Morgan Taylor" in agent_body
        assert "Brake Inspection" in agent_body
        assert "removed from your schedule" in agent_body
        assert "removed from your schedule" in agent_body


def test_sms_router_handles_agent_without_phone_gracefully():
    """Verify that if the assigned agent has no phone number on file, customer is still notified and no crash occurs."""
    router = SMSNotificationRouter()
    cust_id, veh_id, agent_id, sr_id, res_id, cust_phone, agent_phone = create_cancellation_test_data(agent_phone=None)

    with patch.object(router.twilio_client, "send_whatsapp") as mock_whatsapp, \
         patch("serviceBot.services.twilio_sms.is_phone_whitelisted", return_value=True), \
         patch("serviceBot.services.sms_router.get_customer_opt_in", return_value=True), \
         patch("serviceBot.services.sms_router.is_in_quiet_hours", return_value=False), \
         patch("serviceBot.services.sms_router.get_sms_matrix_rules", return_value=[
             {"event_type": "CANCELLED_BY_ADMIN", "recipient_role": "customer", "channel": "WHATSAPP", "enabled": True},
             {"event_type": "CANCELLED_BY_ADMIN", "recipient_role": "agent", "channel": "WHATSAPP", "enabled": True},
         ]):
        mock_whatsapp.return_value = {"success": True, "sid": "SMmock_cancel_456"}

        res = router.process_event(
            event_type="CANCELLED_BY_ADMIN",
            appointment_id=sr_id,
        )

        dispatches = res["dispatches"]
        assert any(d["recipient"] == "customer" and d.get("success") for d in dispatches)
        # Agent dispatch should be safely skipped (no phone)
        assert not any(d["recipient"] == "agent" for d in dispatches)


def test_portal_status_cancellation_releases_capacity_and_calendar_slots():
    """Verify that update_service_request_status to 'cancelled' cleans up capacity reservations and mock slots."""
    cust_id, veh_id, agent_id, sr_id, res_id, cust_phone, agent_phone = create_cancellation_test_data()

    updated = update_service_request_status(sr_id, "cancelled", triggered_by="admin", notes="Cancelled via portal")
    assert updated["status"] == "cancelled"

    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            # 1. service_requests status & confirmation_status
            cursor.execute("SELECT status, confirmation_status FROM service_requests WHERE id = %s;", (sr_id,))
            sr = cursor.fetchone()
            assert sr["status"] == "cancelled"
            assert sr["confirmation_status"] == "cancelled"

            # 2. appointment_reservations status
            cursor.execute("SELECT status FROM appointment_reservations WHERE id = %s;", (res_id,))
            resv = cursor.fetchone()
            assert resv["status"] == "CANCELLED"

            # 3. appointment_reservation_segments deleted
            cursor.execute("SELECT count(*) AS cnt FROM appointment_reservation_segments WHERE reservation_id = %s;", (res_id,))
            assert cursor.fetchone()["cnt"] == 0

            # 4. mock_calendar_slots released
            cursor.execute("SELECT count(*) AS cnt FROM mock_calendar_slots WHERE service_request_id = %s AND is_booked = TRUE;", (sr_id,))
            assert cursor.fetchone()["cnt"] == 0

            # 5. Outbox event created with agent info
            cursor.execute("SELECT event_type, payload FROM outbox_notifications WHERE request_id = %s ORDER BY id;", (sr_id,))
            rows = cursor.fetchall()
            event_types = [r["event_type"] for r in rows]
            assert "sms_status_change" in event_types
