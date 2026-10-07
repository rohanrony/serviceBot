"""Acceptance workflows over real HTTP, real domain services, and PostgreSQL."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest

PORTAL = "/api/v1/portal"


def booking_payload(scenario, *, phone="+15550100001", agent=1, start=None):
    return {
        "customer": {"name": "Alex E2E", "phone": phone},
        "vehicle": {"make": "Toyota", "model": "Camry", "year": 2020},
        "service_request": {
            "service_type": "Oil Change",
            "issue_description": "Oil change",
            "booking_type": "appointment",
            "duration_minutes": 60,
            "booking_time": (start or scenario["start"]).isoformat(),
            "staff_agent_id": agent,
        },
    }


def book(api, scenario, **kwargs):
    response = api.post(
        f"{PORTAL}/service-requests", json=booking_payload(scenario, **kwargs)
    )
    assert response.status_code == 201, response.text
    assert response.json()["success"] is True
    return response.json()["request_id"]


def request_by_id(api, request_id):
    response = api.get(f"{PORTAL}/service-requests")
    assert response.status_code == 200
    return next(row for row in response.json() if row["id"] == request_id)


def edit_payload(scenario, **overrides):
    return {
        "issue_description": "Oil change and brake inspection",
        "vehicle_details": {"make": "Toyota", "model": "Camry", "year": 2020},
        "booking_time": scenario["start"].isoformat(),
        "customer_consent_obtained": True,
        **overrides,
    }


def test_booking_visible_in_portal_and_consumes_agent_capacity(api, scenario):
    query = {"date": scenario["date"], "staff_agent_id": 1}
    start = scenario["start"].strftime("%Y-%m-%d %H:%M:%S")
    before = api.get(f"{PORTAL}/available-slots", params=query)
    assert before.status_code == 200
    assert any(slot["start_time"] == start for slot in before.json()["available_slots"])
    request_id = book(api, scenario)
    row = request_by_id(api, request_id)
    assert row["phone"] == "+15550100001"
    assert row["staff_agent_id"] == 1
    assert row["booking_type"] == "appointment"
    assert row["duration_minutes"] == 60
    assert row["status"] == "pending"
    assert row["confirmation_status"] == "pending_agent_confirmation"
    slots = api.get(f"{PORTAL}/available-slots", params=query).json()["available_slots"]
    assert slots, "The remaining free times must still be offered"
    assert all(slot["start_time"] != start for slot in slots)


def test_competing_bookings_have_one_winner_without_partial_request(api, scenario):
    bodies = [
        booking_payload(scenario, phone=phone)
        for phone in ("+15550100001", "+15550100002")
    ]
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(
            executor.map(
                lambda body: api.post(f"{PORTAL}/service-requests", json=body), bodies
            )
        )
    assert sorted(response.status_code for response in responses) == [201, 409]
    rows = api.get(f"{PORTAL}/service-requests").json()
    assert len(rows) == 2  # baseline unscheduled request plus the one committed booking


@pytest.mark.parametrize(
    "invalid", ["phone", "weekend", "after_closing", "grid", "duration"]
)
def test_invalid_booking_rejected_without_creating_request(api, scenario, invalid):
    payload = booking_payload(scenario)
    if invalid == "phone":
        payload["customer"]["phone"] = "123"
    elif invalid == "weekend":
        day = scenario["start"]
        while day.weekday() != 5:
            day += timedelta(days=1)
        payload["service_request"]["booking_time"] = day.isoformat()
    elif invalid == "after_closing":
        payload["service_request"]["booking_time"] = (
            scenario["start"].replace(hour=17, minute=30).isoformat()
        )
    elif invalid == "grid":
        payload["service_request"]["booking_time"] = (
            scenario["start"].replace(minute=7).isoformat()
        )
    else:
        payload["service_request"]["duration_minutes"] = -15
    response = api.post(f"{PORTAL}/service-requests", json=payload)
    assert response.status_code in {400, 422}, response.text
    assert len(api.get(f"{PORTAL}/service-requests").json()) == 1


def test_reschedule_requires_consent_and_preserves_booking_on_rejection(api, scenario):
    request_id = book(api, scenario)
    before = request_by_id(api, request_id)
    response = api.put(
        f"{PORTAL}/service-requests/{request_id}",
        json=edit_payload(
            scenario,
            booking_time=(scenario["start"] + timedelta(hours=1)).isoformat(),
            customer_consent_obtained=False,
        ),
    )
    assert response.status_code == 400
    assert "consent" in response.json()["detail"].lower()
    after = request_by_id(api, request_id)
    assert after["booking_time"] == before["booking_time"]
    assert after["issue_description"] == before["issue_description"]


def test_reschedule_moves_capacity_and_persists_vehicle_and_issue(api, scenario):
    request_id = book(api, scenario)
    new_time = scenario["start"] + timedelta(hours=1)
    response = api.put(
        f"{PORTAL}/service-requests/{request_id}",
        json=edit_payload(scenario, booking_time=new_time.isoformat()),
    )
    assert response.status_code == 200, response.text
    assert response.json()["success"] is True
    row = request_by_id(api, request_id)
    assert (
        row["booking_time"]
        .replace("T", " ")
        .startswith(new_time.strftime("%Y-%m-%d %H:%M"))
    )
    assert "brake inspection" in row["issue_description"].lower()
    # Released capacity is bookable again, occupied capacity is rejected.
    book(api, scenario, phone="+15550100002")
    conflict = api.post(
        f"{PORTAL}/service-requests",
        json=booking_payload(scenario, phone="+15550100006", start=new_time),
    )
    assert conflict.status_code == 409


def test_reassignment_moves_capacity_to_new_agent(api, scenario):
    request_id = book(api, scenario)
    response = api.patch(
        f"{PORTAL}/service-requests/{request_id}/assign-agent",
        json={"staff_agent_id": 2},
    )
    assert response.status_code == 200, response.text
    assert request_by_id(api, request_id)["staff_agent_id"] == 2
    book(api, scenario, phone="+15550100002", agent=1)
    conflict = api.post(
        f"{PORTAL}/service-requests",
        json=booking_payload(scenario, phone="+15550100006", agent=2),
    )
    assert conflict.status_code == 409


def test_cancellation_releases_capacity_and_clears_confirmation(api, scenario):
    request_id = book(api, scenario)
    response = api.patch(
        f"{PORTAL}/service-requests/{request_id}/status",
        json={"status": "cancelled_by_customer"},
    )
    assert response.status_code == 200
    row = request_by_id(api, request_id)
    assert row["status"] == "cancelled"
    assert row["confirmation_status"] == "cancelled"
    assert row["escalation_status"] == "none"
    book(api, scenario, phone="+15550100002")


def test_request_status_lifecycle_and_terminal_transition_rejection(api):
    for status in ("confirmed", "in_progress", "completed"):
        response = api.patch(
            f"{PORTAL}/service-requests/1/status", json={"status": status}
        )
        assert response.status_code == 200, response.text
        assert request_by_id(api, 1)["status"] == status
    response = api.patch(
        f"{PORTAL}/service-requests/1/status", json={"status": "pending"}
    )
    assert response.status_code == 400
    assert request_by_id(api, 1)["status"] == "completed"


def test_callback_intake_is_visible_as_callback(api, scenario):
    payload = booking_payload(scenario)
    payload["service_request"].update(
        booking_type="callback", booking_time=None, duration_minutes=15
    )
    response = api.post(f"{PORTAL}/service-requests", json=payload)
    assert response.status_code == 201, response.text
    callback = next(
        row
        for row in api.get(f"{PORTAL}/callbacks").json()
        if row["id"] == response.json()["request_id"]
    )
    assert request_by_id(api, callback["id"])["booking_type"] == "callback"
    assert callback["phone"] == "+15550100001"


@pytest.mark.parametrize(
    "query", [{"date": "invalid"}, {"date": "2030-01-07", "duration_minutes": -1}]
)
def test_invalid_availability_inputs_return_client_error(api, query):
    assert api.get(f"{PORTAL}/available-slots", params=query).status_code == 400


def test_staff_create_update_delete_persists(api):
    created = api.post(
        f"{PORTAL}/agents",
        json={
            "name": "Jamie E2E",
            "role": "Advisor",
            "email": "jamie@example.test",
            "phone_number": "+15550100007",
        },
    )
    assert created.status_code == 201
    agent_id = created.json()["id"]
    changed = api.put(
        f"{PORTAL}/agents/{agent_id}",
        json={"name": "Jamie Updated", "role": "Technician"},
    )
    assert changed.status_code == 200
    row = api.get(f"{PORTAL}/agents/{agent_id}").json()
    assert row["name"] == "Jamie Updated"
    assert row["role"] == "Technician"
    assert row["phone_number"] == "+15550100007"
    assert api.delete(f"{PORTAL}/agents/{agent_id}").status_code == 200
    assert api.get(f"{PORTAL}/agents/{agent_id}").status_code == 404


def test_calendar_slot_create_block_reopen_delete(api, scenario):
    new_time = scenario["start"] + timedelta(hours=3)
    created = api.post(
        f"{PORTAL}/agents/1/calendar",
        json={"slot_datetime": new_time.isoformat(), "is_booked": False},
    )
    assert created.status_code == 201, created.text
    slot_id = created.json()["id"]
    for blocked in (True, False):
        response = api.patch(
            f"{PORTAL}/calendar/{slot_id}", json={"is_booked": blocked}
        )
        assert response.status_code == 200
        row = next(
            s
            for s in api.get(f"{PORTAL}/agents/1/calendar").json()
            if s["id"] == slot_id
        )
        assert row["is_booked"] is blocked
    assert api.delete(f"{PORTAL}/calendar/{slot_id}").status_code == 200
    assert all(
        s["id"] != slot_id for s in api.get(f"{PORTAL}/agents/1/calendar").json()
    )


def test_reserved_slot_cannot_be_reopened_or_deleted(api, scenario):
    book(api, scenario)
    reserved = next(
        s
        for s in api.get(f"{PORTAL}/agents/1/calendar").json()
        if s["slot_datetime"] == scenario["start"].strftime("%Y-%m-%d %H:%M:%S")
    )
    assert reserved["is_booked"] is True
    assert (
        api.patch(
            f"{PORTAL}/calendar/{reserved['id']}", json={"is_booked": False}
        ).status_code
        == 409
    )
    assert api.delete(f"{PORTAL}/calendar/{reserved['id']}").status_code == 409


def test_knowledge_upload_overwrite_view_download_delete(api, scenario):
    filename = "e2e-policy.txt"
    for text in ("Warranty lasts twelve months.", "Warranty lasts twenty four months."):
        response = api.post(
            f"{PORTAL}/kb/upload",
            files={"file": (filename, text.encode(), "text/plain")},
        )
        assert response.status_code == 200
        assert response.json()["chunk_count"] == 1
        assert api.get(f"{PORTAL}/kb/view/{filename}").json()["content"] == text
        assert api.get(f"{PORTAL}/kb/download/{filename}").content == text.encode()
        chunks = [
            value[0]
            for value in scenario["collection"].entries.values()
            if value[1]["filename"] == filename
        ]
        assert chunks == [text]  # Overwriting removes stale indexed content.
    assert any(f["filename"] == filename for f in api.get(f"{PORTAL}/kb").json())
    assert api.delete(f"{PORTAL}/kb/{filename}").status_code == 200
    assert api.get(f"{PORTAL}/kb/view/{filename}").status_code == 404
    assert not scenario["collection"].entries


def test_knowledge_rejects_non_utf8_without_creating_file(api):
    response = api.post(
        f"{PORTAL}/kb/upload",
        files={"file": ("invalid.txt", b"\xff\xfe", "text/plain")},
    )
    assert response.status_code == 400
    assert api.get(f"{PORTAL}/kb").json() == []


def test_business_config_round_trip_preserves_other_fields(api):
    original = api.get(f"{PORTAL}/config").json()
    response = api.post(
        f"{PORTAL}/config",
        json={
            "business_name": "Updated E2E Garage",
            "business_hours_start": 9,
            "business_hours_end": 17,
            "min_booking_buffer_hours": 6,
        },
    )
    assert response.status_code == 200, response.text
    saved = api.get(f"{PORTAL}/config").json()
    assert saved["business_name"] == "Updated E2E Garage"
    assert saved["business_hours"] == list(range(9, 17))
    assert saved["min_booking_buffer_hours"] == 6
    assert saved["business_days"] == original["business_days"]


def test_notification_rules_are_independent_per_channel_and_role(api):
    response = api.put(
        f"{PORTAL}/sms/matrix-rules",
        json={
            "event_type": "BOOKING",
            "recipient_role": "admin",
            "channel": "SMS",
            "enabled": True,
        },
    )
    assert response.status_code == 200
    rules = api.get(f"{PORTAL}/sms/matrix-rules").json()
    selected = {
        (r["channel"], r["recipient_role"]): r["enabled"]
        for r in rules
        if r["event_type"] == "BOOKING"
    }
    assert selected[("SMS", "admin")] is True
    assert selected[("WHATSAPP", "admin")] is True
    assert selected[("SMS", "customer")] is True


def test_sms_reply_persists_message_and_state_then_resolve_returns_to_bot(api):
    response = api.post(
        f"{PORTAL}/sms/reply",
        json={
            "conversation_id": 1,
            "message": "Your technician will call you shortly.",
        },
    )
    assert response.status_code == 200
    assert response.json()["success"] is True
    assert response.json()["dispatch"]["success"] is True
    messages = api.get(f"{PORTAL}/sms/conversations/1/messages").json()
    assert [m["direction"] for m in messages] == ["inbound", "outbound"]
    assert messages[-1]["body"] == "Your technician will call you shortly."
    assert messages[-1]["sender_type"] == "agent"
    assert any(
        c["id"] == 1
        for c in api.get(f"{PORTAL}/sms/conversations?state=IN_PROGRESS").json()
    )
    response = api.post(f"{PORTAL}/sms/resolve", json={"conversation_id": 1})
    assert response.json()["state"] == "AUTOMATED"
    assert any(
        c["id"] == 1
        for c in api.get(f"{PORTAL}/sms/conversations?state=AUTOMATED").json()
    )
    assert len(api.get(f"{PORTAL}/sms/conversations/1/messages").json()) == 2


def test_unknown_sms_conversation_reply_reports_failure(api):
    response = api.post(
        f"{PORTAL}/sms/reply", json={"conversation_id": 99999, "message": "Hello"}
    )
    assert response.status_code == 200
    assert response.json()["success"] is False
    assert response.json()["error"] == "Conversation not found"


def test_post_call_webhook_visible_in_calls_and_replay_safe(api):
    payload = {
        "type": "post_call_transcription",
        "data": {
            "conversation_id": "conv-e2e-1",
            "metadata": {"from_number": "+15550100001"},
            "transcript": [],
            "analysis": {"summary": "Customer requested an oil change."},
        },
    }
    first = api.post("/api/v1/telephony/webhook", json=payload)
    assert first.status_code == 200, first.text
    assert first.json()["success"] is True
    duplicate = api.post("/api/v1/telephony/webhook", json=payload)
    assert duplicate.json()["duplicate"] is True
    calls = api.get(f"{PORTAL}/calls").json()
    assert len(calls) == 1
    assert calls[0]["summary"] == payload["data"]["analysis"]["summary"]
    payload["data"]["analysis"]["summary"] = "Conflicting replay"
    assert api.post("/api/v1/telephony/webhook", json=payload).status_code == 409
    assert len(api.get(f"{PORTAL}/calls").json()) == 1


@pytest.mark.parametrize(
    "path,body,status",
    [
        (
            "/api/v1/telephony/webhook",
            {"type": "post_call_transcription", "data": {}},
            400,
        ),
        (
            "/api/v1/telephony/sms/inbound",
            {"From": "+15550100001", "Body": "Hello"},
            400,
        ),
        ("/api/v1/telephony/sms/status", {"MessageSid": "SM-e2e"}, 400),
    ],
)
def test_webhooks_require_identifiers(api, path, body, status):
    response = (
        api.post(path, json=body)
        if path.endswith("/webhook")
        else api.post(path, data=body)
    )
    assert response.status_code == status


def test_voice_service_fields_come_from_catalog(api):
    response = api.post(
        "/api/v1/voice/tools",
        json={
            "tool_call_id": "e2e-fields",
            "name": "get_service_fields",
            "arguments": {"service_name": "Oil Change"},
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["tool_call_id"] == "e2e-fields"
    assert data["result"]["success"] is True
    assert data["result"]["duration_minutes"] == 60


def test_health_and_portal_redirect(api):
    assert api.get("/health").json() == {"status": "healthy"}
    response = api.get("/portal", follow_redirects=False)
    assert response.status_code in {307, 308}
    assert response.headers["location"] == "/portal/"
