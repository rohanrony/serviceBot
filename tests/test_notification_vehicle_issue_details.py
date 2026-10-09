import datetime as dt_mod
from unittest.mock import MagicMock, patch
import pytest

from serviceBot.services.sms_router import SMSNotificationRouter
from serviceBot.services.sms_reminders import (
    fetch_appointment_customer_details,
    run_reminder_polling_worker_cycle,
)


@pytest.fixture(autouse=True)
def mock_db_ctx():
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = []
    mock_cursor.fetchone.return_value = None
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

    with patch("serviceBot.db.connection.get_db_connection", return_value=mock_conn_ctx), \
         patch("serviceBot.db.connection.dict_cursor", return_value=mock_cursor_ctx), \
         patch("serviceBot.db.queries.get_db_connection", return_value=mock_conn_ctx), \
         patch("serviceBot.db.queries.dict_cursor", return_value=mock_cursor_ctx), \
         patch("serviceBot.api.portal.load_config", return_value=cfg):
        yield mock_cursor


@pytest.fixture
def mock_twilio():
    sent = []

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
            "sid": f"SM-mock-{len(sent)+1}",
        }
        sent.append(record)
        return {"success": True, "status": "SENT", "sid": record["sid"]}

    def mock_send_whatsapp(to, body, template_type, appointment_id=None, recipient_type=None):
        return mock_send_sms(to, body, template_type, appointment_id, recipient_type, channel="WHATSAPP")

    client = MagicMock()
    client.send_sms.side_effect = mock_send_sms
    client.send_whatsapp.side_effect = mock_send_whatsapp
    client.sent = sent
    return client


def test_customer_booking_notification_includes_vehicle_and_issue(mock_twilio):
    """
    US1 (T002): Customer booking message MUST include structured Vehicle and Issue lines.
    """
    router = SMSNotificationRouter()
    router.twilio_client = mock_twilio

    rules = [
        {"event_type": "BOOKING", "recipient_role": "customer", "channel": "SMS", "enabled": True},
        {"event_type": "BOOKING", "recipient_role": "agent", "channel": "SMS", "enabled": False},
        {"event_type": "BOOKING", "recipient_role": "admin", "channel": "SMS", "enabled": False},
    ]

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
         patch("serviceBot.services.sms_router.schedule_appointment_reminders"):

        router.process_event(
            event_type="BOOKING",
            appointment_id=101,
            customer_phone="+19195551234",
            booking_time="2026-10-25 14:00:00",
            details=details,
        )

    assert len(mock_twilio.sent) == 1
    msg = mock_twilio.sent[0]["body"]
    assert "Vehicle: 2021 Toyota Camry" in msg
    assert "Issue: Squeaking front brakes" in msg
    assert "Service: Brake Inspection" in msg


def test_customer_rescheduled_notification_includes_vehicle_and_issue(mock_twilio):
    """
    US1 (T003): Customer reschedule message MUST include Vehicle and Issue lines.
    """
    router = SMSNotificationRouter()
    router.twilio_client = mock_twilio

    rules = [
        {"event_type": "RESCHEDULED", "recipient_role": "customer", "channel": "SMS", "enabled": True},
        {"event_type": "RESCHEDULED", "recipient_role": "agent", "channel": "SMS", "enabled": False},
    ]

    details = {
        "customer_name": "Marcus Vance",
        "phone": "+19195551234",
        "vehicle": "2021 Toyota Camry",
        "service_type": "Brake Inspection",
        "time": "2026-10-26 10:00:00",
        "new_agent_name": "Tech Tom",
        "issue": "Squeaking front brakes",
    }

    with patch("serviceBot.services.sms_router.get_sms_matrix_rules", return_value=rules), \
         patch("serviceBot.services.sms_router.get_customer_opt_in", return_value=True), \
         patch("serviceBot.services.sms_router.is_in_quiet_hours", return_value=False), \
         patch("serviceBot.services.sms_router.should_bypass_quiet_hours", return_value=False), \
         patch("serviceBot.services.sms_router.log_sms_dispatch", return_value=1), \
         patch("serviceBot.services.sms_router.update_or_cancel_appointment_reminders"):

        router.process_event(
            event_type="RESCHEDULED",
            appointment_id=102,
            customer_phone="+19195551234",
            booking_time="2026-10-26 10:00:00",
            details=details,
        )

    assert len(mock_twilio.sent) == 1
    msg = mock_twilio.sent[0]["body"]
    assert "Vehicle: 2021 Toyota Camry" in msg
    assert "Issue: Squeaking front brakes" in msg


