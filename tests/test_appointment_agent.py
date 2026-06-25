import sqlite3
import pytest
from unittest.mock import patch
from serviceBot.db.connection import DDL_SCHEMA
from serviceBot.db.queries import check_availability, book_appointment

@pytest.fixture
def mock_db(tmp_path):
    """Create a temporary SQLite database, initialize, and seed mock data."""
    db_file = tmp_path / "test_appointment.db"
    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.executescript(DDL_SCHEMA)
    
    cursor = conn.cursor()
    # Seed staff agent (needed for availability/booking)
    cursor.execute(
        "INSERT INTO staff_agents (id, name, role, email) VALUES (?, ?, ?, ?);",
        (1, 'John Doe', 'Service Advisor', 'john.doe@example.com')
    )
    # Seed customer
    cursor.execute(
        "INSERT INTO customers (id, name, phone, email) VALUES (?, ?, ?, ?);",
        (1, 'Sarah Johnson', '+15551234567', 'sarah.j@example.com')
    )
    # Seed vehicle
    cursor.execute(
        "INSERT INTO vehicles (id, customer_id, make, model, year, vin) VALUES (?, ?, ?, ?, ?, ?);",
        (1, 1, 'Honda', 'Civic', 2020, '1HGCR2F8LAA123456')
    )
    # Seed service request
    cursor.execute(
        "INSERT INTO service_requests (id, customer_id, vehicle_id, service_type, issue_description, status) VALUES (?, ?, ?, ?, ?, ?);",
        (1, 1, 1, 'Brake repair', 'Grinding noise.', 'pending')
    )
    # Seed an existing booked appointment to make a slot busy (e.g. 2026-06-09 14:00:00)
    cursor.execute(
        "INSERT INTO service_requests (id, customer_id, vehicle_id, service_type, issue_description, status, booking_type, booking_time, staff_agent_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
        (2, 1, 1, 'Oil Change', 'Regular maintenance', 'pending', 'appointment', '2026-06-09 14:00:00', 1)
    )
    # Seed services
    cursor.execute(
        "INSERT INTO services (name, description, price_range, duration_minutes) VALUES (?, ?, ?, ?);",
        ("Brake repair", "Brake service", "$100-200", 60)
    )
    cursor.execute(
        "INSERT INTO services (name, description, price_range, duration_minutes) VALUES (?, ?, ?, ?);",
        ("Oil Change", "Oil Change service", "$50-80", 45)
    )
    # Seed mock slots
    cursor.execute(
        "INSERT INTO mock_calendar_slots (slot_datetime, is_booked, staff_agent_id) VALUES (?, ?, ?);",
        ('2026-06-09 14:00:00', 1, 1)
    )
    cursor.execute(
        "INSERT INTO mock_calendar_slots (slot_datetime, is_booked, staff_agent_id) VALUES (?, ?, ?);",
        ('2026-06-09 16:00:00', 0, 1)
    )
    cursor.execute(
        "INSERT INTO mock_calendar_slots (slot_datetime, is_booked, staff_agent_id) VALUES (?, ?, ?);",
        ('2026-06-10 10:00:00', 0, 1)
    )
    conn.commit()
    
    with patch("serviceBot.db.connection.DB_PATH", str(db_file)):
        with patch("serviceBot.db.connection._db_initialized", True):
            yield conn
            
    conn.close()

def test_check_availability_only_unbooked(mock_db):
    """
    Assert check_availability() returns only unbooked slots.
    """
    # Query slots starting from 2026-06-09
    slots = check_availability(preferred_date="2026-06-09")
    
    # It should not include '2026-06-09 14:00:00' because it is booked.
    assert "2026-06-09 14:00:00" not in slots
    # Standard weekday hours should be available
    assert "2026-06-09 16:00:00" in slots
    assert "2026-06-10 10:00:00" in slots

def test_book_appointment_updates_is_booked(mock_db):
    """
    Assert book_appointment() updates the service request.
    """
    slot = "2026-06-09 16:00:00"
    
    # Book the appointment
    appt_id = book_appointment(
        customer_id=1,
        service_request_id=1,
        appointment_datetime=slot,
        service_type="Brake repair"
    )
    
    assert appt_id is not None
    
    # Query database directly to verify service_request has staff agent and time
    cursor = mock_db.cursor()
    cursor.execute("SELECT booking_time, staff_agent_id FROM service_requests WHERE id = ?;", (1,))
    row = cursor.fetchone()
    assert row is not None
    assert row["booking_time"] == slot
    assert row["staff_agent_id"] == 1


def test_appointment_booking_node_success(mock_db):
    """
    Verify appointment_booking_node extracts the slot from state messages,
    books the appointment, and returns the appointment_id.
    """
    from serviceBot.graph.nodes import appointment_booking_node
    from langchain_core.messages import HumanMessage, AIMessage

    initial_state = {
        "messages": [HumanMessage(content="I want to book the slot at 2026-06-09 16:00:00")],
        "customer": {
            "id": 1,
            "name": "Sarah Johnson",
            "phone": "+15551234567",
            "email": "sarah.j@example.com",
            "vehicle_make": "Honda",
            "vehicle_model": "Civic",
            "vehicle_year": 2020
        },
        "service_request_id": 1,
        "appointment_id": None,
        "current_agent": "appointment",
        "dtmf_active": False
    }

    with patch("serviceBot.graph.nodes.ChatOpenAI") as mock_chat:
        mock_instance = mock_chat.return_value
        mock_instance.invoke.return_value = AIMessage(content="Perfect, I have booked your appointment.")

        final_state = appointment_booking_node(initial_state)

        # Assert appointment_id is generated and returned
        assert final_state["appointment_id"] is not None
        # Assert database service request has the booked time and agent
        cursor = mock_db.cursor()
        cursor.execute("SELECT booking_time, staff_agent_id FROM service_requests WHERE id = ?;", (1,))
        row = cursor.fetchone()
        assert row is not None
        assert row["booking_time"] == "2026-06-09 16:00:00"
        assert row["staff_agent_id"] == 1

