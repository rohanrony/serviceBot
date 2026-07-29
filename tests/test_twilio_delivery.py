import pytest
from fastapi.testclient import TestClient
from serviceBot.main import app
from serviceBot.services.twilio_sms import TwilioSMSClient
from serviceBot.db.queries import log_sms_dispatch, get_sms_log_by_id, update_sms_log_status, add_sms_whitelist

client = TestClient(app)


def test_twilio_sms_client_mock_dispatch(dummy_appointment_id):
    add_sms_whitelist("+15550192831", "Mock Target", twilio_verified=True)
    sms_client = TwilioSMSClient()
    res = sms_client.send_sms(
        to="+15550192831",
        body="Test message body",
        template_type="booking_confirmation",
        appointment_id=dummy_appointment_id
    )
    assert res["success"] is True
    assert res["status"] == "SENT"
    assert "sid" in res
    assert res["sid"].startswith("SMmock_")


def test_twilio_status_callback_webhook(dummy_appointment_id):
    log_id = log_sms_dispatch(
        appointment_id=dummy_appointment_id,
        recipient_type="customer",
        recipient_phone="+15550192831",
        template_type="reschedule",
        status="SENT",
        twilio_message_sid="SMtest_callback_123"
    )

    # Post delivery status callback from Twilio
    res = client.post("/api/v1/telephony/sms/status", data={
        "MessageSid": "SMtest_callback_123",
        "MessageStatus": "delivered"
    })
    assert res.status_code == 200

    # Verify log status updated to DELIVERED
    log_entry = get_sms_log_by_id(log_id)
    assert log_entry["status"] == "DELIVERED"


def test_manual_sms_retry_endpoint(dummy_appointment_id):
    add_sms_whitelist("+15550192831", "Mock Target", twilio_verified=True)
    log_id = log_sms_dispatch(
        appointment_id=dummy_appointment_id,
        recipient_type="customer",
        recipient_phone="+15550192831",
        template_type="reminder_2h",
        status="FAILED",
        error_code="30003",
        error_message="Unreachable Destination"
    )

    # Post manual retry API
    retry_res = client.post(f"/api/v1/portal/sms/retry/{log_id}")
    assert retry_res.status_code == 200
    assert retry_res.json()["success"] is True

    # Verify log is updated with new retry count
    updated_log = get_sms_log_by_id(log_id)
    assert updated_log["retry_count"] >= 1
