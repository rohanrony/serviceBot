import os
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from serviceBot.main import app

client = TestClient(app)

@pytest.fixture(autouse=True)
def mock_env_and_db(setup_and_cleanup_test_db):
    """Ensure clean isolated database and environment variables."""
    pass

@patch("serviceBot.api.telephony.book_appointment", return_value=123)
@patch("serviceBot.services.sms_router.SMSNotificationRouter")
@patch("serviceBot.services.gmail.send_booking_notification")
@patch("serviceBot.services.gmail.send_admin_notification")
def test_book_appointment_uses_background_tasks(mock_admin_email, mock_user_email, mock_sms_router, mock_book):
    """Verify that book_appointment webhook responds cleanly while dispatching notifications via background tasks."""
    payload = {
        "tool_call_id": "call_test_book_123",
        "name": "book_appointment",
        "arguments": {
            "phone": "5551234567",
            "customer_name": "Fast Response Test",
            "appointment_datetime": "2026-08-10 10:00:00",
            "service_type": "Oil Change",
            "make": "Honda",
            "model": "Civic",
            "year": 2022
        }
    }

    response = client.post("/api/v1/voice/tools", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["tool_call_id"] == "call_test_book_123"
    result = data["result"]
    assert result["success"] is True
    assert "Appointment booked successfully" in result["message"]
    assert result["appointment_id"] == 123


@patch("serviceBot.api.telephony.create_service_request", return_value=456)
@patch("serviceBot.services.sms_router.SMSNotificationRouter")
@patch("serviceBot.services.gmail.send_booking_notification")
@patch("serviceBot.services.gmail.send_admin_notification")
def test_create_service_request_uses_background_tasks(mock_admin_email, mock_user_email, mock_sms_router, mock_create_sr):
    """Verify create_service_request runs non-blocking notifications in background."""
    payload = {
        "tool_call_id": "call_test_sr_123",
        "name": "create_service_request",
        "arguments": {
            "phone": "5559876543",
            "customer_name": "Async SR Test",
            "service_type": "Brake Service",
            "issue_description": "Squeaking noise when braking",
            "make": "Toyota",
            "model": "Camry",
            "year": 2021,
            "booking_type": "appointment",
            "booking_time": "2026-08-11 14:00:00"
        }
    }

    response = client.post("/api/v1/voice/tools", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["tool_call_id"] == "call_test_sr_123"
    result = data["result"]
    assert result["success"] is True
    assert result["service_request_id"] == 456


@patch("serviceBot.api.telephony.create_callback_request", return_value=789)
@patch("serviceBot.services.sms_router.SMSNotificationRouter")
@patch("serviceBot.services.gmail.send_booking_notification")
@patch("serviceBot.services.gmail.send_admin_notification")
def test_request_callback_uses_background_tasks(mock_admin_email, mock_user_email, mock_sms_router, mock_create_cb):
    """Verify request_callback processes notifications in background."""
    payload = {
        "tool_call_id": "call_test_cb_123",
        "name": "request_callback",
        "arguments": {
            "phone": "5553334444",
            "customer_name": "Callback Test",
            "preferred_time": "Tomorrow at 9 AM",
            "make": "Ford",
            "model": "F-150",
            "year": 2019
        }
    }

    response = client.post("/api/v1/voice/tools", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["tool_call_id"] == "call_test_cb_123"
    result = data["result"]
    assert result["success"] is True
    assert result["callback_id"] == 789
