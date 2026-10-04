import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from serviceBot.services.sms_reminders import (
    format_time_slot_range,
    get_shop_address_and_map_url,
    fetch_appointment_customer_details,
    run_reminder_polling_worker_cycle,
)
from serviceBot.services.sms_router import SMSNotificationRouter
from serviceBot.main import app


def test_format_time_slot_range():
    res = format_time_slot_range("2026-10-15 14:00:00", 60)
    assert res == "Oct 15, 2026 (2:00 PM - 3:00 PM)"

    # N/A handling
    assert format_time_slot_range("N/A") == "N/A"
    assert format_time_slot_range(None) == "N/A"


def test_get_shop_address_and_map_url_auto_generation():
    cfg_with_custom_url = {
        "business_address": "123 Main St, Springfield, NC 27513",
        "google_maps_url": "https://maps.app.goo.gl/custom123"
    }
    addr, map_url = get_shop_address_and_map_url(cfg_with_custom_url)
    assert addr == "123 Main St, Springfield, NC 27513"
    assert map_url == "https://maps.app.goo.gl/custom123"

    cfg_without_custom_url = {
        "business_address": "456 Oak Ave, Raleigh, NC 27601",
        "google_maps_url": ""
    }
    addr2, map_url2 = get_shop_address_and_map_url(cfg_without_custom_url)
    assert addr2 == "456 Oak Ave, Raleigh, NC 27601"
    assert "https://maps.google.com/?q=" in map_url2
    assert "456+Oak+Ave" in map_url2


def test_fetch_appointment_customer_details():
    mock_row = {
        "id": 42,
        "service_type": "Brake Inspection",
        "issue_description": "Grinding noise",
        "booking_time": "2026-10-20 10:00:00",
        "time_slot": "2026-10-20 10:00:00",
        "duration_minutes": 90,
        "customer_name": "Sarah Connor",
        "customer_phone": "+19195551234",
        "vehicle_year": "2021",
        "vehicle_make": "Toyota",
        "vehicle_model": "Camry",
        "agent_id": 5,
        "agent_name": "Tech Tom",
    }

    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = mock_row
    mock_cursor_context = MagicMock()
    mock_cursor_context.__enter__.return_value = mock_cursor
    mock_conn = MagicMock()
    mock_conn_context = MagicMock()
    mock_conn_context.__enter__.return_value = mock_conn

    with patch("serviceBot.db.connection.get_db_connection", return_value=mock_conn_context), \
         patch("serviceBot.db.connection.dict_cursor", return_value=mock_cursor_context):
        details = fetch_appointment_customer_details(42)

    assert details["customer_name"] == "Sarah Connor"
    assert details["service_type"] == "Brake Inspection"
    assert details["booking_time"] == "2026-10-20 10:00:00"
    assert details["duration_minutes"] == 90
    assert details["vehicle"] == "2021 Toyota Camry"
    assert details["agent_name"] == "Tech Tom"


