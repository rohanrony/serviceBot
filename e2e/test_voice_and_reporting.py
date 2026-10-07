"""Voice-to-portal, reporting, and integration configuration acceptance."""

import re
from datetime import timedelta

import pytest

PORTAL = "/api/v1/portal"


def voice(api, name, arguments):
    response = api.post(
        "/api/v1/voice/tools",
        json={"tool_call_id": "e2e-voice", "name": name, "arguments": arguments},
    )
    assert response.status_code == 200
    assert response.json()["tool_call_id"] == "e2e-voice"
    return response.json()["result"]


@pytest.mark.parametrize("flat", [False, True])
def test_voice_intake_creates_real_booking_visible_in_portal(api, scenario, flat):
    args = {
        "customer_name": "Voice E2E",
        "phone": "+15550100006",
        "make": "Honda",
        "model": "Civic",
        "year": 2021,
        "issue_description": "Oil Change",
        "service_type": "Oil Change",
        "booking_type": "appointment",
        "booking_time": scenario["start"].isoformat(),
        "call_sid": "e2e-voice-booking",
    }
    if flat:
        response = api.post(
            "/api/v1/voice/tools?name=create_service_request", json=args
        )
        assert response.status_code == 200
        result = response.json()["result"]
    else:
        result = voice(api, "create_service_request", args)
    assert result["success"] is True, result
    row = next(
        row
        for row in api.get(f"{PORTAL}/service-requests").json()
        if row["id"] == result["service_request_id"]
    )
    assert re.sub(r"\D", "", row["phone"])[-10:] == "5550100006"
    assert row["customer_name"] == "Voice E2E"
    assert row["booking_type"] == "appointment"
    assert row["duration_minutes"] == 60
    assert row["booking_end_time"] == (scenario["start"] + timedelta(hours=1)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    assert "extend" in result["message"].lower()


def test_voice_time_change_in_same_call_updates_one_booking(api, scenario):
    args = {
        "customer_name": "Voice E2E",
        "phone": "+15550100006",
        "make": "Honda",
        "model": "Civic",
        "year": 2021,
        "issue_description": "Oil Change",
        "service_type": "Oil Change",
        "booking_type": "appointment",
        "booking_time": scenario["start"].isoformat(),
        "call_sid": "e2e-voice-revised",
    }
    first = voice(api, "create_service_request", args)
    assert first["success"] is True, first
    args["booking_time"] = (scenario["start"] + timedelta(hours=1)).isoformat()
    revised = voice(api, "create_service_request", args)
    assert revised["success"] is True, revised
    assert revised["is_update"] is True
    assert revised["service_request_id"] == first["service_request_id"]
    rows = [
        r
        for r in api.get(f"{PORTAL}/service-requests").json()
        if re.sub(r"\D", "", r["phone"])[-10:] == "5550100006"
    ]
    assert len(rows) == 1
    assert rows[0]["booking_start_time"] == (
        scenario["start"] + timedelta(hours=1)
    ).strftime("%Y-%m-%d %H:%M:%S")


def test_unknown_voice_tool_reports_failure(api):
    result = voice(api, "not_a_real_tool", {})
    assert result["success"] is False
    assert "Unknown tool" in result["message"]


def test_voice_availability_uses_requested_day_and_real_capacity(api, scenario):
    result = voice(
        api,
        "check_availability",
        {
            "preferred_date": scenario["date"],
            "preferred_time": "10:00 AM",
            "service_type": "Oil Change",
            "booking_type": "appointment",
        },
    )
    assert result["success"] is True, result
    assert result["available_slots"]
    assert all(slot.startswith(scenario["date"]) for slot in result["available_slots"])
    assert scenario["start"].strftime("%Y-%m-%d %H:%M:%S") in result["available_slots"]


def test_unknown_calendar_provider_state_does_not_offer_slots(
    api, scenario, monkeypatch
):
    from serviceBot.services import google_calendar

    monkeypatch.setattr(
        google_calendar, "fetch_agent_events", lambda *args, **kwargs: None
    )
    result = voice(
        api,
        "check_availability",
        {"preferred_date": scenario["date"], "service_type": "Oil Change"},
    )
    assert result["available_slots"] == []


def test_dashboard_counts_and_timeframe_reflect_data(api, db):
    db(
        "INSERT INTO crm_notes (call_id, customer_id, summary, transcript, created_at) VALUES ('old-call', 1, 'Old summary', '', NOW() - INTERVAL '40 days'), ('new-call', 1, 'New summary', '', NOW())"
    )
    recent = api.get(f"{PORTAL}/stats?calls_timeframe=24h").json()
    all_time = api.get(f"{PORTAL}/stats?calls_timeframe=all").json()
    assert recent["total_calls"] == 1
    assert all_time["total_calls"] == 2
    assert recent["total_requests"] == 1
    assert recent["total_appointments"] == 1
    assert recent["pending_requests"] == 1
    assert recent["total_callbacks"] == 0


def test_call_pagination_keeps_distinct_records(api, db):
    db(
        "INSERT INTO crm_notes (call_id, customer_id, summary, transcript, created_at) VALUES ('first-call', 1, 'Older', '', NOW() - INTERVAL '1 minute'), ('second-call', 1, 'Newer', '', NOW())"
    )
    first = api.get(f"{PORTAL}/calls?limit=1&offset=0").json()
    second = api.get(f"{PORTAL}/calls?limit=1&offset=1").json()
    assert [row["call_id"] for row in first] == ["second-call"]
    assert [row["call_id"] for row in second] == ["first-call"]


def test_sla_analytics_and_technician_scorecard_agree(api, db):
    db(
        "UPDATE service_requests SET staff_agent_id = 1, status = 'confirmed', confirmation_status = 'confirmed', confirmation_cutoff_at = NOW() + INTERVAL '1 hour', confirmed_at = NOW(), created_at = NOW() - INTERVAL '10 minutes' WHERE id = 1"
    )
    overview = api.get(f"{PORTAL}/analytics/overview").json()
    assert overview["total_appointments"] == 1
    assert overview["total_confirmed"] == 1
    assert overview["on_time_confirmed"] == 1
    assert overview["sla_on_time_pct"] == 100
    sla = api.get(f"{PORTAL}/analytics/sla").json()
    assert sum(day["on_time"] for day in sla["timeline"]) == 1
    assert sla["latency_distribution"]["under_15m"] == 1
    scorecard = api.get(f"{PORTAL}/analytics/technicians").json()
    tech = next(row for row in scorecard if row["agent_id"] == 1)
    assert tech["total_assigned"] == 1
    assert tech["confirmed_count"] == 1


def test_escalation_filter_and_reporting_show_unresolved_case(api, db):
    db(
        "UPDATE service_requests SET escalation_status = 'escalated', escalation_reason = 'TIMEOUT_NO_RESPONSE' WHERE id = 1"
    )
    rows = api.get(f"{PORTAL}/service-requests?escalated=true").json()
    assert [row["id"] for row in rows] == [1]
    assert rows[0]["candidate_agents"]
    assert api.get(f"{PORTAL}/service-requests?escalated=false").json() == []
    report = api.get(f"{PORTAL}/analytics/escalations").json()
    assert report["reasons"]["TIMEOUT_NO_RESPONSE"] == 1
    assert report["outcomes"]["active_unresolved"] == 1


def test_customer_onboarding_records_role_without_claiming_whatsapp_connection(api):
    response = api.post(
        f"{PORTAL}/twilio/customer-onboard",
        json={
            "phone_number": "+15550100009",
            "friendly_name": "Onboarded E2E",
            "recipient_role": "CUSTOMER",
        },
    )
    assert response.status_code == 200
    record = response.json()["record"]
    assert record["twilio_verified"] is True
    assert record["whatsapp_onboarded"] is False
    records = api.get(f"{PORTAL}/sms/whitelist").json()
    assert any(
        row["id"] == record["id"] and row["recipient_role"] == "CUSTOMER"
        for row in records
    )
    assert api.delete(f"{PORTAL}/sms/whitelist/{record['id']}").status_code == 200
    assert all(
        row["id"] != record["id"] for row in api.get(f"{PORTAL}/sms/whitelist").json()
    )


def test_gmail_config_round_trip_masks_password(api):
    password = "e2e-fake-app-password"
    response = api.post(
        f"{PORTAL}/gmail-config",
        json={
            "gmail_enabled": False,
            "gmail_auth_type": "app_password",
            "gmail_sender": "sender@example.test",
            "gmail_recipient": "admin@example.test",
            "gmail_password": password,
            "enable_agent_selection": True,
        },
    )
    assert response.status_code == 200
    response = api.get(f"{PORTAL}/gmail-config")
    saved = response.json()
    assert saved["gmail_sender"] == "sender@example.test"
    assert saved["gmail_recipient"] == "admin@example.test"
    assert saved["has_password"] is True
    assert password not in response.text
