"""Rescheduling must preserve the saved service scope and report native capacity."""

from datetime import datetime, timedelta

import pytest
from playwright.sync_api import expect

from e2e.scenarios import capacity_snapshot
from e2e.test_canonical_multiservice_booking import (
    LABEL, NAMES, book, catalogue,
)
from e2e.test_voice_and_reporting import voice
from e2e.test_notification_workflows import configure_rules, process
from e2e.test_notification_workflows import provider_capture
from serviceBot.services.booking import BookingService, BookingValidationError


@pytest.fixture
def legacy_booking(api, db, scenario, catalogue):
    # Create real native capacity, then reproduce the pre-fix persisted shape.
    result = book(api, scenario, label="Oil Change")
    assert result["success"] is True, result
    identifier = result["appointment_id"]
    db("UPDATE service_requests SET service_type='Repair', issue_description=%s, "
       "service_components=NULL WHERE id=%s", (LABEL, identifier))
    return identifier


def state(db):
    return {**capacity_snapshot(db),
            "slots": db("SELECT * FROM mock_calendar_slots ORDER BY id"),
            "audit": db("SELECT * FROM service_request_audit_log ORDER BY id")}


def move(api, identifier, target):
    return voice(api, "reschedule_appointment", {
        "phone": "+15550100001", "appointment_id": identifier,
        "new_appointment_datetime": target.isoformat(),
        "customer_consent_obtained": True,
    })


def test_legacy_description_cannot_move_one_hour_as_two_services(api, db, scenario, legacy_booking):
    before = state(db)
    result = move(api, legacy_booking, scenario["start"] + timedelta(hours=2))
    assert result["success"] is False, result
    assert result["error_code"] == "BOOKING_SERVICE_SCOPE_MISMATCH"
    assert result["recorded_duration_minutes"] == 60
    assert result["catalog_duration_minutes"] == 210
    assert result["booking_confirmation_status"] == "unconfirmed"
    assert "review" in result["message"].lower()
    assert state(db) == before


def test_domain_rejects_legacy_description_without_partial_effects(db, scenario, legacy_booking):
    before = state(db)
    with pytest.raises(BookingValidationError, match="review"):
        BookingService().reschedule(request_id=legacy_booking,
            new_datetime=scenario["start"] + timedelta(hours=2),
            customer_consent_obtained=True, triggered_by="regression")
    assert state(db) == before


def test_portal_edit_cannot_bypass_legacy_scope_validation(api, db, scenario, legacy_booking):
    before = state(db)
    response = api.put(f"/api/v1/portal/service-requests/{legacy_booking}", json={
        "issue_description": LABEL, "booking_type": "appointment", "duration_minutes": 60,
        "booking_time": (scenario["start"] + timedelta(hours=1)).isoformat(),
        "customer_consent_obtained": True,
    })
    assert response.status_code == 400, response.text
    assert "review" in response.json()["detail"].lower()
    assert state(db) == before


def test_lookup_calls_out_recorded_duration_instead_of_catalog_estimate(api, legacy_booking):
    result = voice(api, "get_customer_appointments", {"phone": "+15550100001"})
    saved = next(row for row in result["appointments"] if row["id"] == legacy_booking)
    assert saved["duration_minutes"] == 60
    assert "Recorded duration: 60 minutes" in result["message"]
    assert "catalog" in result["agent_guidance"].lower()
    assert "check-in" in result["agent_guidance"].lower()


def test_reschedule_returns_both_persisted_specialist_windows(api, db, scenario, catalogue):
    booked = book(api, scenario)
    assert booked["success"] is True, booked
    target = scenario["start"] + timedelta(hours=1)
    last_job = db("SELECT max(id) AS id FROM outbox_notifications")[0]["id"]
    result = move(api, booked["appointment_id"], target)
    assert result["success"] is True, result
    assert result["duration_minutes"] == 210
    assert result["booking_time"] == target.strftime("%Y-%m-%d %H:%M:%S")
    assert result["expected_end_time"] == (target + timedelta(minutes=210)).strftime("%Y-%m-%d %H:%M:%S")
    assert result["visit_group_id"] == booked["visit_group_id"]
    rows = db("SELECT id,service_type,duration_minutes,staff_agent_id,booking_time "
              "FROM service_requests WHERE visit_group_id=%s ORDER BY booking_time,id", (booked["visit_group_id"],))
    assert [row["service_type"] for row in rows] == NAMES
    assert [row["duration_minutes"] for row in rows] == [90, 120]
    assert [row["staff_agent_id"] for row in rows] == [1, 2]
    assert [r["service_request_id"] for r in result["appointments"]] == [r["id"] for r in rows]
    for row, receipt in zip(rows, result["appointments"], strict=True):
        assert receipt["duration_minutes"] == row["duration_minutes"]
        assert receipt["booking_time"] == row["booking_time"]
        assert receipt["staff_agent_id"] == row["staff_agent_id"]
        reservation = db("SELECT id,starts_at,ends_at FROM appointment_reservations "
                         "WHERE service_request_id=%s AND status='ACTIVE'", (row["id"],))[0]
        assert receipt["reservation_id"] == reservation["id"]
        assert reservation["ends_at"] - reservation["starts_at"] == timedelta(minutes=row["duration_minutes"])
        jobs = db("SELECT payload FROM outbox_notifications WHERE request_id=%s AND id>%s ORDER BY id",
                  (row["id"], last_job))
        assert len(jobs) == 2
        assert all(job["payload"]["duration_minutes"] == row["duration_minutes"]
                   and job["payload"]["booking_time_str"] == row["booking_time"] for job in jobs)
    assert "210" in result["message"]
    assert result["notification_delivery_status"] == "unverified"