def test_customer_reminder_messages_omit_appointment_number_and_include_details():
    mock_details = {
        "customer_name": "Sarah Connor",
        "service_type": "Full Synthetic Oil Change",
        "booking_time": "2026-10-20 14:00:00",
        "duration_minutes": 60,
        "vehicle": "2021 Toyota Camry",
        "agent_name": "Tech Tom",
    }

    due_reminders = [
        {
            "id": 101,
            "appointment_id": 42,
            "recipient_type": "customer",
            "recipient_phone": "+19195551234",
            "reminder_type": "immediate",
            "attempt_kind": "immediate_booking",
            "retry_count": 0,
        },
        {
            "id": 102,
            "appointment_id": 42,
            "recipient_type": "customer",
            "recipient_phone": "+19195551234",
            "reminder_type": "24h",
            "attempt_kind": "intermediate_followup",
            "retry_count": 0,
        },
        {
            "id": 103,
            "appointment_id": 42,
            "recipient_type": "customer",
            "recipient_phone": "+19195551234",
            "reminder_type": "2h",
            "attempt_kind": "final_reminder",
            "retry_count": 0,
        },
        {
            "id": 104,
            "appointment_id": 42,
            "recipient_type": "agent",
            "recipient_phone": "+19195559999",
            "reminder_type": "immediate",
            "attempt_kind": "immediate_booking",
            "retry_count": 0,
        },
    ]

    sent_messages = []

    def mock_send_sms(to, body, template_type, appointment_id, recipient_type):
        sent_messages.append({
            "to": to,
            "body": body,
            "template_type": template_type,
            "appointment_id": appointment_id,
            "recipient_type": recipient_type,
        })
        return {"success": True, "status": "DELIVERED"}

    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = due_reminders
    mock_cursor_context = MagicMock()
    mock_cursor_context.__enter__.return_value = mock_cursor
    mock_conn = MagicMock()
    mock_conn_context = MagicMock()
    mock_conn_context.__enter__.return_value = mock_conn

    cfg = {
        "business_address": "123 Main St, Springfield, NC 27513",
        "google_maps_url": "https://maps.app.goo.gl/davidson-car-care",
        "max_dispatch_retries": 3,
        "retry_backoff_minutes": [1, 5, 15]
    }

    with patch("serviceBot.db.connection.get_db_connection", return_value=mock_conn_context), \
         patch("serviceBot.db.connection.dict_cursor", return_value=mock_cursor_context), \
         patch("serviceBot.api.portal.load_config", return_value=cfg), \
         patch("serviceBot.services.sms_reminders.get_customer_opt_in", return_value=True), \
         patch("serviceBot.services.sms_reminders.fetch_appointment_customer_details", return_value=mock_details), \
         patch("serviceBot.db.queries.get_sms_matrix_rules", return_value=[]), \
         patch("serviceBot.db.queries.get_or_create_sms_conversation", return_value={"id": 1}), \
         patch("serviceBot.db.queries.add_sms_message", return_value=1), \
         patch("serviceBot.services.twilio_sms.TwilioSMSClient.send_whatsapp", side_effect=mock_send_sms), \
         patch("serviceBot.services.twilio_sms.TwilioSMSClient.send_sms", side_effect=mock_send_sms):
        run_reminder_polling_worker_cycle()

    assert len(sent_messages) == 4

    # 1. Customer Immediate Booking
    cust_imm = next(m for m in sent_messages if m["recipient_type"] == "customer" and m["template_type"] == "reminder_immediate")
    imm_body = cust_imm["body"]
    assert "🚗 [APPOINTMENT CONFIRMED]" in imm_body
    assert "Hi Sarah Connor, your appointment is scheduled!" in imm_body
    assert "🔧 Service: Full Synthetic Oil Change" in imm_body
    assert "📅 When: Oct 20, 2026 (2:00 PM - 3:00 PM)" in imm_body
    assert "🚘 Vehicle: 2021 Toyota Camry" in imm_body
    assert "👤 Advisor: Tech Tom" in imm_body
    assert "📍 Location: 123 Main St, Springfield, NC 27513" in imm_body
    assert "🗺️ Map: https://maps.app.goo.gl/davidson-car-care" in imm_body
    assert "Reply STOP to opt out." in imm_body
    # Verify appointment ID is completely absent from customer message
    assert "Appointment #42" not in imm_body
    assert "Appt #42" not in imm_body
    assert "#42" not in imm_body

    # 2. Customer 24h Followup Reminder
    cust_24h = next(m for m in sent_messages if m["recipient_type"] == "customer" and m["template_type"] == "reminder_24h")
    fup_body = cust_24h["body"]
    assert "🗓️ [APPOINTMENT REMINDER]" in fup_body
    assert "Hi Sarah Connor, reminding you of your upcoming appointment:" in fup_body
    assert "🔧 Service: Full Synthetic Oil Change" in fup_body
    assert "📍 Location: 123 Main St, Springfield, NC 27513" in fup_body
    assert "🗺️ Map: https://maps.app.goo.gl/davidson-car-care" in fup_body
    assert "Please let us know if you need to reschedule." in fup_body
    assert "Appointment #42" not in fup_body
    assert "#42" not in fup_body

    # 3. Customer 2h Pre-Visit Reminder
    cust_2h = next(m for m in sent_messages if m["recipient_type"] == "customer" and m["template_type"] == "reminder_2h")
    pre_body = cust_2h["body"]
    assert "⏰ [UPCOMING APPOINTMENT]" in pre_body
    assert "Hi Sarah Connor, your appointment is coming up in 2h!" in pre_body
    assert "🔧 Service: Full Synthetic Oil Change" in pre_body
    assert "📍 Location: 123 Main St, Springfield, NC 27513" in pre_body
    assert "🗺️ Map: https://maps.app.goo.gl/davidson-car-care" in pre_body
    assert "We look forward to seeing you!" in pre_body
    assert "Appointment #42" not in pre_body
    assert "#42" not in pre_body

    # 4. Agent Immediate Booking DOES retain internal ID
    agent_imm = next(m for m in sent_messages if m["recipient_type"] == "agent")
    assert "Service request #42" in agent_imm["body"]


