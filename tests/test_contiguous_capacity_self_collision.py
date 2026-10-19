import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from psycopg2 import OperationalError

from serviceBot.main import app
from serviceBot.services.calendar_availability import verify_contiguous_slot_capacity

client = TestClient(app)


@pytest.mark.parametrize("failure_stage", ["connection", "execute", "fetch"])
def test_capacity_database_failure_cannot_authorize_extension(failure_stage):
    """Unavailable reservation evidence must never authorize extra capacity."""
    connection = MagicMock()
    connection.__enter__.return_value = connection
    cursor = MagicMock()
    cursor.__enter__.return_value = cursor
    cursor.fetchone.return_value = None
    error = OperationalError("reservation database unavailable")
    with patch("serviceBot.services.calendar_availability.get_db_connection", return_value=connection) as connect, \
         patch("serviceBot.services.calendar_availability.dict_cursor", return_value=cursor):
        if failure_stage == "connection":
            connect.side_effect = error
        elif failure_stage == "execute":
            cursor.execute.side_effect = error
        else:
            cursor.fetchone.side_effect = error

        assert verify_contiguous_slot_capacity("2026-10-05 11:00:00", 90) is False


@pytest.mark.parametrize("start_time", ["invalid start time", None, 42])
def test_capacity_unparseable_start_cannot_authorize_extension(start_time):
    with patch("serviceBot.services.calendar_availability.get_db_connection") as connect:
        assert verify_contiguous_slot_capacity(start_time, 90) is False
        connect.assert_not_called()


def test_consolidation_database_failure_prevents_mutation_and_notification():
    """Exercise the real capacity gate through the voice tool boundary."""
    appointment_connection = MagicMock()
    appointment_connection.__enter__.return_value = appointment_connection
    appointment_cursor = MagicMock()
    appointment_cursor.__enter__.return_value = appointment_cursor
    appointment_cursor.fetchone.return_value = {
        "id": 27, "booking_time": "2026-10-05 11:00:00",
        "duration_minutes": 60, "staff_agent_id": 10,
    }
    capacity_connection = MagicMock()
    capacity_connection.__enter__.return_value = capacity_connection
    capacity_cursor = MagicMock()
    capacity_cursor.__enter__.return_value = capacity_cursor
    capacity_cursor.execute.side_effect = OperationalError("reservation database unavailable")
    with patch("serviceBot.api.telephony.get_customer_appointments", return_value=[{
             "id": 27, "phone": "5550100001",
         }]), \
         patch("serviceBot.api.telephony.get_db_connection", return_value=appointment_connection), \
         patch("serviceBot.api.telephony.dict_cursor", return_value=appointment_cursor), \
         patch("serviceBot.services.calendar_availability.get_db_connection", return_value=capacity_connection), \
         patch("serviceBot.services.calendar_availability.dict_cursor", return_value=capacity_cursor), \
         patch("serviceBot.api.telephony.consolidate_appointment_service", return_value={
             "appointment_id": 27, "combined_issues": "Brake inspection",
             "new_duration_minutes": 90, "booking_time": "2026-10-05 11:00:00",
         }) as consolidate, \
         patch("serviceBot.services.sms_router.SMSNotificationRouter.process_event") as notify:
        response = client.post("/api/v1/voice/tools", json={
            "name": "consolidate_appointment_service",
            "arguments": {"appointment_id": 27, "phone": "5550100001",
                          "additional_issue": "Brake inspection", "additional_duration_minutes": 30},
        })

    assert response.status_code == 200
    result = response.json()["result"]
    assert result["success"] is False
    assert result["capacity_blocked"] is True
    consolidate.assert_not_called()
    notify.assert_not_called()

def test_verify_contiguous_slot_capacity_excludes_own_service_request():
    """Verify that verify_contiguous_slot_capacity does not collide with the appointment's own reservation."""
    # Mock database query results
    # When query does NOT exclude service_request_id: returns own reservation -> False
    # When query DOES exclude service_request_id: returns None -> True
    
    mock_cursor = MagicMock()
    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_cursor.__enter__.return_value = mock_cursor

    # Case 1: Without exclude_service_request_id, find own reservation -> returns False
    mock_cursor.fetchone.return_value = {"id": 11}
    with patch("serviceBot.services.calendar_availability.get_db_connection", return_value=mock_conn), \
         patch("serviceBot.services.calendar_availability.dict_cursor", return_value=mock_cursor):
        has_capacity = verify_contiguous_slot_capacity(
            start_time="2026-10-05 11:00:00",
            duration_minutes=90
        )
        assert has_capacity is False
        query, params = mock_cursor.execute.call_args[0]
        assert "service_request_id" not in query

    # Case 2: With exclude_service_request_id=27, own reservation is filtered out -> returns True
    mock_cursor.fetchone.return_value = None
    with patch("serviceBot.services.calendar_availability.get_db_connection", return_value=mock_conn), \
         patch("serviceBot.services.calendar_availability.dict_cursor", return_value=mock_cursor):
        has_capacity = verify_contiguous_slot_capacity(
            start_time="2026-10-05 11:00:00",
            duration_minutes=90,
            exclude_service_request_id=27,
            staff_agent_id=10
        )
        assert has_capacity is True
        query, params = mock_cursor.execute.call_args[0]
        assert "service_request_id != %s" in query
        assert 27 in params
        assert "staff_agent_id = %s" in query
        assert 10 in params


