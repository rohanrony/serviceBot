import pytest
from unittest.mock import patch, MagicMock
import datetime as dt_mod

from serviceBot.services.booking import BookingService, BookingValidationError
from serviceBot.db.queries import cancel_appointment, create_service_request, check_availability
from serviceBot.services.sms_router import SMSNotificationRouter
from serviceBot.services.outbox_worker import _dispatch_outbox_event


def test_cancel_requires_customer_consent(dummy_appointment_id):
    svc = BookingService()
    with pytest.raises(BookingValidationError, match="Customer consent is required"):
        svc.cancel(
            request_id=dummy_appointment_id,
            customer_consent_obtained=False,
            triggered_by="customer"
        )


def test_cancel_appointment_atomicity_and_cleanup(dummy_appointment_id):
    svc = BookingService()
    res = svc.cancel(
        request_id=dummy_appointment_id,
        customer_consent_obtained=True,
        triggered_by="voice_agent",
        reason="Customer had a scheduling conflict"
    )

    assert res["request_id"] == dummy_appointment_id
    assert res["status"] == "cancelled"
    assert res["cancelled"] is True

    # Test idempotency: Calling cancel again returns already_cancelled
    res_second = svc.cancel(
        request_id=dummy_appointment_id,
        customer_consent_obtained=True,
        triggered_by="voice_agent",
    )
    assert res_second["already_cancelled"] is True

    # Verify database state
    from serviceBot.db.connection import get_db_connection, dict_cursor
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            # Check service_requests status
            cursor.execute("SELECT status, confirmation_status, escalation_status, escalation_reason FROM service_requests WHERE id = %s;", (dummy_appointment_id,))
            sr = cursor.fetchone()
            assert sr["status"] == "cancelled"
            assert sr["confirmation_status"] == "cancelled"
            assert sr["escalation_status"] == "none"
            assert sr["escalation_reason"] is None

            # Check appointment_reservations status
            cursor.execute("SELECT status FROM appointment_reservations WHERE service_request_id = %s;", (dummy_appointment_id,))
            resvs = cursor.fetchall()
            for r in resvs:
                assert r["status"] == "CANCELLED"

            # Check segments deleted
            cursor.execute(
                """
                SELECT count(*) AS cnt FROM appointment_reservation_segments s
                JOIN appointment_reservations r ON s.reservation_id = r.id
                WHERE r.service_request_id = %s;
                """,
                (dummy_appointment_id,)
            )
            assert cursor.fetchone()["cnt"] == 0

            # Check mock_calendar_slots released
            cursor.execute(
                "SELECT count(*) AS cnt FROM mock_calendar_slots WHERE service_request_id = %s AND is_booked = TRUE;",
                (dummy_appointment_id,)
            )
            assert cursor.fetchone()["cnt"] == 0

            # Check outbox notifications enqueued
            cursor.execute(
                "SELECT event_type, payload FROM outbox_notifications WHERE request_id = %s ORDER BY id ASC;",
                (dummy_appointment_id,)
            )
            outbox_rows = cursor.fetchall()
            types = [row["event_type"] for row in outbox_rows]
            assert "calendar_projection" in types
            assert "booking_notification" in types


