"""User action -> durable queue -> real worker/SDK -> captured HTTP -> callback.

Only provider transport and external calendar projection are replaced. No real
messages are sent, and no outbox event is manually inserted by these tests.
"""

import json
from collections import Counter, deque
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import pytest
import requests
from twilio.request_validator import RequestValidator

from e2e.test_workflows import PORTAL, book, edit_payload, request_by_id

CUSTOMER = "+15550100001"
AGENT = "+15550100003"
NEW_AGENT = "+15550100004"
ADMIN = "+15550100005"
AUTH_TOKEN = "e2e-captured-provider-token"
PUBLIC_URL = "https://voice.example.test"
HEADERS = {"Authorization": "Bearer e2e-only-cron-secret"}
EVENTS = (
    "BOOKING",
    "RESCHEDULED",
    "REASSIGNED",
    "CANCELLED_BY_CUSTOMER",
    "CANCELLED_BY_ADMIN",
    "STATUS_IN_PROGRESS",
    "STATUS_COMPLETED",
)


class CapturedTwilio:
    def __init__(self, monkeypatch):
        self.monkeypatch = monkeypatch
        self.calls = []
        self.outcomes = deque()
        self.fail_agent_once = False
        self.sequence = 0

    def activate(self):
        # Pytest resets PYTEST_CURRENT_TEST at each phase, so disable the
        # application's mock branch inside the test call, not fixture setup.
        self.monkeypatch.delenv("TESTING", raising=False)
        self.monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    def send(self, request, **kwargs):
        url = urlparse(request.url)
        assert url.hostname == "api.twilio.com", "Unexpected external HTTP request"
        assert request.method == "POST"
        assert url.path.endswith("/Messages.json")
        body = (
            request.body.decode() if isinstance(request.body, bytes) else request.body
        )
        fields = {key: values[0] for key, values in parse_qs(body).items()}
        self.sequence += 1
        sid = f"SM{self.sequence:032x}"
        status = self.outcomes.popleft() if self.outcomes else 201
        if self.fail_agent_once and fields["To"].removeprefix("whatsapp:") == AGENT:
            self.fail_agent_once = False
            status = 500
        self.calls.append({**fields, "sid": sid, "http_status": status})
        payload = (
            {"sid": sid, "status": "queued", "error_code": None}
            if status == 201
            else {
                "code": 20500,
                "message": "Temporary provider failure",
                "status": status,
            }
        )
        response = requests.Response()
        response.status_code = status
        response.url = request.url
        response.request = request
        response.headers["Content-Type"] = "application/json"
        response._content = json.dumps(payload).encode()
        return response


@pytest.fixture
def provider_capture(scenario, db, monkeypatch):
    from serviceBot.services import outbox_worker

    capture = CapturedTwilio(monkeypatch)
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "AC" + "0" * 32)
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", AUTH_TOKEN)
    monkeypatch.setenv("TWILIO_FROM_NUMBER", "+15550100999")
    monkeypatch.setenv("TWILIO_WHATSAPP_FROM_NUMBER", "+15550100888")
    monkeypatch.setenv("TWILIO_WEBHOOK_BASE_URL", PUBLIC_URL)
    monkeypatch.setattr(
        requests.Session,
        "send",
        lambda self, request, **kwargs: capture.send(request, **kwargs),
    )
    # Calendar projection is a separate external integration, not the subject
    # of these notification journeys. Keep its durable worker updates real.
    monkeypatch.setattr(
        outbox_worker, "create_agent_calendar_event", lambda **kwargs: True
    )
    monkeypatch.setattr(
        outbox_worker, "delete_agent_calendar_event", lambda *args, **kwargs: True
    )
    monkeypatch.setattr(
        outbox_worker, "create_admin_calendar_event", lambda **kwargs: True
    )
    monkeypatch.setattr(
        outbox_worker, "delete_admin_calendar_event", lambda *args, **kwargs: True
    )
    for phone in (AGENT, NEW_AGENT, ADMIN):
        db(
            "INSERT INTO sms_whitelist (phone_number, twilio_verified) VALUES (%s, TRUE)",
            (phone,),
        )
    return capture


