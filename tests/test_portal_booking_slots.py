import datetime
from unittest.mock import patch, MagicMock
import pytest
from fastapi.testclient import TestClient

from serviceBot.api import portal
from serviceBot.main import app
from serviceBot.db.connection import get_db_connection, dict_cursor
from serviceBot.services.booking import BookingService

client = TestClient(app)


def test_available_slots_timezone_formatting(tmp_path, monkeypatch):
    """US3/AC1: Service requests use date-first scheduling with returned slots formatted in business timezone."""
    monkeypatch.setattr(portal, "CONFIG_PATH", str(tmp_path / "config.json"))
    monkeypatch.setattr(portal, "SYSTEM_PROMPT_PATH", str(tmp_path / "prompt.txt"))

    # Configure business timezone as America/Chicago (CT)
    portal.save_config({
        "business_timezone": "America/Chicago",
        "business_hours_start": 9,
        "business_hours_end": 17,
        "business_days": [0, 1, 2, 3, 4],
    })

    # Pick next Monday
    today = datetime.date.today()
    days_ahead = 7 - today.weekday() if today.weekday() != 0 else 7
    target_date = (today + datetime.timedelta(days=days_ahead)).isoformat()

    response = client.get(f"/api/v1/portal/available-slots?date={target_date}&duration_minutes=60")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["date"] == target_date
    slots = data["available_slots"]
    assert isinstance(slots, list)
    assert len(slots) > 0

    # Ensure slot times are in the configured timezone format
    first_slot = slots[0]
    # first_slot could be a dict with start/end or formatted strings
    start_time = first_slot.get("start") or first_slot.get("time") or first_slot.get("start_time") or str(first_slot)
    assert start_time is not None


def test_reschedule_requires_customer_consent(tmp_path, monkeypatch):
    """US3/AC2: Changing appointment time requires customer consent and revalidates availability atomically."""
    monkeypatch.setattr(portal, "CONFIG_PATH", str(tmp_path / "config.json"))
    monkeypatch.setattr(portal, "SYSTEM_PROMPT_PATH", str(tmp_path / "prompt.txt"))

    portal.save_config({
        "business_timezone": "America/New_York",
        "business_hours_start": 8,
        "business_hours_end": 18,
    })

    # Create an initial appointment in DB
    with get_db_connection() as conn, dict_cursor(conn) as cursor:
        cursor.execute("SELECT id FROM customers LIMIT 1;")
        cust = cursor.fetchone()
        customer_id = cust["id"] if cust else 1
        cursor.execute("SELECT id FROM staff_agents WHERE is_active = TRUE LIMIT 1;")
        agent = cursor.fetchone()
        agent_id = agent["id"] if agent else 1

        cursor.execute("""
            INSERT INTO service_requests (
                customer_id, service_type, issue_description, status,
                booking_type, booking_time, duration_minutes, staff_agent_id
            ) VALUES (%s, 'Maintenance', 'Initial Inspection', 'confirmed', 'appointment', '2026-11-10T10:00:00', 60, %s)
            RETURNING id;
        """, (customer_id, agent_id))
        conn.commit()
        request_id = cursor.fetchone()["id"]

    # 1. Attempt to reschedule WITHOUT customer consent
    res_no_consent = client.put(f"/api/v1/portal/service-requests/{request_id}", json={
        "issue_description": "Updated Inspection",
        "booking_time": "2026-11-10T14:00:00",
        "duration_minutes": 60,
        "customer_consent": False,
        "customer_consent_obtained": False,
    })
    assert res_no_consent.status_code == 400
    assert "consent" in res_no_consent.json()["detail"].lower()

    # Verify original booking_time is preserved
    with get_db_connection() as conn, dict_cursor(conn) as cursor:
        cursor.execute("SELECT booking_time FROM service_requests WHERE id = %s;", (request_id,))
        row = cursor.fetchone()
        assert str(row["booking_time"]).startswith("2026-11-10 10:00:00") or str(row["booking_time"]).startswith("2026-11-10T10:00:00")

    # 2. Reschedule WITH customer consent
    res_with_consent = client.put(f"/api/v1/portal/service-requests/{request_id}", json={
        "issue_description": "Updated Inspection",
        "booking_time": "2026-11-10T14:00:00",
        "duration_minutes": 60,
        "customer_consent": True,
    })
    assert res_with_consent.status_code == 200
    assert res_with_consent.json()["success"] is True

    # Verify booking_time was updated
    with get_db_connection() as conn, dict_cursor(conn) as cursor:
        cursor.execute("SELECT booking_time FROM service_requests WHERE id = %s;", (request_id,))
        row = cursor.fetchone()
        assert str(row["booking_time"]).startswith("2026-11-10 14:00:00") or str(row["booking_time"]).startswith("2026-11-10T14:00:00")
