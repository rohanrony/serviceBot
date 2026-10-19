"""A disconnected technician must never produce a voice booking confirmation."""

from datetime import timedelta

import pytest

from e2e.scenarios import capacity_snapshot, service
from e2e.test_voice_and_reporting import voice
from serviceBot.services.google_calendar import (
    fetch_agent_events as native_fetch_events,
)


@pytest.mark.parametrize("tool_name", ["create_service_request", "book_appointment"])
@pytest.mark.parametrize("multiple_services", [False, True])
def test_disconnected_qualified_technician_rejects_booking_with_clear_caller_guidance(
    api, db, scenario, monkeypatch, freeze_business_clock, tool_name, multiple_services
):
    freeze_business_clock(scenario["start"] - timedelta(days=2))
    # Only technician 2 is qualified. Exercise the real missing OAuth binding,
    # reservation owner, rollback, and native HTTP tool response.
    service(api, "Disconnected technician service", [2], 30)
    names = ["Disconnected technician service"]
    if multiple_services:
        service(api, "Second disconnected service", [2], 30)
        names.append("Second disconnected service")
    assert db("SELECT agent_id FROM user_google_accounts WHERE agent_id=2") == []
    monkeypatch.setattr(
        "serviceBot.services.google_calendar.fetch_agent_events", native_fetch_events
    )
    before = capacity_snapshot(db)
    result = voice(api, tool_name, {
        "customer_name": "Alex E2E", "phone": "+15550100001",
        "make": "Toyota", "model": "Camry", "year": 2020,
        "service_type": names[0], "services": names,
        "issue_description": ", ".join(names), "booking_type": "appointment",
        "booking_time": scenario["start"].isoformat(),
        "appointment_datetime": scenario["start"].isoformat(),
        "call_sid": "disconnected-technician-regression",
    })
    assert result["success"] is False, result
    assert result["booking_confirmation_status"] == "unconfirmed"
    assert "Do not claim" in result["agent_guidance"]
    assert "could not confirm" in result["customer_message"].lower()
    assert "service_request_id" not in result and "appointment_id" not in result
    assert capacity_snapshot(db) == before


def test_unknown_calendar_lookup_tells_voice_agent_not_to_promise_booking(
    api, db, scenario, monkeypatch, freeze_business_clock
):
    freeze_business_clock(scenario["start"] - timedelta(days=2))
    service(api, "Disconnected lookup service", [2], 30)
    monkeypatch.setattr(
        "serviceBot.services.google_calendar.fetch_agent_events", native_fetch_events
    )
    before = capacity_snapshot(db)
    result = voice(api, "check_availability", {
        "service_type": "Disconnected lookup service", "preferred_date": scenario["date"]
    })
    assert result["success"] is False
    assert result["availability_status"] == "unknown"
    assert "Do not claim" in result["agent_guidance"]
    assert "availability" in result["customer_message"].lower()
    assert result["available_slots"] == []
    assert capacity_snapshot(db) == before
