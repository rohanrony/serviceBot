import datetime as dt_mod

import pytest
from fastapi.testclient import TestClient
from serviceBot.main import app
from serviceBot.db.connection import get_db_connection, dict_cursor

client = TestClient(app)


def _future_business_datetime(hour: int = 10, days_ahead: int = 7) -> str:
    candidate = dt_mod.date.today() + dt_mod.timedelta(days=days_ahead)
    while candidate.weekday() > 4:
        candidate += dt_mod.timedelta(days=1)
    return f"{candidate.isoformat()} {hour:02d}:00:00"


def test_available_slots_custom_duration():
    # Test checking slots for 15 min callback vs 90 min appointment.
    slot_date = _future_business_datetime().split(" ", 1)[0]

    res15 = client.get(f"/api/v1/portal/available-slots?date={slot_date}&duration_minutes=15")
    assert res15.status_code == 200
    data15 = res15.json()
    assert data15["success"] is True

    res90 = client.get(f"/api/v1/portal/available-slots?date={slot_date}&duration_minutes=90")
    assert res90.status_code == 200
    data90 = res90.json()
    assert data90["success"] is True


def test_create_service_request_with_type_and_duration():
    booking_time = _future_business_datetime(hour=10, days_ahead=7)
    payload = {
        "customer": {
            "name": "Dynamic Duration Test",
            "phone": "+15559998877"
        },
        "vehicle": {
            "make": "Toyota",
            "model": "Camry",
            "year": 2022,
            "vin": "1234567890ABCDEFG"
        },
        "service_request": {
            "service_type": "Engine Diagnostic",
            "issue_description": "Check engine light on",
            "booking_time": booking_time,
            "booking_type": "appointment",
            "duration_minutes": 90
        }
    }

    res = client.post("/api/v1/portal/service-requests", json=payload)
    assert res.status_code == 201
    req_id = res.json()["request_id"]

    # Verify database record
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("SELECT booking_type, duration_minutes FROM service_requests WHERE id = %s", (req_id,))
            row = cursor.fetchone()
            assert row["booking_type"] == "appointment"
            assert row["duration_minutes"] == 90
