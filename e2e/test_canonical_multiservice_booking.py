"""Full catalogue labels survive voice tools without a separate services array."""

from datetime import datetime, timedelta

import pytest
from playwright.sync_api import expect

from e2e.scenarios import capacity_snapshot, service, visit_rows
from e2e.test_notification_workflows import configure_rules, process
from e2e.test_notification_workflows import (
    provider_capture as captured_provider_fixture,
)
from e2e.test_voice_and_reporting import voice

provider_capture = captured_provider_fixture

NAMES = ["Brake Repair & Pad Replacement", "Suspension Repair (Shocks & Struts)"]
LABEL = " and ".join(NAMES)


@pytest.fixture
def catalogue(api):
    for name, agent, duration in zip(NAMES, [1, 2], [90, 120], strict=True):
        service(api, name, [agent], duration)


def book(api, scenario, tool="book_appointment", *, issue_only=False, label=LABEL):
    args = {
        "phone": "+15550100001",
        "customer_name": "Alex E2E",
        "make": "Toyota",
        "model": "Corolla",
        "year": 2021,
        "issue_description": label,
        "booking_type": "appointment",
        "booking_time": scenario["start"].isoformat(),
        "appointment_datetime": scenario["start"].isoformat(),
        "call_sid": "canonical-multiservice",
    }
    if not issue_only:
        args["service_type"] = label
    return voice(api, tool, args)


def booking_state(db):
    """Include ancillary writes that a rejected reservation must also roll back."""
    return {
        **capacity_snapshot(db),
        "vehicles": db("SELECT * FROM vehicles ORDER BY id"),
        "calendar_slots": db("SELECT * FROM mock_calendar_slots ORDER BY id"),
    }


def assert_visit(db, scenario, result):
    assert result["success"] is True, result
    assert result["duration_minutes"] == 210
    assert result["expected_end_time"] == (
        scenario["start"] + timedelta(minutes=210)
    ).strftime("%Y-%m-%d %H:%M:%S")
    rows = visit_rows(db, result["visit_group_id"])
    assert [row["service_type"] for row in rows] == NAMES
    assert [row["staff_agent_id"] for row in rows] == [1, 2]
    assert [row["duration_minutes"] for row in rows] == [90, 120]
    assert [datetime.fromisoformat(row["booking_time"]) for row in rows] == [
        scenario["start"],
        scenario["start"] + timedelta(minutes=90),
    ]
    assert [row["linked_appointment_id"] for row in rows] == [
        rows[1]["id"],
        rows[0]["id"],
    ]
    reservations = db(
        "SELECT r.id,r.service_request_id,r.staff_agent_id,r.starts_at,r.ends_at,count(seg.segment_start) AS segments "
        "FROM appointment_reservations r JOIN service_requests sr ON sr.id=r.service_request_id "
        "JOIN appointment_reservation_segments seg ON seg.reservation_id=r.id "
        "WHERE sr.visit_group_id=%s AND r.status='ACTIVE' GROUP BY r.id ORDER BY r.starts_at",
        (result["visit_group_id"],),
    )
    assert [r["ends_at"] - r["starts_at"] for r in reservations] == [
        timedelta(minutes=90),
        timedelta(minutes=120),
    ]
    assert [r["segments"] for r in reservations] == [6, 8]
    assert reservations[0]["ends_at"] == reservations[1]["starts_at"]
    assert db(
        "SELECT service_components FROM service_requests WHERE visit_group_id=%s ORDER BY booking_time,id",
        (result["visit_group_id"],),
    ) == [
        {"service_components": [{"name": name, "duration_minutes": duration}]}
        for name, duration in zip(NAMES, [90, 120], strict=True)
    ]
    receipts = result["appointments"]
    assert [receipt["service_request_id"] for receipt in receipts] == [
        row["id"] for row in rows
    ]
    for row, receipt, reservation in zip(rows, receipts, reservations, strict=True):
        assert receipt["staff_agent_id"] == row["staff_agent_id"]
        assert receipt["duration_minutes"] == row["duration_minutes"]
        assert reservation["id"] == receipt["reservation_id"]
        assert reservation["service_request_id"] == row["id"]
        assert reservation["staff_agent_id"] == row["staff_agent_id"]
        assert reservation["starts_at"] == datetime.fromisoformat(row["booking_time"])
        assert db(
            "SELECT reservation_id,staff_agent_id,segment_start "
            "FROM appointment_reservation_segments WHERE reservation_id=%s ORDER BY segment_start",
            (reservation["id"],),
        ) == [
            {
                "reservation_id": reservation["id"],
                "staff_agent_id": row["staff_agent_id"],
                "segment_start": reservation["starts_at"] + timedelta(minutes=offset),
            }
            for offset in range(0, row["duration_minutes"], 15)
        ]
        jobs = db(
            "SELECT event_type,status,payload FROM outbox_notifications "
            "WHERE request_id=%s ORDER BY event_type",
            (row["id"],),
        )
        assert [(job["event_type"], job["status"]) for job in jobs] == [
            ("booking_notification", "PENDING"),
            ("calendar_projection", "PENDING"),
        ]
        for job in jobs:
            payload = job["payload"]
            assert payload["reservation_id"] == receipt["reservation_id"]
            assert payload["agent_id"] == row["staff_agent_id"]
            assert payload["booking_time_str"] == row["booking_time"]
            assert payload["duration_minutes"] == row["duration_minutes"]
            assert payload["details"]["service_type"] == row["service_type"]
            assert payload["details"]["duration_minutes"] == row["duration_minutes"]
    return rows


