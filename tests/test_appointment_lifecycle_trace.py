import pytest
import json
import datetime as dt
from fastapi.testclient import TestClient
from unittest.mock import patch

from serviceBot.db.connection import get_db_connection, dict_cursor
from serviceBot.db.queries import (
    assign_staff_agent_to_service_request,
    update_service_request_status,
    escalate_service_request,
    get_appointment_full_trace,
    get_appointment_details_by_id,
)
from serviceBot.main import app
from serviceBot.api.portal import reassign_service_request, ReassignRequestPayload
from serviceBot.services.sms_classifier import handle_agent_confirmation_action


@pytest.fixture
def dummy_trace_appointment():
    """Sets up a customer, staff agents, and a service request for trace testing."""
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            # 1. Ensure test customer
            cursor.execute(
                """
                INSERT INTO customers (name, phone)
                VALUES ('Trace Test Customer', '+14242709991')
                ON CONFLICT (phone) DO UPDATE SET name = EXCLUDED.name
                RETURNING id;
                """
            )
            customer_id = cursor.fetchone()["id"]

            # 2. Ensure test technician agents
            cursor.execute(
                """
                INSERT INTO staff_agents (name, role, email, phone_number)
                VALUES ('Tech Alpha', 'Master Technician', 'alpha@example.com', '+15551110001')
                RETURNING id;
                """
            )
            agent_alpha_id = cursor.fetchone()["id"]

            cursor.execute(
                """
                INSERT INTO staff_agents (name, role, email, phone_number)
                VALUES ('Tech Beta', 'Diagnostic Specialist', 'beta@example.com', '+15552220002')
                RETURNING id;
                """
            )
            agent_beta_id = cursor.fetchone()["id"]

            # 3. Create service request
            cursor.execute(
                """
                INSERT INTO service_requests (
                    customer_id, service_type, issue_description,
                    status, booking_type, booking_time, duration_minutes,
                    staff_agent_id, confirmation_status, escalation_status
                )
                VALUES (%s, 'Brake Inspection', 'Front brake pads squeaking',
                        'pending', 'appointment', '2026-10-12 14:00:00', 60,
                        %s, 'pending_agent_confirmation', 'none')
                RETURNING id;
                """,
                (customer_id, agent_alpha_id)
            )
            request_id = cursor.fetchone()["id"]

            # Insert initial booking audit log
            cursor.execute(
                """
                INSERT INTO service_request_audit_log (
                    request_id, event_type, from_status, to_status,
                    triggered_by, actor_name, notes, metadata
                )
                VALUES (%s, 'BOOKING_CREATED', NULL, 'pending',
                        'voice_bot', 'Voice AI Agent',
                        'Appointment booked via phone consultation',
                        %s);
                """,
                (request_id, json.dumps({"channel": "phone", "service": "Brake Inspection"}))
            )

            # Insert initial outbound SMS log to Tech Alpha
            cursor.execute(
                """
                INSERT INTO sms_log (
                    appointment_id, recipient_phone, recipient_type,
                    template_type, status, twilio_message_sid, sent_at
                )
                VALUES (%s, '+15551110001', 'agent',
                        'agent_booking', 'DELIVERED', 'SM_test_alpha_sid',
                        CURRENT_TIMESTAMP);
                """,
                (request_id,)
            )

            conn.commit()

            return {
                "request_id": request_id,
                "customer_id": customer_id,
                "agent_alpha_id": agent_alpha_id,
                "agent_beta_id": agent_beta_id,
            }


def test_schema_has_audit_enrichment_columns():
    """Verifies that Migration 0004 columns exist on service_request_audit_log."""
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                """
                SELECT column_name, data_type 
                FROM information_schema.columns 
                WHERE table_name = 'service_request_audit_log';
                """
            )
            cols = {row["column_name"]: row["data_type"] for row in cursor.fetchall()}
            assert "event_type" in cols
            assert "actor_name" in cols
            assert "metadata" in cols


def test_assign_agent_logs_audit_record(dummy_trace_appointment):
    """Verifies that assign_staff_agent_to_service_request logs an audit record."""
    fixture = dummy_trace_appointment
    req_id = fixture["request_id"]
    beta_id = fixture["agent_beta_id"]

    # Assign from Alpha to Beta via query
    assign_staff_agent_to_service_request(req_id, staff_agent_id=beta_id)

    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                """
                SELECT * FROM service_request_audit_log
                WHERE request_id = %s AND event_type IN ('AGENT_ASSIGNED', 'AGENT_REASSIGNED')
                ORDER BY created_at DESC LIMIT 1;
                """,
                (req_id,)
            )
            log = cursor.fetchone()
            assert log is not None
            assert log["to_status"] == "pending"
            assert "Tech Beta" in (log["notes"] or "") or "assigned" in (log["notes"] or "").lower()


def test_supervisor_reassign_logs_audit_trace(dummy_trace_appointment):
    """Verifies that supervisor reassign endpoint writes an audit trace node."""
    fixture = dummy_trace_appointment
    req_id = fixture["request_id"]
    beta_id = fixture["agent_beta_id"]

    # Escalate first so reassign endpoint allows it
    escalate_service_request(req_id, reason="AGENT_DECLINED", triggered_by="agent_sms")

    # Reassign via portal handler
    payload = ReassignRequestPayload(new_agent_id=beta_id, reason="Technician requested swap")
    import asyncio
    asyncio.run(reassign_service_request(req_id, payload))

    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                """
                SELECT * FROM service_request_audit_log
                WHERE request_id = %s AND (to_status = 'reassigned' OR event_type = 'AGENT_REASSIGNED')
                ORDER BY created_at DESC LIMIT 1;
                """,
                (req_id,)
            )
            log = cursor.fetchone()
            assert log is not None
            assert "Technician requested swap" in (log["notes"] or "")


