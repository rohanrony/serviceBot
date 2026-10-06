import pytest
from unittest.mock import patch, MagicMock
from serviceBot.services.gmail import send_admin_notification
from serviceBot.services.sms_reminders import dispatch_supervisor_escalation_alert
from serviceBot.services.outbox_worker import _dispatch_outbox_event

@patch("serviceBot.services.gmail.send_gmail_api_email")
@patch("serviceBot.services.gmail.load_config")
def test_send_admin_notification_escalation(mock_load, mock_send_api):
    """Verify send_admin_notification properly formats SLA escalation alerts."""
    mock_load.return_value = {
        "gmail_enabled": True,
        "gmail_sender": "sender@davidsoncarcare.com",
        "gmail_recipient": "admin@davidsoncarcare.com",
        "gmail_auth_type": "oauth2"
    }
    mock_send_api.return_value = True

    details = {
        "appointment_id": 401,
        "customer_name": "Jane Doe",
        "phone": "+19195551234",
        "vehicle": "2022 Honda Civic",
        "service_type": "Brake Service",
        "time": "Oct 5 at 10:00 AM",
        "issue": "Squeaking sound when braking",
        "escalation_reason": "TIMEOUT_NO_RESPONSE",
    }

    result = send_admin_notification(
        booking_type="escalation",
        details=details,
        agent_name="Bob Technician",
        agent_email="bob@davidsoncarcare.com"
    )

    assert result is True
    assert mock_send_api.called
    _, kwargs = mock_send_api.call_args

    assert kwargs.get("recipient") == "admin@davidsoncarcare.com"
    subject = kwargs.get("subject", "")
    assert "[URGENT Admin Copy]" in subject
    assert "SLA Escalation" in subject
    assert "Appt #401" in subject
    assert "TIMEOUT_NO_RESPONSE" in subject

    html_body = kwargs.get("html_body", "")
    assert "Admin Alert: SLA Escalation Required" in html_body
    assert "#dc2626" in html_body  # Red alert banner color
    assert "TIMEOUT_NO_RESPONSE" in html_body
    assert "Jane Doe" in html_body
    assert "2022 Honda Civic" in html_body
    assert "Bob Technician" in html_body
    assert "/portal/reassign/401" in html_body

    plain_body = kwargs.get("plain_body", "")
    assert "TIMEOUT_NO_RESPONSE" in plain_body
    assert "/portal/reassign/401" in plain_body


@patch("serviceBot.services.sms_reminders.TwilioSMSClient")
@patch("serviceBot.services.gmail.send_admin_notification")
@patch("serviceBot.db.connection.dict_cursor")
@patch("serviceBot.db.connection.get_db_connection")
@patch("serviceBot.api.portal.load_config")
def test_dispatch_supervisor_escalation_alert_sends_email_and_sms(
    mock_load_cfg, mock_get_conn, mock_dict_cursor, mock_send_admin_email, mock_twilio_cls
):
    """Verify dispatch_supervisor_escalation_alert dispatches both SMS and admin email."""
    mock_load_cfg.return_value = {
        "supervisor_alert_phone": "+19195550999"
    }

    # Mock DB cursor
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_get_conn.return_value.__enter__.return_value = mock_conn
    mock_dict_cursor.return_value.__enter__.return_value = mock_cursor

    mock_row = {
        "id": 402,
        "status": "pending",
        "staff_agent_id": 12,
        "service_type": "Oil Change",
        "issue_description": "Engine oil service",
        "booking_time": "2026-10-06 09:00:00",
        "customer_name": "Marcus Aurelius",
        "customer_phone": "+19195557788",
        "agent_name": "Lucius Mechanic",
        "agent_email": "lucius@davidsoncarcare.com",
        "vehicle_year": 2021,
        "vehicle_make": "Toyota",
        "vehicle_model": "Camry",
        "starts_at": None,
    }
    mock_cursor.fetchone.return_value = mock_row

    # Mock Twilio
    mock_twilio_inst = MagicMock()
    mock_twilio_cls.return_value = mock_twilio_inst
    mock_twilio_inst.send_sms.return_value = {"status": "SENT", "sid": "SM12345"}

    # Mock admin email
    mock_send_admin_email.return_value = True

    res = dispatch_supervisor_escalation_alert(402, reason="TIMEOUT_NO_RESPONSE")

    assert res["success"] is True
    assert res.get("email_sent") is True
    assert mock_twilio_inst.send_sms.called
    assert mock_send_admin_email.called

    email_args, email_kwargs = mock_send_admin_email.call_args
    assert email_kwargs.get("booking_type") == "escalation"
    assert email_kwargs.get("agent_name") == "Lucius Mechanic"
    assert email_kwargs.get("agent_email") == "lucius@davidsoncarcare.com"

    details = email_kwargs.get("details", {})
    assert details.get("appointment_id") == 402
    assert details.get("customer_name") == "Marcus Aurelius"
    assert details.get("vehicle") == "2021 Toyota Camry"
    assert details.get("escalation_reason") == "TIMEOUT_NO_RESPONSE"


