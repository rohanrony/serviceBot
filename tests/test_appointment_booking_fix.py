import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from serviceBot.main import app
from serviceBot.db.queries import book_appointment, get_service_required_fields

client = TestClient(app)

def test_get_service_required_fields_non_exact_catalog():
    """Verify get_service_required_fields handles non-exact service names gracefully."""
    fields = get_service_required_fields("air conditioning service")
    assert fields is not None
    assert "name" in fields
    assert fields["duration_minutes"] > 0

@patch("serviceBot.api.telephony.lookup_customer_by_phone")
@patch("serviceBot.api.telephony.book_appointment")
def test_voice_tools_book_appointment_missing_name_fallback(mock_book, mock_lookup):
    """Verify that if customer_name is missing/unknown, it defaults gracefully instead of throwing validation error."""
    mock_lookup.return_value = None
    mock_book.return_value = 999

    payload = {
        "tool_call_id": "call_fallback_name",
        "name": "book_appointment",
        "arguments": {
            "phone": "424-270-4893",
            "appointment_datetime": "2026-08-10 14:00:00",
            "service_type": "air conditioning service",
            "customer_name": "Unknown Customer"
        }
    }
    response = client.post("/api/v1/voice/tools", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["result"]["success"] is True
    assert data["result"]["appointment_id"] == 999

@patch("serviceBot.api.telephony.lookup_customer_by_phone")
@patch("serviceBot.api.telephony.book_appointment")
def test_voice_tools_book_appointment_ac_service_catalog_match(mock_book, mock_lookup):
    """Verify booking an AC service with multi-word catalog variants succeeds."""
    mock_lookup.return_value = {
        "customer_id": 10,
        "name": "Rohan Roy",
        "phone": "4242704893",
        "make": "Toyota",
        "model": "Corolla",
        "year": 2020
    }
    mock_book.return_value = 1001

    payload = {
        "tool_call_id": "call_ac_service",
        "name": "book_appointment",
        "arguments": {
            "phone": "424-270-4893",
            "customer_name": "Rohan Roy",
            "appointment_datetime": "2026-08-10 16:00:00",
            "service_type": "air conditioning service"
        }
    }
    response = client.post("/api/v1/voice/tools", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["result"]["success"] is True
    assert data["result"]["appointment_id"] == 1001
