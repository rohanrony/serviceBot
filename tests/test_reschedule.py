import datetime as dt_mod

import pytest
from fastapi.testclient import TestClient
from serviceBot.main import app
from serviceBot.db.connection import dict_cursor, get_db_connection

client = TestClient(app)


def _future_business_datetime(hour: int, days_ahead: int) -> str:
    candidate = dt_mod.date.today() + dt_mod.timedelta(days=days_ahead)
    while candidate.weekday() > 4:
        candidate += dt_mod.timedelta(days=1)
    return f"{candidate.isoformat()} {hour:02d}:00:00"

def test_get_customer_appointments_query():
    """Test retrieving active appointments by customer phone number."""
    from serviceBot.db.queries import get_customer_appointments
    
    # Seed a known customer and appointment
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM service_requests WHERE id = 5000 OR customer_id IN (SELECT id FROM customers WHERE id = 1500 OR phone = '555-999-8888');")
        cursor.execute("DELETE FROM customers WHERE id = 1500 OR phone = '555-999-8888';")
        cursor.execute("INSERT INTO customers (id, name, phone) VALUES (1500, 'Resched Customer', '555-999-8888')")
        cursor.execute("INSERT INTO service_requests (id, customer_id, vehicle_id, service_type, issue_description, booking_type, booking_time) VALUES (5000, 1500, 1, 'AC Service & Repair', 'Symptom description', 'appointment', '2026-06-12 10:00:00')")
        conn.commit()
        
    appts = get_customer_appointments("555-999-8888")
    assert len(appts) == 1
    assert appts[0]["id"] == 5000
    assert appts[0]["service_type"] == "AC Service & Repair"
    assert appts[0]["appointment_datetime"] == "2026-06-12 10:00:00"
    assert appts[0]["status"] == "pending"


def test_reschedule_appointment_query():
    """Rescheduling moves a real reservation transactionally to a future local slot."""
    from serviceBot.db.queries import book_appointment, reschedule_appointment

    old_time = _future_business_datetime(10, days_ahead=35)
    new_time = _future_business_datetime(12, days_ahead=35)
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                "INSERT INTO customers (name, phone) VALUES ('Resched Customer 2', '+15550123331') RETURNING id;"
            )
            customer_id = cursor.fetchone()["id"]
            cursor.execute(
                "INSERT INTO vehicles (customer_id, make, model, year) VALUES (%s, 'Honda', 'Accord', 2022) RETURNING id;",
                (customer_id,),
            )
            vehicle_id = cursor.fetchone()["id"]
            cursor.execute(
                """
                INSERT INTO service_requests (customer_id, vehicle_id, service_type, issue_description, status)
                VALUES (%s, %s, 'Oil Change', 'General repair', 'pending')
                RETURNING id;
                """,
                (customer_id, vehicle_id),
            )
            request_id = cursor.fetchone()["id"]

    appointment_id = book_appointment(
        customer_id=customer_id,
        service_request_id=request_id,
        appointment_datetime=old_time,
        service_type="Oil Change",
    )
    assert appointment_id == request_id
    assert reschedule_appointment(appointment_id=appointment_id, new_datetime=new_time) is True

    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                "SELECT booking_time FROM service_requests WHERE id = %s;",
                (appointment_id,),
            )
            row = cursor.fetchone()
            assert row["booking_time"] == new_time

            cursor.execute("DELETE FROM outbox_notifications WHERE request_id = %s;", (appointment_id,))
            cursor.execute("DELETE FROM service_requests WHERE id = %s;", (appointment_id,))
            cursor.execute("DELETE FROM vehicles WHERE id = %s;", (vehicle_id,))
            cursor.execute("DELETE FROM customers WHERE id = %s;", (customer_id,))

def test_voice_tools_reschedule_appointment_flat():
    """The voice-tool reschedule path moves an existing future reservation."""
    from serviceBot.db.queries import book_appointment

    old_time = _future_business_datetime(10, days_ahead=42)
    new_time = _future_business_datetime(12, days_ahead=42)
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                "INSERT INTO customers (name, phone) VALUES ('Resched Customer 3', '+15550124441') RETURNING id;"
            )
            customer_id = cursor.fetchone()["id"]
            cursor.execute(
                "INSERT INTO vehicles (customer_id, make, model, year) VALUES (%s, 'Toyota', 'Camry', 2021) RETURNING id;",
                (customer_id,),
            )
            vehicle_id = cursor.fetchone()["id"]
            cursor.execute(
                """
                INSERT INTO service_requests (customer_id, vehicle_id, service_type, issue_description, status)
                VALUES (%s, %s, 'Oil Change', 'General repair', 'pending')
                RETURNING id;
                """,
                (customer_id, vehicle_id),
            )
            request_id = cursor.fetchone()["id"]

    appointment_id = book_appointment(
        customer_id=customer_id,
        service_request_id=request_id,
        appointment_datetime=old_time,
        service_type="Oil Change",
    )

    response = client.post(
        "/api/v1/voice/tools?name=reschedule_appointment",
        json={
            "phone": "+15550124441",
            "new_appointment_datetime": new_time,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["result"]["success"] is True
    assert data["result"]["appointment_id"] == appointment_id

    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                "SELECT booking_time FROM service_requests WHERE id = %s;",
                (appointment_id,),
            )
            row = cursor.fetchone()
            assert row["booking_time"] == new_time

            cursor.execute("DELETE FROM outbox_notifications WHERE request_id = %s;", (appointment_id,))
            cursor.execute("DELETE FROM service_requests WHERE id = %s;", (appointment_id,))
            cursor.execute("DELETE FROM vehicles WHERE id = %s;", (vehicle_id,))
            cursor.execute("DELETE FROM customers WHERE id = %s;", (customer_id,))
