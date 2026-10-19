from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from serviceBot.main import app
from serviceBot.services import booking

client = TestClient(app)

@pytest.fixture(autouse=True)
def isolated_sessions(monkeypatch):
    monkeypatch.setattr(booking, "_IN_FLIGHT_BOOKING_SESSIONS", {})
    yield
    assert set(booking._IN_FLIGHT_BOOKING_SESSIONS) == {"phone_4242704893"}


def assert_owned_create(mock_create, identifier):
    mock_create.assert_called_once_with(customer_id=42,
        vehicle_details={"make": "Tesla", "model": "Model 3", "year": 2022}, issue="Heating issue",
        service_type="Repair", time_slot=None, booking_type="appointment", booking_time="2026-10-06 09:00:00")
    assert mock_create.call_args.kwargs["customer_id"] == 42
    assert mock_create.call_args.kwargs["booking_time"] == "2026-10-06 09:00:00"
    assert mock_create.call_args.kwargs["vehicle_details"] == {"make": "Tesla", "model": "Model 3", "year": 2022}
    cached = booking.get_session_booking("phone_4242704893")
    assert cached["service_request_id"] == identifier
    assert cached["phone"] == "4242704893"
    assert cached["duration_minutes"] == 60
    assert cached["booking_time"] == "2026-10-06 09:00:00"


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
    assert all(call.args == ("4242704893",) for call in mock_lookup.call_args_list)
    assert_owned_create(mock_create, 101)


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
    assert all(call.args == ("4242704893",) for call in mock_lookup.call_args_list)
    assert_owned_create(mock_create, 102)


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
    assert all(call.args == ("4242704893",) for call in mock_lookup.call_args_list)
    assert_owned_create(mock_create, 103)
