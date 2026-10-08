import pytest
from unittest.mock import MagicMock, patch
from serviceBot.services.sms_router import SMSNotificationRouter


def test_process_event_does_not_send_duplicate_when_both_sms_and_whatsapp_rules_enabled():
    """
    Regression test: When both SMS and WHATSAPP are enabled in sms_matrix_rules
    for an event and recipient role, process_event must dispatch EXACTLY ONE
    message to that recipient, never blasting both channels simultaneously.
    """
    router = SMSNotificationRouter()
    mock_client = MagicMock()
    sent_dispatches = []

    def mock_send_sms(to, body, template_type, appointment_id=None, recipient_type=None, channel="SMS", dispatch_log_id=None):
        sent_dispatches.append({"channel": channel, "recipient": recipient_type, "body": body})
        return {"success": True, "status": "SENT", "sid": f"SM-mock-{len(sent_dispatches)}"}

    def mock_send_whatsapp(to, body, template_type, appointment_id=None, recipient_type=None, dispatch_log_id=None):
        return mock_send_sms(to, body, template_type, appointment_id, recipient_type, channel="WHATSAPP")

    mock_client.send_sms.side_effect = mock_send_sms
    mock_client.send_whatsapp.side_effect = mock_send_whatsapp
    router.twilio_client = mock_client

    # In the production database, both SMS and WHATSAPP are enabled
    rules = [
        {"event_type": "BOOKING", "recipient_role": "customer", "channel": "SMS", "enabled": True},
        {"event_type": "BOOKING", "recipient_role": "customer", "channel": "WHATSAPP", "enabled": True},
        {"event_type": "BOOKING", "recipient_role": "agent", "channel": "SMS", "enabled": True},
        {"event_type": "BOOKING", "recipient_role": "agent", "channel": "WHATSAPP", "enabled": True},
        {"event_type": "BOOKING", "recipient_role": "admin", "channel": "WHATSAPP", "enabled": False},
    ]

    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = []
    mock_cursor_ctx = MagicMock()
    mock_cursor_ctx.__enter__.return_value = mock_cursor
    mock_conn = MagicMock()
    mock_conn_ctx = MagicMock()
    mock_conn_ctx.__enter__.return_value = mock_conn

    details = {
        "customer_name": "Rohan Roy",
        "phone": "+14242704893",
        "vehicle": "2020 Honda Civic",
        "service_type": "Oil Change",
        "time": "2026-10-25 10:00:00",
        "duration_minutes": 60,
        "new_agent_name": "John Doe",
        "agent_name": "John Doe",
        "agent_phone": "+15559998888",
    }

    with patch("serviceBot.services.sms_router.get_sms_matrix_rules", return_value=rules), \
         patch("serviceBot.services.sms_router.get_customer_opt_in", return_value=True), \
         patch("serviceBot.services.sms_router.is_in_quiet_hours", return_value=False), \
         patch("serviceBot.services.sms_router.should_bypass_quiet_hours", return_value=False), \
         patch("serviceBot.services.sms_router.schedule_appointment_reminders"), \
         patch("serviceBot.services.sms_router.log_sms_dispatch", return_value=1), \
         patch("serviceBot.db.connection.get_db_connection", return_value=mock_conn_ctx), \
         patch("serviceBot.db.connection.dict_cursor", return_value=mock_cursor_ctx), \
         patch("serviceBot.db.queries.get_sms_config", return_value={}), \
         patch("serviceBot.db.queries.get_or_create_sms_conversation", return_value={"id": 1}), \
         patch("serviceBot.db.queries.add_sms_message", return_value=1):

        result = router.process_event(
            event_type="BOOKING",
            appointment_id=42,
            customer_phone="+14242704893",
            agent_phone="+15559998888",
            booking_time="2026-10-25 10:00:00",
            details=details,
        )

    customer_dispatches = [d for d in sent_dispatches if d["recipient"] == "customer"]
    agent_dispatches = [d for d in sent_dispatches if d["recipient"] == "agent"]

    assert len(customer_dispatches) == 1, (
        f"Expected exactly 1 customer dispatch, got {len(customer_dispatches)}: {customer_dispatches}"
    )
    assert len(agent_dispatches) == 1, (
        f"Expected exactly 1 agent dispatch, got {len(agent_dispatches)}: {agent_dispatches}"
    )


def test_enabled_channels_returns_single_channel_when_both_configured():
    """
    Verify that _enabled_channels selects a single preferred channel (not both)
    when both SMS and WHATSAPP are active in matrix rules.
    """
    router = SMSNotificationRouter()
    both_rules = [
        {"event_type": "BOOKING", "recipient_role": "customer", "channel": "SMS", "enabled": True},
        {"event_type": "BOOKING", "recipient_role": "customer", "channel": "WHATSAPP", "enabled": True},
    ]

    channels = router._enabled_channels("BOOKING", "customer", both_rules)
    assert len(channels) == 1, f"Expected exactly 1 channel, got {channels}"
    assert channels[0] in ("WHATSAPP", "SMS")


def test_enabled_channels_fallback_returns_single_channel_when_empty_rules():
    """
    Verify that _enabled_channels returns a single fallback channel when rules table is empty.
    """
    router = SMSNotificationRouter()
    channels = router._enabled_channels("BOOKING", "customer", [])
    assert len(channels) == 1, f"Expected fallback of 1 channel, got {channels}"
