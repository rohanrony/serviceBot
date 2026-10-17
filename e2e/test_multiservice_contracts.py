"""Catalog -> real voice HTTP -> linked reservations -> lifecycle and portal."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import pytest
from playwright.sync_api import expect

from e2e.scenarios import (
    capacity_snapshot,
    multi_booking,
    multi_services,
    service,
    visit_rows,
)
from e2e.test_notification_workflows import configure_rules, process
from e2e.test_notification_workflows import (
    provider_capture as captured_provider_fixture,
)
from e2e.test_voice_and_reporting import voice
from e2e.test_workflows import PORTAL

provider_capture = captured_provider_fixture


@pytest.mark.parametrize("mode,agents", [("single", [1, 1]), ("split", [1, 2])])
def test_voice_booking_persists_linked_contiguous_capacity(
    api, db, scenario, mode, agents
):
    services = multi_services(api, mode)
    result = multi_booking(api, scenario, services)
    assert result["success"] is True, result
    rows = visit_rows(db, result["visit_group_id"])
    assert [row["staff_agent_id"] for row in rows] == agents
    assert [row["service_type"] for row in rows] == services
    assert [row["duration_minutes"] for row in rows] == [30, 45]
    assert [datetime.fromisoformat(row["booking_time"]) for row in rows] == [
        scenario["start"],
        scenario["start"] + timedelta(minutes=30),
    ]
    assert rows[0]["linked_appointment_id"] == rows[1]["id"]
    assert rows[1]["linked_appointment_id"] == rows[0]["id"]
    for row in rows:
        segments = db(
            "SELECT s.segment_start FROM appointment_reservation_segments s JOIN appointment_reservations r ON r.id=s.reservation_id WHERE r.service_request_id=%s AND r.status='ACTIVE' ORDER BY s.segment_start",
            (row["id"],),
        )
        assert [segment["segment_start"] for segment in segments] == [
            datetime.fromisoformat(row["booking_time"]) + timedelta(minutes=offset)
            for offset in range(0, row["duration_minutes"], 15)
        ]


def test_three_services_group_with_first_qualified_technician(api, db, scenario):
    services = multi_services(api, "single")
    service(api, "Wheel Alignment", [2], 30)
    result = multi_booking(api, scenario, services + ["Wheel Alignment"])
    assert result["success"] is True, result
    rows = visit_rows(db, result["visit_group_id"])
    assert [row["staff_agent_id"] for row in rows] == [1, 1, 2]
    assert [datetime.fromisoformat(row["booking_time"]) for row in rows] == [
        scenario["start"] + timedelta(minutes=offset) for offset in (0, 30, 75)
    ]


def test_split_conflict_rolls_back_entire_visit(api, db, scenario):
    services = multi_services(api)
    db(
        "UPDATE mock_calendar_slots SET is_booked=TRUE, reservation_status='BLOCKED' WHERE staff_agent_id=2 AND slot_datetime=%s",
        (scenario["start"] + timedelta(minutes=45),),
    )
    before = capacity_snapshot(db)
    result = multi_booking(api, scenario, services)
    assert result["success"] is False, result
    assert capacity_snapshot(db) == before, (
        "A rejected second segment must leave no first segment or queued side effects"
    )


def test_concurrent_visits_have_one_winner_and_no_partial_loser(api, db, scenario):
    services = multi_services(api)

    def attempt(index):
        return multi_booking(
            api,
            scenario,
            services,
            phone=f"+1555010000{index}",
            call_sid=f"multi-race-{index}",
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(attempt, (1, 2)))
    assert sorted(bool(result.get("success")) for result in results) == [False, True]
    groups = db(
        "SELECT visit_group_id, COUNT(*) AS count FROM service_requests WHERE visit_group_id IS NOT NULL GROUP BY visit_group_id"
    )
    assert len(groups) == 1 and groups[0]["count"] == 2
    assert len(db("SELECT id FROM appointment_reservations WHERE status='ACTIVE'")) == 2


@pytest.mark.parametrize("hour,minute,accepted", [(15, 45, True), (16, 0, False)])
def test_configured_closing_bounds_entire_visit(
    api, db, scenario, hour, minute, accepted
):
    services = multi_services(api)
    assert (
        api.post(f"{PORTAL}/config", json={"business_hours_end": 17}).status_code == 200
    )
    before = capacity_snapshot(db)
    result = multi_booking(
        api,
        scenario,
        services,
        appointment_datetime=scenario["start"]
        .replace(hour=hour, minute=minute)
        .isoformat(),
    )
    assert result["success"] is accepted, result
    if not accepted:
        assert capacity_snapshot(db) == before


def test_customer_cancel_cancels_whole_visit_through_public_voice_tool(
    api, db, scenario
):
    result = multi_booking(api, scenario, multi_services(api))
    assert result["success"] is True, result
    cancelled = voice(
        api,
        "cancel_appointment",
        {
            "phone": "+15550100001",
            "appointment_id": result["appointment_id"],
            "customer_consent_obtained": True,
            "reason": "Cancel my whole visit",
        },
    )
    assert cancelled["success"] is True, cancelled
    rows = visit_rows(db, result["visit_group_id"])
    assert all(row["status"] in {"cancelled", "cancelled_by_customer"} for row in rows)
    assert not db(
        "SELECT r.id FROM appointment_reservations r JOIN service_requests sr ON sr.id=r.service_request_id WHERE sr.visit_group_id=%s AND r.status='ACTIVE'",
        (result["visit_group_id"],),
    )


def test_visit_revision_preserves_companion_start_and_releases_removed_capacity(
    api, db, scenario
):
    from serviceBot.services.booking import BookingService

    result = multi_booking(api, scenario, multi_services(api))
    assert result["success"] is True, result
    before = visit_rows(db, result["visit_group_id"])
    # Revision has a domain entry point but no public voice/portal route yet.
    # This is integration coverage, not a claim of a complete browser journey.
    revised = BookingService().revise_multi_service_visit(before[0]["id"])
    assert revised["success"] is True
    after = visit_rows(db, result["visit_group_id"])
    assert after[0]["status"] in {"cancelled", "cancelled_by_customer"}
    assert after[1]["booking_time"] == before[1]["booking_time"]
    assert after[1]["status"] == before[1]["status"]
    assert not db(
        "SELECT id FROM appointment_reservations WHERE service_request_id=%s AND status='ACTIVE'",
        (before[0]["id"],),
    )


def test_multi_visit_queues_customer_notification_with_both_services(
    api, db, scenario, provider_capture
):
    provider_capture.activate()
    configure_rules(api, roles=("customer",))
    services = multi_services(api)
    result = multi_booking(api, scenario, services)
    assert result["success"] is True, result
    process(api)
    calls = [
        call
        for call in provider_capture.calls
        if call["To"].removeprefix("whatsapp:") == "+15550100001"
    ]
    assert calls, (
        "A successful multi-service booking must enqueue its customer notification"
    )
    body = "\n".join(call["Body"] for call in calls)
    assert all(name in body for name in services)
    assert "Taylor E2E" in body and "Morgan E2E" in body


def test_linked_voice_booking_is_visible_in_browser_after_reload(
    page, live_server, api, db, scenario
):
    services = multi_services(api)
    result = multi_booking(api, scenario, services)
    assert result["success"] is True, result
    page.goto(f"{live_server}/portal/")
    for row in visit_rows(db, result["visit_group_id"]):
        expect(page.locator(f'.edit-sr-btn[data-id="{row["id"]}"]')).to_be_visible()
    page.reload()
    for name in services:
        expect(page.locator("#service-requests-list")).to_contain_text(name)


def test_reschedule_moves_every_linked_segment_together(api, db, scenario):
    result = multi_booking(api, scenario, multi_services(api))
    assert result["success"] is True, result
    before = visit_rows(db, result["visit_group_id"])
    target = scenario["start"] + timedelta(hours=2)
    moved = voice(
        api,
        "reschedule_appointment",
        {
            "phone": "+15550100001",
            "appointment_id": result["appointment_id"],
            "new_appointment_datetime": target.isoformat(),
            "appointment_datetime": target.isoformat(),
            "customer_consent_obtained": True,
        },
    )
    assert moved["success"] is True, moved
    after = visit_rows(db, result["visit_group_id"])
    assert [datetime.fromisoformat(row["booking_time"]) for row in after] == [
        datetime.fromisoformat(row["booking_time"]) + timedelta(hours=2)
        for row in before
    ]


def test_callback_visit_uses_distinct_nonoverlapping_windows(api, db, scenario):
    from serviceBot.services.booking import BookingService

    services = multi_services(api)
    # Callback grouping currently has a domain entry point; keep it exercised
    # independently of whether the public voice dispatcher routes to that entry.
    receipts = BookingService().reserve_multi_service_appointment(
        customer_id=1,
        services=services,
        appointment_datetime=scenario["start"].isoformat(),
        booking_type="callback",
    )
    assert len(receipts) == 2
    assert all(row["booking_type"] == "callback" for row in receipts)
    times = [datetime.fromisoformat(row["booking_time"]) for row in receipts]
    assert times[1] - times[0] >= timedelta(minutes=30)
    assert len({row["visit_group_id"] for row in receipts}) == 1
    assert len(visit_rows(db, receipts[0]["visit_group_id"])) == 2


def test_voice_callback_intake_creates_linked_nonoverlapping_requests(
    api, db, scenario
):
    services = multi_services(api)
    result = voice(
        api,
        "create_service_request",
        {
            "phone": "+15550100001",
            "customer_name": "Alex E2E",
            "make": "Toyota",
            "model": "Camry",
            "year": 2020,
            "service_type": ", ".join(services),
            "issue_description": ", ".join(services),
            "booking_type": "callback",
            "booking_time": scenario["start"].isoformat(),
        },
    )
    assert result["success"] is True, result
    rows = db(
        "SELECT booking_type, booking_time, visit_group_id FROM service_requests WHERE customer_id=1 AND booking_type='callback' ORDER BY booking_time",
    )
    assert len(rows) == 2, (
        "Two specialized callbacks must produce two distinct callback requests"
    )
    assert (
        rows[0]["visit_group_id"]
        and rows[0]["visit_group_id"] == rows[1]["visit_group_id"]
    )
    assert datetime.fromisoformat(rows[1]["booking_time"]) - datetime.fromisoformat(
        rows[0]["booking_time"]
    ) >= timedelta(minutes=30)


def test_multiservice_availability_requires_both_specialists(api, db, scenario):
    services = multi_services(api)
    db(
        "INSERT INTO mock_calendar_slots (staff_agent_id, slot_datetime, is_booked, reservation_status) SELECT 2, value, TRUE, 'BLOCKED' FROM generate_series(%s::timestamp, %s::timestamp, INTERVAL '15 minutes') AS value ON CONFLICT (slot_datetime, staff_agent_id) DO UPDATE SET is_booked=TRUE, reservation_status='BLOCKED'",
        (
            scenario["start"].replace(hour=7),
            scenario["start"].replace(hour=17, minute=45),
        ),
    )
    result = voice(
        api,
        "check_availability",
        {
            "service_type": ", ".join(services),
            "service_types": services,
            "preferred_date": scenario["date"],
            "preferred_time": "10:00 AM",
        },
    )
    assert all(
        not slot.startswith(scenario["date"]) for slot in result["available_slots"]
    ), "A free first specialist cannot make an unavailable whole visit bookable"
