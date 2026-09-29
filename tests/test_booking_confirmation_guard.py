import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from serviceBot.main import app
from serviceBot.services.booking import clear_session_booking, get_session_booking, track_session_booking

client = TestClient(app)

@pytest.fixture(autouse=True)
def cleanup_sessions():
    clear_session_booking("test_call_sid_123")
    clear_session_booking("5551234567")
    clear_session_booking("call_alice_789")
    clear_session_booking("5559876543")
    yield
    clear_session_booking("test_call_sid_123")
    clear_session_booking("5551234567")
    clear_session_booking("call_alice_789")
    clear_session_booking("5559876543")


def test_booking_response_includes_start_end_and_extension_notice():
    """Verify booking response includes expected start/end times and extension notice."""
    with patch("serviceBot.api.telephony.lookup_customer_by_phone") as mock_lookup, \
         patch("serviceBot.api.telephony.update_customer_name") as mock_upd_name, \
         patch("serviceBot.api.telephony.create_service_request") as mock_create, \
         patch("serviceBot.api.telephony.get_service_required_fields") as mock_fields:

        mock_lookup.return_value = {"customer_id": 1, "name": "John Doe", "make": "Honda", "model": "Civic", "year": 2020}
        mock_create.return_value = 101
        mock_fields.return_value = {"price_range": "$79-$119", "duration_minutes": 60}

        payload = {
            "name": "create_service_request",
            "arguments": {
                "customer_name": "John Doe",
                "phone": "5551234567",
                "make": "Honda",
                "model": "Civic",
                "year": 2020,
                "issue_description": "Oil Change",
                "booking_type": "appointment",
                "booking_time": "2026-10-05 10:00:00",
                "call_sid": "test_call_sid_123"
            }
        }
        resp = client.post("/api/v1/voice/tools", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        result = data.get("result", data)
        assert result["success"] is True
        # Check start and end time window or duration
        assert "expected_end_time" in result or "10:00 AM" in result.get("message", "")
        # Check extension notice
        assert "extend" in result.get("message", "").lower()


def test_single_booking_on_time_change_deduplication():
    """
    Verify that when create_service_request is called a second time in the same call session
    with a revised time (e.g. 10:00 AM then 10:30 AM), it updates the existing booking
    rather than creating a duplicate.
    """
    with patch("serviceBot.api.telephony.lookup_customer_by_phone") as mock_lookup, \
         patch("serviceBot.api.telephony.update_customer_name") as mock_upd_name, \
         patch("serviceBot.api.telephony.create_service_request") as mock_create, \
         patch("serviceBot.api.telephony.reschedule_appointment") as mock_reschedule, \
         patch("serviceBot.api.telephony.get_service_required_fields") as mock_fields:

        mock_lookup.return_value = {"customer_id": 1, "name": "John Doe", "make": "Honda", "model": "Civic", "year": 2020}
        mock_create.return_value = 101
        mock_reschedule.return_value = True
        mock_fields.return_value = {"price_range": "$79-$119", "duration_minutes": 60}

        # Turn 1: 10:00 AM booking
        payload_1 = {
            "name": "create_service_request",
            "arguments": {
                "customer_name": "John Doe",
                "phone": "5551234567",
                "make": "Honda",
                "model": "Civic",
                "year": 2020,
                "issue_description": "Oil Change",
                "booking_type": "appointment",
                "booking_time": "2026-10-05 10:00:00",
                "call_sid": "test_call_sid_123"
            }
        }
        resp1 = client.post("/api/v1/voice/tools", json=payload_1)
        assert resp1.status_code == 200
        res1 = resp1.json().get("result", resp1.json())
        assert res1["success"] is True
        assert res1.get("service_request_id") == 101

        # Turn 2: Caller changes mind to 10:30 AM in same call session
        payload_2 = {
            "name": "create_service_request",
            "arguments": {
                "customer_name": "John Doe",
                "phone": "5551234567",
                "make": "Honda",
                "model": "Civic",
                "year": 2020,
                "issue_description": "Oil Change",
                "booking_type": "appointment",
                "booking_time": "2026-10-05 10:30:00",
                "call_sid": "test_call_sid_123"
            }
        }
        resp2 = client.post("/api/v1/voice/tools", json=payload_2)
        assert resp2.status_code == 200
        res2 = resp2.json().get("result", resp2.json())
        assert res2["success"] is True
        # Must be recognized as an update of the existing booking 101
        assert res2.get("is_update") is True
        assert res2.get("service_request_id") == 101
        # create_service_request was called once; reschedule was called for the change
        assert mock_create.call_count == 1
        assert mock_reschedule.call_count == 1


def test_book_appointment_deduplication_on_time_change():
    """Verify that book_appointment tool also deduplicates within the same call session."""
    with patch("serviceBot.api.telephony.lookup_customer_by_phone") as mock_lookup, \
         patch("serviceBot.api.telephony.update_customer_name") as mock_upd_name, \
         patch("serviceBot.api.telephony.book_appointment") as mock_book, \
         patch("serviceBot.api.telephony.reschedule_appointment") as mock_reschedule, \
         patch("serviceBot.api.telephony.get_service_required_fields") as mock_fields:

        mock_lookup.return_value = {"customer_id": 1, "name": "Alice Smith", "make": "Ford", "model": "Focus", "year": 2018}
        mock_book.return_value = 202
        mock_reschedule.return_value = True
        mock_fields.return_value = {"price_range": "$120-$200", "duration_minutes": 60}

        payload_1 = {
            "name": "book_appointment",
            "arguments": {
                "customer_name": "Alice Smith",
                "phone": "5559876543",
                "appointment_datetime": "2026-10-05 14:00:00",
                "service_type": "Brake Service",
                "call_sid": "call_alice_789"
            }
        }
        resp1 = client.post("/api/v1/voice/tools", json=payload_1)
        assert resp1.status_code == 200
        res1 = resp1.json().get("result", resp1.json())
        assert res1["success"] is True
        assert res1["appointment_id"] == 202

        # Caller shifts to 14:30:00
        payload_2 = {
            "name": "book_appointment",
            "arguments": {
                "customer_name": "Alice Smith",
                "phone": "5559876543",
                "appointment_datetime": "2026-10-05 14:30:00",
                "service_type": "Brake Service",
                "call_sid": "call_alice_789"
            }
        }
        resp2 = client.post("/api/v1/voice/tools", json=payload_2)
        assert resp2.status_code == 200
        res2 = resp2.json().get("result", resp2.json())
        assert res2["success"] is True
        assert res2.get("is_update") is True
        assert res2.get("appointment_id") == 202
        assert mock_book.call_count == 1
        assert mock_reschedule.call_count == 1