@pytest.mark.parametrize(
    "tool,issue_only",
    [
        ("book_appointment", False),
        ("create_service_request", False),
        ("create_service_request", True),
    ],
)
def test_full_labels_create_two_linked_specialist_appointments(
    api, db, scenario, catalogue, tool, issue_only
):
    assert_visit(db, scenario, book(api, scenario, tool, issue_only=issue_only))


def test_customer_notification_contains_each_specialists_saved_window(
    api, db, scenario, catalogue, provider_capture
):
    provider_capture.activate()
    configure_rules(api, roles=("customer", "agent"))
    rows = assert_visit(db, scenario, book(api, scenario))
    assert process(api) > 0
    messages = [
        call["Body"] for call in provider_capture.calls if call["To"] == "+15550100001"
    ]
    assert len(messages) == len(rows)
    for row, technician in zip(rows, ["Taylor E2E", "Morgan E2E"], strict=True):
        matching = [message for message in messages if row["service_type"] in message]
        assert len(matching) == 1
        assert technician in matching[0]
        start = datetime.fromisoformat(row["booking_time"])
        for instant in [start, start + timedelta(minutes=row["duration_minutes"])]:
            assert instant.strftime("%I:%M %p").lstrip("0") in matching[0]
    assert all(
        job["status"] == "DELIVERED"
        for job in db(
            "SELECT status FROM outbox_notifications WHERE request_id=ANY(%s)",
            ([row["id"] for row in rows],),
        )
    )
    sent = list(provider_capture.calls)
    assert process(api) == 0
    assert provider_capture.calls == sent


@pytest.mark.parametrize("tool", ["book_appointment", "create_service_request"])
def test_punctuation_inside_one_catalogue_name_does_not_split_it(
    api, db, scenario, catalogue, tool
):
    result = book(api, scenario, tool, label=NAMES[0])
    assert result["success"] is True, result
    assert result["duration_minutes"] == 90
    row = db(
        "SELECT service_type,staff_agent_id,duration_minutes FROM service_requests WHERE id=%s",
        (result.get("appointment_id") or result.get("service_request_id"),),
    )[0]
    assert row == {
        "service_type": NAMES[0],
        "staff_agent_id": 1,
        "duration_minutes": 90,
    }