def configure_rules(api, channel="SMS", roles=("customer", "agent", "admin")):
    for event in EVENTS:
        for role in ("customer", "agent", "previous_agent", "admin"):
            for candidate in ("SMS", "WHATSAPP"):
                response = api.put(
                    f"{PORTAL}/sms/matrix-rules",
                    json={
                        "event_type": event,
                        "recipient_role": role,
                        "channel": candidate,
                        "enabled": candidate == channel and role in roles,
                    },
                )
                assert response.status_code == 200


def process(api):
    from serviceBot.services.outbox_worker import process_outbox_batch

    # Single-event batches isolate each dispatch contract. The separate cron
    # batch test below requires the normal multi-event production batch too.
    total = 0
    for _ in range(20):
        count = process_outbox_batch(batch_size=1)
        total += count
        if not count:
            return total
    pytest.fail("Notification processing did not settle within 20 batches")


def notification(db, request_id):
    rows = db(
        "SELECT * FROM outbox_notifications WHERE request_id = %s AND event_type IN ('booking_notification', 'sms_status_change', 'agent_reassignment') ORDER BY id",
        (request_id,),
    )
    assert rows, "The user action must enqueue its own notification"
    return rows[-1]


def logs(api, request_id):
    response = api.get(f"{PORTAL}/sms/logs/appointment/{request_id}")
    assert response.status_code == 200
    return response.json()["logs"]


def signed_callback(api, sid, status="delivered", **extra):
    form = {"MessageSid": sid, "MessageStatus": status, **extra}
    signature = RequestValidator(AUTH_TOKEN).compute_signature(
        f"{PUBLIC_URL}/sms/status", form
    )
    return api.post("/sms/status", data=form, headers={"X-Twilio-Signature": signature})


def test_cron_processes_all_events_generated_by_real_booking(
    api, db, scenario, provider_capture
):
    provider_capture.activate()
    configure_rules(api)
    request_id = book(api, scenario)
    response = api.post("/api/cron/outbox", headers=HEADERS)
    assert response.status_code == 200, response.text
    assert response.json()["processed_events"] == 2
    assert notification(db, request_id)["status"] == "DELIVERED"
    assert len(provider_capture.calls) == 3


