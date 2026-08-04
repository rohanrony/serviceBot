import pytest
from fastapi.testclient import TestClient
from serviceBot.main import app
from serviceBot.db.connection import get_db_connection, dict_cursor

client = TestClient(app)

def test_manual_create_service_request():
    payload = {
        "customer": {
            "name": "Manual Test User",
            "phone": "+15559991234"
        },
        "vehicle": {
            "make": "Toyota",
            "model": "Camry",
            "year": 2021,
            "vin": "12345678901234567"
        },
        "service_request": {
            "service_type": "Oil Change",
            "issue_description": "Manual creation test",
            "slot_id": None
        }
    }
    response = client.post("/api/v1/portal/service-requests", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["success"] is True
    assert "request_id" in data
    
    # Verify in DB
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("SELECT * FROM service_requests WHERE id = %s", (data["request_id"],))
            sr = cursor.fetchone()
            assert sr is not None
            assert sr["issue_description"] == "Manual creation test"
            assert sr["service_type"] == "Oil Change"

def test_manual_edit_service_request():
    # Setup - seed a request first
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("INSERT INTO customers (name, phone) VALUES ('Edit User', '+15557776666') ON CONFLICT (phone) DO NOTHING")
            cursor.execute("SELECT id FROM customers WHERE phone = '+15557776666'")
            customer_id = cursor.fetchone()["id"]
            
            cursor.execute("INSERT INTO vehicles (customer_id, make, model, year) VALUES (%s, 'Honda', 'Accord', 2010) RETURNING id", (customer_id,))
            vehicle_id = cursor.fetchone()["id"]
            
            cursor.execute("""
                INSERT INTO service_requests (customer_id, vehicle_id, service_type, issue_description, status) 
                VALUES (%s, %s, 'Brakes', 'Squeaky brakes', 'pending') RETURNING id
            """, (customer_id, vehicle_id))
            request_id = cursor.fetchone()["id"]
            
    payload = {
        "issue_description": "Squeaky brakes and rotors",
        "vehicle_details": {
            "make": "Honda",
            "model": "Civic",
            "year": 2012,
            "vin": "HND12345"
        }
    }
    
    response = client.put(f"/api/v1/portal/service-requests/{request_id}", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    
    # Verify in DB
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("SELECT * FROM service_requests WHERE id = %s", (request_id,))
            sr = cursor.fetchone()
            assert sr["issue_description"] == "Squeaky brakes and rotors"
            
            cursor.execute("SELECT * FROM vehicles WHERE id = %s", (sr["vehicle_id"],))
            veh = cursor.fetchone()
            assert veh["model"] == "Civic"
            assert veh["year"] == 2012
