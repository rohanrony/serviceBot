"""Negative, retry, rollback, and browser contracts for scheduled recovery."""

from datetime import timedelta

import pytest
from playwright.sync_api import expect

from e2e.test_escalated_assignment import (
    assert_recovered,
    escalate,
    state,
)
from e2e.test_escalated_assignment import (
    assignment_clock as assignment_clock_fixture,
)
from e2e.test_notification_workflows import (
    configure_rules,
    process,
)
from e2e.test_notification_workflows import (
    provider_capture as provider_capture_fixture,
)
from e2e.test_workflows import PORTAL, book

assignment_clock = assignment_clock_fixture
provider_capture = provider_capture_fixture


@pytest.mark.parametrize("method", ["POST", "PUT"])
def test_assignment_method_aliases_share_the_recovery_contract(
    api, db, scenario, assignment_clock, method
):
    now = assignment_clock(scenario["start"] - timedelta(days=2))
    request_id = book(api, scenario)
    escalate(db, request_id, now)
    response = api.request(
        method,
        f"{PORTAL}/service-requests/{request_id}/assign-agent",
        json={"staff_agent_id": 2},
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["escalation_status"] == "reassigned"
    assert_recovered(api, db, request_id, now)


@pytest.mark.parametrize(
    "boundary,status,detail",
    [
        ("completed", 400, "marked as completed"),
        ("cancelled", 400, "marked as cancelled"),
        ("cancelled_by_customer", 400, "marked as cancelled_by_customer"),
        ("past", 400, "must be in the future"),
        ("unassign", 400, "must have an assigned staff agent"),
        ("missing_agent", 400, "does not exist"),
        ("missing_request", 400, "was not found"),
        ("invalid_type", 422, "staff_agent_id"),
    ],
)
def test_invalid_or_closed_assignments_do_not_mutate_any_state(
    api, db, scenario, assignment_clock, boundary, status, detail
):
    now = assignment_clock(scenario["start"] - timedelta(days=2))
    request_id = book(api, scenario)
    escalate(db, request_id, now)
    target_id = request_id
    payload = {"staff_agent_id": 2}
    if boundary in {"completed", "cancelled", "cancelled_by_customer"}:
        db("UPDATE service_requests SET status=%s WHERE id=%s", (boundary, request_id))
    elif boundary == "past":
        assignment_clock(scenario["start"] + timedelta(minutes=1))
    elif boundary == "unassign":
        payload["staff_agent_id"] = None
    elif boundary == "missing_agent":
        payload["staff_agent_id"] = 999999
    elif boundary == "missing_request":
        target_id = 999999
    elif boundary == "invalid_type":
        payload["staff_agent_id"] = "invalid-agent-id"
    before = state(db)
    response = api.patch(
        f"{PORTAL}/service-requests/{target_id}/assign-agent", json=payload
    )
    assert response.status_code == status, response.text
    assert detail in response.text
    assert state(db) == before


def test_database_rejects_unsupported_legacy_status_without_losing_escalation(
    api, db, scenario, assignment_clock
):
    from psycopg2.errors import CheckViolation

    now = assignment_clock(scenario["start"] - timedelta(days=2))
    request_id = book(api, scenario)
    escalate(db, request_id, now)
    before = state(db)
    with pytest.raises(CheckViolation, match="service_requests_status_check"):
        db("UPDATE service_requests SET status='done' WHERE id=%s", (request_id,))
    assert state(db) == before


@pytest.mark.parametrize(
    "provider_state", ["error", "busy", "adjacent", "cancelled_event"]
)
def test_provider_failures_and_interval_edges_match_candidate_and_assignment_decisions(
    api, db, scenario, assignment_clock, monkeypatch, provider_state
):
    from serviceBot.services import booking, google_calendar

    now = assignment_clock(scenario["start"] - timedelta(days=2))
    request_id = book(api, scenario)
    escalate(db, request_id, now)
    start = scenario["start"].replace(tzinfo=booking.BUSINESS_TZ)
    event_start = start + timedelta(minutes=60 if provider_state == "adjacent" else 15)
    event = {
        "start": {"dateTime": event_start.isoformat()},
        "end": {"dateTime": (event_start + timedelta(minutes=15)).isoformat()},
    }
    if provider_state == "cancelled_event":
        event["status"] = "cancelled"

    def events(agent_id, *_args, **_kwargs):
        if agent_id != 2:
            return []
        if provider_state == "error":
            raise OSError("synthetic calendar transport failure")
        return [event]

    monkeypatch.setattr(google_calendar, "fetch_agent_events", events)
    response = api.get(f"{PORTAL}/service-requests/{request_id}/available-agents")
    assert response.status_code == 200, response.text
    candidate = next(row for row in response.json()["agents"] if row["id"] == 2)
    available = provider_state in {"adjacent", "cancelled_event"}
    assert candidate["is_available"] is available
    before = state(db)
    response = api.patch(
        f"{PORTAL}/service-requests/{request_id}/assign-agent",
        json={"staff_agent_id": 2},
    )
    if available:
        assert response.status_code == 200, response.text
        assert_recovered(api, db, request_id, now)
    else:
        assert response.status_code == 409, response.text
        assert state(db) == before


def test_database_failure_after_capacity_transfer_rolls_back_entire_recovery(
    api, db, scenario, assignment_clock
):
    now = assignment_clock(scenario["start"] - timedelta(days=2))
    request_id = book(api, scenario)
    escalate(db, request_id, now)
    before = state(db)
    # A real PostgreSQL fault occurs after reservation/segment writes, without
    # replacing the domain service. These objects exist only in the disposable DB.
    db("""CREATE FUNCTION reject_test_assignment_outbox() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN
        IF NEW.payload->>'agent_id' = '2' THEN
            RAISE EXCEPTION 'synthetic outbox insert failure';
        END IF;
        RETURN NEW;
        END $$""")
    try:
        db("""CREATE TRIGGER reject_test_assignment_outbox BEFORE INSERT ON outbox_notifications
            FOR EACH ROW EXECUTE FUNCTION reject_test_assignment_outbox()""")
        try:
            response = api.patch(
                f"{PORTAL}/service-requests/{request_id}/assign-agent",
                json={"staff_agent_id": 2},
            )
            assert response.status_code == 500, response.text
            assert "synthetic outbox insert failure" in response.text
            assert state(db) == before
        finally:
            db("DROP TRIGGER reject_test_assignment_outbox ON outbox_notifications")
    finally:
        db("DROP FUNCTION reject_test_assignment_outbox()")


def test_recovery_retry_preserves_deadline_reminders_and_notification_idempotency(
    api, db, scenario, assignment_clock, provider_capture
):
    now = assignment_clock(scenario["start"] - timedelta(days=2))
    provider_capture.activate()
    configure_rules(api, roles=("agent", "previous_agent"))
    request_id = book(api, scenario)
    process(api)
    provider_capture.calls.clear()
    old_reminders = db(
        "SELECT id FROM sms_reminders WHERE appointment_id=%s AND recipient_type='agent' AND status='PENDING' ORDER BY id",
        (request_id,),
    )
    assert old_reminders
    customer_reminders = db(
        "SELECT * FROM sms_reminders WHERE appointment_id=%s AND recipient_type='customer' ORDER BY id",
        (request_id,),
    )
    escalate(db, request_id, now)
    response = api.patch(
        f"{PORTAL}/service-requests/{request_id}/assign-agent",
        json={"staff_agent_id": 2},
    )
    assert response.status_code == 200, response.text
    assert not provider_capture.calls, (
        "External dispatch follows the durable local commit"
    )
    assert db(
        "SELECT DISTINCT status FROM sms_reminders WHERE id=ANY(%s)",
        ([row["id"] for row in old_reminders],),
    ) == [{"status": "CANCELLED"}]
    process(api)
    assert sorted(call["To"] for call in provider_capture.calls) == [
        "+15550100003",
        "+15550100004",
    ]
    assert (
        db(
            "SELECT * FROM sms_reminders WHERE appointment_id=%s AND recipient_type='customer' ORDER BY id",
            (request_id,),
        )
        == customer_reminders
    )
    assert_recovered(api, db, request_id, now)
    assignment_clock(now + timedelta(minutes=5))
    before = state(db)
    sent = list(provider_capture.calls)
    response = api.patch(
        f"{PORTAL}/service-requests/{request_id}/assign-agent",
        json={"staff_agent_id": 2},
    )
    assert response.status_code == 200, response.text
    assert state(db) == before
    assert process(api) == 0
    assert provider_capture.calls == sent
    assert_recovered(api, db, request_id, now)


def test_browser_disconnected_candidate_is_disabled_without_attempting_assignment(
    page, live_server, api, db, scenario, assignment_clock, monkeypatch
):
    from serviceBot.services import google_calendar

    now = assignment_clock(scenario["start"] - timedelta(days=2))
    request_id = book(api, scenario)
    escalate(db, request_id, now)
    monkeypatch.setattr(
        google_calendar, "fetch_agent_events", lambda *_args, **_kwargs: None
    )
    before = state(db)
    assignments = []
    page.on(
        "request",
        lambda request: (
            assignments.append(request.url)
            if request.url.endswith("/assign-agent")
            else None
        ),
    )
    page.goto(f"{live_server}/portal/")
    select = page.locator(f'.agent-select-badge[data-id="{request_id}"]')
    with page.expect_response(
        lambda r: r.url.endswith(f"/{request_id}/available-agents")
    ):
        select.focus()
    replacement = select.locator('option[value="2"]')
    expect(replacement).to_be_disabled()
    expect(replacement).to_contain_text("Calendar state unavailable")
    row = page.locator("tr").filter(has=select)
    expect(row.locator(".sla-warning-badge")).to_contain_text("Escalated")
    expect(row.locator(".agent-name-line")).to_have_text("Taylor E2E")
    assert assignments == []
    assert state(db) == before


def test_browser_recovery_leaves_escalations_filter_and_clears_banner(
    page, live_server, api, db, scenario, assignment_clock
):
    now = assignment_clock(scenario["start"] - timedelta(days=2))
    request_id = book(api, scenario)
    escalate(db, request_id, now)
    page.goto(f"{live_server}/portal/")
    page.locator("#filter-sr-status").select_option("escalated")
    select = page.locator(f'.agent-select-badge[data-id="{request_id}"]')
    expect(page.locator("#escalation-alert-banner")).to_be_visible()
    with page.expect_response(
        lambda r: r.url.endswith(f"/{request_id}/available-agents")
    ):
        select.focus()
    expect(select.locator('option[value="2"]')).to_be_enabled()
    with page.expect_response(
        lambda r: (
            r.url.endswith(f"/{request_id}/assign-agent")
            and r.request.method == "PATCH"
        )
    ) as saved:
        select.select_option("2")
    assert saved.value.status == 200, saved.value.text()
    expect(select).to_have_count(0)
    expect(page.locator("#escalation-alert-banner")).not_to_be_visible()
    assert_recovered(api, db, request_id, now)
    page.locator("#filter-sr-status").select_option("all")
    row = page.locator("tr").filter(has=select)
    expect(row.locator(".sla-warning-badge")).to_contain_text("Reassigned")
    page.reload()
    expect(row.locator(".sla-warning-badge")).to_contain_text("Reassigned")
