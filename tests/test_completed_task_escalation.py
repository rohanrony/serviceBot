import pytest
import datetime as dt
from serviceBot.db.connection import get_db_connection, dict_cursor
from serviceBot.db.queries import (
    create_service_request,
    update_service_request_status,
    escalate_service_request,
)
from serviceBot.api.portal import get_service_requests, reassign_service_request, ReassignRequestPayload
from serviceBot.services.sms_reminders import dispatch_supervisor_escalation_alert
from fastapi import HTTPException


@pytest.fixture
def dummy_appt_for_completed():
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            # Create a customer and request
            cursor.execute(
                """
                INSERT INTO customers (name, phone)
                VALUES ('Completed Test Customer', '+15559876543')
                ON CONFLICT (phone) DO UPDATE SET name = EXCLUDED.name
                RETURNING id;
                """
            )
            c_id = cursor.fetchone()["id"]

            cursor.execute(
                """
                INSERT INTO service_requests (
                    customer_id, service_type, issue_description,
                    status, booking_type, booking_time, duration_minutes,
                    confirmation_status, escalation_status, escalation_reason
                )
                VALUES (%s, 'Brake Inspection', 'Check brakes',
                        'in_progress', 'appointment', '2026-10-15 10:00:00', 60,
                        'pending_agent_confirmation', 'escalated', 'TIMEOUT_NO_RESPONSE')
                RETURNING id;
                """,
                (c_id,)
            )
            req_id = cursor.fetchone()["id"]
            conn.commit()
            return req_id


def test_update_service_request_status_completed_clears_escalation(dummy_appt_for_completed):
    req_id = dummy_appt_for_completed

    # Transition to completed
    updated = update_service_request_status(req_id, status="completed", triggered_by="portal_admin")
    assert updated["status"] == "completed"

    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                "SELECT status, escalation_status, escalation_reason FROM service_requests WHERE id = %s;",
                (req_id,)
            )
            sr = cursor.fetchone()
            assert sr["status"] == "completed"
            assert sr["escalation_status"] in ("resolved", "none")
            assert sr["escalation_reason"] is None


@pytest.mark.anyio
async def test_completed_appointment_excluded_from_escalated_queue(dummy_appt_for_completed):
    req_id = dummy_appt_for_completed

    # Even if DB row still had escalation_status='escalated', completed appointments should never appear in escalated queue
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                "UPDATE service_requests SET status = 'completed', escalation_status = 'escalated' WHERE id = %s;",
                (req_id,)
            )
            conn.commit()

    escalated_items = await get_service_requests(escalated=True)
    escalated_ids = [item["id"] for item in escalated_items]
    assert req_id not in escalated_ids


def test_escalate_completed_appointment_skipped(dummy_appt_for_completed):
    req_id = dummy_appt_for_completed
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                "UPDATE service_requests SET status = 'completed', escalation_status = 'none' WHERE id = %s;",
                (req_id,)
            )
            conn.commit()

    esc_result = escalate_service_request(req_id, reason="AGENT_DECLINED")
    assert esc_result["status"] == "completed"
    assert esc_result["escalation_status"] == "none"


def test_dispatch_supervisor_alert_skipped_for_completed(dummy_appt_for_completed):
    req_id = dummy_appt_for_completed
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                "UPDATE service_requests SET status = 'completed' WHERE id = %s;",
                (req_id,)
            )
            conn.commit()

    alert_res = dispatch_supervisor_escalation_alert(req_id, reason="TIMEOUT_NO_RESPONSE")
    assert alert_res.get("skipped") is True


@pytest.mark.anyio
async def test_reassign_completed_appointment_rejected(dummy_appt_for_completed):
    req_id = dummy_appt_for_completed
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                "UPDATE service_requests SET status = 'completed' WHERE id = %s;",
                (req_id,)
            )
            conn.commit()

    payload = ReassignRequestPayload(new_agent_id=1, reason="Test")
    with pytest.raises(HTTPException) as excinfo:
        await reassign_service_request(req_id, payload)
    assert excinfo.value.status_code == 400
    assert "closed or cancelled" in excinfo.value.detail.lower()