@pytest.mark.parametrize("channel", ["SMS", "WHATSAPP"])
@pytest.mark.parametrize("event", EVENTS)
def test_lifecycle_action_dispatches_correct_recipients_and_delivery(
    api, db, scenario, provider_capture, channel, event
):
    provider_capture.activate()
    roles = (
        ("customer", "agent", "admin", "previous_agent")
        if event == "REASSIGNED"
        else ("customer", "agent", "admin")
    )
    configure_rules(api, channel, roles)
    request_id = book(api, scenario)
    assert notification(db, request_id)["status"] == "PENDING"
    assert not provider_capture.calls, "Booking must commit before external dispatch"
    if event != "BOOKING":
        assert process(api) >= 1
        provider_capture.calls.clear()
        if event == "RESCHEDULED":
            response = api.put(
                f"{PORTAL}/service-requests/{request_id}",
                json=edit_payload(
                    scenario,
                    booking_time=(scenario["start"] + timedelta(hours=1)).isoformat(),
                ),
            )
        elif event == "REASSIGNED":
            response = api.post(
                f"{PORTAL}/service-requests/{request_id}/reassign",
                json={"new_agent_id": 2},
            )
        else:
            statuses = {
                "CANCELLED_BY_CUSTOMER": "cancelled_by_customer",
                "CANCELLED_BY_ADMIN": "cancelled",
                "STATUS_IN_PROGRESS": "in_progress",
                "STATUS_COMPLETED": "completed",
            }
            if event in ("STATUS_IN_PROGRESS", "STATUS_COMPLETED"):
                assert (
                    api.patch(
                        f"{PORTAL}/service-requests/{request_id}/status",
                        json={"status": "confirmed"},
                    ).status_code
                    == 200
                )
            if event == "STATUS_COMPLETED":
                assert (
                    api.patch(
                        f"{PORTAL}/service-requests/{request_id}/status",
                        json={"status": "in_progress"},
                    ).status_code
                    == 200
                )
                assert process(api) >= 1
                provider_capture.calls.clear()
            response = api.patch(
                f"{PORTAL}/service-requests/{request_id}/status",
                json={"status": statuses[event]},
            )
        assert response.status_code == 200, response.text
        expected_states = (
            {"PENDING", "DELIVERED"} if event == "REASSIGNED" else {"PENDING"}
        )
        assert notification(db, request_id)["status"] in expected_states
    processed = process(api)
    assert processed >= 1 or event == "REASSIGNED"
    assert notification(db, request_id)["status"] == "DELIVERED"
    expected = (
        [CUSTOMER, NEW_AGENT, AGENT, ADMIN]
        if event == "REASSIGNED"
        else [CUSTOMER, AGENT, ADMIN]
    )
    prefix = "whatsapp:" if channel == "WHATSAPP" else ""
    assert Counter(call["To"] for call in provider_capture.calls) == Counter(
        prefix + phone for phone in expected
    )
    assert all(
        call["From"] == prefix + ("+15550100888" if prefix else "+15550100999")
        for call in provider_capture.calls
    )
    expected_title = {
        "BOOKING": "APPOINTMENT CONFIRMED",
        "RESCHEDULED": "APPOINTMENT RESCHEDULED",
        "REASSIGNED": "APPOINTMENT CONFIRMED",
        "CANCELLED_BY_CUSTOMER": "APPOINTMENT CANCELLED",
        "CANCELLED_BY_ADMIN": "APPOINTMENT CANCELLED",
        "STATUS_IN_PROGRESS": "SERVICE IN PROGRESS",
        "STATUS_COMPLETED": "VEHICLE READY FOR PICKUP",
    }[event]
    customer = next(
        call for call in provider_capture.calls if call["To"] == prefix + CUSTOMER
    )
    assert expected_title in customer["Body"]
    assert all(
        "Oil Change" in call["Body"]
        or (
            event == "REASSIGNED"
            and call["To"] == prefix + AGENT
            and f"#{request_id}" in call["Body"]
        )
        for call in provider_capture.calls
    )
    if event in ("BOOKING", "RESCHEDULED", "REASSIGNED"):
        agent_phone = NEW_AGENT if event == "REASSIGNED" else AGENT
        agent = next(
            call
            for call in provider_capture.calls
            if call["To"] == prefix + agent_phone
        )
        assert "CONFIRM" in agent["Body"]
    for call in provider_capture.calls:
        entry = next(
            row
            for row in logs(api, request_id)
            if row["twilio_message_sid"] == call["sid"]
        )
        assert entry["channel"] == channel
        assert entry["body"] == call["Body"]
        assert entry["status"] == "SENT"
        assert signed_callback(api, call["sid"]).status_code == 200
        assert signed_callback(api, call["sid"]).json()["duplicate"] is True
        assert (
            next(row for row in logs(api, request_id) if row["id"] == entry["id"])[
                "status"
            ]
            == "DELIVERED"
        )
    count = len(provider_capture.calls)
    assert process(api) == 0
    assert len(provider_capture.calls) == count


@pytest.mark.parametrize("reason", ["opt_out", "matrix_disabled", "not_whitelisted"])
def test_booking_suppression_never_calls_provider(
    api, db, scenario, provider_capture, reason
):
    provider_capture.activate()
    configure_rules(api, roles=() if reason == "matrix_disabled" else ("customer",))
    if reason == "opt_out":
        db("UPDATE customers SET sms_opt_in = FALSE WHERE id = 1")
    if reason == "not_whitelisted":
        db("DELETE FROM sms_whitelist WHERE phone_number = %s", (CUSTOMER,))
    request_id = book(api, scenario)
    assert process(api) >= 1
    assert not provider_capture.calls
    entries = logs(api, request_id)
    if reason == "matrix_disabled":
        assert not entries
    else:
        assert [row["status"] for row in entries] == [
            "SKIPPED_OPT_OUT" if reason == "opt_out" else "SKIPPED_NOT_WHITELISTED"
        ]
    assert notification(db, request_id)["status"] == "DELIVERED"