def test_joined_label_availability_checks_second_specialist_capacity(
    api, db, scenario, catalogue
):
    blocked = scenario["start"] + timedelta(minutes=120)
    db(
        "INSERT INTO mock_calendar_slots (staff_agent_id,slot_datetime,is_booked,reservation_status) VALUES (2,%s,TRUE,'BLOCKED') ON CONFLICT (slot_datetime,staff_agent_id) DO UPDATE SET is_booked=TRUE,reservation_status='BLOCKED'",
        (blocked,),
    )
    result = voice(
        api,
        "check_availability",
        {
            "preferred_date": scenario["date"],
            "preferred_time": scenario["start"].strftime("%H:%M"),
            "service_type": LABEL,
            "booking_type": "appointment",
        },
    )
    assert result["success"] is True, result
    assert (
        scenario["start"].strftime("%Y-%m-%d %H:%M:%S") not in result["available_slots"]
    )


@pytest.mark.parametrize(
    "tool,issue_only",
    [
        ("book_appointment", False),
        ("create_service_request", False),
        ("create_service_request", True),
    ],
)
def test_second_specialist_conflict_cannot_fall_back_to_generic_booking(
    api, db, scenario, catalogue, tool, issue_only
):
    blocked = scenario["start"] + timedelta(minutes=120)
    db(
        "INSERT INTO mock_calendar_slots (staff_agent_id,slot_datetime,is_booked,reservation_status) VALUES (2,%s,TRUE,'BLOCKED') ON CONFLICT (slot_datetime,staff_agent_id) DO UPDATE SET is_booked=TRUE,reservation_status='BLOCKED'",
        (blocked,),
    )
    before = booking_state(db)
    result = book(api, scenario, tool, issue_only=issue_only)
    assert result["success"] is False, result
    assert booking_state(db) == before


@pytest.mark.parametrize(
    "tool,issue_only",
    [
        ("book_appointment", False),
        ("create_service_request", False),
        ("create_service_request", True),
    ],
)
def test_repeated_service_is_rejected_without_partial_booking(
    api, db, scenario, catalogue, tool, issue_only
):
    before = booking_state(db)
    result = book(
        api, scenario, tool, issue_only=issue_only, label=" and ".join([NAMES[0]] * 2)
    )
    assert result["success"] is False, result
    assert "only once" in result["message"]
    assert booking_state(db) == before


@pytest.mark.parametrize("first_tool", ["book_appointment", "create_service_request"])
def test_same_call_retry_through_other_tool_preserves_the_whole_visit(
    api, db, scenario, catalogue, first_tool
):
    first = book(
        api, scenario, first_tool, issue_only=first_tool == "create_service_request"
    )
    assert_visit(db, scenario, first)
    before = booking_state(db)
    other_tool = (
        "create_service_request"
        if first_tool == "book_appointment"
        else "book_appointment"
    )
    repeated = book(
        api, scenario, other_tool, issue_only=other_tool == "create_service_request"
    )
    assert repeated["success"] is True, repeated
    assert repeated["duration_minutes"] == 210
    assert booking_state(db) == before


@pytest.mark.parametrize(
    "tool,issue_only",
    [
        ("book_appointment", False),
        ("create_service_request", False),
        ("create_service_request", True),
    ],
)
@pytest.mark.parametrize(
    "provider_failure", [None, RuntimeError("private-calendar-diagnostic")]
)
def test_unverified_second_calendar_rejects_entire_visit_and_forbids_confirmation(
    api, db, scenario, catalogue, monkeypatch, tool, issue_only, provider_failure
):
    from serviceBot.services import google_calendar
    from serviceBot.services.booking import get_session_booking

    def events(agent_id, *args):
        if agent_id == 2:
            if isinstance(provider_failure, Exception):
                raise provider_failure
            return provider_failure
        return []

    monkeypatch.setattr(google_calendar, "fetch_agent_events", events)
    before = booking_state(db)
    result = book(api, scenario, tool, issue_only=issue_only)
    assert result["success"] is False, result
    assert result["booking_confirmation_status"] == "unconfirmed"
    assert "could not confirm" in result["customer_message"].lower()
    assert "Do not claim an appointment was booked" in result["agent_guidance"]
    assert "does not prove" in result["agent_guidance"]
    assert "private-calendar-diagnostic" not in str(result)
    assert get_session_booking("canonical-multiservice") is None
    assert booking_state(db) == before