def test_sms_router_bypass_quiet_hours_interactive_call(dummy_appointment_id):
    router = SMSNotificationRouter()

    # When quiet hours is True, non-urgent, and bypass_quiet_hours is False -> QUEUED
    with patch("serviceBot.services.sms_router.is_in_quiet_hours", return_value=True):
        res_queued = router.process_event(
            event_type="RESCHEDULED",
            appointment_id=dummy_appointment_id,
            customer_phone="+15550192831",
            booking_time="2026-10-25 14:00:00",
            bypass_quiet_hours=False
        )
        cust_dispatch = next((d for d in res_queued["dispatches"] if d["recipient"] == "customer"), None)
        assert cust_dispatch is not None
        assert cust_dispatch["status"] == "QUEUED"

    # When quiet hours is True, but bypass_quiet_hours is True (or triggered_by="voice_agent") -> dispatched immediately
    with patch("serviceBot.services.sms_router.is_in_quiet_hours", return_value=True), \
         patch.object(router, "_dispatch_to", return_value=[{"recipient": "customer", "channel": "sms", "success": True}]) as mock_dispatch:
        res_bypassed = router.process_event(
            event_type="RESCHEDULED",
            appointment_id=dummy_appointment_id,
            customer_phone="+15550192831",
            booking_time="2026-10-25 14:00:00",
            bypass_quiet_hours=True
        )
        mock_dispatch.assert_called_once()
        assert any(d["recipient"] == "customer" and d["success"] is True for d in res_bypassed["dispatches"])


def test_outbox_worker_cancel_calendar_projection_and_notification():
    with patch("serviceBot.services.outbox_worker.delete_agent_calendar_event") as mock_del_agent, \
         patch("serviceBot.services.outbox_worker.delete_admin_calendar_event") as mock_del_admin, \
         patch("serviceBot.services.outbox_worker.send_booking_notification") as mock_send_agent_notif, \
         patch("serviceBot.services.outbox_worker.send_admin_notification") as mock_send_admin_notif, \
         patch("serviceBot.services.sms_router.SMSNotificationRouter.process_event", return_value={"dispatches": [{"recipient": "customer", "status": "SENT", "success": True}]}) as mock_sms:

        # 1. Calendar projection delete
        _dispatch_outbox_event(
            event_type="calendar_projection",
            request_id=999,
            payload={
                "action": "delete",
                "reservation_id": 1,
                "agent_id": 1,
                "calendar_event_id": "servicebot1",
                "booking_time_str": "2026-10-05 13:00:00",
                "duration_minutes": 60,
                "details": {"customer_name": "Test User", "phone": "+15550192831"}
            }
        )
        mock_del_agent.assert_called_once()

        # 2. Booking notification cancellation
        _dispatch_outbox_event(
            event_type="booking_notification",
            request_id=999,
            payload={
                "notification_event": "CANCELLED_BY_CUSTOMER",
                "booking_time_str": "2026-10-05 13:00:00",
                "agent_id": 1,
                "agent_name": "Bob Agent",
                "agent_email": "bob@example.com",
                "agent_phone": "+15550192832",
                "triggered_by": "voice_agent",
                "bypass_quiet_hours": True,
                "details": {
                    "customer_name": "Test User",
                    "phone": "+15550192831",
                    "service_type": "Oil Change",
                    "bypass_quiet_hours": True
                }
            }
        )
        mock_del_admin.assert_called_once_with("2026-10-05 13:00:00")
        mock_send_agent_notif.assert_called_once()
        assert mock_send_agent_notif.call_args[0][0] == "cancel"
        mock_send_admin_notif.assert_called_once()
        assert mock_send_admin_notif.call_args[0][0] == "cancel"
        mock_sms.assert_called_once()
        assert mock_sms.call_args[1]["bypass_quiet_hours"] is True


@pytest.mark.anyio
async def test_telephony_voice_tool_cancel_appointment(dummy_appointment_id):
    from serviceBot.api.telephony import voice_tools
    from serviceBot.db.connection import get_db_connection, dict_cursor

    # Get customer phone for dummy appointment
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                """
                SELECT c.phone FROM service_requests sr
                JOIN customers c ON sr.customer_id = c.id
                WHERE sr.id = %s;
                """,
                (dummy_appointment_id,)
            )
            phone = cursor.fetchone()["phone"]

    payload = {
        "name": "cancel_appointment",
        "arguments": {
            "phone": phone,
            "appointment_id": dummy_appointment_id,
            "cancellation_reason": "No longer needed"
        }
    }

    resp = await voice_tools(payload=payload)
    assert resp["result"]["success"] is True
    assert f"Appointment #{dummy_appointment_id} has been successfully cancelled" in resp["result"]["message"]


