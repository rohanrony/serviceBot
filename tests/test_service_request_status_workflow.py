import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from serviceBot.main import app
from serviceBot.db.connection import get_db_connection, dict_cursor, init_db
from serviceBot.db.queries import (
    update_service_request_status,
    assign_staff_agent_to_service_request,
    ALLOWED_TRANSITIONS
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_db():
    """Ensure DB is initialized for testing."""
    init_db()


import uuid

_test_counter = 0

def create_test_customer_and_request(status="pending"):
    """Helper to insert a customer, staff agent, and service request for testing."""
    global _test_counter
    _test_counter += 1
    phone_num = f"+1555{_test_counter:07d}"
    agent_email = f"fsm_agent_{_test_counter}_{uuid.uuid4().hex[:6]}@test.com"
    slot_time = f"2026-08-10 {(10 + _test_counter % 12):02d}:00:00"

    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("SELECT setval(pg_get_serial_sequence('customers', 'id'), COALESCE(MAX(id), 1)) FROM customers;")
            cursor.execute("SELECT setval(pg_get_serial_sequence('staff_agents', 'id'), COALESCE(MAX(id), 1)) FROM staff_agents;")
            cursor.execute("SELECT setval(pg_get_serial_sequence('service_requests', 'id'), COALESCE(MAX(id), 1)) FROM service_requests;")
            cursor.execute(
                "INSERT INTO customers (name, phone) VALUES (%s, %s) RETURNING id;",
                (f"FSM Test Customer {_test_counter}", phone_num)
            )
            cust_id = cursor.fetchone()["id"]

            # 2. Insert staff agent
            cursor.execute(
                "INSERT INTO staff_agents (name, role, email) VALUES (%s, %s, %s) RETURNING id;",
                (f"FSM Test Agent {_test_counter}", "Technician", agent_email)
            )
            agent_id = cursor.fetchone()["id"]

            # 3. Insert service request
            cursor.execute(
                """
                INSERT INTO service_requests (customer_id, staff_agent_id, service_type, status, booking_type, booking_time)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id;
                """,
                (cust_id, agent_id, "Oil Change", status, "appointment", slot_time)
            )
            req_id = cursor.fetchone()["id"]

            # 4. Insert mock calendar slot
            cursor.execute(
                """
                INSERT INTO mock_calendar_slots (slot_datetime, is_booked, staff_agent_id)
                VALUES (CAST(%s AS TIMESTAMP), TRUE, %s)
                ON CONFLICT (slot_datetime, staff_agent_id) DO UPDATE SET is_booked = TRUE;
                """,
                (slot_time, agent_id)
            )

            return req_id, agent_id, cust_id, slot_time


# ==============================================================================
# 1. FSM STATE TRANSITION TESTS
# ==============================================================================

def test_fsm_allowed_transitions():
    """Test all valid state transitions in the FSM."""
    # Pending -> Confirmed
    req_id, _, _, _ = create_test_customer_and_request(status="pending")
    res1 = update_service_request_status(req_id, "confirmed", triggered_by="agent_sms")
    assert res1["status"] == "confirmed"

    # Confirmed -> In Progress
    res2 = update_service_request_status(req_id, "in_progress", triggered_by="manager_override")
    assert res2["status"] == "in_progress"

    # In Progress -> Completed (using 'done')
    res3 = update_service_request_status(req_id, "done", triggered_by="manager_override")
    assert res3["status"] == "completed"


def test_fsm_pending_to_cancelled():
    """Test Pending -> Cancelled transition."""
    req_id, _, _, _ = create_test_customer_and_request(status="pending")
    res = update_service_request_status(req_id, "cancelled", triggered_by="customer_sms")
    assert res["status"] == "cancelled"


def test_fsm_blocked_illegal_transitions():
    """Test that illegal transitions are strictly rejected by the FSM with ValueError."""
    req_id, _, _, _ = create_test_customer_and_request(status="pending")

    # Complete the request
    update_service_request_status(req_id, "completed", triggered_by="system")

    # Terminal state: completed -> pending (ILLEGAL)
    with pytest.raises(ValueError, match="Invalid FSM transition"):
        update_service_request_status(req_id, "pending", triggered_by="manager_override")

    # Terminal state: completed -> cancelled (ILLEGAL)
    with pytest.raises(ValueError, match="Invalid FSM transition"):
        update_service_request_status(req_id, "cancelled", triggered_by="manager_override")

    # Terminal state: completed -> in_progress (ILLEGAL)
    with pytest.raises(ValueError, match="Invalid FSM transition"):
        update_service_request_status(req_id, "in_progress", triggered_by="manager_override")

    # Terminal state: completed -> rescheduled (ILLEGAL)
    with pytest.raises(ValueError, match="Invalid FSM transition"):
        update_service_request_status(req_id, "rescheduled", triggered_by="manager_override")


def test_fsm_invalid_status_string():
    """Test that completely invalid status strings raise ValueError."""
    req_id, _, _, _ = create_test_customer_and_request(status="pending")
    with pytest.raises(ValueError, match="Invalid status"):
        update_service_request_status(req_id, "invalid_status_xyz")


# ==============================================================================
# 2. AUDIT LOGGING TESTS
# ==============================================================================

def test_audit_logging_on_status_change():
    """Verify that every status change creates a record in service_request_audit_log."""
    req_id, _, _, _ = create_test_customer_and_request(status="pending")

    # Perform transition
    update_service_request_status(req_id, "confirmed", triggered_by="agent_email", notes="Confirmed via email link")

    # Check audit log in DB
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                "SELECT * FROM service_request_audit_log WHERE request_id = %s ORDER BY id DESC;",
                (req_id,)
            )
            logs = cursor.fetchall()
            assert len(logs) >= 1
            latest_log = logs[0]
            assert latest_log["from_status"] == "pending"
            assert latest_log["to_status"] == "confirmed"
            assert latest_log["triggered_by"] == "agent_email"
            assert latest_log["notes"] == "Confirmed via email link"


