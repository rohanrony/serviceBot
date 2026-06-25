import json
from fastapi.testclient import TestClient
from serviceBot.main import app

client = TestClient(app)

def test_mock_flow():
    # 1. Create service request
    print("--- Creating Service Request ---")
    sr_payload = {
        "tool_call_id": "mock_sr_1",
        "name": "create_service_request",
        "arguments": {
            "customer_name": "Shyamili John",
            "phone": "4248429241",
            "make": "Toyota",
            "model": "Corolla",
            "year": 2020,
            "issue_description": "AC malfunction",
            "service_type": "AC Service"
        }
    }
    r = client.post("/api/v1/voice/tools", json=sr_payload)
    print(r.status_code, r.text)

    # 2. Book appointment
    print("\n--- Booking Appointment ---")
    book_payload = {
        "tool_call_id": "mock_book_1",
        "name": "book_appointment",
        "arguments": {
            "phone": "4248429241",
            "appointment_datetime": "2026-06-12 11:00:00",
            "service_type": "AC Service"
        }
    }
    r = client.post("/api/v1/voice/tools", json=book_payload)
    print(r.status_code, r.text)
    book_res = r.json()
    appointment_id = book_res.get("result", {}).get("appointment_id")

    # 3. Request callback
    print("\n--- Creating Callback Request ---")
    callback_payload = {
        "tool_call_id": "mock_callback_1",
        "name": "request_callback",
        "arguments": {
            "phone": "4248429241",
            "customer_name": "Shyamili John",
            "preferred_time": "June 12th Friday 1:00 PM"
        }
    }
    r = client.post("/api/v1/voice/tools", json=callback_payload)
    print(r.status_code, r.text)

    # 4. Reschedule appointment
    print("\n--- Rescheduling Appointment ---")
    resched_payload = {
        "tool_call_id": "mock_resched_1",
        "name": "reschedule_appointment",
        "arguments": {
            "phone": "4248429241",
            "appointment_id": appointment_id,
            "new_appointment_datetime": "2026-06-12 14:00:00"
        }
    }
    r = client.post("/api/v1/voice/tools", json=resched_payload)
    print(r.status_code, r.text)

if __name__ == "__main__":
    test_mock_flow()
