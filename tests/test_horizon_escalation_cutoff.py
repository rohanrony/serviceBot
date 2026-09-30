import datetime as dt
from unittest.mock import patch
import pytest
from serviceBot.services.sms_reminders import (
    calculate_effective_confirmation_cutoff,
    check_and_escalate_unconfirmed_appointments,
)
from serviceBot.db.connection import get_db_connection, dict_cursor


def test_calculate_effective_confirmation_cutoff_advance_booking():
    """Booked Tuesday 9:00 AM for Friday 2:00 PM (lead time > 24h). SLA is 4 business hours."""
    cfg = {
        "sla_advance_booking_hours": 4,
        "sla_medium_booking_hours": 3,
        "sla_short_booking_hours": 1.5,
        "final_reminder_hours": 2,
        "business_hours_start": 8,
        "business_hours_end": 18,
        "overnight_grace_minutes": 30,
    }
    booked_at = dt.datetime(2026, 10, 6, 9, 0)   # Tuesday 9:00 AM
    apt_dt = dt.datetime(2026, 10, 9, 14, 0)     # Friday 2:00 PM

    cutoff = calculate_effective_confirmation_cutoff(booked_at, apt_dt, cfg)
    # SLA deadline: Tuesday 9:00 AM + 4h = Tuesday 1:00 PM (13:00)
    # T_appt - 2h = Friday 12:00 PM
    # Cutoff = min(13:00 Tue, 12:00 Fri) = Tuesday 1:00 PM
    assert cutoff == dt.datetime(2026, 10, 6, 13, 0)


def test_calculate_effective_confirmation_cutoff_overnight_pause():
    """Booked Tuesday 5:00 PM (17:00) for Wednesday 12:00 PM (19h horizon, medium SLA = 3h)."""
    cfg = {
        "sla_advance_booking_hours": 4,
        "sla_medium_booking_hours": 3,
        "sla_short_booking_hours": 1.5,
        "final_reminder_hours": 2,
        "business_hours_start": 8,
        "business_hours_end": 18,
        "overnight_grace_minutes": 30,
    }
    booked_at = dt.datetime(2026, 10, 6, 17, 0)   # Tuesday 5:00 PM
    apt_dt = dt.datetime(2026, 10, 7, 12, 0)      # Wednesday 12:00 PM

    cutoff = calculate_effective_confirmation_cutoff(booked_at, apt_dt, cfg)
    # 17:00 to 18:00 (1 hour Tuesday). Pauses overnight.
    # Resumes Wednesday 8:00 AM. Remaining 2 hours -> Wednesday 10:00 AM.
    # T_appt - 2h = Wednesday 10:00 AM.
    # Cutoff is Wednesday 10:00 AM.
    assert cutoff == dt.datetime(2026, 10, 7, 10, 0)


def test_calculate_effective_confirmation_cutoff_morning_opening_grace():
    """Booked Tuesday 5:30 PM (17:30) for Wednesday 9:00 AM (morning grace applies)."""
    cfg = {
        "sla_advance_booking_hours": 4,
        "sla_medium_booking_hours": 3,
        "sla_short_booking_hours": 1.5,
        "final_reminder_hours": 2,
        "business_hours_start": 8,
        "business_hours_end": 18,
        "overnight_grace_minutes": 30,
    }
    booked_at = dt.datetime(2026, 10, 6, 17, 30)
    apt_dt = dt.datetime(2026, 10, 7, 9, 0)

    cutoff = calculate_effective_confirmation_cutoff(booked_at, apt_dt, cfg)
    # Opening grace applies: Wednesday 8:00 AM + 30 min = 8:30 AM
    assert cutoff == dt.datetime(2026, 10, 7, 8, 30)


def test_check_and_escalate_unconfirmed_appointments():
    """Test background escalation scanner evaluates breached appointments and alerts supervisor."""
    now = dt.datetime.now()
    past_cutoff = now - dt.timedelta(minutes=10)
    future_cutoff = now + dt.timedelta(hours=2)

    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            # 1. Breached unconfirmed appointment
            cursor.execute(
                """
                INSERT INTO service_requests (
                    customer_id, vehicle_id, service_type, issue_description,
                    status, booking_type, confirmation_status, escalation_status,
                    confirmation_cutoff_at
                )
                VALUES (1, 1, 'Brake Repair', 'Breached cutoff test',
                        'pending', 'appointment', 'pending_agent_confirmation', 'none', %s)
                RETURNING id;
                """,
                (past_cutoff,)
            )
            breached_id = cursor.fetchone()["id"]

            # 2. Future unconfirmed appointment (should NOT be escalated)
            cursor.execute(
                """
                INSERT INTO service_requests (
                    customer_id, vehicle_id, service_type, issue_description,
                    status, booking_type, confirmation_status, escalation_status,
                    confirmation_cutoff_at
                )
                VALUES (1, 1, 'Oil Change', 'Future cutoff test',
                        'pending', 'appointment', 'pending_agent_confirmation', 'none', %s)
                RETURNING id;
                """,
                (future_cutoff,)
            )
            future_id = cursor.fetchone()["id"]

            # 3. Already confirmed appointment (should NOT be escalated)
            cursor.execute(
                """
                INSERT INTO service_requests (
                    customer_id, vehicle_id, service_type, issue_description,
                    status, booking_type, confirmation_status, escalation_status,
                    confirmation_cutoff_at
                )
                VALUES (1, 1, 'Tire Balance', 'Confirmed test',
                        'pending', 'appointment', 'confirmed', 'none', %s)
                RETURNING id;
                """,
                (past_cutoff,)
            )
            confirmed_id = cursor.fetchone()["id"]

            conn.commit()

    with patch("serviceBot.services.sms_reminders.dispatch_supervisor_escalation_alert") as mock_sup_alert:
        escalated_count = check_and_escalate_unconfirmed_appointments(as_of_time=now)
        assert escalated_count >= 1

    # Verify breached_id was escalated
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("SELECT escalation_status, escalation_reason FROM service_requests WHERE id = %s;", (breached_id,))
            breached_row = cursor.fetchone()
            assert breached_row["escalation_status"] == "escalated"
            assert breached_row["escalation_reason"] == "TIMEOUT_NO_RESPONSE"

            # Future ID remains none
            cursor.execute("SELECT escalation_status FROM service_requests WHERE id = %s;", (future_id,))
            future_row = cursor.fetchone()
            assert future_row["escalation_status"] == "none"

            # Confirmed ID remains none
            cursor.execute("SELECT escalation_status FROM service_requests WHERE id = %s;", (confirmed_id,))
            confirmed_row = cursor.fetchone()
            assert confirmed_row["escalation_status"] == "none"