def test_customer_reminders_include_vehicle_and_issue(mock_twilio, mock_db_ctx):
    """
    US1 (T004): Customer reminder messages must include Vehicle and Issue.
    """
    due_reminder = {
        "id": 501,
        "appointment_id": 201,
        "recipient_type": "customer",
        "recipient_phone": "+19195551234",
        "reminder_type": "2h",
        "attempt_kind": "intermediate_followup",
        "retry_count": 0,
        "scheduled_at": dt_mod.datetime.now(),
        "status": "PENDING",
    }

    mock_details = {
        "customer_name": "Marcus Vance",
        "service_type": "Brake Inspection",
        "booking_time": "2026-10-25 14:00:00",
        "duration_minutes": 60,
        "vehicle": "2021 Toyota Camry",
        "agent_name": "Tech Tom",
        "issue": "Squeaking front brakes",
    }

    rules = [
        {"event_type": "REMINDER_2H", "recipient_role": "customer", "channel": "SMS", "enabled": True},
    ]

    mock_db_ctx.fetchall.side_effect = lambda: [due_reminder] if "sms_reminders" in str(mock_db_ctx.execute.call_args) else []

    with patch("serviceBot.services.sms_reminders.fetch_appointment_customer_details", return_value=mock_details), \
         patch("serviceBot.services.sms_reminders.get_customer_opt_in", return_value=True), \
         patch("serviceBot.services.sms_reminders.mark_sms_reminder_status"), \
         patch("serviceBot.services.sms_reminders.TwilioSMSClient", return_value=mock_twilio), \
         patch("serviceBot.db.queries.get_sms_matrix_rules", return_value=rules):

        run_reminder_polling_worker_cycle()

    assert len(mock_twilio.sent) == 1
    msg = mock_twilio.sent[0]["body"]
    assert "Vehicle: 2021 Toyota Camry" in msg
    assert "Issue: Squeaking front brakes" in msg


def test_agent_booking_alert_includes_vehicle_and_issue(mock_twilio):
    """
    US2 (T008): Agent booking alert must display Vehicle, Issue, and reply instructions.
    """
    router = SMSNotificationRouter()
    router.twilio_client = mock_twilio

    rules = [
        {"event_type": "BOOKING", "recipient_role": "agent", "channel": "SMS", "enabled": True},
    ]

    details = {
        "customer_name": "Marcus Vance",
        "phone": "+19195551234",
        "vehicle": "2021 Toyota Camry",
        "service_type": "Brake Inspection",
        "time": "2026-10-25 14:00:00",
        "issue": "Squeaking front brakes",
        "agent_name": "Tech Tom",
    }

    with patch("serviceBot.services.sms_router.get_sms_matrix_rules", return_value=rules), \
         patch("serviceBot.services.sms_router.log_sms_dispatch", return_value=1), \
         patch("serviceBot.services.sms_router.schedule_appointment_reminders"):

        router.process_event(
            event_type="BOOKING",
            appointment_id=103,
            agent_phone="+19195559999",
            booking_time="2026-10-25 14:00:00",
            details=details,
        )

    agent_sent = [m for m in mock_twilio.sent if m["recipient_type"] == "agent"]
    assert len(agent_sent) == 1
    msg = agent_sent[0]["body"]
    assert "Vehicle: 2021 Toyota Camry" in msg
    assert "Issue: Squeaking front brakes" in msg
    assert "Reply CONFIRM or C to accept, or DECLINE if unavailable." in msg


