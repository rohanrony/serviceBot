import datetime as dt_mod
from unittest.mock import patch, MagicMock
import pytest
from fastapi.testclient import TestClient

from serviceBot.services.booking import validate_appointment_lead_time, BookingHorizonError
from serviceBot.main import app as portal_app


def test_validate_appointment_lead_time_rejects_under_4_hours():
    now = dt_mod.datetime(2026, 10, 5, 9, 0, 0)
    # 2 hours in the future
    requested = now + dt_mod.timedelta(hours=2)

    valid, earliest, suggestions = validate_appointment_lead_time(
        requested_datetime=requested,
        current_time=now,
        min_buffer_hours=4.0,
        booking_type="appointment"
    )

    assert valid is False
    assert earliest == now + dt_mod.timedelta(hours=4.0)
    assert isinstance(suggestions, list)


def test_validate_appointment_lead_time_accepts_over_4_hours():
    now = dt_mod.datetime(2026, 10, 5, 9, 0, 0)
    # 5 hours in the future
    requested = now + dt_mod.timedelta(hours=5)

    valid, earliest, suggestions = validate_appointment_lead_time(
        requested_datetime=requested,
        current_time=now,
        min_buffer_hours=4.0,
        booking_type="appointment"
    )

    assert valid is True
    assert earliest == now + dt_mod.timedelta(hours=4.0)


def test_validate_appointment_lead_time_allows_callbacks_within_buffer():
    now = dt_mod.datetime(2026, 10, 5, 9, 0, 0)
    requested = now + dt_mod.timedelta(hours=1)

    valid, earliest, suggestions = validate_appointment_lead_time(
        requested_datetime=requested,
        current_time=now,
        min_buffer_hours=4.0,
        booking_type="callback"
    )

    assert valid is True


def test_validate_appointment_lead_time_custom_buffer():
    now = dt_mod.datetime(2026, 10, 5, 9, 0, 0)
    requested = now + dt_mod.timedelta(hours=2.5)

    # With 2-hour buffer, 2.5 hours is valid
    valid_2h, earliest_2h, _ = validate_appointment_lead_time(
        requested_datetime=requested,
        current_time=now,
        min_buffer_hours=2.0,
        booking_type="appointment"
    )
    assert valid_2h is True

    # With 3-hour buffer, 2.5 hours is invalid
    valid_3h, earliest_3h, _ = validate_appointment_lead_time(
        requested_datetime=requested,
        current_time=now,
        min_buffer_hours=3.0,
        booking_type="appointment"
    )
    assert valid_3h is False
    assert earliest_3h == now + dt_mod.timedelta(hours=3.0)


def test_telephony_book_appointment_rejects_insufficient_lead_time():
    fixed_now = dt_mod.datetime(2026, 10, 5, 8, 0, 0) # Monday 8:00 AM
    requested = fixed_now + dt_mod.timedelta(hours=2) # 10:00 AM (only 2 hours lead time)

    class MockDateTime(dt_mod.datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now

    import serviceBot.services.booking as b_mod
    with patch.object(b_mod.dt_mod, "datetime", MockDateTime):
        payload = {
            "name": "book_appointment",
            "arguments": {
                "phone": "+19195550144",
                "customer_name": "Lead Time Tester",
                "appointment_datetime": requested.strftime("%Y-%m-%d %H:%M:%S"),
                "service_type": "Brake Inspection",
                "make": "Honda",
                "model": "Civic",
                "year": 2021
            }
        }
        client = TestClient(portal_app)
        response = client.post("/api/v1/voice/tools", json=payload)
        assert response.status_code == 200
        data = response.json()
        res = data.get("result", {})

        assert res["success"] is False
        assert res.get("error") == "INSUFFICIENT_LEAD_TIME"
        assert res.get("min_buffer_hours") == 4
        assert "earliest_allowed_time" in res
        assert "agent_instruction" in res


def test_portal_create_service_request_rejects_insufficient_lead_time():
    client = TestClient(portal_app)
    fixed_now = dt_mod.datetime(2026, 10, 5, 8, 0, 0)
    requested = fixed_now + dt_mod.timedelta(hours=2) # 10:00 AM

    class MockDateTime(dt_mod.datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now

    import serviceBot.services.booking as b_mod
    with patch.object(b_mod.dt_mod, "datetime", MockDateTime), patch("serviceBot.api.portal.dt_mod.datetime", MockDateTime):
        resp = client.post(
            "/api/v1/portal/service-requests",
            json={
                "customer": {
                    "name": "Portal Lead Time Test",
                    "phone": "+19195550188"
                },
                "vehicle": {
                    "make": "Toyota",
                    "model": "Camry",
                    "year": 2021
                },
                "service_request": {
                    "booking_type": "appointment",
                    "booking_time": requested.strftime("%Y-%m-%d %H:%M:%S"),
                    "service_type": "Oil Change",
                    "issue_description": "Regular maintenance"
                }
            }
        )

        assert resp.status_code == 422
        body = resp.json()
        assert body["detail"]["error_code"] == "LEAD_TIME_VIOLATION"
        assert body["detail"]["min_buffer_hours"] == 4