@patch("serviceBot.services.sms_reminders.TwilioSMSClient")
@patch("serviceBot.services.gmail.send_admin_notification")
@patch("serviceBot.db.connection.dict_cursor")
@patch("serviceBot.db.connection.get_db_connection")
@patch("serviceBot.api.portal.load_config")
def test_dispatch_supervisor_escalation_alert_email_failure_does_not_block_sms(
    mock_load_cfg, mock_get_conn, mock_dict_cursor, mock_send_admin_email, mock_twilio_cls
):
    """Verify that email dispatch failure logs a warning and does not prevent SMS dispatch."""
    mock_load_cfg.return_value = {
        "supervisor_alert_phone": "+19195550999"
    }

    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_get_conn.return_value.__enter__.return_value = mock_conn
    mock_dict_cursor.return_value.__enter__.return_value = mock_cursor

    mock_row = {
        "id": 403,
        "status": "pending",
        "staff_agent_id": 15,
        "customer_name": "Seneca",
        "customer_phone": "+19195559900",
        "agent_name": "Titus",
        "agent_email": "titus@example.com",
    }
    mock_cursor.fetchone.return_value = mock_row

    mock_twilio_inst = MagicMock()
    mock_twilio_cls.return_value = mock_twilio_inst
    mock_twilio_inst.send_sms.return_value = {"status": "SENT", "sid": "SM99999"}

    # Simulate email throwing an exception
    mock_send_admin_email.side_effect = RuntimeError("SMTP connection timeout")

    res = dispatch_supervisor_escalation_alert(403, reason="AGENT_DECLINED")

    # SMS should still succeed
    assert res["success"] is True
    assert res.get("email_sent") is False
    assert mock_twilio_inst.send_sms.called


@patch("serviceBot.services.sms_reminders.dispatch_supervisor_escalation_alert")
def test_outbox_worker_processes_escalation_event(mock_dispatch_alert):
    """Verify that outbox worker can process escalation_alert events."""
    payload = {"reason": "TIMEOUT_NO_RESPONSE"}
    _dispatch_outbox_event("escalation_alert", 405, payload)

    assert mock_dispatch_alert.called
    args, kwargs = mock_dispatch_alert.call_args
    assert args[0] == 405
    assert kwargs.get("reason") == "TIMEOUT_NO_RESPONSE"