def test_verify_contiguous_slot_capacity_enforces_closing_hours():
    """Verify that an appointment extending past 6:00 PM (18:00) is rejected."""
    # 5:00 PM start with 90 minute duration ends at 6:30 PM -> should return False immediately
    has_capacity = verify_contiguous_slot_capacity(
        start_time="2026-10-05 17:00:00",
        duration_minutes=90,
        exclude_service_request_id=27
    )
    assert has_capacity is False

    # 4:30 PM start with 90 minute duration ends at 6:00 PM -> allowed
    with patch("serviceBot.services.calendar_availability.get_db_connection") as mock_get_conn:
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.__enter__.return_value = mock_conn
        mock_cursor.__enter__.return_value = mock_cursor
        mock_cursor.fetchone.return_value = None
        mock_get_conn.return_value = mock_conn
        with patch("serviceBot.services.calendar_availability.dict_cursor", return_value=mock_cursor):
            has_capacity = verify_contiguous_slot_capacity(
                start_time="2026-10-05 16:30:00",
                duration_minutes=90,
                exclude_service_request_id=27
            )
            assert has_capacity is True


def test_consolidate_tool_passes_exclude_service_request_id():
    """Verify that the consolidate_appointment_service voice tool passes exclude_service_request_id to avoid self-collision."""
    mock_sr = {
        "id": 27,
        "booking_time": "2026-10-05 11:00:00",
        "duration_minutes": 60,
        "staff_agent_id": 10,
        "service_type": "Engine Diagnostic",
        "issue_description": "engine heating"
    }

    mock_consolidate_res = {
        "appointment_id": 27,
        "combined_issues": "engine heating; Battery and fluid inspection",
        "new_duration_minutes": 90,
        "booking_time": "2026-10-05 11:00:00",
        "vehicle": {"year": 2020, "make": "Tesla", "model": "Model 3"}
    }

    with patch("serviceBot.api.telephony.get_customer_appointments", return_value=[{
             **mock_sr, "phone": "4242704893",
         }]), \
         patch("serviceBot.api.telephony.verify_contiguous_slot_capacity") as mock_verify_cap, \
         patch("serviceBot.api.telephony.consolidate_appointment_service", return_value=mock_consolidate_res), \
         patch("serviceBot.api.telephony.get_db_connection") as mock_get_conn:

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.__enter__.return_value = mock_conn
        mock_cursor.__enter__.return_value = mock_cursor
        mock_cursor.fetchone.return_value = mock_sr
        mock_get_conn.return_value = mock_conn
        with patch("serviceBot.api.telephony.dict_cursor", return_value=mock_cursor):
            mock_verify_cap.return_value = True

            payload = {
                "name": "consolidate_appointment_service",
                "arguments": {
                    "appointment_id": 27,
                    "phone": "4242704893",
                    "additional_issue": "Battery and fluid inspection",
                    "additional_service_type": "Electric Vehicle Diagnostics",
                    "additional_duration_minutes": 30
                }
            }
            resp = client.post("/api/v1/voice/tools", json=payload)
            assert resp.status_code == 200
            data = resp.json()
            result = data.get("result", data)
            assert result["success"] is True

            # Verify that verify_contiguous_slot_capacity was called with exclude_service_request_id=27 and staff_agent_id=10
            mock_verify_cap.assert_called_once()
            _, kwargs = mock_verify_cap.call_args
            assert kwargs.get("exclude_service_request_id") == 27
            assert kwargs.get("staff_agent_id") == 10
            assert kwargs.get("duration_minutes") == 90


def test_get_customer_appointments_cross_references_caller_phone():
    """Verify that if phone has no appointments, but caller_phone is provided and has appointments, they are returned."""
    with patch("serviceBot.api.telephony.get_customer_appointments") as mock_get_appts:
        def side_effect(ph):
            if ph == "4442704893":
                return []
            if ph == "4242704893":
                return [
                    {
                        "id": 27,
                        "appointment_datetime": "2026-10-25 11:00:00",
                        "booking_type": "appointment",
                        "service_type": "Engine Diagnostic",
                        "issue_description": "engine heating",
                        "duration_minutes": 60,
                        "status": "pending",
                        "year": 2020,
                        "make": "Tesla",
                        "model": "Model 3"
                    }
                ]
            return []

        mock_get_appts.side_effect = side_effect

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
        assert len(result["appointments"]) == 1
        assert result["appointments"][0]["id"] == 27
        assert "found under your calling number (4242704893)" in result["message"]
