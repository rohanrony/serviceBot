import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from serviceBot.main import app

client = TestClient(app)

@patch("serviceBot.api.telephony.lookup_customer_by_phone")
@patch("serviceBot.api.telephony.create_service_request")
def test_create_service_request_reconciles_single_digit_discrepancy(mock_create, mock_lookup):
    mock_lookup.return_value = {"customer_id": 42}
    mock_create.return_value = 101

    payload = {
        "tool_call_id": "call_123",
        "name": "create_service_request",
        "arguments": {
            "customer_name": "Rohan Roy",
            "phone": "4242704892",
            "caller_phone": "+14242704893",
            "make": "Tesla",
            "model": "Model 3",
            "year": 2022,
            "issue_description": "Heating issue",
            "booking_type": "appointment",
            "booking_time": "2026-10-06 09:00:00"
        }
    }
    response = client.post("/api/v1/voice/tools", json=payload)
    assert response.status_code == 200
    assert response.json()["result"]["success"] is True
    # Reconciled phone should have been used in customer lookup
    assert mock_lookup.called
    assert mock_lookup.call_args[0][0] == "4242704893"


@patch("serviceBot.api.telephony.lookup_customer_by_phone")
@patch("serviceBot.api.telephony.create_service_request")
def test_voice_tools_extracts_x_caller_id_header(mock_create, mock_lookup):
    mock_lookup.return_value = {"customer_id": 42}
    mock_create.return_value = 102

    payload = {
        "tool_call_id": "call_124",
        "name": "create_service_request",
        "arguments": {
            "customer_name": "Rohan Roy",
            "phone": "4242704892",
            "make": "Tesla",
            "model": "Model 3",
            "year": 2022,
            "issue_description": "Heating issue",
            "booking_type": "appointment",
            "booking_time": "2026-10-06 09:00:00"
        }
    }
    headers = {"X-Caller-ID": "+14242704893"}
    response = client.post("/api/v1/voice/tools", json=payload, headers=headers)
    assert response.status_code == 200
    assert response.json()["result"]["success"] is True
    assert mock_lookup.called
    assert mock_lookup.call_args[0][0] == "4242704893"


@patch("serviceBot.api.telephony.lookup_customer_by_phone")
@patch("serviceBot.api.telephony.create_service_request")
def test_voice_tools_ignores_unexpanded_template_placeholder(mock_create, mock_lookup):
    mock_lookup.return_value = {"customer_id": 42}
    mock_create.return_value = 103

    payload = {
        "tool_call_id": "call_125",
        "name": "create_service_request",
        "arguments": {
            "customer_name": "Rohan Roy",
            "phone": "4242704893",
            "caller_phone": "{{system__caller_id}}",
            "make": "Tesla",
            "model": "Model 3",
            "year": 2022,
            "issue_description": "Heating issue",
            "booking_type": "appointment",
            "booking_time": "2026-10-06 09:00:00"
        }
    }
    response = client.post("/api/v1/voice/tools", json=payload)
    assert response.status_code == 200
    assert response.json()["result"]["success"] is True
    assert mock_lookup.called
    assert mock_lookup.call_args[0][0] == "4242704893"
