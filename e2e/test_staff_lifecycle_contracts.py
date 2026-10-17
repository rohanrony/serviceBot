"""Signed staff replies and deactivation with real assignment/reservation state."""

from datetime import timedelta

import pytest

from e2e.scenarios import capacity_snapshot
from e2e.test_notification_workflows import AGENT, configure_rules, process
from e2e.test_notification_workflows import (
    provider_capture as captured_provider_fixture,
)
from e2e.test_reminder_contracts import inbound
from e2e.test_workflows import PORTAL, book, request_by_id

provider_capture = captured_provider_fixture


@pytest.mark.parametrize(
    "reply,expected",
    [("CONFIRM ALL", "confirmed"), ("CONFIRM 2", "indexed"), ("CONFIRM", "menu")],
)
def test_multiple_assignments_require_explicit_selection(
    api, db, scenario, provider_capture, reply, expected
):
    provider_capture.activate()
    configure_rules(api, roles=("agent",))
    ids = [
        book(api, scenario, start=scenario["start"] + timedelta(hours=index))
        for index in (0, 1)
    ]
    process(api)
    provider_capture.calls.clear()
    inbound(api, AGENT, reply, f"SM-multiple-{expected}")
    rows = [request_by_id(api, request_id) for request_id in ids]
    if expected == "menu":
        assert all(
            row["confirmation_status"] == "pending_agent_confirmation" for row in rows
        )
        body = "\n".join(call["Body"] for call in provider_capture.calls)
        assert all(str(request_id) in body for request_id in ids)
    elif expected == "indexed":
        assert rows[0]["confirmation_status"] == "pending_agent_confirmation"
        assert rows[1]["confirmation_status"] == "confirmed"
    else:
        assert all(row["confirmation_status"] == "confirmed" for row in rows)
        assert not db(
            "SELECT id FROM sms_reminders WHERE appointment_id=ANY(%s) AND recipient_type='agent' AND status='PENDING'",
            (ids,),
        )


def test_decline_reassigns_to_available_qualified_staff(
    api, db, scenario, provider_capture
):
    provider_capture.activate()
    configure_rules(api, roles=("agent", "admin"))
    assert (
        api.put(
            f"{PORTAL}/services/1",
            json={"name": "Oil Change", "duration_minutes": 60, "agent_ids": [1, 2]},
        ).status_code
        == 200
    )
    request_id = book(api, scenario)
    process(api)
    inbound(api, AGENT, "DECLINE", "SM-qualified-decline")
    row = request_by_id(api, request_id)
    assert row["staff_agent_id"] == 2
    assert row["confirmation_status"] == "pending_agent_confirmation"
    assert row["escalation_status"] == "reassigned"
    reservations = db(
        "SELECT staff_agent_id FROM appointment_reservations WHERE service_request_id=%s AND status='ACTIVE'",
        (request_id,),
    )
    assert reservations and all(item["staff_agent_id"] == 2 for item in reservations)
    segments = db(
        "SELECT s.staff_agent_id FROM appointment_reservation_segments s JOIN appointment_reservations r ON r.id=s.reservation_id WHERE r.service_request_id=%s AND r.status='ACTIVE'",
        (request_id,),
    )
    assert len(segments) == 4 and all(
        segment["staff_agent_id"] == 2 for segment in segments
    )


def test_decline_never_reassigns_service_to_unqualified_staff(
    api, scenario, provider_capture
):
    provider_capture.activate()
    configure_rules(api, roles=("agent", "admin"))
    assert (
        api.put(
            f"{PORTAL}/services/1",
            json={"name": "Oil Change", "duration_minutes": 60, "agent_ids": [1]},
        ).status_code
        == 200
    )
    request_id = book(api, scenario)
    process(api)
    inbound(api, AGENT, "DECLINE", "SM-no-qualified-replacement")
    row = request_by_id(api, request_id)
    assert row["staff_agent_id"] == 1, (
        "An available but unqualified technician is not a fallback"
    )
    assert row["escalation_status"] == "escalated"
    assert row["escalation_reason"] == "AGENT_DECLINED"


def test_inactive_reassignment_is_rejected_without_changing_capacity(api, db, scenario):
    request_id = book(api, scenario)
    assert api.delete(f"{PORTAL}/agents/2").status_code == 200
    before = capacity_snapshot(db)
    response = api.post(
        f"{PORTAL}/service-requests/{request_id}/reassign", json={"new_agent_id": 2}
    )
    assert response.status_code in {400, 404, 409, 422}, response.text
    assert capacity_snapshot(db) == before


def test_deactivation_clears_tags_and_connections_but_keeps_historical_rows(
    api, db, scenario
):
    assert (
        api.put(
            f"{PORTAL}/services/1", json={"name": "Oil Change", "agent_ids": [1]}
        ).status_code
        == 200
    )
    request_id = book(api, scenario)
    db(
        "INSERT INTO user_google_accounts (agent_id, email, access_token) VALUES (1, 'synthetic@example.test', 'synthetic-encrypted-value')"
    )
    response = api.delete(f"{PORTAL}/agents/1")
    assert response.status_code == 200, response.text
    assert request_id in response.json()["escalated_service_request_ids"]
    assert db("SELECT is_active FROM staff_agents WHERE id=1")[0]["is_active"] is False
    assert not db("SELECT agent_id FROM user_google_accounts WHERE agent_id=1")
    assert not db("SELECT service_id FROM service_staff_agents WHERE staff_agent_id=1")
    row = request_by_id(api, request_id)
    assert (
        row["staff_agent_id"] == 1 and row["escalation_reason"] == "AGENT_DEACTIVATED"
    )
    assert db(
        "SELECT id FROM appointment_reservations WHERE service_request_id=%s AND status='ACTIVE'",
        (request_id,),
    )
