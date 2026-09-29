import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from serviceBot.main import app

client = TestClient(app)

def test_consolidate_appointment_success():
    """Verify consolidating an additional issue into an existing appointment when capacity is available."""
    mock_consolidate_res = {
        "appointment_id": 1042,
        "combined_issues": "Oil Change and multipoint inspection; Brake squeak and rotor check",
        "new_duration_minutes": 90,
        "booking_time": "2026-10-02 10:00:00",
        "vehicle": {"year": 2021, "make": "Toyota", "model": "Camry"}
    }

    with patch("serviceBot.api.telephony.verify_contiguous_slot_capacity", return_value=True), \
         patch("serviceBot.api.telephony.consolidate_appointment_service", return_value=mock_consolidate_res), \
         patch("serviceBot.api.telephony.get_customer_appointments") as mock_get_appts:

        mock_get_appts.return_value = [
            {
                "id": 1042,
                "appointment_datetime": "2026-10-02 10:00:00",
                "service_type": "Oil Change",
                "issue_description": "Oil Change and multipoint inspection",
                "duration_minutes": 45
            }
        ]

        payload = {
            "tool_call_id": "call_consolidate_1",
            "name": "consolidate_appointment_service",
            "arguments": {
                "appointment_id": 1042,
                "phone": "5551234567",
                "additional_issue": "Brake squeak and rotor check",
                "additional_service_type": "Brake Inspection",
                "additional_duration_minutes": 45
            }
        }
        resp = client.post("/api/v1/voice/tools", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        result = data.get("result", data)

        assert result["success"] is True
        assert result["appointment_id"] == 1042
        assert "Brake squeak" in result["combined_issues"]
        assert result["new_duration_minutes"] == 90
        assert "10:00" in result["start_time"]
        assert "11:30" in result["expected_end_time"]
        assert "extend" in result["message"].lower()


def test_consolidate_appointment_capacity_blocked():
    """Verify that when contiguous capacity is blocked, tool returns capacity_blocked=True and alternative suggestions."""
    with patch("serviceBot.api.telephony.verify_contiguous_slot_capacity", return_value=False), \
         patch("serviceBot.api.telephony.get_customer_appointments") as mock_get_appts:

        mock_get_appts.return_value = [
            {
                "id": 1042,
                "appointment_datetime": "2026-10-02 10:00:00",
                "service_type": "Oil Change",
                "issue_description": "Oil Change and multipoint inspection",
                "duration_minutes": 45
            }
        ]

        payload = {
            "tool_call_id": "call_consolidate_2",
            "name": "consolidate_appointment_service",
            "arguments": {
                "appointment_id": 1042,
                "phone": "5551234567",
                "additional_issue": "Brake squeak and rotor check",
                "additional_service_type": "Brake Inspection",
                "additional_duration_minutes": 45
            }
        }
        resp = client.post("/api/v1/voice/tools", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        result = data.get("result", data)

        assert result["success"] is False
        assert result["capacity_blocked"] is True
        assert result["appointment_id"] == 1042
        assert "cannot accommodate" in result["message"] or "separate" in result["message"] or "slot" in result["message"]