def test_sms_router_customer_messages_omit_appointment_number_and_include_map():
    router = SMSNotificationRouter()
    mock_client = MagicMock()
    mock_client.send_whatsapp.return_value = {"success": True, "status": "SENT", "sid": "WA-123"}
    router.twilio_client = mock_client

    rules = [
        {"event_type": "RESCHEDULED", "recipient_role": "customer", "channel": "WHATSAPP", "enabled": True},
        {"event_type": "RESCHEDULED", "recipient_role": "agent", "channel": "WHATSAPP", "enabled": True},
    ]

    details = {
        "customer_name": "Sarah Connor",
        "service_type": "Tire Rotation",
        "vehicle": "2021 Toyota Camry",
        "time": "2026-10-25 15:00:00",
        "duration_minutes": 60,
        "new_agent_name": "Tech Tom",
        "issue": "Routine rotation",
    }

    with patch("serviceBot.services.sms_router.get_sms_matrix_rules", return_value=rules), \
         patch("serviceBot.services.sms_router.get_customer_opt_in", return_value=True), \
         patch("serviceBot.services.sms_router.should_bypass_quiet_hours", return_value=False), \
         patch("serviceBot.services.sms_router.is_in_quiet_hours", return_value=False), \
         patch("serviceBot.services.sms_router.log_sms_dispatch", return_value=1), \
         patch("serviceBot.db.queries.get_sms_config", return_value={}), \
         patch("serviceBot.db.queries.get_or_create_sms_conversation", return_value={"id": 1}), \
         patch("serviceBot.db.queries.add_sms_message", return_value=1), \
         patch("serviceBot.services.sms_router.update_or_cancel_appointment_reminders"):
        res = router.process_event(
            event_type="RESCHEDULED",
            appointment_id=77,
            customer_phone="+19195551234",
            agent_phone="+19195559999",
            booking_time="2026-10-25 15:00:00",
            details=details,
        )

    customer_calls = [call for call in mock_client.send_whatsapp.call_args_list if call.kwargs.get("recipient_type") == "customer"]
    assert len(customer_calls) >= 1
    cust_body = customer_calls[0].kwargs["body"]
    assert "🗓️ [APPOINTMENT RESCHEDULED]" in cust_body
    assert "Appt #77" not in cust_body
    assert "#77" not in cust_body
    assert "Location: 123 Main St" in cust_body
    assert "Map: https://maps.google.com/?q=" in cust_body

    agent_calls = [call for call in mock_client.send_whatsapp.call_args_list if call.kwargs.get("recipient_type") == "agent"]
    assert len(agent_calls) >= 1
    agent_body = agent_calls[0].kwargs["body"]
    assert "Appt #77" in agent_body


def test_portal_config_endpoints_support_address_and_maps(tmp_path):
    scratch_cfg = tmp_path / "test_config.json"
    scratch_cfg.write_text('{"business_address": "Old Address"}')
    scratch_prompt = tmp_path / "test_prompt.txt"
    scratch_prompt.write_text("Test prompt")

    with patch("serviceBot.api.portal.CONFIG_PATH", str(scratch_cfg)), \
         patch("serviceBot.api.portal.SYSTEM_PROMPT_PATH", str(scratch_prompt)), \
         patch("serviceBot.api.portal.sync_prompt_to_elevenlabs"), \
         patch("serviceBot.db.queries.get_sms_config", return_value={}), \
         patch("serviceBot.db.queries.update_sms_config", return_value={}):
        client = TestClient(app)

        # 1. Update config via POST /api/v1/portal/config
        update_payload = {
            "business_address": "789 Pine Road, Charlotte, NC 28202",
            "google_maps_url": "https://maps.app.goo.gl/custompine"
        }

        post_res = client.post("/api/v1/portal/config", json=update_payload)
        assert post_res.status_code == 200

        # 2. Retrieve config via GET /api/v1/portal/config
        get_res = client.get("/api/v1/portal/config")
        assert get_res.status_code == 200
        cfg = get_res.json()
        assert cfg["business_address"] == "789 Pine Road, Charlotte, NC 28202"
        assert cfg["google_maps_url"] == "https://maps.app.goo.gl/custompine"

        # 3. Retrieve config via GET /api/v1/portal/sms/config
        sms_res = client.get("/api/v1/portal/sms/config")
        assert sms_res.status_code == 200
        sms_cfg = sms_res.json()
        assert sms_cfg["business_address"] == "789 Pine Road, Charlotte, NC 28202"
        assert sms_cfg["google_maps_url"] == "https://maps.app.goo.gl/custompine"