@patch("serviceBot.services.gmail.send_gmail_via_api")
@patch("serviceBot.db.connection.get_db_connection")
@patch("serviceBot.db.connection.dict_cursor")
@patch("serviceBot.services.gmail.load_config")
def test_send_admin_notification_fallback_to_user_google_accounts(mock_load_cfg, mock_dict_cur, mock_get_conn, mock_send_via_api):
    """Verify that when system SMTP password is missing, send_admin_notification falls back to connected Google account."""
    mock_load_cfg.return_value = {
        "gmail_enabled": True,
        "gmail_sender": "rohanrony@gmail.com",
        "gmail_recipient": "rohan.roy@edvenswainc.com",
        "gmail_auth_type": "app_password",
        "gmail_password": "",  # Empty password triggers fallback
    }

    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_get_conn.return_value.__enter__.return_value = mock_conn
    mock_dict_cur.return_value.__enter__.return_value = mock_cursor
    mock_cursor.fetchone.return_value = {
        "agent_id": 8,
        "email": "rohanrony@gmail.com",
        "granted_scopes": "https://www.googleapis.com/auth/gmail.send openid"
    }
    mock_send_via_api.return_value = True

    details = {
        "appointment_id": 32,
        "customer_name": "Rohan Roy",
        "escalation_reason": "TIMEOUT_NO_RESPONSE"
    }

    res = send_admin_notification(
        booking_type="escalation",
        details=details,
        agent_name="Jane Smith",
        agent_email="jane.smith@example.com"
    )

    assert res is True
    assert mock_send_via_api.called
    _, kwargs = mock_send_via_api.call_args
    assert kwargs["agent_id"] == 8
    assert kwargs["recipient"] == "rohan.roy@edvenswainc.com"


@patch("serviceBot.services.sms_reminders.TwilioSMSClient")
@patch("serviceBot.services.gmail.send_admin_notification")
@patch("serviceBot.db.connection.dict_cursor")
@patch("serviceBot.db.connection.get_db_connection")
@patch("serviceBot.api.portal.load_config")
@patch("serviceBot.db.queries.get_sms_config")
@patch("serviceBot.db.queries.get_sms_matrix_rules")
def test_dispatch_escalation_alert_uses_admin_phone_from_sms_config(
    mock_matrix_rules, mock_sms_cfg, mock_load_cfg, mock_get_conn, mock_dict_cursor, mock_send_admin_email, mock_twilio_cls
):
    """Verify that dispatch_supervisor_escalation_alert prioritizes admin_phone_number given by admin."""
    mock_load_cfg.return_value = {"supervisor_alert_phone": ""}
    mock_sms_cfg.return_value = {"admin_phone_number": "+14242704893"}
    mock_matrix_rules.return_value = [
        {"event_type": "ESCALATION", "recipient_role": "admin", "channel": "SMS", "enabled": True},
        {"event_type": "ESCALATION", "recipient_role": "admin", "channel": "EMAIL", "enabled": True},
    ]

    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_get_conn.return_value.__enter__.return_value = mock_conn
    mock_dict_cursor.return_value.__enter__.return_value = mock_cursor

    mock_row = {
        "id": 501,
        "status": "pending",
        "staff_agent_id": 10,
        "customer_name": "Test Customer",
        "agent_name": "Test Agent",
        "agent_email": "agent@test.com"
    }
    mock_cursor.fetchone.return_value = mock_row

    mock_twilio_inst = MagicMock()
    mock_twilio_cls.return_value = mock_twilio_inst
    mock_twilio_inst.send_sms.return_value = {"status": "SENT", "sid": "SM_ADMIN_01"}
    mock_send_admin_email.return_value = True

    res = dispatch_supervisor_escalation_alert(501, reason="AGENT_DECLINED")

    assert res["success"] is True
    assert res["admin_phone"] == "+14242704893"
    assert res["email_sent"] is True
    assert res["message_sent"] is True
    assert mock_twilio_inst.send_sms.called
    sms_call_kwargs = mock_twilio_inst.send_sms.call_args[1]
    assert sms_call_kwargs["to"] == "+14242704893"
    assert sms_call_kwargs["recipient_type"] == "admin"


