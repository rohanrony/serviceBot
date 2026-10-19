"""Normal dropdown recovery through real HTTP, services, DB, and Chromium."""

from datetime import timedelta

import pytest
from playwright.sync_api import expect

from e2e.scenarios import capacity_snapshot
from e2e.test_notification_workflows import (
    provider_capture as captured_provider_fixture,
)
from e2e.test_workflows import PORTAL, book, request_by_id

provider_capture = captured_provider_fixture


@pytest.fixture
def assignment_clock(freeze_business_clock):
    """Use the shared clock that recognizes database datetime values."""
    return freeze_business_clock


def escalate(db, request_id, now, *, unassigned=False):
    db(
        """UPDATE service_requests SET escalation_status='escalated',
        escalation_reason='TIMEOUT_NO_RESPONSE', confirmation_cutoff_at=%s,
        status='confirmed', confirmation_status='confirmed', confirmed_at=%s
        WHERE id=%s""",
        (now - timedelta(minutes=5), now - timedelta(hours=1), request_id),
    )
    if unassigned:
        db(
            "DELETE FROM appointment_reservation_segments WHERE reservation_id IN "
            "(SELECT id FROM appointment_reservations WHERE service_request_id=%s)",
            (request_id,),
        )
        db(
            "DELETE FROM appointment_reservations WHERE service_request_id=%s",
            (request_id,),
        )
        db("DELETE FROM mock_calendar_slots WHERE service_request_id=%s", (request_id,))
        db("UPDATE service_requests SET staff_agent_id=NULL WHERE id=%s", (request_id,))


def state(db):
    return {
        **capacity_snapshot(db),
        "reminders": db("SELECT * FROM sms_reminders ORDER BY id"),
        "audit": db("SELECT * FROM service_request_audit_log ORDER BY id"),
        "slots": db("SELECT * FROM mock_calendar_slots ORDER BY id"),
    }


def assert_recovered(api, db, request_id, now):
    row = request_by_id(api, request_id)
    assert row["staff_agent_id"] == 2
    assert row["status"] == "pending"
    assert row["confirmation_status"] == "pending_agent_confirmation"
    assert row["escalation_status"] == "reassigned"
    assert row["escalation_reason"] is None
    stored = db(
        "SELECT confirmed_at, confirmation_cutoff_at FROM service_requests WHERE id=%s",
        (request_id,),
    )[0]
    assert stored["confirmed_at"] is None
    assert stored["confirmation_cutoff_at"] == now.replace(tzinfo=None) + timedelta(
        minutes=15
    )
    reservations = db(
        "SELECT id, staff_agent_id FROM appointment_reservations WHERE service_request_id=%s AND status='ACTIVE'",
        (request_id,),
    )
    assert len(reservations) == 1
    assert reservations[0]["staff_agent_id"] == 2
    segments = db(
        "SELECT staff_agent_id, segment_start FROM appointment_reservation_segments WHERE reservation_id=%s ORDER BY segment_start",
        (reservations[0]["id"],),
    )
    assert len(segments) == 4
    assert {segment["staff_agent_id"] for segment in segments} == {2}


@pytest.mark.parametrize("unassigned", [False, True])
def test_normal_assignment_persists_recovery_and_fresh_deadline(
    api, db, scenario, assignment_clock, unassigned
):
    now = assignment_clock(scenario["start"] - timedelta(days=2))
    request_id = book(api, scenario)
    escalate(db, request_id, now, unassigned=unassigned)
    response = api.patch(
        f"{PORTAL}/service-requests/{request_id}/assign-agent",
        json={"staff_agent_id": 2},
    )
    assert response.status_code == 200, response.text
    assert_recovered(api, db, request_id, now)
    data = response.json()["data"]
    assert data["escalation_status"] == "reassigned"
    assert data["escalation_reason"] is None
    assert data["confirmed_at"] is None
    queued = db(
        "SELECT event_type, payload FROM outbox_notifications WHERE request_id=%s ORDER BY id DESC LIMIT 2",
        (request_id,),
    )
    assert {item["event_type"] for item in queued} == {
        "calendar_projection",
        "booking_notification",
    }
    assert all(item["payload"]["agent_id"] == 2 for item in queued)


