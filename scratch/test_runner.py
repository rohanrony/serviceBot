import os
import sys

os.environ["LOG_FILE"] = ""
os.environ["ANONYMIZED_TELEMETRY"] = "False"
os.environ["CHROMA_TELEMETRY_IMPL"] = "None"
os.environ["PYTEST_CURRENT_TEST"] = "1"
os.environ["DATABASE_URL"] = "postgresql://mock:mock@localhost:5432/mock"
os.environ["OPENAI_API_KEY"] = "sk-dummy"
os.environ["ELEVENLABS_API_KEY"] = "dummy"

from unittest.mock import patch, MagicMock

print("--- Step 1: Testing Twilio SMS Client Mock Mode ---")
from serviceBot.services.twilio_sms import TwilioSMSClient

with patch('serviceBot.services.twilio_sms.get_sms_config', return_value={'environment': 'PRODUCTION'}), \
     patch('serviceBot.services.twilio_sms.is_phone_whitelisted', return_value=True), \
     patch('serviceBot.services.twilio_sms.log_sms_dispatch', return_value=101):
    sms = TwilioSMSClient()
    res = sms.send_sms(to="+15550001111", body="Test booking confirmation", template_type="booking", appointment_id=101)
    print("  Twilio SMS dispatch result:", res)
    assert res["success"] is True
    assert res["status"] == "SENT"
    assert res["sid"].startswith("SMmock_")
    print("  ✓ TwilioSMSClient mock dispatch test PASSED")

print("\n--- Step 2: Testing SMS Notification Router Matrix ---")
from serviceBot.services.sms_router import SMSNotificationRouter

with patch('serviceBot.services.twilio_sms.get_sms_config', return_value={'environment': 'PRODUCTION'}), \
     patch('serviceBot.services.twilio_sms.is_phone_whitelisted', return_value=True), \
     patch('serviceBot.services.twilio_sms.log_sms_dispatch', return_value=102), \
     patch('serviceBot.services.sms_router.get_sms_matrix_rules', return_value=[]), \
     patch('serviceBot.services.sms_router.get_customer_opt_in', return_value=True), \
     patch('serviceBot.services.sms_router.log_sms_dispatch', return_value=102), \
     patch('serviceBot.services.sms_router.schedule_appointment_reminders', return_value=None), \
     patch('serviceBot.services.sms_router.update_or_cancel_appointment_reminders', return_value=None):
    router = SMSNotificationRouter()
    
    # 2a. BOOKING event
    booking_res = router.process_event(
        event_type="BOOKING",
        appointment_id=101,
        customer_phone="+15550002001",
        agent_phone="+15550002002",
        booking_time="2026-10-25 14:00:00"
    )
    recipients = [d["recipient"] for d in booking_res["dispatches"]]
    print("  BOOKING dispatch recipients:", recipients)
    assert "customer" in recipients
    assert "agent" in recipients
    print("  ✓ BOOKING event router test PASSED")

    # 2b. RESCHEDULED event
    resched_res = router.process_event(
        event_type="RESCHEDULED",
        appointment_id=101,
        customer_phone="+15550002003",
        booking_time="2026-11-01 10:00:00"
    )
    resched_recipients = [d["recipient"] for d in resched_res["dispatches"]]
    print("  RESCHEDULED dispatch recipients:", resched_recipients)
    assert "customer" in resched_recipients
    print("  ✓ RESCHEDULED event router test PASSED")

    # 2c. REASSIGNED event
    reassign_res = router.process_event(
        event_type="REASSIGNED",
        appointment_id=101,
        customer_phone="+15550002004",
        agent_phone="+15550002005",
        previous_agent_phone="+15550002006",
        booking_time="2026-10-25 14:00:00"
    )
    reassign_recipients = [d["recipient"] for d in reassign_res["dispatches"]]
    print("  REASSIGNED dispatch recipients:", reassign_recipients)
    assert "agent" in reassign_recipients
    assert "previous_agent" in reassign_recipients
    assert "customer" not in reassign_recipients
    print("  ✓ REASSIGNED event router test PASSED")

print("\n--- Step 3: Testing Voice Tools API (create_service_request -> SMS trigger) ---")
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Mock nodes/langchain dependencies before importing telephony router
with patch("serviceBot.graph.nodes.handoff_node", return_value={"handoff_summary": "mock"}):
    from serviceBot.api.telephony import voice_router

    test_app = FastAPI()
    test_app.include_router(voice_router)
    client = TestClient(test_app)

    with patch("serviceBot.api.telephony.get_booking_details") as mock_details, \
         patch("serviceBot.api.telephony.create_service_request") as mock_create, \
         patch("serviceBot.api.telephony.lookup_customer_by_phone") as mock_lookup, \
         patch("serviceBot.services.sms_router.SMSNotificationRouter.process_event") as mock_process_event, \
         patch("serviceBot.services.gmail.send_booking_notification"), \
         patch("serviceBot.services.gmail.send_admin_notification"):
        
        mock_lookup.return_value = {"customer_id": 42}
        mock_create.return_value = 201
        mock_details.return_value = {
            "customer_name": "Jane Doe",
            "phone": "+15550020001",
            "vehicle": "2020 Toyota Camry",
            "service_type": "Oil Change",
            "issue": "Routine service",
            "time": "2026-10-25 14:00:00"
        }
        mock_process_event.return_value = {"dispatches": [{"recipient": "customer", "status": "SENT"}]}

        payload = {
            "tool_call_id": "sms_apt_1",
            "name": "create_service_request",
            "arguments": {
                "customer_name": "Jane Doe",
                "phone": "555-002-0001",
                "make": "Toyota",
                "model": "Camry",
                "year": 2020,
                "issue_description": "Oil change",
                "booking_type": "appointment",
                "booking_time": "2026-10-25 14:00:00"
            }
        }

        response = client.post("/api/v1/voice/tools", json=payload)
        print("  Voice tools API response status:", response.status_code)
        print("  Voice tools API response body:", response.json())
        assert response.status_code == 200
        assert response.json()["result"]["success"] is True
        
        # Verify SMSNotificationRouter.process_event was called when creating service request
        mock_process_event.assert_called_once()
        evt_call = mock_process_event.call_args.kwargs
        print("  SMS router process_event called with kwargs:", evt_call)
        assert evt_call["event_type"] == "BOOKING"
        assert evt_call["appointment_id"] == 201
        assert evt_call["customer_phone"] == "+15550020001"
        print("  ✓ Service request creation SMS trigger integration test PASSED")

print("\n========================================================")
print("🎉 ALL LOCAL FUNCTIONALITY & SMS TESTS PASSED SUCCESSFULLY!")
print("========================================================")
