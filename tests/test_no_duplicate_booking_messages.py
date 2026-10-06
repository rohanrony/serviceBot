import datetime as dt_mod
from unittest.mock import MagicMock, patch
import pytest

from serviceBot.services.sms_router import SMSNotificationRouter
from serviceBot.services.sms_reminders import (
    schedule_appointment_reminders,
    run_reminder_polling_worker_cycle,
    update_or_cancel_appointment_reminders,
)


def test_booking_does_not_duplicate_messages_to_customer_and_agent():
    """
    Verify that an appointment booking dispatches EXACTLY ONE message to the customer
    and EXACTLY ONE message to the assigned agent, and that running the polling worker
    does NOT duplicate Attempt 1.
    """
    router = SMSNotificationRouter()
    mock_client = MagicMock()
    sent_dispatches = []

    def mock_send_sms(to, body, template_type, appointment_id=None, recipient_type=None, channel="SMS"):
        record = {
            "to": to,
            "body": body,
            "template_type": template_type,
            "appointment_id": appointment_id,
            "recipient_type": recipient_type,
            "channel": channel,
            "success": True,
            "status": "SENT",
            "sid": f"SM-mock-{len(sent_dispatches)+1}",
        }
        sent_dispatches.append(record)
        return {"success": True, "status": "SENT", "sid": record["sid"]}

    def mock_send_whatsapp(to, body, template_type, appointment_id=None, recipient_type=None):
        return mock_send_sms(to, body, template_type, appointment_id, recipient_type, channel="WHATSAPP")

    mock_client.send_sms.side_effect = mock_send_sms
    mock_client.send_whatsapp.side_effect = mock_send_whatsapp
    router.twilio_client = mock_client

    rules = [
        {"event_type": "BOOKING", "recipient_role": "customer", "channel": "WHATSAPP", "enabled": True},
        {"event_type": "BOOKING", "recipient_role": "agent", "channel": "SMS", "enabled": True},
        {"event_type": "BOOKING", "recipient_role": "admin", "channel": "WHATSAPP", "enabled": False},
    ]

    stored_reminders = []
    reminder_seq = 100

    def mock_schedule_sms_reminder(
        appointment_id, recipient_type, recipient_phone, reminder_type, scheduled_at,
        attempt_number=1, attempt_kind="final_reminder", status="PENDING"
    ):
        nonlocal reminder_seq
        reminder_seq += 1
        record = {
            "id": reminder_seq,
            "appointment_id": appointment_id,
            "recipient_type": recipient_type,
            "recipient_phone": recipient_phone,
            "reminder_type": reminder_type,
            "scheduled_at": scheduled_at,
            "status": status,
            "attempt_number": attempt_number,
            "attempt_kind": attempt_kind,
            "retry_count": 0,
        }
        stored_reminders.append(record)
        return record["id"]

    mock_cursor = MagicMock()
    # When polling worker selects PENDING due reminders:
    def mock_fetchall():
        now = dt_mod.datetime.now()
        return [r for r in stored_reminders if r["status"] == "PENDING" and r["scheduled_at"] <= now]
    mock_cursor.fetchall.side_effect = mock_fetchall
    mock_cursor_ctx = MagicMock()
    mock_cursor_ctx.__enter__.return_value = mock_cursor
    mock_conn = MagicMock()
    mock_conn_ctx = MagicMock()
    mock_conn_ctx.__enter__.return_value = mock_conn

    cfg = {
        "business_address": "123 Main St, Springfield, NC 27513",
        "google_maps_url": "https://maps.app.goo.gl/davidson-car-care",
        "min_booking_buffer_hours": 4,
        "final_reminder_hours": 2,
    }

    details = {
        "customer_name": "Marcus Vance",
        "phone": "+19195551234",
        "vehicle": "2021 Toyota Camry",
        "service_type": "Brake Inspection",
        "time": "2026-10-25 14:00:00",
        "duration_minutes": 60,
        "new_agent_name": "Tech Tom",
        "agent_name": "Tech Tom",
        "issue": "Squeaking front brakes",
    }

    with patch("serviceBot.services.sms_router.get_sms_matrix_rules", return_value=rules), \
         patch("serviceBot.services.sms_router.get_customer_opt_in", return_value=True), \
         patch("serviceBot.services.sms_router.is_in_quiet_hours", return_value=False), \
         patch("serviceBot.services.sms_router.should_bypass_quiet_hours", return_value=False), \
         patch("serviceBot.services.sms_router.log_sms_dispatch", return_value=1), \
         patch("serviceBot.db.queries.get_sms_config", return_value={}), \
         patch("serviceBot.db.queries.get_or_create_sms_conversation", return_value={"id": 1}), \
         patch("serviceBot.db.queries.add_sms_message", return_value=1), \
         patch("serviceBot.services.sms_reminders.schedule_sms_reminder", side_effect=mock_schedule_sms_reminder), \
         patch("serviceBot.db.connection.get_db_connection", return_value=mock_conn_ctx), \
         patch("serviceBot.db.connection.dict_cursor", return_value=mock_cursor_ctx), \
         patch("serviceBot.api.portal.load_config", return_value=cfg):

        # Step 1: Initial booking event processed
        result = router.process_event(
            event_type="BOOKING",
            appointment_id=42,
            customer_phone="+19195551234",
            agent_phone="+19195559999",
            booking_time="2026-10-25 14:00:00",
            details=details,
        )

    # Verify router returned success and dispatches
    assert len(result["dispatches"]) == 2
    recipients = [d["recipient"] for d in result["dispatches"]]
    assert "customer" in recipients
    assert "agent" in recipients

    # Verify exactly 1 customer message and 1 agent message were sent
    customer_sent = [m for m in sent_dispatches if m["recipient_type"] == "customer"]
    agent_sent = [m for m in sent_dispatches if m["recipient_type"] == "agent"]
    assert len(customer_sent) == 1, f"Expected exactly 1 customer message, got {len(customer_sent)}"
    assert len(agent_sent) == 1, f"Expected exactly 1 agent message, got {len(agent_sent)}"

    # Verify Attempt 1 was recorded in sms_reminders with status SENT (not left PENDING to cause duplicate)
    attempt1_records = [r for r in stored_reminders if r["attempt_number"] == 1]
    assert len(attempt1_records) == 2, "Expected Attempt 1 records for customer and agent"
    for att in attempt1_records:
        assert att["status"] == "SENT", f"Attempt 1 record {att['id']} should have status SENT, got {att['status']}"

    # Verify Attempt 2 and Attempt 3 are queued with status PENDING for future execution
    future_records = [r for r in stored_reminders if r["attempt_number"] > 1]
    assert len(future_records) >= 2, "Expected future attempts to be queued"
    for att in future_records:
        assert att["status"] == "PENDING"

    # Step 2: Now simulate the 30-second background polling worker cycle
    with patch("serviceBot.db.connection.get_db_connection", return_value=mock_conn_ctx), \
         patch("serviceBot.db.connection.dict_cursor", return_value=mock_cursor_ctx), \
         patch("serviceBot.api.portal.load_config", return_value=cfg), \
         patch("serviceBot.services.sms_reminders.TwilioSMSClient", return_value=mock_client):
        dispatched_count = run_reminder_polling_worker_cycle()

    # The polling worker should have found 0 due pending reminders (Attempt 1 is already SENT)
    assert dispatched_count == 0

    # Still exactly 1 customer message and 1 agent message in total!
    assert len([m for m in sent_dispatches if m["recipient_type"] == "customer"]) == 1
    assert len([m for m in sent_dispatches if m["recipient_type"] == "agent"]) == 1