@pytest.mark.anyio
async def test_cancelled_appointment_clears_escalation_and_excluded_from_escalated_queue(dummy_appointment_id):
    from serviceBot.api.portal import get_service_requests
    from serviceBot.db.queries import escalate_service_request
    from serviceBot.services.sms_reminders import dispatch_supervisor_escalation_alert
    from serviceBot.db.connection import get_db_connection, dict_cursor

    # 1. Artificially mark dummy_appointment_id as escalated
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                """
                UPDATE service_requests
                SET escalation_status = 'escalated',
                    escalation_reason = 'TIMEOUT_NO_RESPONSE',
                    confirmation_status = 'pending_agent_confirmation'
                WHERE id = %s;
                """,
                (dummy_appointment_id,)
            )
            conn.commit()

    # 2. Query portal escalated service requests - should be visible
    escalated_items = await get_service_requests(escalated=True)
    escalated_ids = [item["id"] for item in escalated_items]
    assert dummy_appointment_id in escalated_ids

    # 3. Cancel the appointment via BookingService
    svc = BookingService()
    res = svc.cancel(
        request_id=dummy_appointment_id,
        customer_consent_obtained=True,
        triggered_by="customer_portal",
        reason="No longer required"
    )
    assert res["status"] == "cancelled"

    # 4. Verify DB state has escalation_status reset to 'none' and reason cleared
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                "SELECT status, confirmation_status, escalation_status, escalation_reason FROM service_requests WHERE id = %s;",
                (dummy_appointment_id,)
            )
            sr = cursor.fetchone()
            assert sr["status"] == "cancelled"
            assert sr["confirmation_status"] == "cancelled"
            assert sr["escalation_status"] == "none"
            assert sr["escalation_reason"] is None

    # 5. Query portal escalated service requests - should NO LONGER be returned
    escalated_items_after = await get_service_requests(escalated=True)
    escalated_ids_after = [item["id"] for item in escalated_items_after]
    assert dummy_appointment_id not in escalated_ids_after

    # 6. Attempting to escalate an already cancelled appointment should be ignored / skipped
    esc_result = escalate_service_request(dummy_appointment_id, reason="AGENT_DECLINED")
    assert esc_result["status"] == "cancelled"
    assert esc_result["escalation_status"] == "none"

    # 7. Attempting to send supervisor alert on cancelled appointment should skip
    alert_res = dispatch_supervisor_escalation_alert(dummy_appointment_id, reason="TIMEOUT_NO_RESPONSE")
    assert alert_res.get("skipped") is True


def test_update_service_request_status_cancelled_clears_escalation(dummy_appointment_id):
    from serviceBot.db.queries import update_service_request_status
    from serviceBot.db.connection import get_db_connection, dict_cursor

    # 1. Artificially mark request as escalated
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                """
                UPDATE service_requests
                SET status = 'pending',
                    escalation_status = 'escalated',
                    escalation_reason = 'AGENT_DECLINED'
                WHERE id = %s;
                """,
                (dummy_appointment_id,)
            )
            conn.commit()

    # 2. Update status to 'cancelled' via queries.update_service_request_status
    updated = update_service_request_status(dummy_appointment_id, status="cancelled", triggered_by="portal_admin")
    assert updated["status"] == "cancelled"

    # 3. Verify escalation_status is reset to 'none' and confirmation_status is 'cancelled'
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                "SELECT status, confirmation_status, escalation_status, escalation_reason FROM service_requests WHERE id = %s;",
                (dummy_appointment_id,)
            )
            sr = cursor.fetchone()
            assert sr["status"] == "cancelled"
            assert sr["confirmation_status"] == "cancelled"
            assert sr["escalation_status"] == "none"
            assert sr["escalation_reason"] is None