def test_agent_followup_reminder_full_multiline_block(mock_twilio, mock_db_ctx):
    """
    US2 (T009): Agent Attempt 2 reminder must display full multi-line alert block with Vehicle and Issue.
    """
    due_reminder = {
        "id": 601,
        "appointment_id": 301,
        "recipient_type": "agent",
        "recipient_phone": "+19195559999",
        "reminder_type": "2h",
        "attempt_kind": "intermediate_followup",
        "retry_count": 0,
        "scheduled_at": dt_mod.datetime.now(),
        "status": "PENDING",
    }

    mock_details = {
        "customer_name": "Marcus Vance",
        "customer_phone": "+19195551234",
        "service_type": "Brake Inspection",
        "booking_time": "2026-10-25 14:00:00",
        "duration_minutes": 60,
        "vehicle": "2021 Toyota Camry",
        "agent_name": "Tech Tom",
        "issue": "Squeaking front brakes",
    }

    rules = [
        {"event_type": "REMINDER_2H", "recipient_role": "agent", "channel": "SMS", "enabled": True},
    ]

    mock_db_ctx.fetchall.side_effect = lambda: [due_reminder] if "sms_reminders" in str(mock_db_ctx.execute.call_args) else []

    with patch("serviceBot.services.sms_reminders.fetch_appointment_customer_details", return_value=mock_details), \
         patch("serviceBot.services.sms_reminders.mark_sms_reminder_status"), \
         patch("serviceBot.services.sms_reminders.TwilioSMSClient", return_value=mock_twilio), \
         patch("serviceBot.db.queries.get_sms_matrix_rules", return_value=rules):

        run_reminder_polling_worker_cycle()

    assert len(mock_twilio.sent) == 1
    msg = mock_twilio.sent[0]["body"]
    assert "Vehicle: 2021 Toyota Camry" in msg
    assert "Issue: Squeaking front brakes" in msg
    assert "Appt #301" in msg
    assert "Reply CONFIRM or C to accept, or DECLINE" in msg


def test_agent_urgent_reminder_full_multiline_block(mock_twilio, mock_db_ctx):
    """
    US2 (T010): Agent Attempt 3 final urgent reminder must display full multi-line alert block with Vehicle and Issue.
    """
    due_reminder = {
        "id": 602,
        "appointment_id": 302,
        "recipient_type": "agent",
        "recipient_phone": "+19195559999",
        "reminder_type": "final",
        "attempt_kind": "final_reminder",
        "retry_count": 0,
        "scheduled_at": dt_mod.datetime.now(),
        "status": "PENDING",
    }

    mock_details = {
        "customer_name": "Marcus Vance",
        "customer_phone": "+19195551234",
        "service_type": "Brake Inspection",
        "booking_time": "2026-10-25 14:00:00",
        "duration_minutes": 60,
        "vehicle": "2021 Toyota Camry",
        "agent_name": "Tech Tom",
        "issue": "Squeaking front brakes",
    }

    rules = [
        {"event_type": "REMINDER_FINAL", "recipient_role": "agent", "channel": "SMS", "enabled": True},
    ]

    mock_db_ctx.fetchall.side_effect = lambda: [due_reminder] if "sms_reminders" in str(mock_db_ctx.execute.call_args) else []

    with patch("serviceBot.services.sms_reminders.fetch_appointment_customer_details", return_value=mock_details), \
         patch("serviceBot.services.sms_reminders.mark_sms_reminder_status"), \
         patch("serviceBot.services.sms_reminders.TwilioSMSClient", return_value=mock_twilio), \
         patch("serviceBot.db.queries.get_sms_matrix_rules", return_value=rules):

        run_reminder_polling_worker_cycle()

    assert len(mock_twilio.sent) == 1
    msg = mock_twilio.sent[0]["body"]
    assert "URGENT" in msg
    assert "Vehicle: 2021 Toyota Camry" in msg
    assert "Issue: Squeaking front brakes" in msg
    assert "Reply CONFIRM or C to accept, or DECLINE" in msg


