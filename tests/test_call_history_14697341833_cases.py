import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from serviceBot.main import app

client = TestClient(app)

@patch("serviceBot.api.telephony.lookup_customer_by_phone")
@patch("serviceBot.api.telephony.book_appointment")
def test_book_appointment_elevenlabs_omits_customer_name(mock_book, mock_lookup):
    """
    Case from call 14697341833 (conv_1401kysty93nf7jae1c14jd6c4cp):
    ElevenLabs invokes book_appointment with only phone, appointment_datetime, service_type.
    customer_name is NOT in the JSON payload.
    Must succeed with fallback customer name ('Valued Customer').
    """
    mock_lookup.return_value = None
    mock_book.return_value = 888

    payload = {
        "phone": "469-734-1833",
        "appointment_datetime": "2026-08-03 09:00:00",
        "service_type": "Oil change"
    }
    response = client.post("/api/v1/voice/tools", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["result"]["success"] is True
    assert data["result"]["appointment_id"] == 888


@patch("serviceBot.api.telephony.is_within_business_hours")
@patch("serviceBot.api.telephony.lookup_customer_by_phone")
@patch("serviceBot.api.telephony.handoff_node")
def test_cba_webbook_elevenlabs_alternate_keys(mock_handoff, mock_lookup, mock_hours):
    """
    Case from call 14697341833:
    ElevenLabs invokes cba_webbook with 'phone_number' and 'summary_text' flat keys.
    Must be detected as cba_webhook handoff and return success + transfer_phone_number.
    """
    mock_hours.return_value = True
    mock_lookup.return_value = {"customer_id": 99, "name": "Swapnil Dangi", "phone": "4697341833"}
    mock_handoff.return_value = {"handoff_summary": "Customer needs human assistance for appointment."}

    payload = {
        "phone_number": "+14697341833",
        "summary_text": "Customer wants to book an oil change for a 2020 BMW X3 on August 3rd at 9 AM."
    }
    response = client.post("/api/v1/voice/tools", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["result"]["success"] is True
    assert "transferred" in data["result"]["message"].lower()
    assert "transfer_phone_number" in data["result"]


@patch("serviceBot.api.telephony.lookup_customer_by_phone")
@patch("serviceBot.api.telephony.create_callback_request")
def test_request_callback_fallback_vehicle_details(mock_create_cb, mock_lookup):
    """
    Verify request_callback succeeds even if vehicle details are missing from tool arguments.
    """
    mock_lookup.return_value = None
    mock_create_cb.return_value = 777

    payload = {
        "tool_call_id": "call_cb_fallback",
        "name": "request_callback",
        "arguments": {
            "phone": "469-734-1833",
            "customer_name": "Swapnil Dangi"
        }
    }
    response = client.post("/api/v1/voice/tools", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["result"]["success"] is True
    assert data["result"]["callback_id"] == 777
