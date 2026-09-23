"""Contracts for notification channel selection, durable replay, and outbox failure semantics."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from serviceBot.db.connection import dict_cursor, get_db_connection
from serviceBot.db.queries import add_sms_whitelist, get_sms_log_by_id, log_sms_dispatch
from serviceBot.services.outbox_worker import NotificationDeliveryError, _require_notification_delivery
from serviceBot.services.outbox_worker import _dispatch_outbox_event
from serviceBot.services.quiet_hours import run_quiet_hours_queue_worker_cycle
from serviceBot.services.sms_router import SMSNotificationRouter


def _router_with_mock_client() -> tuple[SMSNotificationRouter, MagicMock]:
    router = SMSNotificationRouter()
    client = MagicMock()
    client.send_sms.return_value = {"success": True, "status": "SENT", "sid": "SM-sms"}
    client.send_whatsapp.return_value = {"success": True, "status": "SENT", "sid": "SM-whatsapp"}
    router.twilio_client = client
    return router, client


@patch("serviceBot.services.sms_router.schedule_appointment_reminders")
@patch("serviceBot.services.sms_router.is_in_quiet_hours", return_value=False)
@patch("serviceBot.services.sms_router.get_customer_opt_in", return_value=True)
@patch(
    "serviceBot.services.sms_router.get_sms_matrix_rules",
    return_value=[
        {"event_type": "BOOKING", "recipient_role": "customer", "channel": "SMS", "enabled": True},
        {"event_type": "BOOKING", "recipient_role": "customer", "channel": "WHATSAPP", "enabled": False},
    ],
)
def test_router_uses_enabled_sms_channel_not_whatsapp(
    _rules, _opt_in, _quiet, _reminders, dummy_appointment_id
):
    router, client = _router_with_mock_client()

    result = router.process_event(
        event_type="BOOKING",
        appointment_id=dummy_appointment_id,
        customer_phone="+15550123456",
        booking_time="2026-10-25 14:00:00",
    )

    client.send_sms.assert_called_once()
    client.send_whatsapp.assert_not_called()
    assert result["dispatches"] == [
        {"recipient": "customer", "channel": "SMS", "success": True, "status": "SENT", "sid": "SM-sms"}
    ]


@patch("serviceBot.services.sms_router.schedule_appointment_reminders")
@patch("serviceBot.services.sms_router.is_in_quiet_hours", return_value=False)
@patch("serviceBot.services.sms_router.get_customer_opt_in", return_value=True)
@patch(
    "serviceBot.services.sms_router.get_sms_matrix_rules",
    return_value=[
        {"event_type": "BOOKING", "recipient_role": "customer", "channel": "SMS", "enabled": False},
        {"event_type": "BOOKING", "recipient_role": "customer", "channel": "WHATSAPP", "enabled": True},
    ],
)
def test_router_uses_enabled_whatsapp_channel(
    _rules, _opt_in, _quiet, _reminders, dummy_appointment_id
):
    router, client = _router_with_mock_client()

    result = router.process_event(
        event_type="BOOKING",
        appointment_id=dummy_appointment_id,
        customer_phone="+15550123457",
        booking_time="2026-10-25 14:00:00",
    )

    client.send_whatsapp.assert_called_once()
    client.send_sms.assert_not_called()
    assert result["dispatches"][0]["channel"] == "WHATSAPP"


def test_quiet_hours_release_reuses_stored_body_and_channel(dummy_appointment_id):
    phone = "+15550123458"
    body = "The exact queued booking confirmation."
    add_sms_whitelist(phone, "Quiet Hours Contract", twilio_verified=True)
    log_id = log_sms_dispatch(
        appointment_id=dummy_appointment_id,
        recipient_type="customer",
        recipient_phone=phone,
        template_type="booking",
        status="QUEUED",
        scheduled_send_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=1),
        body=body,
        channel="WHATSAPP",
    )

    run_quiet_hours_queue_worker_cycle()

    log = get_sms_log_by_id(log_id)
    assert log["status"] == "SENT"
    assert log["body"] == body
    assert log["channel"] == "WHATSAPP"
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("SELECT COUNT(*) AS total FROM sms_log WHERE id = %s;", (log_id,))
            assert cursor.fetchone()["total"] == 1


def test_outbox_refuses_to_mark_failed_enabled_delivery_as_delivered():
    with pytest.raises(NotificationDeliveryError):
        _require_notification_delivery(
            {"dispatches": [{"recipient": "customer", "status": "FAILED", "success": False}]}
        )

    _require_notification_delivery(
        {"dispatches": [{"recipient": "customer", "status": "QUEUED", "success": False}]}
    )


@patch("serviceBot.services.outbox_worker._require_notification_delivery")
@patch("serviceBot.services.outbox_worker.send_admin_notification")
@patch("serviceBot.services.outbox_worker.create_admin_calendar_event")
@patch("serviceBot.services.outbox_worker.delete_admin_calendar_event")
@patch("serviceBot.services.outbox_worker.send_booking_notification")
def test_booking_outbox_dispatches_reschedule_event_to_the_intended_contacts(
    send_booking, _delete_admin, _create_admin, send_admin, _require_delivery
):
    details = {"customer_name": "Ada", "phone": "+15550100000", "service_type": "Oil Change", "issue": "Routine", "duration_minutes": 60}
    router = MagicMock()
    router.process_event.return_value = {"dispatches": [{"recipient": "customer", "status": "SENT", "success": True}]}
    payload = {
        "booking_type": "appointment",
        "notification_event": "RESCHEDULED_REASSIGNED",
        "agent_email": "new@example.test",
        "agent_name": "New Agent",
        "agent_phone": "+15550100002",
        "previous_agent_phone": "+15550100001",
        "booking_time_str": "2026-10-15 10:30:00",
        "details": details,
    }
    with patch("serviceBot.services.sms_router.SMSNotificationRouter", return_value=router):
        _dispatch_outbox_event("booking_notification", request_id=None, payload=payload)

    send_booking.assert_called_once_with("reschedule", details, agent_email="new@example.test")
    send_admin.assert_called_once_with("reschedule", details, agent_name="New Agent", agent_email="new@example.test")
    router.process_event.assert_called_once_with(
        event_type="RESCHEDULED_REASSIGNED",
        appointment_id=None,
        customer_phone="+15550100000",
        agent_phone="+15550100002",
        previous_agent_phone="+15550100001",
        booking_time="2026-10-15 10:30:00",
        details=details,
    )