@patch("serviceBot.services.sms_reminders.TwilioSMSClient")
@patch("serviceBot.services.gmail.send_admin_notification")
@patch("serviceBot.db.connection.dict_cursor")
@patch("serviceBot.db.connection.get_db_connection")
@patch("serviceBot.api.portal.load_config")
@patch("serviceBot.db.queries.get_sms_config")
def test_dispatch_escalation_alert_does_not_default_to_hardcoded_fake_number(
    mock_sms_cfg, mock_load_cfg, mock_get_conn, mock_dict_cursor, mock_send_admin_email, mock_twilio_cls
):
    """Verify that when no admin phone is configured, it does NOT send to +19195550199."""
    mock_load_cfg.return_value = {}  # No supervisor_alert_phone or admin_phone
    mock_sms_cfg.return_value = {}

    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_get_conn.return_value.__enter__.return_value = mock_conn
    mock_dict_cursor.return_value.__enter__.return_value = mock_cursor

    mock_row = {
        "id": 502,
        "status": "pending",
        "staff_agent_id": 10,
        "customer_name": "No Phone Admin Appt",
        "agent_name": "Test Agent",
        "agent_email": "agent@test.com"
    }
    mock_cursor.fetchone.return_value = mock_row

    mock_twilio_inst = MagicMock()
    mock_twilio_cls.return_value = mock_twilio_inst
    mock_send_admin_email.return_value = True

    res = dispatch_supervisor_escalation_alert(502, reason="AGENT_DECLINED")

    # Twilio send_sms should NOT be called with fake +19195550199
    assert not mock_twilio_inst.send_sms.called
    assert not mock_twilio_inst.send_whatsapp.called
    assert res["admin_phone"] is None
    assert res["message_sent"] is False
    # Email should still be sent
    assert res["email_sent"] is True
    assert res["success"] is True


@patch("serviceBot.services.sms_reminders.TwilioSMSClient")
@patch("serviceBot.services.gmail.send_admin_notification")
@patch("serviceBot.db.connection.dict_cursor")
@patch("serviceBot.db.connection.get_db_connection")
@patch("serviceBot.api.portal.load_config")
@patch("serviceBot.db.queries.get_sms_config")
@patch("serviceBot.db.queries.get_sms_matrix_rules")
def test_dispatch_escalation_alert_with_matrix_whatsapp_channel(
    mock_matrix_rules, mock_sms_cfg, mock_load_cfg, mock_get_conn, mock_dict_cursor, mock_send_admin_email, mock_twilio_cls
):
    """Verify that when WhatsApp is configured in matrix for ESCALATION admin, WhatsApp message is dispatched."""
    mock_load_cfg.return_value = {"admin_phone_number": "+14242704893"}
    mock_sms_cfg.return_value = {}
    mock_matrix_rules.return_value = [
        {"event_type": "ESCALATION", "recipient_role": "admin", "channel": "SMS", "enabled": False},
        {"event_type": "ESCALATION", "recipient_role": "admin", "channel": "WHATSAPP", "enabled": True},
        {"event_type": "ESCALATION", "recipient_role": "admin", "channel": "EMAIL", "enabled": True},
    ]

    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_get_conn.return_value.__enter__.return_value = mock_conn
    mock_dict_cursor.return_value.__enter__.return_value = mock_cursor

    mock_row = {
        "id": 503,
        "status": "pending",
        "staff_agent_id": 10,
        "customer_name": "WhatsApp Esc Appt",
        "agent_name": "Tech 1",
        "agent_email": "tech@test.com"
    }
    mock_cursor.fetchone.return_value = mock_row

    mock_twilio_inst = MagicMock()
    mock_twilio_cls.return_value = mock_twilio_inst
    mock_twilio_inst.send_whatsapp.return_value = {"status": "SENT", "sid": "WA_ADMIN_01"}
    mock_send_admin_email.return_value = True

    res = dispatch_supervisor_escalation_alert(503, reason="TIMEOUT_NO_RESPONSE")

    assert res["success"] is True
    assert not mock_twilio_inst.send_sms.called
    assert mock_twilio_inst.send_whatsapp.called
    wa_kwargs = mock_twilio_inst.send_whatsapp.call_args[1]
    assert wa_kwargs["to"] == "+14242704893"
    assert wa_kwargs["recipient_type"] == "admin"
    assert "WHATSAPP" in res["channels"]
    assert "EMAIL" in res["channels"]