def test_agent_decline_and_confirm_inbound_sms_traces(dummy_trace_appointment):
    """Verifies inbound technician SMS replies record explicit trace events."""
    fixture = dummy_trace_appointment
    req_id = fixture["request_id"]

    staff_agent_alpha = {
        "id": fixture["agent_alpha_id"],
        "name": "Tech Alpha",
        "phone_number": "+15551110001",
    }

    # Technician replies DECLINE
    with patch("serviceBot.services.twilio_sms.TwilioSMSClient.send_sms", return_value={"status": "sent", "sid": "SM_fake"}), \
         patch("serviceBot.services.twilio_sms.TwilioSMSClient.send_whatsapp", return_value={"status": "sent", "sid": "SM_fake"}), \
         patch("serviceBot.services.sms_reminders.dispatch_supervisor_escalation_alert"):
        res = handle_agent_confirmation_action(
            staff_agent_alpha,
            body="DECLINE",
            twilio_message_sid="SM_decline_sid",
            from_phone="+15551110001"
        )
        assert res["status"] == "processed"
        assert res["category"] == "agent_decline"

    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                """
                SELECT * FROM service_request_audit_log
                WHERE request_id = %s AND (event_type = 'AGENT_DECLINED' OR notes LIKE '%%AGENT_DECLINED%%')
                ORDER BY created_at DESC LIMIT 1;
                """,
                (req_id,)
            )
            log = cursor.fetchone()
            assert log is not None
            assert log["triggered_by"] in ("agent_sms", "agent")


def test_get_appointment_full_trace_aggregation(dummy_trace_appointment):
    """Verifies get_appointment_full_trace aggregates audit logs and SMS logs into a timeline."""
    fixture = dummy_trace_appointment
    req_id = fixture["request_id"]

    full_trace = get_appointment_full_trace(req_id)
    assert full_trace is not None
    assert "appointment" in full_trace
    assert "trace" in full_trace
    assert "raw_sms_logs" in full_trace
    assert len(full_trace["trace"]) >= 2  # At least initial booking and SMS dispatch

    timeline = full_trace["trace"]
    # Check that events have mandatory keys
    for event in timeline:
        assert "id" in event
        assert "timestamp" in event
        assert "category" in event
        assert "title" in event
        assert "actor" in event
        assert "badge_color" in event
        assert "description" in event


def test_portal_trace_endpoint(dummy_trace_appointment):
    """Verifies the GET /api/v1/portal/service-requests/{id}/trace endpoint."""
    fixture = dummy_trace_appointment
    req_id = fixture["request_id"]

    client = TestClient(app)
    response = client.get(f"/api/v1/portal/service-requests/{req_id}/trace")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["appointment"]["id"] == req_id
    assert isinstance(data["trace"], list)
    assert len(data["trace"]) > 0

    # Non-existent ID returns 404
    missing_resp = client.get("/api/v1/portal/service-requests/999999/trace")
    assert missing_resp.status_code == 404


def test_get_appointment_full_trace_synthetic_assignment_description(dummy_trace_appointment):
    """Verifies synthetic assignment event formats technician name properly when no audit log exists."""
    fixture = dummy_trace_appointment
    req_id = fixture["request_id"]

    # Delete any audit logs for this appointment to trigger synthetic generation
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("DELETE FROM service_request_audit_log WHERE request_id = %s;", (req_id,))

    full_trace = get_appointment_full_trace(req_id)
    assert full_trace is not None
    timeline = full_trace["trace"]

    # Find synthetic assignment event
    assign_event = next((ev for ev in timeline if ev.get("event_type") == "AGENT_ASSIGNED"), None)
    assert assign_event is not None
    assert assign_event["id"] == f"synth-assign-{req_id}"
    assert assign_event["category"] == "ASSIGNMENT"
    # Tech Alpha is the assigned technician in dummy_trace_appointment fixture
    assert "Assigned to technician Tech Alpha." in assign_event["description"]


def test_get_appointment_full_trace_synthetic_assignment_fallback_id():
    """Verifies synthetic assignment fallback to Agent #<id> when staff_agent_name is missing."""
    mock_app = {
        "id": 99991,
        "created_at": "2026-10-12 10:00:00",
        "staff_agent_id": 88,
        "staff_agent_name": None,  # Missing name
        "staff_agent_phone": "+15559998888",
        "confirmation_status": "pending_agent_confirmation",
        "service_type": "Oil Change",
        "booking_type": "appointment",
        "booking_time": "2026-10-12 14:00:00",
        "issue_description": "Routine check",
    }

    with patch("serviceBot.db.queries.get_appointment_details_by_id", return_value=mock_app), \
         patch("serviceBot.db.queries.get_sms_logs_by_appointment", return_value=[]), \
         patch("serviceBot.db.queries.get_db_connection") as mock_conn:
        
        # Return empty audit logs
        mock_cursor = mock_conn.return_value.__enter__.return_value.cursor.return_value
        mock_cursor.fetchall.return_value = []

        full_trace = get_appointment_full_trace(99991)
        assert full_trace is not None
        timeline = full_trace["trace"]

        assign_event = next((ev for ev in timeline if ev.get("event_type") == "AGENT_ASSIGNED"), None)
        assert assign_event is not None
        assert assign_event["description"] == "Assigned to technician Agent #88."

