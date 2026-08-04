import pytest
from fastapi.testclient import TestClient
from serviceBot.main import app
from serviceBot.db.connection import get_db_connection
from serviceBot.db.queries import check_availability, book_appointment

client = TestClient(app)

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

def test_reschedule_appointment_checks_google_calendar(monkeypatch):
    from serviceBot.db.queries import reschedule_appointment
    # Clean up and seed
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM vehicles WHERE customer_id = 999;")
        cursor.execute("DELETE FROM service_requests WHERE customer_id = 999;")
        cursor.execute("DELETE FROM customers WHERE id = 999;")
        cursor.execute("INSERT INTO staff_agents (id, name, role) VALUES (1, 'Agent 1', 'Advisor') ON CONFLICT (id) DO NOTHING;")
        cursor.execute("INSERT INTO staff_agents (id, name, role) VALUES (2, 'Agent 2', 'Advisor') ON CONFLICT (id) DO NOTHING;")
        # Insert customer
        cursor.execute("INSERT INTO customers (id, name, phone, email) VALUES (999, 'Test Reschedule Customer', '555-999-9999', 'cust@example.com');")
        # Insert vehicle
        cursor.execute("INSERT INTO vehicles (id, customer_id, make, model, year) VALUES (999, 999, 'Honda', 'Civic', 2020);")
        # Insert service request
        cursor.execute("""
            INSERT INTO service_requests (id, customer_id, vehicle_id, service_type, issue_description, status, booking_type, booking_time, staff_agent_id)
            VALUES (999, 999, 999, 'Oil Change', 'Needs oil change', 'pending', 'appointment', '2026-06-12 10:00:00', 1);
        """)
        conn.commit()

    # Mock google_calendar check: agent 1 is busy, agent 2 is free.
    called_agents = []
    def mock_is_agent_free(agent_id, slot_datetime_str, duration_minutes=60):
        called_agents.append(agent_id)
        if agent_id == 1:
            return False # busy
        return True # agent 2 is free

    monkeypatch.setattr("serviceBot.services.google_calendar.is_agent_free", mock_is_agent_free)
    monkeypatch.setattr("serviceBot.services.google_calendar.create_agent_calendar_event", lambda *args, **kwargs: True)

    success = reschedule_appointment(appointment_id=999, new_datetime="2026-06-12 11:00:00")
    assert success is True

    # Check database changes
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # Verify service request details updated with agent 2 at new time
        cursor.execute("SELECT booking_time, staff_agent_id FROM service_requests WHERE id = 999;")
        row = cursor.fetchone()
        assert row["booking_time"] == "2026-06-12 11:00:00"
        assert row["staff_agent_id"] == 2

    # Clean up
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM service_requests WHERE id = 999;")
        cursor.execute("DELETE FROM customers WHERE id = 999;")
        conn.commit()

