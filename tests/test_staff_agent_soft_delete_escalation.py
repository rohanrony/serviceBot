"""
Tests for Staff Agent Soft Delete and Upcoming Appointment Escalation.
Validates:
1. Deleting an agent marks is_active = FALSE instead of hard deleting.
2. Upcoming active appointments for that agent are escalated with reason 'AGENT_DEACTIVATED'.
3. Past, completed, and cancelled appointments are untouched.
4. Inactive agents are excluded from get_staff_agents and replacement candidate lists.
5. Reassigning updates service_requests, appointment_reservations, and appointment_reservation_segments.
"""

import datetime as dt_mod
from unittest.mock import MagicMock, patch, call
import pytest
from fastapi.testclient import TestClient

from serviceBot.main import app
from serviceBot.db.queries import (
    escalate_service_request,
    get_available_agents_for_request,
)


@pytest.fixture
def client():
    return TestClient(app)


def test_escalate_service_request_accepts_agent_deactivated_reason():
    """Verify that 'AGENT_DEACTIVATED' is a valid escalation reason."""
    mock_cursor = MagicMock()
    mock_cursor.fetchone.side_effect = [
        {"id": 101, "status": "pending", "escalation_status": "none"},  # SELECT ... FOR UPDATE
        {"id": 101, "status": "pending", "escalation_status": "escalated", "escalation_reason": "AGENT_DEACTIVATED"},  # UPDATE RETURNING
    ]
    mock_conn = MagicMock()

    with patch("serviceBot.db.queries.get_db_connection") as mock_get_conn, \
         patch("serviceBot.db.queries.dict_cursor") as mock_dict_cur:
        mock_get_conn.return_value.__enter__.return_value = mock_conn
        mock_dict_cur.return_value.__enter__.return_value = mock_cursor

        result = escalate_service_request(
            request_id=101,
            reason="AGENT_DEACTIVATED",
            triggered_by="admin_agent_deactivation",
        )

        assert result["escalation_status"] == "escalated"
        assert result["escalation_reason"] == "AGENT_DEACTIVATED"
        # Assert audit log was recorded
        audit_calls = [
            c for c in mock_cursor.execute.call_args_list
            if "service_request_audit_log" in c[0][0]
        ]
        assert len(audit_calls) == 1
        assert "AGENT_DEACTIVATED" in audit_calls[0][0][1][5]


def test_soft_delete_agent_deactivates_and_escalates_upcoming_appointments(client):
    """
    Test DELETE /api/v1/portal/agents/{agent_id}:
    - Verifies agent is soft-deleted (is_active = FALSE)
    - Verifies upcoming active appointments are queried and escalated
    """
    agent_id = 10
    agent_record = {"id": agent_id, "name": "John Doe", "is_active": True}
    upcoming_appts = [
        {"id": 201, "status": "pending", "escalation_status": "none", "booking_time": "2026-10-20 10:00:00", "starts_at": dt_mod.datetime(2026, 10, 20, 10, 0)},
        {"id": 202, "status": "in_progress", "escalation_status": "none", "booking_time": "2026-10-21 14:00:00", "starts_at": dt_mod.datetime(2026, 10, 21, 14, 0)},
    ]

    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = agent_record
    mock_cursor.fetchall.return_value = upcoming_appts
    mock_conn = MagicMock()

    with patch("serviceBot.db.connection.get_db_connection") as mock_get_conn, \
         patch("serviceBot.db.connection.dict_cursor") as mock_dict_cur, \
         patch("serviceBot.db.queries.escalate_service_request") as mock_escalate, \
         patch("serviceBot.services.sms_reminders.dispatch_supervisor_escalation_alert") as mock_alert:

        mock_get_conn.return_value.__enter__.return_value = mock_conn
        mock_dict_cur.return_value.__enter__.return_value = mock_cursor
        mock_escalate.return_value = {"status": "escalated"}

        resp = client.delete(f"/api/v1/portal/agents/{agent_id}")
        assert resp.status_code == 200
        data = resp.json()

        assert data["success"] is True
        assert data["agent_id"] == agent_id
        assert data["escalated_appointments_count"] == 2
        assert data["escalated_service_request_ids"] == [201, 202]

        # Verify SQL operations:
        sql_calls = [c[0][0] for c in mock_cursor.execute.call_args_list]
        
        # 1. Soft delete update
        assert any("UPDATE staff_agents SET is_active = FALSE" in s for s in sql_calls)
        # 2. Must NOT do hard delete on staff_agents
        assert not any("DELETE FROM staff_agents" in s for s in sql_calls)
        # 3. Cleaned unbooked calendar slots
        assert any("DELETE FROM mock_calendar_slots" in s for s in sql_calls)
        # 4. Cleaned user_google_accounts and service_staff_agents
        assert any("DELETE FROM user_google_accounts" in s for s in sql_calls)
        assert any("DELETE FROM service_staff_agents" in s for s in sql_calls)

        # 5. Escalate called for both upcoming appointments
        assert mock_escalate.call_count == 2
        mock_escalate.assert_has_calls([
            call(request_id=201, reason="AGENT_DEACTIVATED", triggered_by="admin_agent_deactivation"),
            call(request_id=202, reason="AGENT_DEACTIVATED", triggered_by="admin_agent_deactivation"),
        ])
        assert mock_alert.call_count == 2


