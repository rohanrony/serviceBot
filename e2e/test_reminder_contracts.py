"""Frozen-clock confirmation, reminder, escalation and late-response contracts."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from twilio.request_validator import RequestValidator

from e2e.test_notification_workflows import (
    ADMIN,
    AGENT,
    AUTH_TOKEN,
    HEADERS,
    NEW_AGENT,
    PUBLIC_URL,
    configure_rules,
    process,
)
from e2e.test_notification_workflows import (
    provider_capture as captured_provider_fixture,
)
from e2e.test_workflows import PORTAL, book, request_by_id

provider_capture = captured_provider_fixture


@pytest.mark.parametrize(
    "start,expected",
    [
        ("2030-03-09T22:00:00", "2030-03-10T12:00:00+00:00"),
        ("2030-11-02T22:00:00", "2030-11-03T13:00:00+00:00"),
    ],
)
def test_quiet_hour_release_uses_local_opening_across_dst(start, expected):
    from serviceBot.services.quiet_hours import calculate_quiet_hours_release_time

    local = datetime.fromisoformat(start).replace(tzinfo=ZoneInfo("America/New_York"))
    release = calculate_quiet_hours_release_time(
        now_dt=local, config={"quiet_end_time": "08:00"}
    )
    assert release.replace(tzinfo=UTC) == datetime.fromisoformat(expected)


@pytest.mark.parametrize(
    "start,expected",
    [
        ("2030-03-08T17:00:00", "2030-03-11T08:00:00"),
        ("2030-11-01T17:00:00", "2030-11-04T08:00:00"),
    ],
)
def test_business_deadline_preserves_wall_clock_across_dst_weekend(start, expected):
    from serviceBot.services.sms_reminders import compute_business_hours_deadline

    result = compute_business_hours_deadline(
        datetime.fromisoformat(start),
        2,
        business_days=[0, 1, 2, 3, 4],
        business_hours=list(range(7, 18)),
    )
    assert result == datetime.fromisoformat(expected)


def inbound(api, phone, body, sid):
    form = {"From": phone, "Body": body, "MessageSid": sid}
    signature = RequestValidator(AUTH_TOKEN).compute_signature(
        f"{PUBLIC_URL}/sms/inbound", form
    )
    response = api.post(
        "/sms/inbound", data=form, headers={"X-Twilio-Signature": signature}
    )
    assert response.status_code == 200, response.text
    return response


def ready_booking(api, scenario, capture, freeze_business_clock, horizon=48):
    capture.activate()
    configure_rules(api, roles=("customer", "agent"))
    booked_at = scenario["start"] - timedelta(hours=horizon)
    freeze_business_clock(booked_at)
    request_id = book(api, scenario)
    assert process(api) >= 1
    assert (
        api.put(f"{PORTAL}/sms/config", json={"admin_phone_number": ADMIN}).status_code
        == 200
    )
    capture.calls.clear()
    return request_id, booked_at


@pytest.mark.parametrize(
    "start,hours,expected",
    [
        ("2030-01-07T07:00:00", 4, "2030-01-07T11:00:00"),
        ("2030-01-07T06:30:00", 1, "2030-01-07T08:00:00"),
        ("2030-01-11T17:00:00", 2, "2030-01-14T08:00:00"),
        ("2030-01-12T10:00:00", 1.5, "2030-01-14T08:30:00"),
        ("2030-01-07T17:30:00", 1, "2030-01-08T07:30:00"),
    ],
)
def test_business_hour_deadlines_pause_outside_operating_window(start, hours, expected):
    from serviceBot.services.sms_reminders import compute_business_hours_deadline

    actual = compute_business_hours_deadline(
        datetime.fromisoformat(start),
        hours,
        business_days=[0, 1, 2, 3, 4],
        business_hours=list(range(7, 18)),
    )
    assert actual == datetime.fromisoformat(expected)


@pytest.mark.parametrize(
    "horizon,sla", [(4, 1.5), (5.99, 1.5), (6, 3), (23.99, 3), (24, 4), (48, 4)]
)
def test_confirmation_cutoff_uses_horizon_tier_and_safety_ceiling(horizon, sla):
    from serviceBot.services.sms_reminders import (
        calculate_effective_confirmation_cutoff,
    )

    booked = datetime.fromisoformat("2030-01-07T08:00:00")
    appointment = booked + timedelta(hours=horizon)
    config = {
        "business_hours_start": 7,
        "business_hours_end": 18,
        "business_days": [0, 1, 2, 3, 4],
        "sla_advance_booking_hours": 4,
        "sla_medium_booking_hours": 3,
        "sla_short_booking_hours": 1.5,
        "final_reminder_hours": 2,
    }
    expected = min(booked + timedelta(hours=sla), appointment - timedelta(hours=2))
    assert (
        calculate_effective_confirmation_cutoff(booked, appointment, config) == expected
    )


def test_early_morning_cutoff_is_after_opening_but_before_appointment():
    from serviceBot.services.sms_reminders import (
        calculate_effective_confirmation_cutoff,
    )

    config = {
        "business_hours_start": 7,
        "business_hours_end": 18,
        "business_days": [0, 1, 2, 3, 4],
        "overnight_grace_minutes": 30,
        "final_reminder_hours": 2,
    }
    cutoff = calculate_effective_confirmation_cutoff(
        datetime.fromisoformat("2030-01-11T17:30:00"),
        datetime.fromisoformat("2030-01-14T08:00:00"),
        config,
    )
    assert cutoff == datetime.fromisoformat("2030-01-14T07:30:00")


@pytest.mark.parametrize(
    "horizon,followup_hours,final_hours", [(48, 2, 4), (8, 1.5, 3), (4, 0.75, 2)]
)
def test_booking_generates_all_three_staff_attempts_for_horizon(
    api,
    db,
    scenario,
    provider_capture,
    freeze_business_clock,
    horizon,
    followup_hours,
    final_hours,
):
    # Anchor booking during operating hours so the cadence's expected values
    # are independent of nights/weekends; appointment dates remain future.
    start = (
        scenario["start"] + timedelta(days=(-scenario["start"].weekday()) % 7)
    ).replace(hour=8)
    appointment = start + timedelta(hours=horizon)
    local = {**scenario, "start": appointment, "date": appointment.date().isoformat()}
    request_id, booked = ready_booking(
        api, local, provider_capture, freeze_business_clock, horizon
    )
    rows = db(
        "SELECT * FROM sms_reminders WHERE appointment_id=%s AND recipient_type='agent' ORDER BY attempt_number",
        (request_id,),
    )
    assert [row["attempt_number"] for row in rows] == [1, 2, 3]
    assert rows[0]["status"] == "SENT"
    assert rows[1]["scheduled_at"] == booked + timedelta(hours=followup_hours)
    assert rows[2]["scheduled_at"] == booked + timedelta(hours=final_hours)
    assert request_by_id(api, request_id)["confirmation_cutoff_at"]


@pytest.mark.parametrize("seconds,expected", [(-1, 0), (0, 1), (1, 1)])
def test_timeout_escalates_only_when_cutoff_is_reached_once(
    api, db, scenario, provider_capture, freeze_business_clock, seconds, expected
):
    from serviceBot.services.sms_reminders import (
        check_and_escalate_unconfirmed_appointments,
    )

    request_id, _booked = ready_booking(
        api, scenario, provider_capture, freeze_business_clock
    )
    cutoff = db(
        "SELECT confirmation_cutoff_at FROM service_requests WHERE id=%s", (request_id,)
    )[0]["confirmation_cutoff_at"]
    assert (
        check_and_escalate_unconfirmed_appointments(
            as_of_time=cutoff + timedelta(seconds=seconds)
        )
        == expected
    )
    row = request_by_id(api, request_id)
    assert row["escalation_status"] == ("escalated" if expected else "none")
    if expected:
        assert row["escalation_reason"] == "TIMEOUT_NO_RESPONSE"
        assert len(provider_capture.calls) == 1
        assert provider_capture.calls[0]["To"] == ADMIN
        assert "TIMEOUT_NO_RESPONSE" in provider_capture.calls[0]["Body"]
        assert db(
            "SELECT id FROM service_request_audit_log WHERE request_id=%s AND triggered_by='escalation_monitor'",
            (request_id,),
        )
        assert (
            check_and_escalate_unconfirmed_appointments(
                as_of_time=cutoff + timedelta(minutes=1)
            )
            == 0
        )


@pytest.mark.parametrize("keyword", ["DECLINE", "UNAVAILABLE", "NO"])
def test_staff_decline_records_reason_and_alerts_supervisor(
    api, db, scenario, provider_capture, freeze_business_clock, keyword
):
    request_id, _ = ready_booking(
        api, scenario, provider_capture, freeze_business_clock
    )
    inbound(api, AGENT, keyword, f"SM-decline-{keyword}")
    row = request_by_id(api, request_id)
    assert row["confirmation_status"] == "declined"
    assert row["escalation_status"] == "escalated"
    assert row["escalation_reason"] == "AGENT_DECLINED"
    assert any(
        call["To"] == ADMIN and "AGENT_DECLINED" in call["Body"]
        for call in provider_capture.calls
    )


def test_late_confirmation_before_reassignment_resolves_escalation(
    api, db, scenario, provider_capture, freeze_business_clock
):
    from serviceBot.services.sms_reminders import (
        check_and_escalate_unconfirmed_appointments,
    )

    request_id, _ = ready_booking(
        api, scenario, provider_capture, freeze_business_clock
    )
    cutoff = db(
        "SELECT confirmation_cutoff_at FROM service_requests WHERE id=%s", (request_id,)
    )[0]["confirmation_cutoff_at"]
    assert check_and_escalate_unconfirmed_appointments(as_of_time=cutoff) == 1
    inbound(api, AGENT, "CONFIRM", "SM-late-before")
    row = request_by_id(api, request_id)
    assert row["staff_agent_id"] == 1
    assert row["confirmation_status"] == "confirmed"
    assert row["escalation_status"] == "resolved"
    assert not db(
        "SELECT id FROM sms_reminders WHERE appointment_id=%s AND recipient_type='agent' AND status='PENDING'",
        (request_id,),
    )
    assert db(
        "SELECT notes FROM service_request_audit_log WHERE request_id=%s AND notes ILIKE '%%Late confirmation%%'",
        (request_id,),
    )


def test_old_staff_confirmation_after_reassignment_cannot_confirm_new_staff(
    api, db, scenario, provider_capture, freeze_business_clock
):
    request_id, _ = ready_booking(
        api, scenario, provider_capture, freeze_business_clock
    )
    assert (
        api.post(
            f"{PORTAL}/service-requests/{request_id}/reassign", json={"new_agent_id": 2}
        ).status_code
        == 200
    )
    provider_capture.calls.clear()
    inbound(api, AGENT, "CONFIRM", "SM-late-after")
    row = request_by_id(api, request_id)
    assert row["staff_agent_id"] == 2
    assert row["confirmation_status"] == "pending_agent_confirmation"
    assert any(
        "already reassigned" in call["Body"].lower() for call in provider_capture.calls
    )
    inbound(api, NEW_AGENT, "CONFIRM", "SM-new-confirm")
    assert request_by_id(api, request_id)["confirmation_status"] == "confirmed"


def test_reassignment_has_fifteen_minute_confirmation_window(
    api, db, scenario, provider_capture, freeze_business_clock
):
    request_id, booked = ready_booking(
        api, scenario, provider_capture, freeze_business_clock
    )
    assert (
        api.post(
            f"{PORTAL}/service-requests/{request_id}/reassign", json={"new_agent_id": 2}
        ).status_code
        == 200
    )
    cutoff = db(
        "SELECT confirmation_cutoff_at FROM service_requests WHERE id=%s", (request_id,)
    )[0]["confirmation_cutoff_at"]
    assert cutoff == booked + timedelta(minutes=15)


@pytest.mark.parametrize("terminal", ["confirmed", "cancelled", "completed"])
def test_terminal_requests_cannot_timeout_or_alert_supervisor(
    api, db, scenario, provider_capture, freeze_business_clock, terminal
):
    from serviceBot.services.sms_reminders import (
        check_and_escalate_unconfirmed_appointments,
    )

    request_id, _ = ready_booking(
        api, scenario, provider_capture, freeze_business_clock
    )
    if terminal == "confirmed":
        inbound(api, AGENT, "CONFIRM", "SM-terminal-confirm")
    else:
        if terminal == "completed":
            assert (
                api.patch(
                    f"{PORTAL}/service-requests/{request_id}/status",
                    json={"status": "confirmed"},
                ).status_code
                == 200
            )
            assert (
                api.patch(
                    f"{PORTAL}/service-requests/{request_id}/status",
                    json={"status": "in_progress"},
                ).status_code
                == 200
            )
        assert (
            api.patch(
                f"{PORTAL}/service-requests/{request_id}/status",
                json={"status": terminal},
            ).status_code
            == 200
        )
    provider_capture.calls.clear()
    assert (
        check_and_escalate_unconfirmed_appointments(
            as_of_time=scenario["start"] + timedelta(days=1)
        )
        == 0
    )
    assert not provider_capture.calls


def test_disabled_reminder_rule_prevents_real_generated_attempt(
    api, db, scenario, provider_capture, freeze_business_clock
):
    request_id, _ = ready_booking(
        api, scenario, provider_capture, freeze_business_clock
    )
    for role in ("customer", "agent"):
        for event in (
            "REMINDER_FOLLOWUP",
            "REMINDER_FINAL",
            "REMINDER_24H",
            "REMINDER_2H",
        ):
            for channel in ("SMS", "WHATSAPP"):
                assert (
                    api.put(
                        f"{PORTAL}/sms/matrix-rules",
                        json={
                            "event_type": event,
                            "recipient_role": role,
                            "channel": channel,
                            "enabled": False,
                        },
                    ).status_code
                    == 200
                )
    db(
        "UPDATE sms_reminders SET scheduled_at=NOW()-INTERVAL '2 days' WHERE appointment_id=%s AND status='PENDING'",
        (request_id,),
    )
    response = api.post("/api/cron/reminders", headers=HEADERS)
    assert response.status_code == 200
    assert not provider_capture.calls
    assert all(
        row["status"] == "CANCELLED"
        for row in db(
            "SELECT status FROM sms_reminders WHERE appointment_id=%s AND attempt_number>1",
            (request_id,),
        )
    )


def test_generated_staff_reminder_retry_honors_backoff_and_recovers(
    api, db, scenario, provider_capture, freeze_business_clock
):
    from serviceBot.services.sms_reminders import run_reminder_polling_worker_cycle

    request_id, _ = ready_booking(
        api, scenario, provider_capture, freeze_business_clock
    )
    row = db(
        "SELECT * FROM sms_reminders WHERE appointment_id=%s AND recipient_type='agent' AND attempt_number=2",
        (request_id,),
    )[0]
    # Only advance time; generated reminder data and dispatch logic stay real.
    freeze_business_clock(row["scheduled_at"])
    provider_capture.outcomes.append(500)
    assert run_reminder_polling_worker_cycle() == 1
    failed = db("SELECT * FROM sms_reminders WHERE id=%s", (row["id"],))[0]
    assert failed["status"] == "PENDING" and failed["retry_count"] == 1
    assert failed["scheduled_at"] == row["scheduled_at"] + timedelta(minutes=1)
    assert run_reminder_polling_worker_cycle() == 0
    assert len(provider_capture.calls) == 1
    freeze_business_clock(failed["scheduled_at"])
    assert run_reminder_polling_worker_cycle() == 1
    recovered = db("SELECT * FROM sms_reminders WHERE id=%s", (row["id"],))[0]
    assert recovered["status"] == "SENT" and recovered["retry_count"] == 1
    assert len(provider_capture.calls) == 2
    assert provider_capture.calls[0]["Body"] == provider_capture.calls[1]["Body"]
    assert run_reminder_polling_worker_cycle() == 0


def test_generated_staff_delivery_exhaustion_alerts_supervisor_and_stops_retrying(
    api, db, scenario, provider_capture, freeze_business_clock
):
    from serviceBot.services.sms_reminders import run_reminder_polling_worker_cycle

    request_id, _ = ready_booking(
        api, scenario, provider_capture, freeze_business_clock
    )
    reminder = db(
        "SELECT * FROM sms_reminders WHERE appointment_id=%s AND recipient_type='agent' AND attempt_number=2",
        (request_id,),
    )[0]
    provider_capture.outcomes.extend([500, 500, 500, 500])
    previous_time = reminder["scheduled_at"]
    for retry_count, backoff in enumerate((1, 5, 15), start=1):
        freeze_business_clock(previous_time)
        assert run_reminder_polling_worker_cycle() == 1
        retry = db("SELECT * FROM sms_reminders WHERE id=%s", (reminder["id"],))[0]
        assert retry["status"] == "PENDING" and retry["retry_count"] == retry_count
        assert retry["scheduled_at"] == previous_time + timedelta(minutes=backoff)
        assert run_reminder_polling_worker_cycle() == 0
        previous_time = retry["scheduled_at"]
    freeze_business_clock(previous_time)
    assert run_reminder_polling_worker_cycle() == 1
    terminal = db("SELECT * FROM sms_reminders WHERE id=%s", (reminder["id"],))[0]
    assert terminal["status"] == "FAILED" and terminal["retry_count"] == 3
    staff_calls = [
        call
        for call in provider_capture.calls
        if call["To"].removeprefix("whatsapp:") == AGENT
    ]
    assert len(staff_calls) == 4 and len({call["Body"] for call in staff_calls}) == 1
    assert run_reminder_polling_worker_cycle() == 0
    row = request_by_id(api, request_id)
    assert (
        row["escalation_status"] == "escalated"
        and row["escalation_reason"] == "DELIVERY_FAILED"
    )
    assert any(
        call["To"] == ADMIN and "DELIVERY_FAILED" in call["Body"]
        for call in provider_capture.calls
    )


def test_all_documented_reminder_settings_round_trip_without_losing_other_config(api):
    before = api.get(f"{PORTAL}/config").json()
    settings = {
        "min_booking_buffer_hours": 5,
        "initial_notification_enabled": False,
        "sla_advance_booking_hours": 5.0,
        "sla_medium_booking_hours": 2.5,
        "sla_short_booking_hours": 1.0,
        "final_reminder_hours": 1.5,
        "overnight_grace_minutes": 45,
        "max_dispatch_retries": 2,
        "business_hours_start": 8,
        "business_hours_end": 17,
        "business_days": [0, 1, 2, 3],
        "supervisor_alert_phone": ADMIN,
        "auto_reassign_on_escalation": True,
        "reassignment_confirmation_window_minutes": 20,
    }
    assert api.post(f"{PORTAL}/config", json=settings).status_code == 200
    saved = api.get(f"{PORTAL}/config").json()
    mismatches = {
        key: {"expected": value, "actual": saved.get(key)}
        for key, value in settings.items()
        if saved.get(key) != value
    }
    assert not mismatches, f"Every documented control must persist: {mismatches}"
    assert saved["business_name"] == before["business_name"]
