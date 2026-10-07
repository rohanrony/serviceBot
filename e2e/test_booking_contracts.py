"""Booking/history requirements: clocks, capacity, consolidation and isolation."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from xml.etree import ElementTree

import pytest

from e2e.test_voice_and_reporting import voice
from e2e.test_workflows import PORTAL, book, booking_payload, request_by_id


def intake(scenario, **changes):
    return {
        "customer_name": "Alex E2E",
        "phone": "+15550100001",
        "make": "Toyota",
        "model": "Camry",
        "year": 2020,
        "service_type": "Oil Change",
        "issue_description": "Oil change and multipoint inspection",
        "booking_type": "appointment",
        "booking_time": scenario["start"].isoformat(),
        "call_sid": "booking-contract-call",
        **changes,
    }


@pytest.mark.parametrize("seconds,accepted", [(-1, True), (0, True), (1, False)])
@pytest.mark.parametrize("entry", ["portal", "voice"])
def test_four_hour_lead_time_boundary_is_atomic(
    api, db, scenario, freeze_business_clock, seconds, accepted, entry
):
    freeze_business_clock(
        scenario["start"] - timedelta(hours=4) + timedelta(seconds=seconds)
    )
    before = db("SELECT COUNT(*) AS count FROM service_requests")[0]["count"]
    if entry == "portal":
        response = api.post(
            f"{PORTAL}/service-requests", json=booking_payload(scenario)
        )
        assert response.status_code == (201 if accepted else 422), response.text
        if not accepted:
            assert response.json()["detail"]["error_code"] == "LEAD_TIME_VIOLATION"
    else:
        result = voice(api, "create_service_request", intake(scenario))
        assert result["success"] is accepted, result
        if not accepted:
            assert result["error"] == "INSUFFICIENT_LEAD_TIME"
            assert result["min_buffer_hours"] == 4
            assert result["earliest_allowed_time"]
    assert db("SELECT COUNT(*) AS count FROM service_requests")[0][
        "count"
    ] == before + int(accepted)
    if not accepted:
        assert not db("SELECT id FROM appointment_reservations")
        assert not db("SELECT id FROM outbox_notifications")


@pytest.mark.parametrize("buffer,accepted", [(2, True), (8, False)])
def test_configured_lead_time_applies_to_new_reservations(
    api, scenario, freeze_business_clock, buffer, accepted
):
    assert (
        api.post(
            f"{PORTAL}/config", json={"min_booking_buffer_hours": buffer}
        ).status_code
        == 200
    )
    freeze_business_clock(scenario["start"] - timedelta(hours=3))
    response = api.post(f"{PORTAL}/service-requests", json=booking_payload(scenario))
    assert response.status_code == (201 if accepted else 422), response.text
    if not accepted:
        assert response.json()["detail"]["min_buffer_hours"] == buffer


@pytest.mark.parametrize(
    "duration,normalized",
    [(1, 15), (14, 15), (15, 15), (16, 30), (59, 60), (60, 60), (61, 75)],
)
def test_duration_consumes_every_normalized_segment(
    api, db, scenario, duration, normalized
):
    payload = booking_payload(scenario)
    payload["service_request"]["duration_minutes"] = duration
    response = api.post(f"{PORTAL}/service-requests", json=payload)
    assert response.status_code == 201, response.text
    request_id = response.json()["request_id"]
    assert request_by_id(api, request_id)["duration_minutes"] == normalized
    segments = db(
        "SELECT s.segment_start FROM appointment_reservation_segments s JOIN appointment_reservations r ON r.id=s.reservation_id WHERE r.service_request_id=%s ORDER BY s.segment_start",
        (request_id,),
    )
    assert [row["segment_start"] for row in segments] == [
        scenario["start"] + timedelta(minutes=offset)
        for offset in range(0, normalized, 15)
    ]


@pytest.mark.parametrize(
    "boundary,accepted",
    [
        ("opening", True),
        ("closing_exact", True),
        ("closing_overrun", False),
        ("before_opening", False),
        ("weekend", False),
    ],
)
def test_configured_business_window_boundary(api, db, scenario, boundary, accepted):
    day = scenario["start"]
    starts = {
        "opening": day.replace(hour=7),
        "closing_exact": day.replace(hour=17),
        "closing_overrun": day.replace(hour=17, minute=15),
        "before_opening": day.replace(hour=6, minute=45),
        "weekend": day + timedelta(days=(5 - day.weekday()) % 7),
    }
    response = api.post(
        f"{PORTAL}/service-requests",
        json=booking_payload(scenario, start=starts[boundary]),
    )
    assert response.status_code == (201 if accepted else 400), response.text
    if not accepted:
        assert not db("SELECT id FROM appointment_reservations")


@pytest.mark.parametrize(
    "busy_kind", ["local_block", "provider_overlap", "provider_all_day"]
)
def test_availability_excludes_local_and_provider_busy_capacity(
    api, db, scenario, monkeypatch, busy_kind
):
    from serviceBot.services import booking, google_calendar

    if busy_kind == "local_block":
        db(
            "UPDATE mock_calendar_slots SET reservation_status='BLOCKED' WHERE staff_agent_id=1 AND slot_datetime=%s",
            (scenario["start"],),
        )
    else:
        event = (
            {
                "start": {"date": scenario["date"]},
                "end": {
                    "date": (scenario["start"] + timedelta(days=1)).date().isoformat()
                },
            }
            if busy_kind == "provider_all_day"
            else {
                "start": {
                    "dateTime": (scenario["start"] + timedelta(minutes=15))
                    .replace(tzinfo=booking.BUSINESS_TZ)
                    .isoformat()
                },
                "end": {
                    "dateTime": (scenario["start"] + timedelta(minutes=30))
                    .replace(tzinfo=booking.BUSINESS_TZ)
                    .isoformat()
                },
            }
        )
        monkeypatch.setattr(
            google_calendar, "fetch_agent_events", lambda *args, **kwargs: [event]
        )
    response = api.get(
        f"{PORTAL}/available-slots",
        params={"date": scenario["date"], "staff_agent_id": 1},
    )
    assert response.status_code == 200
    assert all(
        row["start_time"] != scenario["start"].strftime("%Y-%m-%d %H:%M:%S")
        for row in response.json()["available_slots"]
    )
    booking_response = api.post(
        f"{PORTAL}/service-requests", json=booking_payload(scenario)
    )
    assert booking_response.status_code == 409, booking_response.text


def consolidate(api, request_id, **extra):
    return voice(
        api,
        "consolidate_appointment_service",
        {
            "appointment_id": request_id,
            "phone": "+15550100001",
            "additional_issue": "Brake squeak and rotor check",
            "additional_service_type": "Brake Inspection",
            "additional_duration_minutes": 30,
            **extra,
        },
    )


def test_consolidation_extends_one_booking_and_reserves_added_capacity(
    api, db, scenario
):
    request_id = book(api, scenario)
    result = consolidate(api, request_id)
    assert result["success"] is True, result
    assert result["new_duration_minutes"] == 90
    assert "Brake squeak" in result["combined_issues"]
    row = request_by_id(api, request_id)
    assert row["duration_minutes"] == 90
    assert row["booking_end_time"] == (
        scenario["start"] + timedelta(minutes=90)
    ).strftime("%Y-%m-%d %H:%M:%S")
    assert (
        len(
            db(
                "SELECT s.* FROM appointment_reservation_segments s JOIN appointment_reservations r ON r.id=s.reservation_id WHERE r.service_request_id=%s",
                (request_id,),
            )
        )
        == 6
    )
    conflict = api.post(
        f"{PORTAL}/service-requests",
        json=booking_payload(
            scenario, phone="+15550100002", start=scenario["start"] + timedelta(hours=1)
        ),
    )
    assert conflict.status_code == 409


def test_blocked_consolidation_leaves_original_booking_and_notifications_unchanged(
    api, db, scenario
):
    request_id = book(api, scenario)
    book(
        api,
        scenario,
        phone="+15550100002",
        start=scenario["start"] + timedelta(hours=1),
    )
    before = request_by_id(api, request_id)
    events = db(
        "SELECT id FROM outbox_notifications WHERE request_id=%s", (request_id,)
    )
    result = consolidate(api, request_id)
    assert result["success"] is False and result["capacity_blocked"] is True, result
    after = request_by_id(api, request_id)
    for field in ("duration_minutes", "issue_description", "booking_end_time"):
        assert after[field] == before[field]
    assert (
        db("SELECT id FROM outbox_notifications WHERE request_id=%s", (request_id,))
        == events
    )


@pytest.mark.parametrize("invalid", [0, -15, "not-a-duration"])
def test_invalid_consolidation_cannot_mutate_booking(api, scenario, invalid):
    request_id = book(api, scenario)
    before = request_by_id(api, request_id)
    result = consolidate(api, request_id, additional_duration_minutes=invalid)
    assert result["success"] is False, result
    after = request_by_id(api, request_id)
    assert after["duration_minutes"] == before["duration_minutes"]
    assert after["issue_description"] == before["issue_description"]


def test_consolidation_cannot_merge_another_customers_request(api, db, scenario):
    request_id = book(api, scenario)
    other = book(api, scenario, phone="+15550100002", agent=2)
    before = request_by_id(api, other)
    result = consolidate(api, request_id, source_appointment_ids=[other])
    assert result["success"] is False, (
        "Cross-customer source IDs must be rejected atomically"
    )
    assert request_by_id(api, other)["status"] == before["status"]
    assert request_by_id(api, request_id)["duration_minutes"] == 60


def test_same_call_concurrent_intake_cannot_create_two_requests(api, db, scenario):
    args = intake(scenario)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda _: voice(api, "create_service_request", args.copy()), range(2)
            )
        )
    assert any(result["success"] for result in results)
    rows = db(
        "SELECT id FROM service_requests WHERE issue_description=%s",
        (args["issue_description"],),
    )
    assert len(rows) == 1
    assert len(db("SELECT id FROM appointment_reservations WHERE status='ACTIVE'")) == 1


def test_customer_lookup_and_inbound_context_include_issue_duration_and_vehicle(
    api, db, scenario
):
    request_id = book(api, scenario)
    issue = 'Oil change; customer says "engine <rattle> & shake"'
    db(
        "UPDATE service_requests SET issue_description=%s WHERE id=%s",
        (issue, request_id),
    )
    result = voice(api, "get_customer_appointments", {"phone": "+15550100001"})
    assert result["success"] is True
    appointment = next(row for row in result["appointments"] if row["id"] == request_id)
    assert appointment["issue_description"] == issue
    assert appointment["duration_minutes"] == 60
    assert appointment["make"] == "Toyota" and appointment["model"] == "Camry"
    response = api.post(
        "/api/v1/telephony/inbound",
        data={"From": "+15550100001", "CallSid": "CA-context"},
    )
    assert response.status_code == 200
    tree = ElementTree.fromstring(response.text)
    parameters = {
        node.attrib["name"]: node.attrib["value"] for node in tree.iter("Parameter")
    }
    assert parameters["customer_name"] == "Alex E2E"
    assert issue in parameters["upcoming_appointments_summary"]
    assert "60 min" in parameters["upcoming_appointments_summary"]
    assert "Toyota Camry" in parameters["upcoming_appointments_summary"]


def test_unknown_caller_cannot_receive_existing_customer_context(api):
    response = api.post(
        "/api/v1/telephony/inbound",
        data={"From": "+15550100901", "CallSid": "CA-unknown"},
    )
    assert response.status_code == 200
    parameters = {
        node.attrib["name"]: node.attrib["value"]
        for node in ElementTree.fromstring(response.text).iter("Parameter")
    }
    assert parameters["caller_phone"] == "5550100901"
    assert (
        not {"customer_name", "upcoming_appointments_summary", "recent_history_summary"}
        & parameters.keys()
    )


@pytest.mark.parametrize("name", ["handoff", "transfer_call"])
def test_closed_shop_handoff_offers_callback_without_creating_booking(
    api, db, scenario, freeze_business_clock, name
):
    freeze_business_clock(scenario["start"].replace(hour=22))
    result = voice(
        api, name, {"phone": "+15550100001", "issue_description": "Brake noise"}
    )
    assert result["success"] is False
    assert "callback" in result["message"].lower()
    assert not db("SELECT id FROM appointment_reservations")
