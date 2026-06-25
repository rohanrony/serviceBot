import pytest
from fastapi.testclient import TestClient
from serviceBot.main import app
from serviceBot.db.connection import get_db_connection

client = TestClient(app)

def test_get_customer_appointments_query():
    """Test retrieving active appointments by customer phone number."""
    from serviceBot.db.queries import get_customer_appointments
    
    # Seed a known customer and appointment
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO customers (id, name, phone) VALUES (15, 'Resched Customer', '555-999-8888')")
        cursor.execute("INSERT OR IGNORE INTO service_requests (id, customer_id, vehicle_id, service_type, issue_description, booking_type, booking_time) VALUES (50, 15, 1, 'AC Service & Repair', 'Symptom description', 'appointment', '2026-06-12 10:00:00')")
        conn.commit()
        
    appts = get_customer_appointments("555-999-8888")
    assert len(appts) >= 1
    assert appts[0]["id"] == 50
    assert appts[0]["appointment_datetime"] == "2026-06-12 10:00:00"
    assert appts[0]["status"] == "pending"


def test_reschedule_appointment_query():
    """Test rescheduling an appointment to a new available slot."""
    from serviceBot.db.queries import reschedule_appointment
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        # Seed customer, appointment and slot
        cursor.execute("INSERT OR IGNORE INTO customers (id, name, phone) VALUES (16, 'Resched Customer 2', '555-999-7777')")
        cursor.execute("INSERT OR IGNORE INTO mock_calendar_slots (slot_datetime, is_booked) VALUES ('2026-06-15 14:00:00', 1)")
        cursor.execute("INSERT OR IGNORE INTO mock_calendar_slots (slot_datetime, is_booked) VALUES ('2026-06-15 16:00:00', 0)")
        cursor.execute("INSERT OR IGNORE INTO service_requests (id, customer_id, vehicle_id, service_type, issue_description, booking_type, booking_time) VALUES (51, 16, 1, 'Oil Change', 'General repair', 'appointment', '2026-06-15 14:00:00')")
        conn.commit()

    # Reschedule
    success = reschedule_appointment(appointment_id=51, new_datetime="2026-06-15 16:00:00")
    assert success is True

    # Verify slots and appointment status
    with get_db_connection() as conn:
        cursor = conn.cursor()
        # Old slot should be unbooked
        cursor.execute("SELECT is_booked FROM mock_calendar_slots WHERE slot_datetime = '2026-06-15 14:00:00'")
        assert cursor.fetchone()["is_booked"] == 0
        
        # New slot should be booked
        cursor.execute("SELECT is_booked FROM mock_calendar_slots WHERE slot_datetime = '2026-06-15 16:00:00'")
        assert cursor.fetchone()["is_booked"] == 1
        
        # Appointment should be updated
        cursor.execute("SELECT booking_time FROM service_requests WHERE id = 51")
        row = cursor.fetchone()
        assert row["booking_time"] == "2026-06-15 16:00:00"


def test_voice_tools_reschedule_appointment_flat():
    """Test that voice tool reschedule_appointment flat payload executes correctly."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        # Seed database state
        cursor.execute("INSERT OR IGNORE INTO customers (id, name, phone) VALUES (17, 'Resched Customer 3', '424-270-4893')")
        cursor.execute("INSERT OR IGNORE INTO mock_calendar_slots (slot_datetime, is_booked) VALUES ('2026-06-16 10:00:00', 1)")
        cursor.execute("INSERT OR IGNORE INTO mock_calendar_slots (slot_datetime, is_booked) VALUES ('2026-06-16 11:00:00', 0)")
        cursor.execute("INSERT OR IGNORE INTO service_requests (id, customer_id, vehicle_id, service_type, issue_description, booking_type, booking_time) VALUES (52, 17, 1, 'Oil Change', 'General repair', 'appointment', '2026-06-16 10:00:00')")
        conn.commit()

    payload = {
        "phone": "424-270-4893",
        "new_appointment_datetime": "2026-06-16 11:00:00"
    }
    
    response = client.post("/api/v1/voice/tools?name=reschedule_appointment", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["result"]["success"] is True
    assert data["result"]["appointment_id"] == 52
    
    # Verify DB update
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT booking_time FROM service_requests WHERE id = 52")
        row = cursor.fetchone()
        assert row["booking_time"] == "2026-06-16 11:00:00"
