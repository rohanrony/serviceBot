import sys
import os
from unittest.mock import patch
from fastapi.testclient import TestClient

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from serviceBot.main import app
from serviceBot.db.connection import get_db_connection
from serviceBot.services.twilio_sms import TwilioSMSClient
from serviceBot.db.queries import add_sms_whitelist

client = TestClient(app)


def test_post_call_webhook_prevents_duplicate_if_booking_exists():
    print("Testing post_call_webhook duplicate prevention...")
    
    with patch("serviceBot.api.telephony.generate_service_summary") as mock_summarize, \
         patch("serviceBot.api.telephony.extract_callback_from_transcript") as mock_extract_callback, \
         patch("serviceBot.services.gmail.send_booking_notification") as mock_booking_email, \
         patch("serviceBot.services.gmail.send_admin_notification") as mock_admin_email:

        mock_summarize.return_value = "Customer booked an appointment."
        mock_extract_callback.return_value = {
            "preferred_time": "tomorrow at 10:00 AM",
            "service_type": "Oil Change",
            "issue_description": "Regular maintenance"
        }

        # 1. Clean DB
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM crm_notes WHERE call_id = 'conv_test_dup_123';")
            cursor.execute("DELETE FROM service_requests WHERE customer_id IN (SELECT id FROM customers WHERE phone = '+15558889999');")
            cursor.execute("DELETE FROM customers WHERE phone = '+15558889999';")
            conn.commit()

        # 2. Pre-create customer and an existing appointment booked 1 minute ago during the call
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

        # 3. Trigger post-call webhook
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

        # 4. Verify only 1 service_request exists for this customer (no duplicate callback created)
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) AS total FROM service_requests WHERE customer_id = %s;", (c_id,))
            count = cursor.fetchone()["total"]
            assert count == 1, f"Expected 1 service request, found {count}"

            cursor.execute("SELECT booking_type FROM service_requests WHERE id = %s;", (sr_id,))
            sr_row = cursor.fetchone()
            assert sr_row["booking_type"] == "appointment", "Existing appointment booking_type should remain untouched"

        # 5. Verify duplicate emails were not sent by post_call_webhook
        assert mock_booking_email.call_count == 0, "Duplicate booking email should not be sent"
        assert mock_admin_email.call_count == 0, "Duplicate admin email should not be sent"

        # Cleanup
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM crm_notes WHERE call_id = 'conv_test_dup_123';")
            cursor.execute("DELETE FROM service_requests WHERE customer_id IN (SELECT id FROM customers WHERE phone = '+15558889999');")
            cursor.execute("DELETE FROM customers WHERE phone = '+15558889999';")
            conn.commit()

    print("✔ Post-call webhook duplicate prevention test PASSED!")


def test_twilio_sms_clean_formatting():
    print("Testing Twilio SMS clean phone number formatting...")
    add_sms_whitelist("+15550192831", "Mock Target", twilio_verified=True)
    sms_client = TwilioSMSClient()
    sms_client.from_number = "whatsapp:+14155238886"

    res = sms_client.send_sms(
        to="+15550192831",
        body="Test standard SMS body",
        template_type="booking_confirmation",
        appointment_id=999
    )

    assert res["success"] is True
    assert res["status"] == "SENT"
    assert res["sid"].startswith("SMmock_")
    print("✔ Twilio SMS clean phone number formatting test PASSED!")


def test_existing_customer_continuity():
    print("Testing existing customer context lookup & name updating...")
    from serviceBot.db.queries import lookup_customer_by_phone, update_customer_name

    # Clean DB
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM service_requests WHERE customer_id IN (SELECT id FROM customers WHERE phone = '+15557776666');")
        cursor.execute("DELETE FROM customers WHERE phone = '+15557776666';")
        conn.commit()

    # Pre-create existing customer with an active appointment
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO customers (name, phone) VALUES (%s, %s) RETURNING id;",
            ("Alice Smith", "+15557776666")
        )
        c_id = cursor.fetchone()["id"]
        cursor.execute(
            """
            INSERT INTO service_requests (customer_id, service_type, issue_description, status, booking_type, booking_time)
            VALUES (%s, 'Brake Inspection', 'Squeaking sound', 'pending', 'appointment', '2026-08-01 10:00:00') RETURNING id;
            """,
            (c_id,)
        )
        conn.commit()

    # 1. Test lookup returns existing appointment
    c_data = lookup_customer_by_phone("+15557776666")
    assert c_data is not None
    assert c_data["customer_id"] == c_id
    assert c_data["name"] == "Alice Smith"
    assert c_data["open_sr_id"] is not None
    assert c_data["open_sr_type"] == "Brake Inspection"

    # 2. Test updating name
    updated = update_customer_name(c_id, "Alice Jones")
    assert updated is True

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM customers WHERE id = %s;", (c_id,))
        row = cursor.fetchone()
        assert row["name"] == "Alice Jones"

        # Clean DB
        cursor.execute("DELETE FROM service_requests WHERE customer_id = %s;", (c_id,))
        cursor.execute("DELETE FROM customers WHERE id = %s;", (c_id,))
        conn.commit()

    print("✔ Existing customer context lookup & name updating test PASSED!")


if __name__ == "__main__":
    test_post_call_webhook_prevents_duplicate_if_booking_exists()
    test_twilio_sms_clean_formatting()
    test_existing_customer_continuity()
    print("\n🎉 ALL NOTIFICATION, SMS, AND CUSTOMER CONTINUITY TESTS PASSED SUCCESSFULLY!")