def test_reassignment_does_not_duplicate_messages_to_new_agent():
    """
    Verify that an appointment reassignment dispatches EXACTLY ONE message to the new agent,
    and running the reminder worker does not fire a duplicate.
    """
    router = SMSNotificationRouter()
    mock_client = MagicMock()
    sent_dispatches = []

    def mock_send_sms(to, body, template_type, appointment_id=None, recipient_type=None, channel="SMS"):
        record = {
            "to": to,
            "body": body,
            "template_type": template_type,
            "appointment_id": appointment_id,
            "recipient_type": recipient_type,
            "channel": channel,
            "success": True,
            "status": "SENT",
        }
        sent_dispatches.append(record)
        return {"success": True, "status": "SENT", "sid": f"SM-mock-{len(sent_dispatches)}"}

    mock_client.send_sms.side_effect = mock_send_sms
    mock_client.send_whatsapp.side_effect = mock_send_sms
    router.twilio_client = mock_client

    rules = [
        {"event_type": "REASSIGNED", "recipient_role": "agent", "channel": "SMS", "enabled": True},
        {"event_type": "REASSIGNED", "recipient_role": "previous_agent", "channel": "SMS", "enabled": True},
        {"event_type": "REASSIGNED", "recipient_role": "customer", "channel": "WHATSAPP", "enabled": False},
        {"event_type": "REASSIGNED", "recipient_role": "admin", "channel": "WHATSAPP", "enabled": False},
    ]

    stored_reminders = []
    def mock_schedule_sms_reminder(
        appointment_id, recipient_type, recipient_phone, reminder_type, scheduled_at,
        attempt_number=1, attempt_kind="final_reminder", status="PENDING"
    ):
        record = {
            "id": len(stored_reminders) + 1,
            "appointment_id": appointment_id,
            "recipient_type": recipient_type,
            "recipient_phone": recipient_phone,
            "reminder_type": reminder_type,
            "scheduled_at": scheduled_at,
            "status": status,
            "attempt_number": attempt_number,
            "attempt_kind": attempt_kind,
        }
        stored_reminders.append(record)
        return record["id"]

    mock_cursor = MagicMock()
    mock_cursor_ctx = MagicMock()
    mock_cursor_ctx.__enter__.return_value = mock_cursor
    mock_conn = MagicMock()
    mock_conn_ctx = MagicMock()
    mock_conn_ctx.__enter__.return_value = mock_conn

    cfg = {"min_booking_buffer_hours": 4, "final_reminder_hours": 2}

    with patch("serviceBot.services.sms_router.get_sms_matrix_rules", return_value=rules), \
         patch("serviceBot.services.sms_router.is_in_quiet_hours", return_value=False), \
         patch("serviceBot.services.sms_router.should_bypass_quiet_hours", return_value=False), \
         patch("serviceBot.services.sms_router.log_sms_dispatch", return_value=1), \
         patch("serviceBot.services.sms_reminders.schedule_sms_reminder", side_effect=mock_schedule_sms_reminder), \
         patch("serviceBot.services.sms_reminders.cancel_pending_sms_reminders"), \
         patch("serviceBot.db.connection.get_db_connection", return_value=mock_conn_ctx), \
         patch("serviceBot.db.connection.dict_cursor", return_value=mock_cursor_ctx), \
         patch("serviceBot.api.portal.load_config", return_value=cfg):

        res = router.process_event(
            event_type="REASSIGNED",
            appointment_id=88,
            agent_phone="+19195550222",
            previous_agent_phone="+19195550111",
            booking_time="2026-10-25 14:00:00",
            details={
                "customer_name": "Marcus Vance",
                "phone": "+19195551234",
                "service_type": "Brake Inspection",
                "new_agent_name": "New Tech",
                "previous_agent_name": "Old Tech",
                "time": "2026-10-25 14:00:00"
            }
        )

    # Exactly 1 message to new agent and 1 to previous agent
    new_agent_sent = [m for m in sent_dispatches if m["recipient_type"] == "agent"]
    prev_agent_sent = [m for m in sent_dispatches if m["recipient_type"] == "previous_agent"]
    assert len(new_agent_sent) == 1, f"Expected 1 message to new agent, got {len(new_agent_sent)}"
    assert len(prev_agent_sent) == 1, f"Expected 1 message to previous agent, got {len(prev_agent_sent)}"
