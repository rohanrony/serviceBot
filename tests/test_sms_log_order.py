import pytest
from unittest.mock import patch, MagicMock

def test_get_sms_logs_by_appointment_query_ordering():
    """Verify that get_sms_logs_by_appointment executes ORDER BY created_at DESC, id DESC."""
    from serviceBot.db.queries import get_sms_logs_by_appointment
    
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = [
        {
            "id": 2,
            "appointment_id": 10,
            "created_at": "2026-07-31 16:00:00",
            "sent_at": "2026-07-31 16:00:01",
            "status": "DELIVERED",
            "recipient_type": "CUSTOMER"
        },
        {
            "id": 1,
            "appointment_id": 10,
            "created_at": "2026-07-31 15:00:00",
            "sent_at": "2026-07-31 15:00:01",
            "status": "DELIVERED",
            "recipient_type": "CUSTOMER"
        }
    ]
    
    mock_conn = MagicMock()
    
    with patch("serviceBot.db.queries.get_db_connection") as mock_get_conn, \
         patch("serviceBot.db.queries.dict_cursor") as mock_dict_cursor:
        mock_get_conn.return_value.__enter__.return_value = mock_conn
        mock_dict_cursor.return_value.__enter__.return_value = mock_cursor
        
        logs = get_sms_logs_by_appointment(10)
        
        # Verify SQL query includes ORDER BY created_at DESC, id DESC
        assert mock_cursor.execute.called
        query_executed = mock_cursor.execute.call_args[0][0]
        assert "ORDER BY created_at DESC, id DESC" in query_executed
        
        # Verify return list structure
        assert len(logs) == 2
        assert logs[0]["id"] == 2
        assert logs[1]["id"] == 1


def test_get_appointment_sms_logs_endpoint_ordering():
    """Verify that portal API endpoint passes through descending ordered logs."""
    from fastapi.testclient import TestClient
    from serviceBot.main import app
    
    mock_logs = [
        {"id": 105, "created_at": "2026-07-31 16:30:00", "body": "Latest notification"},
        {"id": 101, "created_at": "2026-07-31 10:00:00", "body": "Initial booking confirmation"}
    ]
    mock_app_details = {
        "id": 42,
        "customer_name": "John Doe",
        "customer_phone": "+15551234567",
        "service_type": "Brake Inspection",
        "status": "CONFIRMED"
    }

    with patch("serviceBot.db.queries.get_sms_logs_by_appointment", return_value=mock_logs), \
         patch("serviceBot.db.queries.get_appointment_details_by_id", return_value=mock_app_details):
        
        client = TestClient(app)
        res = client.get("/api/v1/portal/sms/logs/appointment/42")
        
        assert res.status_code == 200
        data = res.json()
        
        assert "logs" in data
        logs = data["logs"]
        assert len(logs) == 2
        # First log is the latest
        assert logs[0]["id"] == 105
        assert logs[1]["id"] == 101


def test_iso_utc_timestamp_formatting():
    """Verify _to_iso_utc_str converts string and datetime objects into ISO 8601 UTC with Z suffix."""
    import datetime
    from serviceBot.db.queries import _to_iso_utc_str
    
    dt = datetime.datetime(2026, 7, 31, 20, 15, 30)
    formatted_dt = _to_iso_utc_str(dt)
    assert formatted_dt == "2026-07-31T20:15:30Z"
    
    str_ts = "2026-07-31 20:15:30"
    formatted_str = _to_iso_utc_str(str_ts)
    assert formatted_str == "2026-07-31T20:15:30Z"
    
    str_iso = "2026-07-31T20:15:30Z"
    assert _to_iso_utc_str(str_iso) == "2026-07-31T20:15:30Z"
    
    assert _to_iso_utc_str(None) is None


def test_app_js_timezone_helper_integration():
    """Verify app.js contains formatLocalTimestamp and integrates with SMS logs and chat views."""
    import os
    js_path = os.path.join(os.path.dirname(__file__), "..", "serviceBot", "static", "app.js")
    with open(js_path, "r", encoding="utf-8") as f:
        js_content = f.read()

    assert "function formatLocalTimestamp" in js_content
    assert "formatLocalTimestamp(l.created_at)" in js_content
    assert "formatLocalTimestamp(l.sent_at)" in js_content
    assert "formatLocalTimestamp(l.scheduled_send_at)" in js_content
    assert "formatLocalTimestamp(m.created_at" in js_content