def test_unverified_second_calendar_cannot_produce_an_available_slot(
    api, db, scenario, catalogue, monkeypatch
):
    from serviceBot.services import google_calendar

    monkeypatch.setattr(
        google_calendar,
        "fetch_agent_events",
        lambda agent_id, *args: None if agent_id == 2 else [],
    )
    before = booking_state(db)
    result = voice(
        api,
        "check_availability",
        {
            "service_type": LABEL,
            "preferred_date": scenario["date"],
            "booking_type": "appointment",
        },
    )
    assert result["success"] is False, result
    assert result["availability_status"] == "unknown"
    assert result["available_slots"] == []
    assert result["booking_confirmation_status"] == "unconfirmed"
    assert "could not confirm" in result["customer_message"].lower()
    assert booking_state(db) == before


@pytest.mark.parametrize("browser_timezone", ["UTC", "America/Los_Angeles"])
def test_joined_label_booking_shows_both_technicians_and_windows_after_reload(
    page, live_server, api, db, scenario, catalogue, browser_timezone
):
    for name, duration in zip(NAMES, [90, 120], strict=True):
        details = voice(api, "get_service_fields", {"service_name": name})
        assert details["success"] is True, details
        assert details["service_name"] == name
        assert details["duration_minutes"] == duration
    availability = voice(
        api,
        "check_availability",
        {
            "service_type": LABEL,
            "preferred_date": scenario["date"],
            "preferred_time": scenario["start"].strftime("%H:%M"),
            "booking_type": "appointment",
        },
    )
    assert availability["success"] is True, availability
    assert (
        scenario["start"].strftime("%Y-%m-%d %H:%M:%S")
        in availability["available_slots"]
    )
    rows = assert_visit(db, scenario, book(api, scenario))
    from zoneinfo import ZoneInfo

    persisted = {row["id"]: row for row in api.get("/api/v1/portal/service-requests").json()}
    for row, offset, duration in zip(rows, [0, 90], [90, 120], strict=True):
        start = (scenario["start"] + timedelta(minutes=offset)).replace(
            tzinfo=ZoneInfo("America/New_York")
        )
        assert persisted[row["id"]]["booking_start_iso"] == start.isoformat()
        assert persisted[row["id"]]["booking_end_iso"] == (
            start + timedelta(minutes=duration)
        ).isoformat()
    page.goto(f"{live_server}/portal/")
    page.reload()
    for row, technician, offset, duration in zip(
        rows, ["Taylor E2E", "Morgan E2E"], [0, 90], [90, 120], strict=True
    ):
        rendered = page.locator(f'.edit-sr-btn[data-id="{row["id"]}"]').locator(
            "xpath=ancestor::tr"
        )
        expect(rendered).to_contain_text(row["service_type"])
        expect(rendered).to_contain_text(technician)
        for minutes in [offset, offset + duration]:
            clock = (
                (scenario["start"] + timedelta(minutes=minutes))
                .strftime("%I:%M %p")
                .lstrip("0")
            )
            expect(rendered).to_contain_text(clock)


def test_unknown_calendar_leaves_no_promised_visit_in_portal_after_reload(
    page, live_server, api, db, scenario, catalogue, monkeypatch, provider_capture
):
    from serviceBot.services import google_calendar

    provider_capture.activate()
    configure_rules(api, roles=("customer", "agent"))
    monkeypatch.setattr(
        google_calendar,
        "fetch_agent_events",
        lambda agent_id, *args: None if agent_id == 2 else [],
    )
    before = booking_state(db)
    original_ids = [
        row["id"] for row in api.get("/api/v1/portal/service-requests").json()
    ]
    result = book(api, scenario)
    assert result["success"] is False, result
    assert result["booking_confirmation_status"] == "unconfirmed"
    assert "could not confirm" in result["customer_message"].lower()
    assert booking_state(db) == before
    assert process(api) == 0
    assert provider_capture.calls == []
    assert [
        row["id"] for row in api.get("/api/v1/portal/service-requests").json()
    ] == original_ids
    page.goto(f"{live_server}/portal/")
    page.reload()
    listing = page.locator("#service-requests-list")
    expect(listing.locator(".edit-sr-btn")).to_have_count(len(original_ids))
    for name in NAMES:
        expect(listing).not_to_contain_text(name)
