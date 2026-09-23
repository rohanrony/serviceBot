from datetime import date, timedelta
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch
from serviceBot.main import app
from serviceBot.db.connection import get_db_connection

client = TestClient(app)


def _next_business_slot(hour: int) -> str:
    candidate = date.today() + timedelta(days=1)
    while candidate.weekday() > 4:
        candidate += timedelta(days=1)
    return f"{candidate.isoformat()} {hour:02d}:00:00"


def test_create_callback_request_query():
    """Test that callback requests can be created in the database and queried."""
    from serviceBot.db.queries import create_callback_request
    from serviceBot.db.connection import dict_cursor

    phone = "+15550001111"
    reservation_time = _next_business_slot(16)
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("DELETE FROM service_requests WHERE customer_id IN (SELECT id FROM customers WHERE phone = %s);", (phone,))
            cursor.execute("DELETE FROM customers WHERE phone = %s;", (phone,))
            cursor.execute("INSERT INTO customers (name, phone) VALUES ('Test Customer', %s) RETURNING id;", (phone,))
            customer_id = cursor.fetchone()["id"]
            cursor.execute("INSERT INTO vehicles (customer_id, make, model, year) VALUES (%s, 'Toyota', 'Corolla', 2015) RETURNING id;", (customer_id,))
            vehicle_id = cursor.fetchone()["id"]
            cursor.execute("INSERT INTO service_requests (customer_id, vehicle_id, service_type, issue_description) VALUES (%s, %s, 'Oil Change', 'General service') RETURNING id;", (customer_id, vehicle_id))
            request_id = cursor.fetchone()["id"]

    try:
        cb_id = create_callback_request(
            customer_id=customer_id,
            service_request_id=request_id,
            preferred_time=reservation_time,
        )
        assert cb_id is not None

        with get_db_connection() as conn:
            with dict_cursor(conn) as cursor:
                cursor.execute("SELECT * FROM service_requests WHERE id = %s;", (cb_id,))
                row = cursor.fetchone()
                assert row is not None
                assert row["customer_id"] == customer_id
                assert row["booking_type"] == "callback"
                assert row["booking_time"] == reservation_time
    finally:
        with get_db_connection() as conn:
            with dict_cursor(conn) as cursor:
                cursor.execute("DELETE FROM service_requests WHERE customer_id = %s;", (customer_id,))
                cursor.execute("DELETE FROM customers WHERE id = %s;", (customer_id,))


def test_get_callbacks_endpoint():
    """Test that GET /api/v1/portal/callbacks returns callback requests."""
    response = client.get("/api/v1/portal/callbacks")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    # The seeded callbacks should be returned
    if len(data) > 0:
        assert "customer_name" in data[0]
        assert "phone" in data[0]
        assert "status" in data[0]


def test_voice_tools_request_callback():
    """Test that voice tool request_callback creates customer, service request, and callback request."""
    # Ensure service is seeded so matching succeeds
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM services WHERE name = 'AC Service & Repair';")
            cursor.execute("INSERT INTO services (name, description, price_range, duration_minutes) VALUES ('AC Service & Repair', 'A/C service', '$150-250', 60);")
            cursor.execute("DELETE FROM service_requests WHERE customer_id IN (SELECT id FROM customers WHERE phone IN ('4242704893', '424-270-4893'));")
            cursor.execute("DELETE FROM customers WHERE phone IN ('4242704893', '424-270-4893');")
            conn.commit()

    # Ensure any mock customer is cleared first or doesn't clash
    payload = {
        "tool_call_id": "call_callback_1",
        "name": "request_callback",
        "arguments": {
            "customer_name": "Callback User",
            "phone": "424-270-4893",
            "service_type": "AC Service & Repair",
            "make": "Ford",
            "model": "F-150",
            "year": 2018,
            "issue_description": "AC blows hot air",
            "preferred_time": _next_business_slot(15),
        }
    }
    
    response = client.post("/api/v1/voice/tools", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["tool_call_id"] == "call_callback_1"
    assert data["result"]["success"] is True
    assert "callback_id" in data["result"]
    
    cb_id = data["result"]["callback_id"]
    
    # Verify DB state
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT sr.id, c.name, c.phone, sr.service_type, sr.issue_description, sr.booking_time
            FROM service_requests sr
            JOIN customers c ON sr.customer_id = c.id
            WHERE sr.id = %s
        """, (cb_id,))
        row = cursor.fetchone()
        assert row is not None
        assert row["name"] == "Callback User"
        assert row["phone"] == "4242704893"
        assert row["service_type"] == "AC Service & Repair"
        assert row["issue_description"] == "AC blows hot air"
        assert row["booking_time"] == _next_business_slot(15)
