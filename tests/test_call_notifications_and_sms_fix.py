import os
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from serviceBot.main import app
from serviceBot.db.connection import get_db_connection
from serviceBot.services.twilio_sms import TwilioSMSClient
from serviceBot.db.queries import add_sms_whitelist

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_db():
    yield
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM crm_notes WHERE call_id = 'conv_test_dup_123';")
        cursor.execute("DELETE FROM service_requests WHERE customer_id IN (SELECT id FROM customers WHERE phone = '+15558889999');")
        cursor.execute("DELETE FROM customers WHERE phone = '+15558889999';")
        conn.commit()


@patch("serviceBot.api.telephony.generate_service_summary")
@patch("serviceBot.api.telephony.extract_callback_from_transcript")
@patch("serviceBot.services.gmail.send_booking_notification")
@patch("serviceBot.services.gmail.send_admin_notification")
def test_post_call_webhook_prevents_duplicate_if_booking_exists(
    mock_admin_email, mock_booking_email, mock_extract_callback, mock_summarize
):
    """
    Verifies that post_call_webhook does NOT create a duplicate callback service request
    or re-trigger emails if a service request was already created for the customer within 5 minutes.
    """
    mock_summarize.return_value = "Customer booked an appointment."
    mock_extract_callback.return_value = {
        "preferred_time": "tomorrow at 10:00 AM",
        "service_type": "Oil Change",
        "issue_description": "Regular maintenance"
    }

    # 1. Pre-create customer and an existing appointment booked 1 minute ago during the call
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO customers (name, phone) VALUES (%s, %s) RETURNING id;",
            ("Test Customer", "+15558889999")
        )
        c_id = cursor.fetchone()["id"]
        cursor.execute(
            """
            INSERT INTO service_requests (customer_id, service_type, issue_description, status, booking_type, booking_time)
            VALUES (%s, 'Oil Change', 'Regular maintenance', 'pending', 'appointment', 'tomorrow at 10:00 AM') RETURNING id;
            """,
            (c_id,)
        )
        sr_id = cursor.fetchone()["id"]
        conn.commit()

    # 2. Trigger post-call webhook
    payload = {
        "type": "post_call_transcription",
        "event_timestamp": 1700000000,
        "data": {
            "conversation_id": "conv_test_dup_123",
            "agent_id": "agent_test_123",
            "analysis": {"summary": "Customer booked an appointment."},
            "metadata": {"from_number": "+15558889999"},
            "transcript": [
                {"role": "user", "message": "Can you book an appointment and call me back tomorrow?"}
            ]
        }
    }

    response = client.post("/api/v1/telephony/webhook", json=payload)
    assert response.status_code == 200
    assert response.json() == {"success": True}

    # 3. Verify only 1 service_request exists for this customer (no duplicate callback created)
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) AS total FROM service_requests WHERE customer_id = %s;", (c_id,))
        count = cursor.fetchone()["total"]
        assert count == 1, f"Expected 1 service request, found {count}"

        cursor.execute("SELECT booking_type FROM service_requests WHERE id = %s;", (sr_id,))
        sr_row = cursor.fetchone()
        assert sr_row["booking_type"] == "appointment", "Existing appointment booking_type should remain untouched"

    # 4. Verify duplicate emails were not sent by post_call_webhook
    assert mock_booking_email.call_count == 0
    assert mock_admin_email.call_count == 0


def test_twilio_sms_clean_formatting_for_standard_phones(dummy_appointment_id):
    """
    Verifies that TwilioSMSClient cleans whatsapp: prefix for standard SMS destinations.
    """
    add_sms_whitelist("+15550192831", "Mock Target", twilio_verified=True)
    sms_client = TwilioSMSClient()
    sms_client.from_number = "whatsapp:+14155238886"

    res = sms_client.send_sms(
        to="+15550192831",
        body="Test standard SMS body",
        template_type="booking_confirmation",
        appointment_id=dummy_appointment_id
    )

    assert res["success"] is True
    assert res["status"] == "SENT"
