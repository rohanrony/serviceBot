import sys
from fastapi.testclient import TestClient
from unittest.mock import patch
from serviceBot.main import app

client = TestClient(app)

@patch("serviceBot.api.telephony.lookup_customer_by_phone")
@patch("serviceBot.api.telephony.book_appointment")
def run_debug(mock_book, mock_lookup):
    mock_lookup.return_value = {
        "customer_id": 42,
        "name": "Sarah Johnson",
        "phone": "5551234567",
        "make": "Honda",
        "model": "Civic",
        "year": 2020,
        "open_sr_id": 101
    }
    mock_book.return_value = 202
    
    import serviceBot.api.telephony as tel
    print("BEFORE CALL, module book_appointment:", tel.book_appointment)
    
    payload = {
        "tool_call_id": "call_789",
        "name": "book_appointment",
        "arguments": {
            "phone": "555-123-4567",
            "appointment_datetime": "2026-06-10 10:00:00",
            "service_type": "Brake repair"
        }
    }
    response = client.post("/api/v1/voice/tools", json=payload)
    print("STATUS CODE:", response.status_code)
    print("RESPONSE JSON:", response.json())
    print("AFTER CALL, module book_appointment:", tel.book_appointment)

if __name__ == "__main__":
    run_debug()