def make_retry_due(db, event_id):
    db(
        "UPDATE outbox_notifications SET next_retry_at = NOW() - INTERVAL '1 second' WHERE id = %s",
        (event_id,),
    )


def test_real_booking_transient_failure_retries_same_request_once(
    api, db, scenario, provider_capture
):
    provider_capture.activate()
    configure_rules(api, roles=("customer",))
    provider_capture.outcomes.append(500)
    request_id = book(api, scenario)
    assert process(api) >= 1
    event = notification(db, request_id)
    assert event["status"] == "PENDING"
    assert event["attempts"] == 1
    assert logs(api, request_id)[0]["status"] == "FAILED"
    assert process(api) == 0, "Backoff must prevent immediate retry"
    make_retry_due(db, event["id"])
    assert process(api) == 1
    assert notification(db, request_id)["status"] == "DELIVERED"
    assert len(provider_capture.calls) == 2
    assert {key: provider_capture.calls[0][key] for key in ("To", "From", "Body")} == {
        key: provider_capture.calls[1][key] for key in ("To", "From", "Body")
    }
    assert signed_callback(api, provider_capture.calls[-1]["sid"]).status_code == 200
    assert {row["status"] for row in logs(api, request_id)} == {"FAILED", "DELIVERED"}
    assert process(api) == 0


def test_retry_exhaustion_is_terminal_without_undoing_committed_booking(
    api, db, scenario, provider_capture
):
    provider_capture.activate()
    configure_rules(api, roles=("customer",))
    provider_capture.outcomes.extend([500, 500])
    request_id = book(api, scenario)
    event = notification(db, request_id)
    db("UPDATE outbox_notifications SET max_attempts = 2 WHERE id = %s", (event["id"],))
    assert process(api) >= 1
    make_retry_due(db, event["id"])
    assert process(api) == 1
    terminal = notification(db, request_id)
    assert terminal["status"].startswith("FAILED")
    assert terminal["attempts"] == 2
    assert all(row["status"] == "FAILED" for row in logs(api, request_id))
    assert request_by_id(api, request_id)["status"] == "pending"
    assert process(api) == 0
    assert len(provider_capture.calls) == 2


def test_partial_failure_does_not_resend_successful_recipient(
    api, db, scenario, provider_capture
):
    provider_capture.activate()
    configure_rules(api, roles=("customer", "agent"))
    provider_capture.fail_agent_once = True
    request_id = book(api, scenario)
    assert process(api) >= 1
    event = notification(db, request_id)
    assert event["status"] == "PENDING"
    make_retry_due(db, event["id"])
    assert process(api) == 1
    assert notification(db, request_id)["status"] == "DELIVERED"
    assert Counter(call["To"] for call in provider_capture.calls) == {
        CUSTOMER: 1,
        AGENT: 2,
    }


def test_delayed_sent_callback_does_not_regress_delivered_notification(
    api, scenario, provider_capture
):
    provider_capture.activate()
    configure_rules(api, roles=("customer",))
    request_id = book(api, scenario)
    assert process(api) >= 1
    sid = provider_capture.calls[0]["sid"]
    assert signed_callback(api, sid, "delivered").status_code == 200
    assert signed_callback(api, sid, "sent").status_code == 200
    assert logs(api, request_id)[0]["status"] == "DELIVERED"


def test_concurrent_workers_dispatch_one_committed_notification(
    api, db, scenario, provider_capture
):
    provider_capture.activate()
    configure_rules(api, roles=("customer",))
    request_id = book(api, scenario)
    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(lambda _: process(api), range(2)))
    assert notification(db, request_id)["status"] == "DELIVERED"
    assert len(provider_capture.calls) == 1


