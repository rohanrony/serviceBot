import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from serviceBot.main import app

client = TestClient(app)

def test_voice_tools_endpoint_not_found_initially():
    # If endpoint doesn't exist yet, it should 404
    payload = {
        "tool_call_id": "call_123",
        "name": "check_availability",
        "arguments": {"preferred_date": "2026-06-10"}
    }
    response = client.post("/api/v1/voice/tools", json=payload)
    # TDD Red expectation:
    # If the router is not yet registered or defined, this will return 404 or fail.
    # Note: once we implement the green phase, this test will either be adjusted or we assert it succeeds.
    # So we write our target assertions to assert success for implemented cases.

@patch("serviceBot.api.telephony.check_availability")
def test_voice_tools_check_availability(mock_check):
    mock_check.return_value = ["2026-06-10 10:00:00", "2026-06-10 11:00:00"]
    payload = {
        "tool_call_id": "call_123",
        "name": "check_availability",
        "arguments": {"preferred_date": "2026-06-10"}
    }
    response = client.post("/api/v1/voice/tools", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["tool_call_id"] == "call_123"
    assert data["result"]["success"] is True
    assert "2026-06-10 10:00:00" in data["result"]["available_slots"]

@patch("serviceBot.api.telephony.lookup_customer_by_phone")
@patch("serviceBot.api.telephony.create_service_request")
def test_voice_tools_create_service_request(mock_create, mock_lookup):
    mock_lookup.return_value = {"customer_id": 42}
    mock_create.return_value = 101
    
    payload = {
        "tool_call_id": "call_456",
        "name": "create_service_request",
        "arguments": {
            "customer_name": "Sarah Johnson",
            "phone": "555-123-4567",
            "make": "Honda",
            "model": "Civic",
            "year": 2020,
            "issue_description": "Grinding noise when stopping"
        }
    }
    response = client.post("/api/v1/voice/tools", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["tool_call_id"] == "call_456"
    assert data["result"]["success"] is True
    assert data["result"]["service_request_id"] == 101

@patch("serviceBot.api.telephony.lookup_customer_by_phone")
@patch("serviceBot.api.telephony.book_appointment")
def test_voice_tools_book_appointment(mock_book, mock_lookup):
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
    assert response.status_code == 200
    data = response.json()
    assert data["tool_call_id"] == "call_789"
    assert data["result"]["success"] is True
    assert data["result"]["appointment_id"] == 202

@patch("serviceBot.api.telephony.FAQService")
def test_voice_tools_faq(mock_faq_class):
    mock_instance = MagicMock()
    mock_instance.answer_question.return_value = "Business hours are 8 AM to 6 PM."
    mock_faq_class.return_value = mock_instance
    
    payload = {
        "tool_call_id": "call_abc",
        "name": "query_knowledge_base",
        "arguments": {"query_text": "What are your business hours?"}
    }
    response = client.post("/api/v1/voice/tools", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["tool_call_id"] == "call_abc"
    assert data["result"]["success"] is True
    assert "8 AM to 6 PM" in data["result"]["answer"]

@patch("serviceBot.api.telephony.is_within_business_hours")
@patch("serviceBot.api.telephony.lookup_customer_by_phone")
def test_voice_tools_handoff(mock_lookup, mock_hours):
    mock_hours.return_value = True
    mock_lookup.return_value = {"customer_id": 42, "name": "Sarah Johnson", "phone": "555-123-4567"}
    payload = {
        "tool_call_id": "call_xyz",
        "name": "cba_webhook", # matching the user's tool name in the screenshot!
        "arguments": {
            "phone": "555-123-4567",
            "issue_description": "Transmission slipping"
        }
    }
    response = client.post("/api/v1/voice/tools", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["tool_call_id"] == "call_xyz"
    assert data["result"]["success"] is True
    assert "transferred" in data["result"]["message"].lower()


@patch("serviceBot.api.telephony.is_within_business_hours")
@patch("serviceBot.api.telephony.lookup_customer_by_phone")
def test_voice_tools_handoff_outside_hours(mock_lookup, mock_hours):
    mock_hours.return_value = False
    mock_lookup.return_value = {"customer_id": 42, "name": "Sarah Johnson", "phone": "555-123-4567"}
    payload = {
        "tool_call_id": "call_xyz",
        "name": "cba_webhook",
        "arguments": {
            "phone": "555-123-4567",
            "issue_description": "Transmission slipping"
        }
    }
    response = client.post("/api/v1/voice/tools", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["tool_call_id"] == "call_xyz"
    assert data["result"]["success"] is False
    assert "closed" in data["result"]["message"].lower()



@patch("serviceBot.api.telephony.lookup_customer_by_phone")
@patch("serviceBot.api.telephony.book_appointment")
def test_voice_tools_flat_book_appointment(mock_book, mock_lookup):
    mock_lookup.return_value = {
        "customer_id": 42,
        "name": "Sarah Johnson",
        "phone": "4242704893",
        "make": "Honda",
        "model": "Civic",
        "year": 2020,
        "open_sr_id": 101
    }
    mock_book.return_value = 303
    
    # Flat JSON body representing direct custom tool request parameters from ElevenLabs
    payload = {
        "phone": "424-270-4893",
        "appointment_datetime": "2026-06-11 11:00:00",
        "service_type": "Oil change"
    }
    response = client.post("/api/v1/voice/tools", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["appointment_id"] == 303
    assert data["result"]["success"] is True
    assert data["result"]["appointment_id"] == 303


@patch("serviceBot.api.telephony.check_availability")
def test_voice_tools_flat_check_availability(mock_check):
    mock_check.return_value = ["2026-06-11 10:00:00"]
    payload = {
        "preferred_date": "2026-06-11"
    }
    response = client.post("/api/v1/voice/tools", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "2026-06-11 10:00:00" in data["available_slots"]


@patch("serviceBot.api.telephony.get_service_required_fields")
def test_voice_tools_get_service_fields_success(mock_get_fields):
    mock_get_fields.return_value = {
        "name": "Oil Change",
        "description": "Premium oil change",
        "price_range": "$79-119",
        "duration_minutes": 45,
        "req_customer_name": 1,
        "req_phone_number": 1,
        "req_vehicle_details": 1,
        "req_issue_description": 0,
        "req_location": 0
    }
    payload = {
        "tool_call_id": "call_abc",
        "name": "get_service_fields",
        "arguments": {"service_name": "Oil Change"}
    }
    response = client.post("/api/v1/voice/tools", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["tool_call_id"] == "call_abc"
    assert data["result"]["success"] is True
    assert data["result"]["service_found"] is True
    assert data["result"]["service_name"] == "Oil Change"
    assert data["result"]["required_fields"]["customer_name"] is True
    assert data["result"]["required_fields"]["issue_description"] is False

@patch("serviceBot.api.telephony.get_service_required_fields")
def test_voice_tools_get_service_fields_flat(mock_get_fields):
    mock_get_fields.return_value = {
        "name": "Brake Repair",
        "description": "Brake pad replacement",
        "price_range": "$150-400",
        "duration_minutes": 90,
        "req_customer_name": 1,
        "req_phone_number": 1,
        "req_vehicle_details": 1,
        "req_issue_description": 1,
        "req_location": 0
    }
    payload = {
        "service_name": "Brake Repair"
    }
    response = client.post("/api/v1/voice/tools", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["service_found"] is True
    assert data["service_name"] == "Brake Repair"
    assert data["required_fields"]["customer_name"] is True

@patch("serviceBot.api.telephony.get_service_required_fields")
@patch("serviceBot.api.portal.load_config")
def test_voice_tools_get_service_fields_fallback(mock_load_config, mock_get_fields):
    mock_get_fields.return_value = None
    mock_load_config.return_value = {
        "required_fields": {
            "customer_name": True,
            "phone_number": False,
            "vehicle_details": True,
            "issue_description": False,
            "location": True
        }
    }
    payload = {
        "service_name": "Unknown service"
    }
    response = client.post("/api/v1/voice/tools", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["service_found"] is False
    assert data["required_fields"]["customer_name"] is True
    assert data["required_fields"]["phone_number"] is False


def test_create_service_request_phone_validation_failure():
    payload = {
        "tool_call_id": "call_invalid_phone",
        "name": "create_service_request",
        "arguments": {
            "customer_name": "Sarah Johnson",
            "phone": "12345",
            "make": "Honda",
            "model": "Civic",
            "year": 2020,
            "issue_description": "Grinding noise"
        }
    }
    response = client.post("/api/v1/voice/tools", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["tool_call_id"] == "call_invalid_phone"
    assert data["result"]["success"] is False
    assert "validation failed" in data["result"]["message"].lower()

@patch("serviceBot.api.telephony.lookup_customer_by_phone")
@patch("serviceBot.api.telephony.create_service_request")
def test_create_service_request_phone_validation_success(mock_create, mock_lookup):
    mock_lookup.return_value = {"customer_id": 42}
    mock_create.return_value = 101
    
    payload = {
        "tool_call_id": "call_valid_phone",
        "name": "create_service_request",
        "arguments": {
            "customer_name": "Sarah Johnson",
            "phone": "+1 (555) 123-4567",
            "make": "Honda",
            "model": "Civic",
            "year": 2020,
            "issue_description": "Grinding noise",
            "service_type": "Oil Change (Full Synthetic)"
        }
    }
    response = client.post("/api/v1/voice/tools", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["tool_call_id"] == "call_valid_phone"
    assert data["result"]["success"] is True
    # Verify the number is normalized to 10 digits when passed to lookup_customer_by_phone
    mock_lookup.assert_called_once_with("5551234567")
    mock_create.assert_called_once_with(
        customer_id=42,
        vehicle_details={"make": "Honda", "model": "Civic", "year": 2020},
        issue="Grinding noise",
        service_type="Oil Change (Full Synthetic)",
        time_slot=None
    )


@patch("serviceBot.api.telephony.lookup_customer_by_phone")
@patch("serviceBot.api.telephony.create_callback_request")
def test_voice_tools_request_callback(mock_create_cb, mock_lookup):
    mock_lookup.return_value = {
        "customer_id": 42,
        "name": "Sarah Johnson",
        "phone": "5551234567",
        "make": "Honda",
        "model": "Civic",
        "year": 2020,
        "open_sr_id": 101
    }
    mock_create_cb.return_value = 500
    
    payload = {
        "tool_call_id": "call_cb",
        "name": "request_callback",
        "arguments": {
            "phone": "555-123-4567",
            "customer_name": "Sarah Johnson",
            "service_request_id": 101,
            "preferred_time": "Tomorrow at 10 AM"
        }
    }
    response = client.post("/api/v1/voice/tools", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["tool_call_id"] == "call_cb"
    assert data["result"]["success"] is True
    assert data["result"]["callback_id"] == 500
    mock_create_cb.assert_called_once_with(
        customer_id=42,
        service_request_id=101,
        preferred_time="Tomorrow at 10 AM",
        vehicle_details={"make": "Honda", "model": "Civic", "year": 2020}
    )


@patch("serviceBot.api.telephony.get_customer_appointments")
@patch("serviceBot.api.telephony.reschedule_appointment")
def test_voice_tools_reschedule_appointment(mock_resched, mock_get_appts):
    mock_get_appts.return_value = [{"id": 52, "appointment_datetime": "2026-06-14 10:00:00"}]
    mock_resched.return_value = True
    
    payload = {
        "tool_call_id": "call_resched",
        "name": "reschedule_appointment",
        "arguments": {
            "phone": "555-123-4567",
            "new_appointment_datetime": "2026-06-14 11:00:00"
        }
    }
    response = client.post("/api/v1/voice/tools", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["tool_call_id"] == "call_resched"
    assert data["result"]["success"] is True
    assert data["result"]["appointment_id"] == 52


@patch("serviceBot.api.telephony.get_customer_appointments")
def test_voice_tools_get_customer_appointments(mock_get_appts):
    mock_get_appts.return_value = [{"id": 52, "appointment_datetime": "2026-06-14 10:00:00", "service_type": "Repair"}]
    
    payload = {
        "tool_call_id": "call_get_appts",
        "name": "get_customer_appointments",
        "arguments": {
            "phone": "555-123-4567"
        }
    }
    response = client.post("/api/v1/voice/tools", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["tool_call_id"] == "call_get_appts"
    assert data["result"]["success"] is True
    assert len(data["result"]["appointments"]) == 1
    assert data["result"]["appointments"][0]["id"] == 52
    assert data["result"]["appointments"][0]["service_type"] == "Repair"


@patch("serviceBot.api.telephony.lookup_customer_by_phone")
@patch("serviceBot.api.telephony.create_service_request")
def test_voice_tools_create_service_request_multiple_issues(mock_create, mock_lookup):
    mock_lookup.return_value = {"customer_id": 42}
    mock_create.return_value = 102
    
    payload = {
        "tool_call_id": "call_multi_issue",
        "name": "create_service_request",
        "arguments": {
            "customer_name": "Mark Taylor",
            "phone": "555-888-9999",
            "make": "Ford",
            "model": "F-150",
            "year": 2022,
            "issue_description": "Oil Change and Brake Inspection & Repair",
            "service_type": "Oil Change & Brake Inspection"
        }
    }
    response = client.post("/api/v1/voice/tools", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["tool_call_id"] == "call_multi_issue"
    assert data["result"]["success"] is True
    assert data["result"]["service_request_id"] == 102
    mock_create.assert_called_once_with(
        customer_id=42,
        vehicle_details={"make": "Ford", "model": "F-150", "year": 2022},
        issue="Oil Change and Brake Inspection & Repair",
        service_type="Oil Change & Brake Inspection",
        time_slot=None
    )