def test_second_specialist_conflict_rolls_back_entire_reschedule(api, db, scenario, catalogue):
    booked = book(api, scenario)
    target = scenario["start"] + timedelta(days=1)
    db("INSERT INTO mock_calendar_slots(staff_agent_id,slot_datetime,is_booked,reservation_status) "
       "VALUES(2,%s,TRUE,'BLOCKED') ON CONFLICT(slot_datetime,staff_agent_id) "
       "DO UPDATE SET is_booked=TRUE,reservation_status='BLOCKED'", (target + timedelta(minutes=90),))
    before = state(db)
    result = move(api, booked["appointment_id"], target)
    assert result["success"] is False, result
    assert result["booking_confirmation_status"] == "unconfirmed"
    assert state(db) == before


@pytest.mark.parametrize("legacy", [True, False])
def test_reschedule_worker_sends_only_actual_saved_component_windows(
    api, db, scenario, catalogue, provider_capture, legacy
):
    provider_capture.activate()
    configure_rules(api, roles=("customer", "agent"))
    booked = book(api, scenario, label="Oil Change" if legacy else LABEL)
    assert booked["success"] is True, booked
    assert process(api) > 0
    if legacy:
        db("UPDATE service_requests SET service_type='Repair',issue_description=%s,service_components=NULL WHERE id=%s",
           (LABEL, booked["appointment_id"]))
    provider_capture.calls.clear()
    result = move(api, booked["appointment_id"], scenario["start"] + timedelta(hours=1))
    assert result["success"] is (not legacy), result
    if legacy:
        assert process(api) == 0
        assert provider_capture.calls == []
    else:
        assert process(api) > 0
        messages = [call["Body"] for call in provider_capture.calls if call["To"] == "+15550100001"]
        assert len(messages) == 2
        for receipt in result["appointments"]:
            matching = [message for message in messages if receipt["service_type"] in message]
            assert len(matching) == 1
            for instant in (receipt["booking_time"], receipt["expected_end_time"]):
                assert datetime.fromisoformat(instant).strftime("%I:%M %p").lstrip("0") in matching[0]
        sent = list(provider_capture.calls)
        assert process(api) == 0
        assert provider_capture.calls == sent


@pytest.mark.parametrize("legacy", [True, False])
def test_portal_reload_shows_only_actual_saved_reschedule_windows(
    page, live_server, api, db, scenario, catalogue, legacy
):
    if legacy:
        booked = book(api, scenario, label="Oil Change")
        db("UPDATE service_requests SET service_type='Repair',issue_description=%s,service_components=NULL WHERE id=%s",
           (LABEL, booked["appointment_id"]))
    else:
        booked = book(api, scenario)
    target = scenario["start"] + timedelta(hours=1)
    before = state(db)
    result = move(api, booked["appointment_id"], target)
    assert result["success"] is (not legacy), result
    expected_ids = [row["id"] for row in before["service_requests"]]
    assert [row["id"] for row in db("SELECT id FROM service_requests ORDER BY id")] == expected_ids
    if legacy:
        assert state(db) == before
    ids = [booked["appointment_id"]] if legacy else [r["service_request_id"] for r in result["appointments"]]
    page.goto(f"{live_server}/portal/")
    page.reload()
    for identifier in ids:
        row = db("SELECT booking_time,duration_minutes FROM service_requests WHERE id=%s", (identifier,))[0]
        rendered = page.locator(f'.edit-sr-btn[data-id="{identifier}"]').locator("xpath=ancestor::tr")
        start = datetime.fromisoformat(row["booking_time"])
        for instant in (start, start + timedelta(minutes=row["duration_minutes"])):
            expect(rendered).to_contain_text(instant.strftime("%I:%M %p").lstrip("0"))
    expect(page.locator("#service-requests-list .edit-sr-btn")).to_have_count(len(expected_ids))