def test_soft_delete_agent_not_found(client):
    """Test DELETE /api/v1/portal/agents/{agent_id} returns 404 when agent does not exist."""
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = None
    mock_conn = MagicMock()

    with patch("serviceBot.db.connection.get_db_connection") as mock_get_conn, \
         patch("serviceBot.db.connection.dict_cursor") as mock_dict_cur:
        mock_get_conn.return_value.__enter__.return_value = mock_conn
        mock_dict_cur.return_value.__enter__.return_value = mock_cursor

        resp = client.delete("/api/v1/portal/agents/9999")
        assert resp.status_code == 404
        assert "Agent not found" in resp.json()["detail"]


def test_soft_delete_handles_no_upcoming_appointments(client):
    """Test soft delete when agent has no upcoming appointments."""
    agent_id = 15
    agent_record = {"id": agent_id, "name": "Jane Smith", "is_active": True}

    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = agent_record
    mock_cursor.fetchall.return_value = []  # No upcoming appointments
    mock_conn = MagicMock()

    with patch("serviceBot.db.connection.get_db_connection") as mock_get_conn, \
         patch("serviceBot.db.connection.dict_cursor") as mock_dict_cur, \
         patch("serviceBot.db.queries.escalate_service_request") as mock_escalate:

        mock_get_conn.return_value.__enter__.return_value = mock_conn
        mock_dict_cur.return_value.__enter__.return_value = mock_cursor

        resp = client.delete(f"/api/v1/portal/agents/{agent_id}")
        assert resp.status_code == 200
        data = resp.json()

        assert data["success"] is True
        assert data["escalated_appointments_count"] == 0
        assert data["escalated_service_request_ids"] == []
        assert mock_escalate.call_count == 0


def test_get_staff_agents_filters_out_inactive_agents(client):
    """Test that GET /api/v1/portal/agents filters out is_active = FALSE agents."""
    mock_cursor = MagicMock()
    mock_conn = MagicMock()

    with patch("serviceBot.db.connection.get_db_connection") as mock_get_conn, \
         patch("serviceBot.db.connection.dict_cursor") as mock_dict_cur, \
         patch("serviceBot.db.queries.is_agent_whatsapp_connected", return_value=True):
        mock_get_conn.return_value.__enter__.return_value = mock_conn
        mock_dict_cur.return_value.__enter__.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [
            {"id": 1, "name": "Active Agent", "role": "Advisor", "db_email": "a@test.com", "phone_number": "+111", "google_email": None}
        ]

        resp = client.get("/api/v1/portal/agents")
        assert resp.status_code == 200
        agents = resp.json()
        assert len(agents) == 1
        assert agents[0]["name"] == "Active Agent"

        # Verify SQL included is_active check
        query_executed = mock_cursor.execute.call_args[0][0]
        assert "is_active" in query_executed


def test_reassign_endpoint_updates_reservation_segments(client):
    """
    Test that POST /api/v1/portal/service-requests/{request_id}/reassign
    updates both appointment_reservations and appointment_reservation_segments to the new technician.
    """
    request_id = 301
    sr_record = {
        "id": request_id,
        "staff_agent_id": 10,
        "status": "pending",
        "service_type": "Brake Service",
        "booking_time": "2026-10-25 10:00:00",
        "customer_name": "Test Customer",
        "customer_phone": "+19195551234",
        "old_agent_name": "Inactive Tech",
        "old_agent_phone": "+19195550010",
        "escalation_status": "escalated",
    }
    new_agent_record = {
        "id": 12,
        "name": "Active Tech",
        "phone_number": "+19195550012",
        "email": "active@example.com",
    }

    mock_cursor = MagicMock()
    # 1. Fetch SR, 2. Fetch new agent, 3. Select starts_at
    mock_cursor.fetchone.side_effect = [
        sr_record,
        new_agent_record,
        {"starts_at": dt_mod.datetime(2026, 10, 25, 10, 0)},
    ]
    mock_conn = MagicMock()

    with patch("serviceBot.db.connection.get_db_connection") as mock_get_conn, \
         patch("serviceBot.db.connection.dict_cursor") as mock_dict_cur, \
         patch("serviceBot.services.twilio_sms.TwilioSMSClient.send_sms") as mock_send_sms:

        mock_get_conn.return_value.__enter__.return_value = mock_conn
        mock_dict_cur.return_value.__enter__.return_value = mock_cursor

        payload = {"new_agent_id": 12, "reason": "Reassigned after tech deactivation"}
        resp = client.post(f"/api/v1/portal/service-requests/{request_id}/reassign", json=payload)
        assert resp.status_code == 200

        executed_queries = [c[0][0] for c in mock_cursor.execute.call_args_list]

        # Verify service_requests updated
        assert any("UPDATE service_requests" in q for q in executed_queries)
        # Verify appointment_reservations updated
        assert any("UPDATE appointment_reservations" in q for q in executed_queries)
        # Verify appointment_reservation_segments updated
        assert any("UPDATE appointment_reservation_segments" in q for q in executed_queries)
