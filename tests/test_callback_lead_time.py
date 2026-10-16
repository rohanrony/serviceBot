import datetime as dt_mod
from unittest.mock import patch, MagicMock
import pytest
from fastapi.testclient import TestClient

from serviceBot.services.booking import validate_appointment_lead_time
from serviceBot.db.queries import _generate_dynamic_slots, resolve_asap_callback_time
from serviceBot.services.prompt_service import update_prompt_lead_time_buffers
from serviceBot.main import app as portal_app


def test_validate_callback_lead_time_rejects_under_2_hours():
    now = dt_mod.datetime(2026, 10, 16, 14, 0, 0)
    # 15 minutes in the future (the short notice bug)
    requested_15m = now + dt_mod.timedelta(minutes=15)

    valid, earliest, suggestions = validate_appointment_lead_time(
        requested_datetime=requested_15m,
        current_time=now,
        min_buffer_hours=2.0,
        booking_type="callback"
    )

    assert valid is False
    assert earliest == now + dt_mod.timedelta(hours=2.0)
    assert isinstance(suggestions, list)

    # 1 hour in the future (still under 2 hours)
    requested_1h = now + dt_mod.timedelta(hours=1)
    valid_1h, earliest_1h, _ = validate_appointment_lead_time(
        requested_datetime=requested_1h,
        current_time=now,
        min_buffer_hours=2.0,
        booking_type="callback"
    )
    assert valid_1h is False
    assert earliest_1h == now + dt_mod.timedelta(hours=2.0)


def test_validate_callback_lead_time_accepts_over_2_hours():
    now = dt_mod.datetime(2026, 10, 16, 14, 0, 0)
    # 2.5 hours in the future
    requested = now + dt_mod.timedelta(hours=2.5)

    valid, earliest, suggestions = validate_appointment_lead_time(
        requested_datetime=requested,
        current_time=now,
        min_buffer_hours=2.0,
        booking_type="callback"
    )

    assert valid is True
    assert earliest == now + dt_mod.timedelta(hours=2.0)


def test_validate_callback_lead_time_defaults_to_config_when_none():
    now = dt_mod.datetime(2026, 10, 16, 14, 0, 0)
    requested = now + dt_mod.timedelta(hours=1.5)

    with patch("serviceBot.api.portal.load_config", return_value={"min_callback_buffer_hours": 2.0, "min_booking_buffer_hours": 4.0}):
        valid, earliest, _ = validate_appointment_lead_time(
            requested_datetime=requested,
            current_time=now,
            booking_type="callback"
        )
        assert valid is False
        assert earliest == now + dt_mod.timedelta(hours=2.0)


def test_dynamic_slots_for_callback_respects_buffer():
    now = dt_mod.datetime(2026, 10, 16, 10, 0, 0)
    with patch("serviceBot.services.timezone_service.now_in_business_tz", return_value=now), \
         patch("serviceBot.api.portal.load_config", return_value={"min_callback_buffer_hours": 2.0}):
        slots = _generate_dynamic_slots("2026-10-16", duration_minutes=15, interval_minutes=15, booking_type="callback")
        assert len(slots) > 0
        for s in slots:
            slot_dt = dt_mod.datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
            assert slot_dt >= now + dt_mod.timedelta(hours=2.0)


def test_resolve_asap_callback_time_respects_buffer():
    now = dt_mod.datetime(2026, 10, 16, 10, 0, 0) # 10:00 AM on a Friday
    with patch("serviceBot.services.timezone_service.now_in_business_tz", return_value=now), \
         patch("serviceBot.api.portal.load_config", return_value={"min_callback_buffer_hours": 2.0}):
        asap_str = resolve_asap_callback_time()
        asap_dt = dt_mod.datetime.strptime(asap_str, "%Y-%m-%d %H:%M:%S")
        assert asap_dt >= now + dt_mod.timedelta(hours=2.0)


def test_telephony_create_service_request_callback_rejects_insufficient_lead_time():
    fixed_now = dt_mod.datetime(2026, 10, 16, 14, 0, 0)
    requested = fixed_now + dt_mod.timedelta(minutes=15) # 15 min short notice

    with patch("serviceBot.services.timezone_service.now_in_business_tz", return_value=fixed_now), \
         patch("serviceBot.api.portal.load_config", return_value={"min_callback_buffer_hours": 2.0, "min_booking_buffer_hours": 4.0}):
        client = TestClient(portal_app)
        payload = {
            "name": "create_service_request",
            "arguments": {
                "phone": "+19195550144",
                "customer_name": "Callback Short Notice Tester",
                "booking_type": "callback",
                "booking_time": requested.strftime("%Y-%m-%d %H:%M:%S"),
                "issue_description": "Oil change"
            }
        }
        res = client.post("/api/v1/voice/tools", json=payload)
        assert res.status_code == 200
        data = res.json()
        assert data["result"]["success"] is False
        assert data["result"]["error"] == "INSUFFICIENT_LEAD_TIME"
        assert "at least 2 hours advance notice" in data["result"]["agent_instruction"]


def test_prompt_service_updates_lead_time_buffers():
    sample_prompt = """
### 1. CORE INTENT
- If they prefer a callback: Callback calls are made during business hours (Monday–Friday 7:00 AM – 6:00 PM ET). If the caller mentions a preferred day or time window, confirm it.
- **If Appointment:**
  2. **4-Hour Minimum Planning Horizon Restriction (MANDATORY):**
     - To ensure technicians have adequate time to prepare work bays, tools, and parts, our shop requires at least 4 hours advance notice for all in-shop appointments.
     - You must NEVER offer, suggest, or book an in-shop appointment slot earlier than 4 hours from the current time (`now + 4 hours`).
     - If no slots work today, offer tomorrow or an advisor callback (callbacks have no 4-hour buffer).
"""
    updated = update_prompt_lead_time_buffers(
        sample_prompt,
        appointment_buffer_hours=3.0,
        callback_buffer_hours=2.0
    )

    assert "3-Hour Minimum Planning Horizon Restriction" in updated
    assert "at least 3 hours advance notice for all in-shop appointments" in updated
    assert "earlier than 3 hours from the current time" in updated
    assert "Callbacks require at least 2 hours advance notice" in updated
    assert "advisor callbacks require at least 2 hours advance notice" in updated
    assert "callbacks have no 4-hour buffer" not in updated


def test_portal_config_endpoint_supports_callback_buffer():
    client = TestClient(portal_app)
    get_res = client.get("/api/v1/portal/config")
    assert get_res.status_code == 200
    cfg = get_res.json()
    assert "min_callback_buffer_hours" in cfg

    # Test update endpoint
    with patch("serviceBot.api.portal.save_config") as mock_save, \
         patch("serviceBot.api.portal.sync_prompt_to_elevenlabs", return_value=None):
        post_res = client.post("/api/v1/portal/config", json={"min_callback_buffer_hours": 2.5})
        assert post_res.status_code == 200
        mock_save.assert_called_once()
        saved_data = mock_save.call_args[0][0]
        assert saved_data["min_callback_buffer_hours"] == 2.5