@pytest.mark.parametrize(
    "failure", ["unknown_calendar", "unqualified", "inactive", "capacity_race"]
)
def test_rejected_assignment_preserves_all_state(
    api, db, scenario, assignment_clock, monkeypatch, failure
):
    from serviceBot.services import google_calendar

    now = assignment_clock(scenario["start"] - timedelta(days=2))
    request_id = book(api, scenario)
    escalate(db, request_id, now)
    if failure == "unknown_calendar":
        monkeypatch.setattr(
            google_calendar, "fetch_agent_events", lambda *args, **kwargs: None
        )
    elif failure == "unqualified":
        db(
            "INSERT INTO service_staff_agents (service_id, staff_agent_id) VALUES (1, 1)"
        )
    elif failure == "inactive":
        db("UPDATE staff_agents SET is_active=FALSE WHERE id=2")
    candidates = api.get(
        f"{PORTAL}/service-requests/{request_id}/available-agents"
    ).json()["agents"]
    if failure == "inactive":
        assert not any(agent["id"] == 2 for agent in candidates)
    else:
        candidate = next(agent for agent in candidates if agent["id"] == 2)
        assert candidate["is_available"] is (failure == "capacity_race")
    if failure == "capacity_race":
        book(api, scenario, phone="+15550100002", agent=2)
    before = state(db)
    response = api.patch(
        f"{PORTAL}/service-requests/{request_id}/assign-agent",
        json={"staff_agent_id": 2},
    )
    assert response.status_code == 409, response.text
    assert state(db) == before


def test_same_agent_does_not_clear_escalation_or_restart_clock(
    api, db, scenario, assignment_clock
):
    now = assignment_clock(scenario["start"] - timedelta(days=2))
    request_id = book(api, scenario)
    escalate(db, request_id, now)
    before = state(db)
    response = api.patch(
        f"{PORTAL}/service-requests/{request_id}/assign-agent",
        json={"staff_agent_id": 1},
    )
    assert response.status_code == 200, response.text
    assert state(db) == before
    assert response.json()["data"]["escalation_status"] == "escalated"


def test_grouped_candidate_must_be_qualified_for_every_booked_service(
    api, db, scenario, assignment_clock
):
    import json

    now = assignment_clock(scenario["start"] - timedelta(days=2))
    request_id = book(api, scenario)
    escalate(db, request_id, now)
    db("INSERT INTO services (name, duration_minutes) VALUES ('Brake Inspection', 30)")
    db(
        "INSERT INTO service_staff_agents (service_id, staff_agent_id) VALUES (1, 1), (1, 2), (2, 1)"
    )
    components = [
        {"name": "Oil Change", "duration_minutes": 30},
        {"name": "Brake Inspection", "duration_minutes": 30},
    ]
    db(
        "UPDATE service_requests SET service_type='Oil Change, Brake Inspection', service_components=%s WHERE id=%s",
        (json.dumps(components), request_id),
    )
    candidates = api.get(
        f"{PORTAL}/service-requests/{request_id}/available-agents"
    ).json()["agents"]
    replacement = next(agent for agent in candidates if agent["id"] == 2)
    assert replacement["skills_match"] is False
    assert replacement["is_available"] is False
    before = state(db)
    response = api.patch(
        f"{PORTAL}/service-requests/{request_id}/assign-agent",
        json={"staff_agent_id": 2},
    )
    assert response.status_code == 409
    assert state(db) == before


def test_reassigning_one_visit_segment_preserves_its_confirmed_companion(
    api, db, scenario, assignment_clock
):
    from uuid import uuid4

    now = assignment_clock(scenario["start"] - timedelta(days=2))
    request_id = book(api, scenario)
    companion_id = book(api, scenario, start=scenario["start"] + timedelta(hours=1))
    db(
        "UPDATE service_requests SET visit_group_id=%s WHERE id=ANY(%s)",
        (str(uuid4()), [request_id, companion_id]),
    )
    escalate(db, request_id, now)
    db(
        "UPDATE service_requests SET status='confirmed', confirmation_status='confirmed', confirmed_at=%s WHERE id=%s",
        (now.replace(tzinfo=None), companion_id),
    )

    def companion_state():
        return {
            "request": db(
                "SELECT * FROM service_requests WHERE id=%s", (companion_id,)
            ),
            "reservation": db(
                "SELECT * FROM appointment_reservations WHERE service_request_id=%s",
                (companion_id,),
            ),
            "outbox": db(
                "SELECT * FROM outbox_notifications WHERE request_id=%s ORDER BY id",
                (companion_id,),
            ),
            "audit": db(
                "SELECT * FROM service_request_audit_log WHERE request_id=%s ORDER BY id",
                (companion_id,),
            ),
        }

    before = companion_state()
    response = api.patch(
        f"{PORTAL}/service-requests/{request_id}/assign-agent",
        json={"staff_agent_id": 2},
    )
    assert response.status_code == 200, response.text
    assert_recovered(api, db, request_id, now)
    assert companion_state() == before


