import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from serviceBot.main import app

client = TestClient(app)

def test_inbound_call_injects_customer_name_and_upcoming_appointments():
    """
    Verify that an inbound call from an existing customer with upcoming appointments
    enriches TwiML with customer_name, upcoming_appointments_summary, and recent_history_summary.
    """
    mock_customer = {
        "customer_id": 42,
        "name": "Jane Smith",
        "phone": "5551234567",
        "make": "Toyota",
        "model": "Camry",
        "year": 2021
    }
    mock_upcoming = [
        {
            "id": 1042,
            "appointment_datetime": "2026-10-05 10:00:00",
            "service_type": "Oil Change",
            "issue_description": "Engine oil change and multipoint inspection",
            "duration_minutes": 45,
            "status": "pending",
            "year": 2021,
            "make": "Toyota",
            "model": "Camry"
        }
    ]
    mock_history = [
        {
            "id": 901,
            "booking_time": "2026-08-14 09:00:00",
            "service_type": "Tire Rotation",
            "issue_description": "Front tires uneven wear",
            "duration_minutes": 30,
            "status": "completed",
            "year": 2021,
            "make": "Toyota",
            "model": "Camry"
        }
    ]

    with patch("serviceBot.api.telephony.lookup_customer_by_phone", return_value=mock_customer), \
         patch("serviceBot.api.telephony.get_customer_appointments", return_value=mock_upcoming), \
         patch("serviceBot.api.telephony.get_customer_service_history", return_value=mock_history):

        resp = client.post("/api/v1/telephony/inbound", data={"From": "+15551234567", "CallSid": "CA123"})
        assert resp.status_code == 200
        twiml = resp.text

        # Verify Parameter tags
        assert '<Parameter name="customer_name" value="Jane Smith"' in twiml
        assert '<Parameter name="caller_phone" value="5551234567"' in twiml
        assert '<Parameter name="upcoming_appointments_summary"' in twiml
        assert "Oil Change" in twiml
        assert "Engine oil change and multipoint inspection" in twiml
        assert "45 min" in twiml or "45 minutes" in twiml or "45" in twiml
        assert '<Parameter name="recent_history_summary"' in twiml
        assert "Tire Rotation" in twiml


def test_inbound_call_new_customer():
    """Verify that an inbound call from an unknown number only injects caller_phone."""
    with patch("serviceBot.api.telephony.lookup_customer_by_phone", return_value=None), \
         patch("serviceBot.api.telephony.get_customer_appointments", return_value=[]), \
         patch("serviceBot.api.telephony.get_customer_service_history", return_value=[]):

        resp = client.post("/api/v1/telephony/inbound", data={"From": "+15550009999", "CallSid": "CA999"})
        assert resp.status_code == 200
        twiml = resp.text

        assert '<Parameter name="caller_phone" value="5550009999"' in twiml
        assert '<Parameter name="customer_name"' not in twiml
        assert '<Parameter name="upcoming_appointments_summary"' not in twiml


def test_get_customer_appointments_tool_returns_issue_and_duration():
    """Verify get_customer_appointments tool outputs issue_description and duration_minutes."""
    mock_appts = [
        {
            "id": 55,
            "appointment_datetime": "2026-10-10 14:00:00",
            "service_type": "Brake Service",
            "issue_description": "Front brake grinding and squeaking",
            "duration_minutes": 60,
            "status": "pending",
            "year": 2019,
            "make": "Honda",
            "model": "Civic"
        }
    ]

    with patch("serviceBot.api.telephony.get_customer_appointments", return_value=mock_appts):
        payload = {
            "tool_call_id": "call_appt_1",
            "name": "get_customer_appointments",
            "arguments": {"phone": "5551234567"}
        }
        resp = client.post("/api/v1/voice/tools", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        result = data.get("result", data)
        assert result["success"] is True
        assert len(result["appointments"]) == 1
        appt = result["appointments"][0]
        assert appt["id"] == 55
        assert appt["issue_description"] == "Front brake grinding and squeaking"
        assert appt["duration_minutes"] == 60
        assert appt["make"] == "Honda"
