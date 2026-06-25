import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch
from serviceBot.main import app
from serviceBot.db.connection import get_db_connection

client = TestClient(app)

def test_create_callback_request_query():
    """Test that callback requests can be created in the database and queried."""
    from serviceBot.db.queries import create_callback_request
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        # Ensure a customer exists for testing
        cursor.execute("INSERT OR IGNORE INTO customers (id, name, phone) VALUES (10, 'Test Customer', '555-000-1111')")
        cursor.execute("INSERT OR IGNORE INTO vehicles (id, customer_id, make, model, year) VALUES (20, 10, 'Toyota', 'Corolla', 2015)")
        cursor.execute("INSERT OR IGNORE INTO service_requests (id, customer_id, vehicle_id, service_type, issue_description) VALUES (20, 10, 20, 'Oil Change', 'General service')")
        conn.commit()

    # Create callback
    cb_id = create_callback_request(customer_id=10, service_request_id=20, preferred_time="Today at 4 PM")
    assert cb_id is not None

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM service_requests WHERE id = ?", (cb_id,))
        row = cursor.fetchone()
        assert row is not None
        assert row["customer_id"] == 10
        assert row["booking_type"] == "callback"
        assert row["booking_time"] == "Today at 4 PM"


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
            "preferred_time": "Today at 3 PM"
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
            WHERE sr.id = ?
        """, (cb_id,))
        row = cursor.fetchone()
        assert row is not None
        assert row["name"] == "Callback User"
        assert row["phone"] == "4242704893"
        assert row["service_type"] == "AC Service & Repair"
        assert row["issue_description"] == "AC blows hot air"
        assert row["booking_time"] == "Today at 3 PM"