def test_supervisor_escalation_alert_includes_vehicle_and_issue(mock_twilio, mock_db_ctx):
    """
    US2 (T011): Supervisor escalation alert must include Vehicle and Issue details.
    """
    due_reminder = {
        "id": 701,
        "appointment_id": 401,
        "recipient_type": "supervisor",
        "recipient_phone": "+19195550000",
        "reminder_type": "escalation",
        "attempt_kind": "supervisor_alert",
        "retry_count": 0,
        "scheduled_at": dt_mod.datetime.now(),
        "status": "PENDING",
    }

    mock_details = {
        "customer_name": "Marcus Vance",
        "customer_phone": "+19195551234",
        "service_type": "Brake Inspection",
        "booking_time": "2026-10-25 14:00:00",
        "duration_minutes": 60,
        "vehicle": "2021 Toyota Camry",
        "agent_name": "Tech Tom",
        "issue": "Squeaking front brakes",
    }

    mock_db_ctx.fetchall.side_effect = lambda: [due_reminder] if "sms_reminders" in str(mock_db_ctx.execute.call_args) else []

    with patch("serviceBot.services.sms_reminders.fetch_appointment_customer_details", return_value=mock_details), \
         patch("serviceBot.services.sms_reminders.mark_sms_reminder_status"), \
         patch("serviceBot.services.sms_reminders.TwilioSMSClient", return_value=mock_twilio):

        run_reminder_polling_worker_cycle()

    assert len(mock_twilio.sent) == 1
    msg = mock_twilio.sent[0]["body"]
    assert "ESCALATION ALERT" in msg
    assert "Vehicle: 2021 Toyota Camry" in msg
    assert "Issue: Squeaking front brakes" in msg


def test_partial_vehicle_and_empty_issue_fallbacks_cleanly(mock_twilio):
    """
    US3 (T014): Missing vehicle year or empty issue must not render 'None' or 'Issue: N/A'.
    """
    router = SMSNotificationRouter()
    router.twilio_client = mock_twilio

    rules = [
        {"event_type": "BOOKING", "recipient_role": "customer", "channel": "SMS", "enabled": True},
    ]

    details = {
        "customer_name": "Marcus Vance",
        "phone": "+19195551234",
        "vehicle": "Honda Civic",  # Missing year
        "service_type": "Oil Change",
        "time": "2026-10-25 14:00:00",
        "issue": "N/A",  # Empty / placeholder issue
    }

    with patch("serviceBot.services.sms_router.get_sms_matrix_rules", return_value=rules), \
         patch("serviceBot.services.sms_router.get_customer_opt_in", return_value=True), \
         patch("serviceBot.services.sms_router.is_in_quiet_hours", return_value=False), \
         patch("serviceBot.services.sms_router.should_bypass_quiet_hours", return_value=False), \
         patch("serviceBot.services.sms_router.log_sms_dispatch", return_value=1), \
         patch("serviceBot.services.sms_router.schedule_appointment_reminders"):

        router.process_event(
            event_type="BOOKING",
            appointment_id=105,
            customer_phone="+19195551234",
            booking_time="2026-10-25 14:00:00",
            details=details,
        )

    assert len(mock_twilio.sent) == 1
    msg = mock_twilio.sent[0]["body"]
    assert "Vehicle: Honda Civic" in msg
    assert "None" not in msg
    assert "Issue: N/A" not in msg


