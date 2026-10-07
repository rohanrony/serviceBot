"""Acceptance boundaries for retry integrity, consent changes and missing keys."""

from datetime import timedelta

import pytest
from twilio.request_validator import RequestValidator

from e2e.test_notification_workflows import (
    AUTH_TOKEN,
    CUSTOMER,
    PUBLIC_URL,
    configure_rules,
    logs,
    make_retry_due,
    notification,
    process,
)
from e2e.test_notification_workflows import (
    provider_capture as captured_provider_fixture,
)
from e2e.test_workflows import PORTAL, book

provider_capture = captured_provider_fixture


@pytest.mark.parametrize("channel", ["SMS", "WHATSAPP"])
def test_manual_retry_preserves_original_message_and_channel(
    api, scenario, provider_capture, channel
):
    provider_capture.activate()
    configure_rules(api, channel=channel, roles=("customer",))
    provider_capture.outcomes.append(500)
    request_id = book(api, scenario)
    assert process(api) >= 1
    entry = logs(api, request_id)[0]
    assert entry["status"] == "FAILED"
    original = provider_capture.calls[0]
    response = api.post(f"{PORTAL}/sms/retry/{entry['id']}")
    assert response.status_code == 200, response.text
    assert len(provider_capture.calls) == 2
    assert {key: provider_capture.calls[-1][key] for key in ("To", "From", "Body")} == {
        key: original[key] for key in ("To", "From", "Body")
    }
    entries = logs(api, request_id)
    assert len(entries) == 1, (
        "Retry must update the original delivery record, not create another logical message"
    )
    assert entries[0]["id"] == entry["id"] and entries[0]["retry_count"] == 1
    assert entries[0]["status"] == "SENT" and entries[0]["channel"] == channel


def test_cross_channel_partial_failure_does_not_repeat_successful_sms(
    api, db, scenario, provider_capture
):
    provider_capture.activate()
    configure_rules(api, roles=("customer",))
    assert (
        api.put(
            f"{PORTAL}/sms/matrix-rules",
            json={
                "event_type": "BOOKING",
                "recipient_role": "customer",
                "channel": "WHATSAPP",
                "enabled": True,
            },
        ).status_code
        == 200
    )
    provider_capture.outcomes.extend([201, 500])
    request_id = book(api, scenario)
    assert process(api) >= 1
    calls = list(provider_capture.calls)
    assert len(calls) == 2 and {call["To"] for call in calls} == {
        CUSTOMER,
        "whatsapp:" + CUSTOMER,
    }
    successful = next(call for call in calls if call["http_status"] == 201)
    failed = next(call for call in calls if call["http_status"] == 500)
    event = notification(db, request_id)
    assert event["status"] == "PENDING"
    make_retry_due(db, event["id"])
    assert process(api) == 1
    assert sum(call["To"] == successful["To"] for call in provider_capture.calls) == 1
    assert sum(call["To"] == failed["To"] for call in provider_capture.calls) == 2


@pytest.mark.parametrize("channel", ["SMS", "WHATSAPP"])
def test_opt_out_after_queueing_prevents_quiet_hour_release(
    api, db, scenario, provider_capture, freeze_business_clock, channel
):
    from serviceBot.services.quiet_hours import run_quiet_hours_queue_worker_cycle

    provider_capture.activate()
    configure_rules(api, channel=channel, roles=("customer",))
    freeze_business_clock((scenario["start"] - timedelta(days=7)).replace(hour=22))
    assert (
        api.put(
            f"{PORTAL}/sms/config",
            json={
                "quiet_hours_enabled": True,
                "quiet_start_time": "21:00",
                "quiet_end_time": "08:00",
            },
        ).status_code
        == 200
    )
    request_id = book(api, scenario)
    assert process(api) >= 1
    assert not provider_capture.calls
    entry = logs(api, request_id)[0]
    assert entry["status"] == "QUEUED"
    form = {"From": CUSTOMER, "Body": "STOP", "MessageSid": f"SM-queued-stop-{channel}"}
    signature = RequestValidator(AUTH_TOKEN).compute_signature(
        f"{PUBLIC_URL}/sms/inbound", form
    )
    assert (
        api.post(
            "/sms/inbound", data=form, headers={"X-Twilio-Signature": signature}
        ).status_code
        == 200
    )
    assert db("SELECT sms_opt_in FROM customers WHERE id=1")[0]["sms_opt_in"] is False
    provider_capture.calls.clear()
    db(
        "UPDATE sms_log SET scheduled_send_at=NOW()-INTERVAL '2 days' WHERE id=%s",
        (entry["id"],),
    )
    run_quiet_hours_queue_worker_cycle()
    assert not provider_capture.calls, (
        "Consent must be rechecked at dispatch, not only when queued"
    )
    fresh = next(row for row in logs(api, request_id) if row["id"] == entry["id"])
    assert fresh["status"] == "SKIPPED_OPT_OUT"


def test_production_missing_credentials_never_claims_message_sent(
    api, db, scenario, provider_capture, monkeypatch
):
    provider_capture.activate()
    configure_rules(api, roles=("customer",))
    assert (
        api.put(f"{PORTAL}/sms/config", json={"environment": "PRODUCTION"}).status_code
        == 200
    )
    for key in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN"):
        monkeypatch.delenv(key, raising=False)
    request_id = book(api, scenario)
    process(api)
    assert not provider_capture.calls
    entries = logs(api, request_id)
    assert entries and all(
        row["status"] not in {"SENT", "DELIVERED"} for row in entries
    )
    assert notification(db, request_id)["status"] != "DELIVERED"