# ==============================================================================
# 3. CALENDAR SLOT RELEASE BEHAVIOR TESTS
# ==============================================================================




# ==============================================================================
# 4. REASSIGNMENT RESTRICTIONS
# ==============================================================================

def test_cannot_reassign_agent_on_completed_request():
    """Verify that reassigning staff agent on a completed or cancelled request raises ValueError."""
    req_id, _, _, _ = create_test_customer_and_request(status="pending")

    # Mark as completed
    update_service_request_status(req_id, "completed")

    # Attempt agent reassignment
    with pytest.raises(ValueError, match="Cannot reassign agent for service request"):
        assign_staff_agent_to_service_request(req_id, staff_agent_id=1)


# ==============================================================================
# 5. PORTAL API INTEGRATION TESTS
# ==============================================================================

def test_portal_patch_status_endpoint_valid_and_invalid():
    """Integration test for PATCH /api/v1/portal/service-requests/{id}/status endpoint."""
    req_id, _, _, _ = create_test_customer_and_request(status="pending")

    # 1. Valid patch to confirmed
    res = client.patch(f"/api/v1/portal/service-requests/{req_id}/status", json={"status": "confirmed"})
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["data"]["status"] == "confirmed"

    # 2. Valid patch to completed
    res2 = client.patch(f"/api/v1/portal/service-requests/{req_id}/status", json={"status": "completed"})
    assert res2.status_code == 200

    # 3. Invalid FSM patch from completed -> pending (400 Bad Request)
    res3 = client.patch(f"/api/v1/portal/service-requests/{req_id}/status", json={"status": "pending"})
    assert res3.status_code == 400
    assert "detail" in res3.json()


def test_portal_get_service_requests_returns_sla_columns():
    """Verify GET /api/v1/portal/service-requests endpoint returns notification_dispatched_at and sla_expires_at."""
    req_id, _, _, _ = create_test_customer_and_request(status="pending")

    res = client.get("/api/v1/portal/service-requests")
    assert res.status_code == 200
    items = res.json()
    assert isinstance(items, list)

    target_req = next((r for r in items if r["id"] == req_id), None)
    assert target_req is not None
    assert "notification_dispatched_at" in target_req
    assert "sla_expires_at" in target_req