def test_router_enriches_missing_vehicle_and_generic_issue_from_database(mock_twilio, mock_db_ctx):
    """
    Reproduction test: If details is passed with missing vehicle or generic issue ('Repair'),
    router must enrich details from the database using appointment_id.
    """
    router = SMSNotificationRouter()
    router.twilio_client = mock_twilio

    rules = [
        {"event_type": "RESCHEDULED", "recipient_role": "customer", "channel": "SMS", "enabled": True},
        {"event_type": "RESCHEDULED", "recipient_role": "agent", "channel": "SMS", "enabled": True},
    ]

    db_row = {
        "id": 38,
        "service_type": "Repair",
        "issue_description": "Brake inspection",
        "booking_time": "2026-10-13 14:00:00",
        "time_slot": "2026-10-13 14:00:00",
        "duration_minutes": 60,
        "customer_name": "Rohan Roy",
        "customer_phone": "+14242704893",
        "vehicle_year": 2014,
        "vehicle_make": "Ford",
        "vehicle_model": "Model T",
        "agent_id": 8,
        "agent_name": "Mathew Tan",
        "agent_phone": "+14242704893",
    }
    mock_db_ctx.fetchone.return_value = db_row

    # Incomplete details payload like outbox_worker provides:
    incomplete_details = {
        "customer_name": "Rohan Roy",
        "phone": "+14242704893",
        "service_type": "Repair",
        "issue": "Repair",  # Generic / identical to service_type
        "duration_minutes": 60,
        "agent_name": "Mathew Tan",
        "new_agent_name": "Mathew Tan",
        "time": "2026-10-13 14:00:00",
        # 'vehicle' key omitted completely!
    }

    with patch("serviceBot.services.sms_router.get_sms_matrix_rules", return_value=rules), \
         patch("serviceBot.services.sms_router.get_customer_opt_in", return_value=True), \
         patch("serviceBot.services.sms_router.is_in_quiet_hours", return_value=False), \
         patch("serviceBot.services.sms_router.should_bypass_quiet_hours", return_value=False), \
         patch("serviceBot.services.sms_router.log_sms_dispatch", return_value=1), \
         patch("serviceBot.services.sms_router.update_or_cancel_appointment_reminders"):

        router.process_event(
            event_type="RESCHEDULED",
            appointment_id=38,
            customer_phone="+14242704893",
            agent_phone="+14242704893",
            booking_time="2026-10-13 14:00:00",
            details=incomplete_details,
        )

    assert len(mock_twilio.sent) >= 1
    cust_msg = next(m for m in mock_twilio.sent if m["recipient_type"] == "customer")["body"]
    agent_msg = next(m for m in mock_twilio.sent if m["recipient_type"] == "agent")["body"]

    assert "Vehicle: 2014 Ford Model T" in cust_msg
    assert "Issue: Brake inspection" in cust_msg

    assert "Vehicle: 2014 Ford Model T" in agent_msg
    assert "Issue: Brake inspection" in agent_msg


def test_booking_service_enqueues_vehicle_and_actual_issue_in_outbox():
    """
    Verify BookingService._enqueue_projection_events includes vehicle and actual
    issue_description in outbox_notifications payload details instead of hardcoding service_type.
    """
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = {
        "name": "Mathew Tan",
        "phone_number": "+14242704893",
        "email": "mathew@example.com",
    }
    customer = {"name": "Rohan Roy", "phone": "+14242704893"}
    starts_at = dt_mod.datetime(2026, 10, 13, 14, 0, 0)

    import json
    from serviceBot.services.booking import BookingService
    BookingService._enqueue_projection_events(
        mock_cursor,
        request_id=38,
        reservation_id=19,
        staff_agent_id=8,
        old_staff_agent_id=None,
        old_starts_at=None,
        booking_type="appointment",
        starts_at=starts_at,
        duration_minutes=60,
        customer=customer,
        service_type="Repair",
        vehicle_str="2014 Ford Model T",
        issue_description="Brake inspection",
    )

    outbox_calls = [
        call for call in mock_cursor.execute.call_args_list
        if "INSERT INTO outbox_notifications" in str(call[0][0])
    ]
    assert len(outbox_calls) == 2  # calendar_projection and booking_notification
    for call in outbox_calls:
        payload = json.loads(call[0][1][2])
        assert payload["details"]["vehicle"] == "2014 Ford Model T"
        assert payload["details"]["issue"] == "Brake inspection"