def test_replacement_is_eligible_for_escalation_only_at_its_new_deadline(
    api, db, scenario, assignment_clock
):
    from serviceBot.db.queries import get_breached_unconfirmed_appointments

    now = assignment_clock(scenario["start"] - timedelta(days=2))
    request_id = book(api, scenario)
    escalate(db, request_id, now)
    response = api.patch(
        f"{PORTAL}/service-requests/{request_id}/assign-agent",
        json={"staff_agent_id": 2},
    )
    assert response.status_code == 200

    def breached(at):
        return {
            row["id"] for row in get_breached_unconfirmed_appointments(as_of_time=at)
        }

    assert request_id not in breached(
        now + timedelta(minutes=15) - timedelta(microseconds=1)
    )
    assert request_id in breached(now + timedelta(minutes=15))


@pytest.mark.parametrize("unassigned", [False, True])
def test_browser_normal_dropdown_removes_red_warning_and_survives_reload(
    page, live_server, api, db, scenario, assignment_clock, unassigned
):
    now = assignment_clock(scenario["start"] - timedelta(days=2))
    request_id = book(api, scenario)
    escalate(db, request_id, now, unassigned=unassigned)
    page.goto(f"{live_server}/portal/")
    select = page.locator(f'.agent-select-badge[data-id="{request_id}"]')
    row = page.locator("tr").filter(has=select)
    expect(row.locator(".sla-warning-badge")).to_contain_text("Escalated")
    with page.expect_response(
        lambda r: r.url.endswith(f"/{request_id}/available-agents")
    ):
        select.click()
    replacement = page.locator('#reassign-agent-select')
    expect(replacement.locator('option[value="2"]')).to_be_enabled()
    with page.expect_response(
        lambda r: (
            r.url.endswith(f"/{request_id}/reassign")
            and r.request.method == "POST"
        )
    ) as saved:
        replacement.select_option("2")
        page.locator("#reassign-submit-btn").click()
    assert saved.value.status == 200, saved.value.text()
    expect(row.locator(".sla-warning-badge")).to_contain_text("Reassigned")
    expect(row.locator(".agent-name-line")).to_have_text("Morgan E2E")
    expect(row.locator(".reassign-sr-btn")).to_have_count(0)
    expect(page.locator("#escalation-alert-banner")).not_to_be_visible()
    assert_recovered(api, db, request_id, now)
    page.reload()
    expect(row.locator(".sla-warning-badge")).to_contain_text("Reassigned")
    expect(row.locator(".agent-name-line")).to_have_text("Morgan E2E")


@pytest.mark.parametrize("unassigned", [False, True])
def test_normal_recovery_dispatches_to_replacement_and_former_agent(
    api, db, scenario, assignment_clock, provider_capture, unassigned
):
    from e2e.test_notification_workflows import configure_rules, notification, process

    now = assignment_clock(scenario["start"] - timedelta(days=2))
    provider_capture.activate()
    configure_rules(api, roles=("agent", "previous_agent"))
    request_id = book(api, scenario)
    process(api)
    provider_capture.calls.clear()
    escalate(db, request_id, now, unassigned=unassigned)
    response = api.patch(
        f"{PORTAL}/service-requests/{request_id}/assign-agent",
        json={"staff_agent_id": 2},
    )
    assert response.status_code == 200, response.text
    assert not provider_capture.calls
    process(api)
    assert notification(db, request_id)["status"] == "DELIVERED"
    expected_recipients = (
        ["+15550100004"] if unassigned else ["+15550100003", "+15550100004"]
    )
    assert sorted(call["To"] for call in provider_capture.calls) == expected_recipients
    assert all(str(request_id) in call["Body"] for call in provider_capture.calls)
    assert_recovered(api, db, request_id, now)


def test_browser_assignment_race_shows_error_and_preserves_escalation(
    page, live_server, api, db, scenario, assignment_clock
):
    now = assignment_clock(scenario["start"] - timedelta(days=2))
    request_id = book(api, scenario)
    escalate(db, request_id, now)
    page.goto(f"{live_server}/portal/")
    select = page.locator(f'.agent-select-badge[data-id="{request_id}"]')
    with page.expect_response(
        lambda r: r.url.endswith(f"/{request_id}/available-agents")
    ):
        select.click()
    replacement = page.locator('#reassign-agent-select')
    expect(replacement.locator('option[value="2"]')).to_be_enabled()
    book(api, scenario, phone="+15550100002", agent=2)
    before = state(db)
    with page.expect_response(
        lambda r: (
            r.url.endswith(f"/{request_id}/reassign")
            and r.request.method == "POST"
        )
    ) as saved:
        replacement.select_option("2")
        page.locator("#reassign-submit-btn").click()
    assert saved.value.status == 409
    expect(page.locator(".toast").last).to_contain_text("no longer available")
    row = page.locator("tr").filter(has=select)
    expect(row.locator(".sla-warning-badge")).to_contain_text("Escalated")
    expect(row.locator(".agent-name-line")).to_have_text("Taylor E2E")
    assert state(db) == before