def test_stale_worker_claim_recovers_without_duplicate_delivery(
    api, db, scenario, provider_capture
):
    provider_capture.activate()
    configure_rules(api, roles=("customer",))
    request_id = book(api, scenario)
    event = notification(db, request_id)
    db(
        "UPDATE outbox_notifications SET status = 'PROCESSING', updated_at = NOW() - INTERVAL '10 minutes' WHERE id = %s",
        (event["id"],),
    )
    assert process(api) >= 1
    assert notification(db, request_id)["status"] == "DELIVERED"
    assert process(api) == 0
    assert len(provider_capture.calls) == 1


def test_booking_generated_reminders_reach_provider_once(
    api, db, scenario, provider_capture
):
    provider_capture.activate()
    configure_rules(api, roles=("customer", "agent"))
    request_id = book(api, scenario)
    assert process(api) >= 1
    pending = db(
        "SELECT * FROM sms_reminders WHERE appointment_id = %s AND status = 'PENDING'",
        (request_id,),
    )
    assert {row["recipient_type"] for row in pending} == {"customer", "agent"}
    provider_capture.calls.clear()
    # Advance only these real, generated reminders; do not construct synthetic ones.
    db(
        "UPDATE sms_reminders SET scheduled_at = NOW() - INTERVAL '2 days' WHERE appointment_id = %s AND status = 'PENDING'",
        (request_id,),
    )
    response = api.post("/api/cron/reminders", headers=HEADERS)
    assert response.status_code == 200
    assert len(provider_capture.calls) == len(pending)
    assert not db(
        "SELECT id FROM sms_reminders WHERE appointment_id = %s AND status = 'PENDING'",
        (request_id,),
    )
    assert (
        api.post("/api/cron/reminders", headers=HEADERS).json()["reminders_sent"] == 0
    )
    assert len(provider_capture.calls) == len(pending)


@pytest.mark.parametrize("flat", [False, True])
def test_voice_booking_dispatches_e164_customer_request(
    api, db, scenario, provider_capture, flat
):
    provider_capture.activate()
    configure_rules(api, roles=("customer",))
    arguments = {
        "customer_name": "Alex E2E",
        "phone": CUSTOMER,
        "make": "Toyota",
        "model": "Camry",
        "year": 2020,
        "issue_description": "Oil Change",
        "service_type": "Oil Change",
        "booking_type": "appointment",
        "booking_time": scenario["start"].isoformat(),
        "call_sid": "captured-voice-notification",
    }
    response = api.post(
        "/api/v1/voice/tools?name=create_service_request"
        if flat
        else "/api/v1/voice/tools",
        json=arguments
        if flat
        else {
            "tool_call_id": "captured-call",
            "name": "create_service_request",
            "arguments": arguments,
        },
    )
    assert response.status_code == 200
    result = response.json()["result"]
    assert result["success"] is True, result
    request_id = result["service_request_id"]
    assert notification(db, request_id)["status"] == "PENDING"
    assert process(api) >= 1
    assert len(provider_capture.calls) == 1
    assert provider_capture.calls[0]["To"] == CUSTOMER
    assert "Oil Change" in provider_capture.calls[0]["Body"]
    assert signed_callback(api, provider_capture.calls[0]["sid"]).status_code == 200
    assert logs(api, request_id)[0]["status"] == "DELIVERED"


