"""Details trace uses persisted booking duration and explicit business instants."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from playwright.sync_api import expect

from e2e.browser_network import route_offline_browser_request
from e2e.test_workflows import PORTAL, booking_payload


def create_timed_booking(api, scenario, kind, duration):
    payload = booking_payload(scenario)
    payload["service_request"].update(booking_type=kind, duration_minutes=duration)
    response = api.post(f"{PORTAL}/service-requests", json=payload)
    assert response.status_code == 201, response.text
    return response.json()["request_id"]


@pytest.mark.parametrize("kind,duration", [("callback", 15), ("appointment", 45)])
def test_trace_window_matches_persisted_duration_after_reschedule_and_cancel(api, db, scenario, kind, duration):
    from serviceBot.db.queries import cancel_appointment, reschedule_appointment

    request_id = create_timed_booking(api, scenario, kind, duration)
    moved = scenario["start"] + timedelta(hours=1)
    reschedule_appointment(request_id, moved.isoformat(), True, "test")
    cancel_appointment(request_id, True, "test")
    for path in (f"{PORTAL}/service-requests/{request_id}/trace", f"{PORTAL}/sms/logs/appointment/{request_id}"):
        response = api.get(path)
        assert response.status_code == 200, response.text
        appointment = response.json()["appointment"]
        assert appointment["status"] == "cancelled"
        assert appointment["duration_minutes"] == duration
        start = datetime.fromisoformat(appointment["booking_start_time"])
        end = datetime.fromisoformat(appointment["booking_end_time"])
        assert start.tzinfo is not None and end.tzinfo is not None
        assert start == moved.replace(tzinfo=ZoneInfo("America/New_York"))
        assert end - start == timedelta(minutes=duration)
    reservation = db("SELECT starts_at, ends_at FROM appointment_reservations WHERE service_request_id=%s", (request_id,))[0]
    assert reservation["starts_at"] == moved
    assert reservation["ends_at"] == moved + timedelta(minutes=duration)


@pytest.mark.parametrize("browser_timezone", ["UTC", "America/New_York"])
@pytest.mark.parametrize("day,offset", [("2026-10-29", "-04:00"), ("2026-11-05", "-05:00")])
def test_trace_callback_window_renders_business_time_across_dst(api, db, scenario, freeze_business_clock, browser_instance, live_server, browser_timezone, day, offset):
    starts = datetime.fromisoformat(day + "T14:00:00")
    freeze_business_clock(starts - timedelta(days=2))
    request_id = create_timed_booking(api, {**scenario, "start": starts}, "callback", 15)
    from serviceBot.db.queries import cancel_appointment
    cancel_appointment(request_id, True, "test")
    response = api.get(f"{PORTAL}/service-requests/{request_id}/trace")
    assert response.status_code == 200
    appointment = response.json()["appointment"]
    with browser_instance.new_context(timezone_id=browser_timezone) as context:
        context.route("**/*", route_offline_browser_request)
        page = context.new_page()
        page.goto(f"{live_server}/portal/", wait_until="domcontentloaded")
        page.locator(f'.details-sms-log-btn[data-id="{request_id}"]').click()
        overview = page.locator("#details-overview-header-card")
        expect(overview).to_be_visible()
        expect(overview).to_contain_text("02:00 PM")
        expect(overview).to_contain_text("02:15 PM")
        expect(overview).to_contain_text("15 mins")
    assert appointment["booking_start_time"].endswith(offset)
