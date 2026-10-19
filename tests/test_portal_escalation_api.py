import datetime as dt
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient
from serviceBot.main import app
from serviceBot.db.connection import get_db_connection, dict_cursor


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def setup_escalated_request():
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            # 1. Tech 1 (original agent)
            cursor.execute("SELECT id FROM staff_agents WHERE phone_number = '+19195551111';")
            t1 = cursor.fetchone()
            if not t1:
                cursor.execute(
                    """
                    INSERT INTO staff_agents (name, role, email, phone_number)
                    VALUES ('Tech One', 'technician', 'tech.one@example.com', '+19195551111')
                    RETURNING id;
                    """
                )
                t1 = cursor.fetchone()
            agent_id = t1["id"]

            # 2. Tech 2 (replacement candidate)
            cursor.execute("SELECT id FROM staff_agents WHERE phone_number = '+19195552222';")
            t2 = cursor.fetchone()
            if not t2:
                cursor.execute(
                    """
                    INSERT INTO staff_agents (name, role, email, phone_number)
                    VALUES ('Tech Two', 'technician', 'tech.two@example.com', '+19195552222')
                    RETURNING id;
                    """
                )
                t2 = cursor.fetchone()
            candidate_id = t2["id"]

            # 3. Customer
            cursor.execute(
                """
                INSERT INTO customers (name, phone)
                VALUES ('Sarah Jenkins', '+19195553333')
                ON CONFLICT (phone) DO UPDATE SET name = EXCLUDED.name
                RETURNING id;
                """
            )
            customer = cursor.fetchone()
            customer_id = customer["id"]

            # 4. Vehicle
            cursor.execute(
                """
                INSERT INTO vehicles (customer_id, make, model, year)
                VALUES (%s, 'Honda', 'Civic', 2022)
                RETURNING id;
                """,
                (customer_id,)
            )
            vehicle = cursor.fetchone()
            vehicle_id = vehicle["id"]

            # 5. Service request (escalated)
            cursor.execute(
                """
                INSERT INTO service_requests (
                    customer_id, vehicle_id, service_type, issue_description,
                    status, booking_type, booking_time, duration_minutes, staff_agent_id,
                    confirmation_status, escalation_status, escalation_reason, confirmation_cutoff_at
                )
                VALUES (%s, %s, 'Brake Fluid Flush', 'Dirty brake fluid',
                        'pending', 'appointment', '2026-10-08 14:00:00', 60, %s,
                        'pending_agent_confirmation', 'escalated', 'TIMEOUT_NO_RESPONSE', CURRENT_TIMESTAMP)
                RETURNING id;
                """,
                (customer_id, vehicle_id, agent_id)
            )
            req_id = cursor.fetchone()["id"]

            # 6. Reservation
            starts_at = dt.datetime(2026, 10, 8, 14, 0)
            ends_at = dt.datetime(2026, 10, 8, 15, 0)
            cursor.execute(
                """
                INSERT INTO appointment_reservations (service_request_id, staff_agent_id, starts_at, ends_at, status)
                VALUES (%s, %s, %s, %s, 'ACTIVE')
                RETURNING id;
                """,
                (req_id, agent_id, starts_at, ends_at)
            )

            conn.commit()

    return {
        "request_id": req_id,
        "original_agent_id": agent_id,
        "candidate_agent_id": candidate_id,
    }


def test_get_service_requests_with_escalated_filter(client, setup_escalated_request, monkeypatch):
    from serviceBot.services import timezone_service
    current = dt.datetime(2026, 10, 7, 12, tzinfo=timezone_service.get_business_zoneinfo())
    monkeypatch.setattr(timezone_service, "now_in_business_tz", lambda: current)
    data = setup_escalated_request
    resp = client.get("/api/v1/portal/service-requests?escalated=true")
    assert resp.status_code == 200
    items = resp.json()
    assert isinstance(items, list)
    assert len(items) >= 1

    # Find the target escalated item
    target = next((item for item in items if item["id"] == data["request_id"]), None)
    assert target is not None
    assert target["escalation_status"] == "escalated"
    assert target["escalation_reason"] == "TIMEOUT_NO_RESPONSE"
    assert "candidate_agents" in target
    assert isinstance(target["candidate_agents"], list)
    assert any(c["id"] == data["candidate_agent_id"] for c in target["candidate_agents"])