@pytest.mark.parametrize("status", ["undelivered", "failed"])
def test_provider_failure_callback_updates_actual_dispatch_and_rejects_tampering(
    api, scenario, provider_capture, status
):
    provider_capture.activate()
    configure_rules(api, roles=("customer",))
    request_id = book(api, scenario)
    assert process(api) >= 1
    sid = provider_capture.calls[0]["sid"]
    bad = api.post(
        "/sms/status",
        data={"MessageSid": sid, "MessageStatus": status},
        headers={"X-Twilio-Signature": "invalid"},
    )
    assert bad.status_code == 403
    assert logs(api, request_id)[0]["status"] == "SENT"
    response = signed_callback(
        api, sid, status, ErrorCode="30005", ErrorMessage="Unknown recipient"
    )
    assert response.status_code == 200
    entry = logs(api, request_id)[0]
    assert entry["status"] == "FAILED"
    assert entry["error_code"] == "30005"
    assert entry["error_message"] == "Unknown recipient"
    assert (
        signed_callback(
            api, sid, status, ErrorCode="30005", ErrorMessage="Unknown recipient"
        ).json()["duplicate"]
        is True
    )
    assert len(logs(api, request_id)) == 1


def test_real_booking_quiet_queue_releases_original_dispatch_once(
    api, db, scenario, provider_capture, monkeypatch
):
    from datetime import datetime

    from serviceBot.services import quiet_hours, sms_router

    provider_capture.activate()
    configure_rules(api, channel="WHATSAPP", roles=("customer",))
    response = api.put(
        f"{PORTAL}/sms/config",
        json={
            "quiet_hours_enabled": True,
            "quiet_start_time": "21:00",
            "quiet_end_time": "08:00",
        },
    )
    assert response.status_code == 200
    clock = datetime.now(quiet_hours.TIMEZONE_NY).replace(hour=22, minute=0, second=0)
    in_quiet = quiet_hours.is_in_quiet_hours
    release_time = quiet_hours.calculate_quiet_hours_release_time
    monkeypatch.setattr(sms_router, "is_in_quiet_hours", lambda: in_quiet(now_dt=clock))
    monkeypatch.setattr(
        sms_router,
        "calculate_quiet_hours_release_time",
        lambda: release_time(now_dt=clock),
    )
    request_id = book(api, scenario)
    assert process(api) >= 1
    assert not provider_capture.calls
    entry = logs(api, request_id)[0]
    assert entry["status"] == "QUEUED"
    db(
        "UPDATE sms_log SET scheduled_send_at = NOW() - INTERVAL '2 days' WHERE id = %s",
        (entry["id"],),
    )
    assert quiet_hours.run_quiet_hours_queue_worker_cycle() == 1
    assert quiet_hours.run_quiet_hours_queue_worker_cycle() == 0
    assert len(provider_capture.calls) == 1
    assert provider_capture.calls[0]["To"] == "whatsapp:" + CUSTOMER
    assert provider_capture.calls[0]["Body"] == entry["body"]
    assert signed_callback(api, provider_capture.calls[0]["sid"]).status_code == 200
    fresh = logs(api, request_id)
    assert len(fresh) == 1
    assert fresh[0]["id"] == entry["id"]
    assert fresh[0]["status"] == "DELIVERED"


def test_agent_confirmation_stops_booking_generated_prompts(
    api, db, scenario, provider_capture
):
    provider_capture.activate()
    configure_rules(api, roles=("customer", "agent"))
    request_id = book(api, scenario)
    assert process(api) >= 1
    assert db(
        "SELECT id FROM sms_reminders WHERE appointment_id = %s AND recipient_type = 'agent' AND status = 'PENDING'",
        (request_id,),
    )
    form = {"From": AGENT, "Body": "CONFIRM", "MessageSid": "SM-captured-confirm"}
    signature = RequestValidator(AUTH_TOKEN).compute_signature(
        f"{PUBLIC_URL}/sms/inbound", form
    )
    response = api.post(
        "/sms/inbound", data=form, headers={"X-Twilio-Signature": signature}
    )
    assert response.status_code == 200
    assert request_by_id(api, request_id)["confirmation_status"] == "confirmed"
    assert not db(
        "SELECT id FROM sms_reminders WHERE appointment_id = %s AND recipient_type = 'agent' AND status = 'PENDING'",
        (request_id,),
    )
    provider_capture.calls.clear()
    assert (
        api.post("/api/cron/reminders", headers=HEADERS).json()["reminders_sent"] == 0
    )
    assert not provider_capture.calls
