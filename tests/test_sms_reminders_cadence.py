import datetime as dt_mod
from unittest.mock import patch, MagicMock
import pytest

from serviceBot.services.sms_reminders import (
    schedule_appointment_reminders,
    run_reminder_polling_worker_cycle,
    calculate_effective_confirmation_cutoff,
)
from serviceBot.db.connection import get_db_connection, dict_cursor


@pytest.fixture
def sample_appointment():
    """Creates a sample appointment in the test DB for reminder testing."""
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                "INSERT INTO customers (name, phone) VALUES ('Cadence Customer', '+19195550111') ON CONFLICT (phone) DO UPDATE SET name = EXCLUDED.name RETURNING id;"
            )
            cust_id = cursor.fetchone()["id"]

            cursor.execute(
                "INSERT INTO staff_agents (name, phone_number, role) VALUES ('Tech Tom', '+19195550222', 'technician') RETURNING id;"
            )
            agent_id = cursor.fetchone()["id"]

            cursor.execute(
                """
                INSERT INTO service_requests (customer_id, staff_agent_id, service_type, issue_description, status, booking_time, booking_type)
                VALUES (%s, %s, 'Brake Inspection', 'Squeaking brakes', 'pending', '2026-10-10 14:00:00', 'appointment')
                RETURNING id;
                """,
                (cust_id, agent_id),
            )
            appt_id = cursor.fetchone()["id"]
            conn.commit()
            return appt_id, "+19195550111", "+19195550222"


def test_schedule_appointment_reminders_queues_attempts_and_persists_cutoff(sample_appointment):
    appt_id, cust_phone, agent_phone = sample_appointment
    booking_time = "2026-10-10 14:00:00"

    schedule_appointment_reminders(
        appointment_id=appt_id,
        booking_time_str=booking_time,
        customer_phone=cust_phone,
        agent_phone=agent_phone,
    )

    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("SELECT confirmation_cutoff_at, confirmation_status FROM service_requests WHERE id = %s;", (appt_id,))
            sr = cursor.fetchone()
            assert sr["confirmation_cutoff_at"] is not None
            assert sr["confirmation_status"] == "pending_agent_confirmation"

            cursor.execute(
                "SELECT * FROM sms_reminders WHERE appointment_id = %s ORDER BY attempt_number ASC, scheduled_at ASC;",
                (appt_id,)
            )
            reminders = cursor.fetchall()
            assert len(reminders) >= 3

            attempts = [r["attempt_number"] for r in reminders]
            assert 1 in attempts
            assert 3 in attempts

            # Verify Attempt 1 includes both customer and agent
            att1 = [r for r in reminders if r["attempt_number"] == 1]
            recipients = {r["recipient_type"] for r in att1}
            assert "customer" in recipients
            assert "agent" in recipients


def test_polling_worker_handles_carrier_error_retry_backoff(sample_appointment):
    appt_id, cust_phone, agent_phone = sample_appointment

    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            past_time = dt_mod.datetime.now() - dt_mod.timedelta(minutes=5)
            cursor.execute(
                """
                INSERT INTO sms_reminders (appointment_id, recipient_type, recipient_phone, reminder_type, scheduled_at, status, attempt_number, attempt_kind, retry_count)
                VALUES (%s, 'agent', %s, 'immediate', %s, 'PENDING', 1, 'immediate_booking', 0)
                RETURNING id;
                """,
                (appt_id, agent_phone, past_time)
            )
            rem_id = cursor.fetchone()["id"]
            conn.commit()

    # Simulate carrier delivery failure
    mock_fail = {"success": False, "status": "FAILED", "error": "Carrier timeout (30008)"}
    with patch("serviceBot.services.sms_reminders.TwilioSMSClient.send_sms", return_value=mock_fail):
        run_reminder_polling_worker_cycle()

    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("SELECT status, retry_count, last_error, scheduled_at FROM sms_reminders WHERE id = %s;", (rem_id,))
            row = cursor.fetchone()
            assert row["retry_count"] == 1
            assert row["status"] == "PENDING"
            assert "30008" in (row["last_error"] or "")
            assert row["scheduled_at"] > dt_mod.datetime.now()


def test_polling_worker_max_retries_marks_failed(sample_appointment):
    appt_id, cust_phone, agent_phone = sample_appointment

    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            past_time = dt_mod.datetime.now() - dt_mod.timedelta(minutes=5)
            cursor.execute(
                """
                INSERT INTO sms_reminders (appointment_id, recipient_type, recipient_phone, reminder_type, scheduled_at, status, attempt_number, attempt_kind, retry_count)
                VALUES (%s, 'agent', %s, 'final', %s, 'PENDING', 3, 'final_reminder', 3)
                RETURNING id;
                """,
                (appt_id, agent_phone, past_time)
            )
            rem_id = cursor.fetchone()["id"]
            conn.commit()

    mock_fail = {"success": False, "status": "FAILED", "error": "Undeliverable number (30003)"}
    with patch("serviceBot.services.sms_reminders.TwilioSMSClient.send_sms", return_value=mock_fail):
        run_reminder_polling_worker_cycle()

    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("SELECT status, retry_count, last_error FROM sms_reminders WHERE id = %s;", (rem_id,))
            row = cursor.fetchone()
            assert row["status"] == "FAILED"
            assert "30003" in (row["last_error"] or "")