def test_reassign_service_request_success(client, setup_escalated_request, monkeypatch):
    from types import SimpleNamespace
    from serviceBot.services import booking, timezone_service

    # The fixture owns a fixed October 8 reservation; keep its clock fixed too.
    current = dt.datetime(2026, 10, 7, 12, tzinfo=timezone_service.get_business_zoneinfo())
    class DateTimeMeta(type):
        def __instancecheck__(cls, value):
            return isinstance(value, dt.datetime)
    class FrozenDateTime(dt.datetime, metaclass=DateTimeMeta):
        @classmethod
        def now(cls, tz=None):
            return current.astimezone(tz) if tz else current.replace(tzinfo=None)
    clock = SimpleNamespace(**vars(dt))
    clock.datetime = FrozenDateTime
    monkeypatch.setattr(booking, "dt_mod", clock)
    monkeypatch.setattr(timezone_service, "now_in_business_tz", lambda: current)
    data = setup_escalated_request
    req_id = data["request_id"]
    new_agent_id = data["candidate_agent_id"]

    with patch("serviceBot.services.twilio_sms.TwilioSMSClient.send_sms") as mock_sms:
        mock_sms.return_value = {"status": "DELIVERED", "sid": "SM_REASSIGN_001"}
        resp = client.post(
            f"/api/v1/portal/service-requests/{req_id}/reassign",
            json={
                "new_agent_id": new_agent_id,
                "reason": "Technician unavailable / timeout"
            }
        )

    assert resp.status_code == 200
    res_data = resp.json()
    assert res_data["success"] is True
    assert res_data["new_agent_id"] == new_agent_id
    assert res_data["escalation_status"] == "reassigned"

    # Verify DB state
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("SELECT staff_agent_id, escalation_status, confirmation_status FROM service_requests WHERE id = %s;", (req_id,))
            row = cursor.fetchone()
            assert row["staff_agent_id"] == new_agent_id
            assert row["escalation_status"] == "reassigned"
            assert row["confirmation_status"] == "pending_agent_confirmation"

            cursor.execute("SELECT staff_agent_id FROM appointment_reservations WHERE service_request_id = %s;", (req_id,))
            res_row = cursor.fetchone()
            assert res_row["staff_agent_id"] == new_agent_id


def test_reassign_invalid_request_or_agent(client, setup_escalated_request):
    data = setup_escalated_request
    # 1. Nonexistent request
    resp = client.post(
        "/api/v1/portal/service-requests/9999999/reassign",
        json={"new_agent_id": data["candidate_agent_id"]}
    )
    assert resp.status_code == 404

    # 2. Nonexistent agent
    resp = client.post(
        f"/api/v1/portal/service-requests/{data['request_id']}/reassign",
        json={"new_agent_id": 9999999}
    )
    assert resp.status_code == 404


def test_portal_config_get_and_update(client):
    # GET config
    resp = client.get("/api/v1/portal/config")
    assert resp.status_code == 200
    cfg = resp.json()
    assert "min_booking_buffer_hours" in cfg

    # UPDATE config
    update_payload = {
        "min_booking_buffer_hours": 3,
        "sla_advance_booking_hours": 5.0,
        "supervisor_alert_phone": "+19195550999"
    }
    post_resp = client.post("/api/v1/portal/config", json=update_payload)
    assert post_resp.status_code == 200

    # Verify persistence
    get_resp = client.get("/api/v1/portal/config")
    updated_cfg = get_resp.json()
    assert updated_cfg["min_booking_buffer_hours"] == 3
    assert updated_cfg["sla_advance_booking_hours"] == 5.0
    assert updated_cfg["supervisor_alert_phone"] == "+19195550999"

    # Reset back to original values
    client.post(
        "/api/v1/portal/config",
        json={
            "min_booking_buffer_hours": 4,
            "sla_advance_booking_hours": 4.0,
            "supervisor_alert_phone": "+14242704893"
        }
    )


def test_available_agents_for_escalated_request_checks_actual_availability(client, setup_escalated_request):
    data = setup_escalated_request
    req_id = data["request_id"]

    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("SELECT id FROM staff_agents WHERE phone_number = '+19195554444';")
            t3 = cursor.fetchone()
            if not t3:
                cursor.execute(
                    """
                    INSERT INTO staff_agents (name, role, email, phone_number)
                    VALUES ('Tech Three', 'technician', 'tech.three@example.com', '+19195554444')
                    RETURNING id;
                    """
                )
                t3 = cursor.fetchone()
            tech3_id = t3["id"]
            conn.commit()

    # 1. Fetch available agents - Tech Three has no conflicting appointments, so must be Available
    resp = client.get(f"/api/v1/portal/service-requests/{req_id}/available-agents")
    assert resp.status_code == 200
    agents = resp.json()["agents"]
    candidate = next((a for a in agents if a["id"] == tech3_id), None)
    assert candidate is not None
    assert candidate["is_available"] is True, f"Expected Tech Three to be available, got: {candidate}"
    assert candidate["reason"] == "Available"
    assert "current_job_count_today" in candidate

    # 2. Add an overlapping appointment for Tech Three in service_requests at the same time
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                """
                INSERT INTO service_requests (
                    customer_id, vehicle_id, service_type, issue_description,
                    status, booking_type, booking_time, duration_minutes, staff_agent_id
                )
                VALUES (%s, %s, 'Oil Change', 'Routine oil change',
                        'pending', 'appointment', '2026-10-08 14:00:00', 60, %s)
                RETURNING id;
                """,
                (1, 1, tech3_id)
            )
            overlap_req_id = cursor.fetchone()["id"]
            conn.commit()

    try:
        # 3. Tech Three should now be detected as busy due to the conflicting appointment!
        resp2 = client.get(f"/api/v1/portal/service-requests/{req_id}/available-agents")
        assert resp2.status_code == 200
        agents2 = resp2.json()["agents"]
        candidate2 = next((a for a in agents2 if a["id"] == tech3_id), None)
        assert candidate2 is not None
        assert candidate2["is_available"] is False, f"Expected Tech Three to be busy with overlapping appointment, got: {candidate2}"
        assert candidate2["reason"] == "Booked for another appointment"
    finally:
        with get_db_connection() as conn:
            with dict_cursor(conn) as cursor:
                cursor.execute("DELETE FROM service_requests WHERE id = %s;", (overlap_req_id,))
                conn.commit()


