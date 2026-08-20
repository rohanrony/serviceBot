import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from serviceBot.main import app
from serviceBot.db.queries import get_available_slots_for_date

client = TestClient(app)

def test_available_slots_weekend_returns_empty():
    """Verify weekend dates return no available slots."""
    # 2026-08-08 is Saturday
    slots = get_available_slots_for_date("2026-08-08")
    assert slots == []

def test_available_slots_weekday_with_db():
    """Verify available slots calculation for a weekday using actual/seeded db."""
    with patch("serviceBot.services.google_calendar.is_agent_free", return_value=True):
        # 2026-08-10 is Monday
        slots = get_available_slots_for_date("2026-08-10")
        assert len(slots) > 0
        assert "start_time" in slots[0]
        assert "available_agents_count" in slots[0]

def test_available_slots_various_date_formats():
    """Verify get_available_slots_for_date accepts YYYY-MM-DD, MM/DD/YYYY, and ISO format strings."""
    with patch("serviceBot.services.google_calendar.fetch_agent_events", return_value=[]):
        slots_iso = get_available_slots_for_date("2026-08-10")
        slots_us = get_available_slots_for_date("08/10/2026")
        slots_dt = get_available_slots_for_date("2026-08-10T17:00:00")
        assert len(slots_iso) > 0
        assert len(slots_us) == len(slots_iso)
        assert len(slots_dt) == len(slots_iso)

def test_get_available_slots_endpoint():
    """Test GET /api/v1/portal/available-slots endpoint."""
    with patch("serviceBot.db.queries.get_available_slots_for_date") as mock_get_slots:
        mock_get_slots.return_value = [
            {"start_time": "2026-08-10 09:00:00", "end_time": "2026-08-10 10:00:00", "available_agents_count": 2}
        ]
        res = client.get("/api/v1/portal/available-slots?date=2026-08-10")
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert len(data["available_slots"]) == 1
        assert data["available_slots"][0]["start_time"] == "2026-08-10 09:00:00"

def test_edit_service_request_reschedule_without_consent_fails():
    """Test PUT /api/v1/portal/service-requests/{id} fails 400 when consent is not obtained."""
    with patch("serviceBot.db.connection.get_db_connection") as mock_conn:
        mock_cursor = MagicMock()
        mock_conn.return_value.__enter__.return_value = mock_conn
        mock_conn.dict_cursor.return_value.__enter__.return_value = mock_cursor
        
        # Existing request with different booking time
        mock_cursor.fetchone.return_value = {
            "customer_id": 1,
            "issue_description": "Oil Change",
            "status": "pending",
            "booking_time": "2026-08-07 10:00:00",
            "vehicle_id": 10
        }

        payload = {
            "issue_description": "Oil Change",
            "vehicle_details": {"make": "Toyota", "model": "Camry", "year": 2020, "vin": ""},
            "booking_time": "2026-08-10 14:00:00",
            "customer_consent_obtained": False
        }

        res = client.put("/api/v1/portal/service-requests/100", json=payload)
        assert res.status_code == 400
        assert "Customer consent is required" in res.json()["detail"]

def test_edit_service_request_reschedule_with_consent_success():
    """Test PUT /api/v1/portal/service-requests/{id} succeeds 200 when consent is obtained."""
    with patch("serviceBot.db.connection.get_db_connection") as mock_conn:
        mock_cursor = MagicMock()
        mock_conn.return_value.__enter__.return_value = mock_conn
        mock_conn.dict_cursor.return_value.__enter__.return_value = mock_cursor
        
        mock_cursor.fetchone.side_effect = [
            # 1. SELECT SR
            {"customer_id": 1, "issue_description": "Oil Change", "status": "pending", "booking_time": "2026-08-07 10:00:00"},
            # 2. RETURNING vehicle_id
            {"vehicle_id": 10},
            # 3. SELECT customer phone
            {"phone": "+15551234567", "name": "David"}
        ]

        with patch("serviceBot.db.queries.reschedule_appointment", return_value=True) as mock_reschedule:
            with patch("serviceBot.services.twilio_sms.TwilioSMSClient.send_sms") as mock_sms:
                payload = {
                    "issue_description": "Oil Change",
                    "vehicle_details": {"make": "Toyota", "model": "Camry", "year": 2020, "vin": ""},
                    "booking_time": "2026-08-10 14:00:00",
                    "customer_consent_obtained": True
                }

                res = client.put("/api/v1/portal/service-requests/100", json=payload)
                assert res.status_code == 200
                assert res.json()["success"] is True
                mock_reschedule.assert_called_once_with(
                    appointment_id=100,
                    new_datetime="2026-08-10 14:00:00",
                    customer_consent_obtained=True,
                    triggered_by="portal_staff"
                )
