import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from serviceBot.main import app

client = TestClient(app)

def test_create_service_request_reconciles_acoustic_area_code_to_caller_id():
    """Verify that when spoken phone has a 1-digit area code discrepancy (e.g. 444 vs 424)
    with matching 7-digit suffix, create_service_request auto-reconciles to the verified caller ID."""
    mock_cursor = MagicMock()
    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_cursor.__enter__.return_value = mock_cursor

    # Mock customer lookup: 4242704893 exists as customer 17
    mock_customer = {"id": 17, "customer_id": 17, "name": "Rohan Roy", "phone": "+14242704893"}
    
    with patch("serviceBot.api.telephony.lookup_customer_by_phone", return_value=mock_customer) as mock_lookup, \
         patch("serviceBot.api.telephony.create_service_request", return_value=99) as mock_create_sr, \
         patch("serviceBot.api.telephony.get_db_connection", return_value=mock_conn), \
         patch("serviceBot.api.telephony.dict_cursor", return_value=mock_cursor):

        payload = {
            "name": "create_service_request",
            "arguments": {
                "customer_name": "Rohan Roy",
                "phone": "4442704893",           # Spoken phone with 444 acoustic error
                "caller_phone": "4242704893",    # Verified Twilio Caller ID
                "make": "Tesla",
                "model": "Model 3",
                "year": 2020,
                "issue_description": "Battery check",
                "booking_type": "callback"
            }
        }
        resp = client.post("/api/v1/voice/tools", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        result = data.get("result", data)
        assert result["success"] is True

        # Verify that create_service_request was called with customer_id=17 (reconciled!)
        mock_create_sr.assert_called_once()
        call_kwargs = mock_create_sr.call_args[1] if mock_create_sr.call_args[1] else {}
        call_args = mock_create_sr.call_args[0]
        cid = call_kwargs.get("customer_id") if "customer_id" in call_kwargs else call_args[0]
        assert cid == 17


def test_get_customer_appointments_merges_caller_phone_and_suffix():
    """Verify get_customer_appointments merges appointments from caller_phone and falls back to 7-digit suffix."""
    appts_for_444 = [
        {
            "id": 23,
            "appointment_datetime": "2026-10-06 07:00:00",
            "booking_type": "appointment",
            "service_type": "Repair",
            "issue_description": "Windshield",
            "duration_minutes": 60,
            "status": "pending",
            "year": 2018,
            "make": "Toyota",
            "model": "Corolla"
        }
    ]
    appts_for_caller = [
        {
            "id": 27,
            "appointment_datetime": "2026-10-05 12:00:00",
            "booking_type": "appointment",
            "service_type": "Engine Diagnostic",
            "issue_description": "Heating",
            "duration_minutes": 60,
            "status": "pending",
            "year": 2020,
            "make": "Tesla",
            "model": "3"
        }
    ]

    def mock_get_appts(ph):
        if ph == "4442704893":
            return appts_for_444
        if ph == "4242704893":
            return appts_for_caller
        return []

    # 1. Test caller_phone merge: spoken phone (23) and caller phone (27) are merged
    with patch("serviceBot.api.telephony.get_customer_appointments", side_effect=mock_get_appts):
        payload = {
            "name": "get_customer_appointments",
            "arguments": {
                "phone": "4442704893",
                "caller_phone": "4242704893"
            }
        }
        resp = client.post("/api/v1/voice/tools", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        result = data.get("result", data)
        assert result["success"] is True

        appt_ids = [a["id"] for a in result["appointments"]]
        assert 23 in appt_ids
        assert 27 in appt_ids
        assert result["upcoming_count"] == 2

    # 2. Test suffix fallback: when no appointments found for spoken phone or caller phone, suffix matches ID 28
    mock_cursor = MagicMock()
    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_cursor.__enter__.return_value = mock_cursor
    mock_cursor.fetchall.return_value = [
        {
            "id": 28,
            "appointment_datetime": "2026-10-02 10:00:00",
            "booking_type": "appointment",
            "service_type": "Repair",
            "issue_description": "Battery inspection",
            "duration_minutes": 60,
            "status": "pending",
            "year": 2020,
            "make": "Tesla",
            "model": "Model 3"
        }
    ]

    with patch("serviceBot.api.telephony.get_customer_appointments", return_value=[]), \
         patch("serviceBot.api.telephony.get_db_connection", return_value=mock_conn), \
         patch("serviceBot.api.telephony.dict_cursor", return_value=mock_cursor):

        payload = {
            "name": "get_customer_appointments",
            "arguments": {
                "phone": "9992704893",
                "caller_phone": "9992704893"
            }
        }
        resp = client.post("/api/v1/voice/tools", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        result = data.get("result", data)
        assert result["success"] is True

        appt_ids = [a["id"] for a in result["appointments"]]
        assert 28 in appt_ids
        assert result["upcoming_count"] == 1


def test_reschedule_appointment_reconciles_typo_via_caller_phone():
    """Verify reschedule_appointment falls back to caller_phone if spoken phone yields no appointments."""
    with patch("serviceBot.api.telephony.get_customer_appointments") as mock_get_appts, \
         patch("serviceBot.api.telephony.reschedule_appointment") as mock_resched:

        def side_effect(ph):
            if ph == "4442704893":
                return []
            if ph == "4242704893":
                return [{"id": 28, "appointment_datetime": "2026-10-02 10:00:00"}]
            return []

        mock_get_appts.side_effect = side_effect

        payload = {
            "name": "reschedule_appointment",
            "arguments": {
                "phone": "4442704893",
                "caller_phone": "4242704893",
                "appointment_id": 28,
                "new_appointment_datetime": "2026-10-02 14:00:00"
            }
        }
        resp = client.post("/api/v1/voice/tools", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        result = data.get("result", data)
        assert result["success"] is True
        mock_resched.assert_called_once()
        assert mock_resched.call_args[1]["appointment_id"] == 28
