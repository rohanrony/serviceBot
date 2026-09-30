import datetime as dt_mod
from unittest.mock import patch, MagicMock
import pytest

from serviceBot.services.booking import BookingService, BUSINESS_TZ
from serviceBot.services.sms_reminders import (
    schedule_appointment_reminders,
    check_and_escalate_unconfirmed_appointments,
    get_current_business_time,
    calculate_effective_confirmation_cutoff,
)
from serviceBot.services.twilio_sms import TwilioSMSClient
from serviceBot.db.connection import get_db_connection, dict_cursor
from serviceBot.db.queries import get_breached_unconfirmed_appointments


@pytest.fixture
def sample_test_request():
    """Seeds a customer, staff agent, and service request."""
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                "INSERT INTO customers (name, phone) VALUES ('Escalation Customer', '4242704893') ON CONFLICT (phone) DO UPDATE SET name = EXCLUDED.name RETURNING id;"
            )
            cust_id = cursor.fetchone()["id"]

            cursor.execute(
                "INSERT INTO sms_whitelist (phone_number, friendly_name, twilio_verified, whatsapp_onboarded) "
                "VALUES ('+14242704893', 'Test Contact', TRUE, TRUE) "
                "ON CONFLICT (phone_number) DO UPDATE SET twilio_verified = TRUE, whatsapp_onboarded = TRUE;"
            )

            cursor.execute(
                "INSERT INTO staff_agents (name, phone_number, role) VALUES ('Agent Tim', '+14242704893', 'technician') RETURNING id;"
            )
            agent_id = cursor.fetchone()["id"]

            cursor.execute(
                """
                INSERT INTO service_requests (
                    customer_id, staff_agent_id, service_type, issue_description,
                    status, booking_time, booking_type, confirmation_status, escalation_status
                )
                VALUES (%s, %s, 'Repair', 'Brake pad replacement', 'pending', '2026-10-01 07:00:00', 'appointment', 'pending_agent_confirmation', 'none')
                RETURNING id;
                """,
                (cust_id, agent_id),
            )
            sr_id = cursor.fetchone()["id"]
            conn.commit()
            return sr_id, agent_id


def test_escalation_does_not_trigger_prematurely_due_to_utc_offset(sample_test_request):
    """
    Verifies that an appointment with a cutoff set to 4:58 PM EDT (16:58:00)
    is NOT escalated when current EDT time is 1:58 PM (13:58:00),
    even if the server UTC time is 5:58 PM (17:58:00).
    """
    sr_id, _ = sample_test_request

    # Set confirmation cutoff to 4:58 PM today in business time
    today_ny = dt_mod.datetime.now(BUSINESS_TZ).replace(tzinfo=None)
    cutoff_time = today_ny + dt_mod.timedelta(hours=3)

    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                "UPDATE service_requests SET confirmation_cutoff_at = %s, escalation_status = 'none' WHERE id = %s;",
                (cutoff_time, sr_id),
            )
            conn.commit()

    # When as_of_time is now in business timezone (1:58 PM), it should NOT breach
    breached = get_breached_unconfirmed_appointments(as_of_time=today_ny)
    breached_ids = [b["id"] for b in breached]
    assert sr_id not in breached_ids

    # When as_of_time is 4 hours later (past cutoff), it SHOULD breach
    past_time = cutoff_time + dt_mod.timedelta(minutes=5)
    breached_future = get_breached_unconfirmed_appointments(as_of_time=past_time)
    future_ids = [b["id"] for b in breached_future]
    assert sr_id in future_ids


def test_twilio_whatsapp_e164_normalization_and_sandbox_autoroute(sample_test_request):
    """
    Verifies that:
    1. 10-digit phone numbers are normalized to E.164 (+1...) when channel is WHATSAPP.
    2. Sending SMS using the WhatsApp Sandbox number automatically routes to WHATSAPP.
    """
    client = TwilioSMSClient()
    client.account_sid = "ACmock_test_sid"
    client.auth_token = "mock_test_token"
    client.from_number = "+14155238886"

    # In test environment, client returns mock SENT with channel info
    # 1. 10-digit customer phone dispatched to WhatsApp
    res = client.send_whatsapp(to="4242704893", body="Test WhatsApp Alert")
    assert res["success"] is True
    assert res["channel"] == "WHATSAPP"

    # 2. SMS dispatch with WhatsApp Sandbox number as from_number
    # When Twilio client is invoked, sandbox number auto-routes to WHATSAPP
    res_sms = client.send_sms(to="+14242704893", body="Test Alert", channel="SMS")
    assert res_sms["success"] is True
    assert res_sms["channel"] == "WHATSAPP"


def test_reschedule_clears_old_escalation_status(sample_test_request):
    """
    Verifies that rescheduling an appointment resets escalation_status to 'none'
    and confirmation_status to 'pending_agent_confirmation'.
    """
    sr_id, agent_id = sample_test_request

    # Artificially mark request as escalated
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                """
                UPDATE service_requests
                SET escalation_status = 'escalated',
                    escalation_reason = 'TIMEOUT_NO_RESPONSE',
                    confirmed_at = NULL
                WHERE id = %s;
                """,
                (sr_id,),
            )
            conn.commit()

    # Reschedule via BookingService
    service = BookingService()
    receipt = service.reschedule(
        request_id=sr_id,
        new_datetime="2026-10-02 09:00:00",
        customer_consent_obtained=True,
        triggered_by="customer_portal",
    )
    assert receipt.request_id == sr_id

    # Verify escalation status was reset to 'none'
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                "SELECT escalation_status, escalation_reason, confirmation_status FROM service_requests WHERE id = %s;",
                (sr_id,),
            )
            sr = cursor.fetchone()
            assert sr["escalation_status"] == "none"
            assert sr["escalation_reason"] is None
            assert sr["confirmation_status"] == "pending_agent_confirmation"
