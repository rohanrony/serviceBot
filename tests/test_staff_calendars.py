import datetime as dt_mod

import pytest
from fastapi.testclient import TestClient
from serviceBot.main import app
from serviceBot.db.connection import dict_cursor, get_db_connection
from serviceBot.db.queries import check_availability, book_appointment

client = TestClient(app)


def _future_business_datetime(hour: int, days_ahead: int = 28) -> str:
    candidate = dt_mod.date.today() + dt_mod.timedelta(days=days_ahead)
    while candidate.weekday() > 4:
        candidate += dt_mod.timedelta(days=1)
    return f"{candidate.isoformat()} {hour:02d}:00:00"

@pytest.fixture(autouse=True)
def clean_db():
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM service_requests WHERE booking_time = '2026-06-12 15:00:00';")
        cursor.execute("DELETE FROM service_requests WHERE booking_time = '2026-06-11 09:00:00';")
        conn.commit()
    yield
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM service_requests WHERE booking_time = '2026-06-12 15:00:00';")
        cursor.execute("DELETE FROM service_requests WHERE booking_time = '2026-06-11 09:00:00';")
        conn.commit()

def test_get_staff_agents_endpoint():
    response = client.get("/api/v1/portal/agents")
    assert response.status_code == 200
    agents = response.json()
    assert isinstance(agents, list)
    assert len(agents) >= 3
    # Check seeded agents exist
    names = [a["name"] for a in agents]
    assert "John Doe" in names
    assert "Jane Smith" in names
    assert "Bob Johnson" in names



def test_db_queries_integration():
    # Insert test slot
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO staff_agents (id, name, role) VALUES (1, 'Agent 1', 'Advisor') ON CONFLICT (id) DO NOTHING;")
        cursor.execute("DELETE FROM service_requests WHERE CAST(booking_time AS TEXT) LIKE '2026-10-15 08:00%%';")
        conn.commit()

    # Test check_availability returns standard business slots
    avail = check_availability(preferred_date="2026-10-15 08:00:00")
    # Verify that '2026-10-15 08:00:00' is listed (a standard weekday slot)
    assert "2026-10-15 08:00:00" in avail
    
    # Test book_appointment bookings
    appt_id = book_appointment(
        customer_id=1,
        service_request_id=1,
        appointment_datetime="2026-10-15 08:00:00",
        service_type="Oil Change"
    )
    assert appt_id is not None
    
    # Check that the appointment is booked in service_requests
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT booking_time, staff_agent_id FROM service_requests WHERE id = %s;", (appt_id,))
        row = cursor.fetchone()
        assert row is not None
        assert row["booking_time"] == "2026-10-15 08:00:00"


def test_create_and_delete_staff_agent_endpoint():
    # 1. Create a staff member
    payload = {
        "name": "Alice Williams",
        "role": "Technician",
        "email": "alice.w@example.com"
    }
    response = client.post("/api/v1/portal/agents", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["success"] is True
    agent_id = data["id"]
    assert data["name"] == "Alice Williams"

    # Verify agent exists in the agents list
    get_response = client.get("/api/v1/portal/agents")
    agents = get_response.json()
    names = [a["name"] for a in agents]
    assert "Alice Williams" in names

    # 2. Delete the staff member
    delete_response = client.delete(f"/api/v1/portal/agents/{agent_id}")
    assert delete_response.status_code == 200
    assert delete_response.json()["success"] is True

    # Verify agent is gone
    get_response = client.get("/api/v1/portal/agents")
    agents = get_response.json()
    names = [a["name"] for a in agents]
    assert "Alice Williams" not in names

def test_reschedule_appointment_falls_back_to_local_agent_without_google(monkeypatch):
    """Rescheduling prefers the prior agent but falls back using committed local reservations."""
    from serviceBot.db.queries import reschedule_appointment
    from serviceBot.services.booking import BookingService

    old_time = _future_business_datetime(10)
    target_time = _future_business_datetime(12)
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                "INSERT INTO customers (name, phone) VALUES ('Reschedule Primary', '+15550121111') RETURNING id;"
            )
            primary_customer_id = cursor.fetchone()["id"]
            cursor.execute(
                "INSERT INTO vehicles (customer_id, make, model, year) VALUES (%s, 'Honda', 'Civic', 2020) RETURNING id;",
                (primary_customer_id,),
            )
            primary_vehicle_id = cursor.fetchone()["id"]
            cursor.execute(
                """
                INSERT INTO service_requests (customer_id, vehicle_id, service_type, issue_description, status)
                VALUES (%s, %s, 'Oil Change', 'Needs oil change', 'pending')
                RETURNING id;
                """,
                (primary_customer_id, primary_vehicle_id),
            )
            primary_request_id = cursor.fetchone()["id"]

            cursor.execute(
                "INSERT INTO customers (name, phone) VALUES ('Reschedule Blocker', '+15550122222') RETURNING id;"
            )
            blocker_customer_id = cursor.fetchone()["id"]
            cursor.execute(
                "INSERT INTO vehicles (customer_id, make, model, year) VALUES (%s, 'Ford', 'Focus', 2020) RETURNING id;",
                (blocker_customer_id,),
            )
            blocker_vehicle_id = cursor.fetchone()["id"]
            cursor.execute(
                """
                INSERT INTO service_requests (customer_id, vehicle_id, service_type, issue_description, status)
                VALUES (%s, %s, 'Oil Change', 'Blocks the first agent', 'pending')
                RETURNING id;
                """,
                (blocker_customer_id, blocker_vehicle_id),
            )
            blocker_request_id = cursor.fetchone()["id"]

    booking = BookingService()
    booking.reserve_or_create(
        customer_id=primary_customer_id,
        service_request_id=primary_request_id,
        appointment_datetime=old_time,
        service_type="Oil Change",
        requested_agent_id=1,
    )
    booking.reserve_or_create(
        customer_id=blocker_customer_id,
        service_request_id=blocker_request_id,
        appointment_datetime=target_time,
        service_type="Oil Change",
        requested_agent_id=1,
    )

    def provider_must_not_be_called(*_args, **_kwargs):
        raise AssertionError("Provider availability must not participate in local rescheduling.")

    monkeypatch.setattr("serviceBot.services.google_calendar.is_agent_free", provider_must_not_be_called)

    assert reschedule_appointment(primary_request_id, target_time) is True

    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                "SELECT booking_time, staff_agent_id FROM service_requests WHERE id = %s;",
                (primary_request_id,),
            )
            row = cursor.fetchone()
            assert row["booking_time"] == target_time
            assert row["staff_agent_id"] == 2

            cursor.execute(
                "DELETE FROM outbox_notifications WHERE request_id IN (%s, %s);",
                (primary_request_id, blocker_request_id),
            )
            cursor.execute(
                "DELETE FROM service_requests WHERE id IN (%s, %s);",
                (primary_request_id, blocker_request_id),
            )
            cursor.execute(
                "DELETE FROM vehicles WHERE id IN (%s, %s);",
                (primary_vehicle_id, blocker_vehicle_id),
            )
            cursor.execute(
                "DELETE FROM customers WHERE id IN (%s, %s);",
                (primary_customer_id, blocker_customer_id),
            )

