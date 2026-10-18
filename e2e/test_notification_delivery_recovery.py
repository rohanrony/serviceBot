"""Signed provider failure -> durable SMS recovery -> captured Twilio transport."""

from concurrent.futures import ThreadPoolExecutor

import pytest

from e2e.test_notification_workflows import (
    ADMIN, AGENT, CUSTOMER, PUBLIC_URL, configure_rules, provider_capture as shared_provider_capture, signed_callback,
)
from e2e.test_workflows import book

# Expose the shared captured transport fixture to pytest's module discovery.
provider_capture = shared_provider_capture


def original_whatsapp(api, db, scenario, role="customer", template=None):
    request_id = book(api, scenario)
    db("UPDATE outbox_notifications SET status='DELIVERED' WHERE request_id=%s", (request_id,))
    row = db(
        "INSERT INTO sms_log (appointment_id,recipient_type,recipient_phone,template_type,status,twilio_message_sid,body,channel) VALUES (%s,%s,%s,%s,'SENT','SMoriginal63016','Original booking details','WHATSAPP') RETURNING id",
        (request_id, role, {"customer": CUSTOMER, "agent": AGENT, "admin": ADMIN}[role], template or ("agent_booking" if role == "agent" else "booking")),
    )[0]
    return request_id, row["id"]


def fallback_events(db):
    return db("SELECT * FROM outbox_notifications WHERE event_type='sms_delivery_fallback' ORDER BY id")


@pytest.mark.parametrize("role,template", [("customer", "booking"), ("agent", "agent_booking"), ("agent", "agent_rescheduled"), ("admin", "admin_booking")])
def test_whatsapp_63016_recovers_once_through_sms_and_requests_real_callback(
    api, db, scenario, provider_capture, role, template
):
    from serviceBot.services.outbox_worker import process_outbox_batch

    provider_capture.activate()
    configure_rules(api, roles=("customer", "agent", "admin"))
    request_id, source_id = original_whatsapp(api, db, scenario, role, template)
    for status in ("undelivered", "failed", "sent", "undelivered"):
        response = signed_callback(api, "SMoriginal63016", status, ErrorCode="63016")
        assert response.status_code == 200, response.text
    events = fallback_events(db)
    assert len(events) == 1
    assert events[0]["payload"]["source_log_id"] == source_id
    assert db("SELECT status,error_code FROM sms_log WHERE id=%s", (source_id,)) == [{"status": "FAILED", "error_code": "63016"}]
    assert process_outbox_batch() == 1
    assert len(provider_capture.calls) == 1
    call = provider_capture.calls[0]
    assert call["To"] == {"customer": CUSTOMER, "agent": AGENT, "admin": ADMIN}[role]
    assert call["Body"] == "Original booking details"
    assert call["StatusCallback"] == f"{PUBLIC_URL}/api/v1/telephony/sms/status"
    fallback_id = events[0]["payload"]["fallback_log_id"]
    assert db("SELECT channel,status,twilio_message_sid FROM sms_log WHERE id=%s", (fallback_id,)) == [{"channel": "SMS", "status": "SENT", "twilio_message_sid": call["sid"]}]
    # Worker recovery after acceptance must reuse the recorded SID.
    db("UPDATE outbox_notifications SET status='PENDING',next_retry_at=NOW() WHERE id=%s", (events[0]["id"],))
    assert process_outbox_batch() == 1
    assert len(provider_capture.calls) == 1
    assert signed_callback(api, call["sid"], "delivered").status_code == 200
    assert db("SELECT status FROM sms_log WHERE id=%s", (fallback_id,)) == [{"status": "DELIVERED"}]


@pytest.mark.parametrize("blocked", ["other_error", "sms_disabled", "sms_missing", "opt_out", "already_delivered", "original_sms"])
def test_ineligible_delivery_failure_cannot_enqueue_sms_recovery(
    api, db, scenario, provider_capture, blocked
):
    provider_capture.activate()
    configure_rules(api)
    request_id, source_id = original_whatsapp(api, db, scenario)
    if blocked == "sms_disabled":
        db("UPDATE sms_matrix_rules SET enabled=FALSE WHERE event_type='BOOKING' AND recipient_role='customer' AND channel='SMS'")
    elif blocked == "sms_missing":
        db("DELETE FROM sms_matrix_rules WHERE event_type='BOOKING' AND recipient_role='customer' AND channel='SMS'")
    elif blocked == "opt_out":
        db("UPDATE customers SET sms_opt_in=FALSE WHERE id=(SELECT customer_id FROM service_requests WHERE id=%s)", (request_id,))
    elif blocked == "already_delivered":
        db("UPDATE sms_log SET status='DELIVERED' WHERE id=%s", (source_id,))
    elif blocked == "original_sms":
        db("UPDATE sms_log SET channel='SMS' WHERE id=%s", (source_id,))
    response = signed_callback(api, "SMoriginal63016", "undelivered", ErrorCode="30003" if blocked == "other_error" else "63016")
    assert response.status_code == 200
    assert not fallback_events(db)


@pytest.mark.parametrize("change", ["opt_out", "sms_disabled"])
def test_sms_recovery_rechecks_policy_before_provider_dispatch(
    api, db, scenario, provider_capture, change
):
    from serviceBot.services.outbox_worker import process_outbox_batch

    provider_capture.activate()
    configure_rules(api)
    request_id, _ = original_whatsapp(api, db, scenario)
    assert signed_callback(api, "SMoriginal63016", "undelivered", ErrorCode="63016").status_code == 200
    events = fallback_events(db)
    assert len(events) == 1
    if change == "opt_out":
        db("UPDATE customers SET sms_opt_in=FALSE WHERE id=(SELECT customer_id FROM service_requests WHERE id=%s)", (request_id,))
    else:
        db("UPDATE sms_matrix_rules SET enabled=FALSE WHERE event_type='BOOKING' AND recipient_role='customer' AND channel='SMS'")
    assert process_outbox_batch() == 1
    assert not provider_capture.calls
    assert db("SELECT status FROM sms_log WHERE id=%s", (events[0]["payload"]["fallback_log_id"],))[0]["status"].startswith("SKIPPED")


def test_concurrent_failure_callbacks_create_one_sms_recovery(
    api, db, scenario, provider_capture
):
    provider_capture.activate()
    configure_rules(api)
    original_whatsapp(api, db, scenario)
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(
            lambda status: signed_callback(api, "SMoriginal63016", status, ErrorCode="63016"),
            ("undelivered", "failed"),
        ))
    assert all(response.status_code == 200 for response in responses)
    assert len(fallback_events(db)) == 1
    assert len(db("SELECT id FROM sms_log WHERE channel='SMS' AND body='Original booking details'")) == 1


def test_callback_enqueue_failure_rolls_back_status_and_fallback_log(
    api, db, scenario, provider_capture, monkeypatch
):
    from serviceBot.services import outbox_worker

    provider_capture.activate()
    configure_rules(api)
    _, source_id = original_whatsapp(api, db, scenario)
    enqueue = outbox_worker.enqueue_outbox_event

    def fail(cursor, event_type, request_id, payload):
        if event_type == "sms_delivery_fallback":
            raise RuntimeError("Synthetic enqueue failure")
        return enqueue(cursor, event_type, request_id, payload)

    monkeypatch.setattr(outbox_worker, "enqueue_outbox_event", fail)
    response = signed_callback(api, "SMoriginal63016", "undelivered", ErrorCode="63016")
    assert response.status_code == 500
    assert db("SELECT status FROM sms_log WHERE id=%s", (source_id,)) == [{"status": "SENT"}]
    assert not fallback_events(db)
    assert not db("SELECT id FROM sms_log WHERE channel='SMS' AND body='Original booking details'")


@pytest.mark.parametrize("stage", ["admission", "dispatch"])
def test_local_phone_recovery_respects_e164_customer_opt_out(
    api, db, scenario, provider_capture, stage
):
    from serviceBot.services.outbox_worker import process_outbox_batch

    provider_capture.activate()
    configure_rules(api)
    request_id, source_id = original_whatsapp(api, db, scenario)
    db("UPDATE sms_log SET recipient_phone=%s WHERE id=%s", (CUSTOMER[-10:], source_id))
    assert db("SELECT phone FROM customers WHERE id=(SELECT customer_id FROM service_requests WHERE id=%s)", (request_id,)) == [{"phone": CUSTOMER}]
    if stage == "admission":
        db("UPDATE customers SET sms_opt_in=FALSE WHERE id=(SELECT customer_id FROM service_requests WHERE id=%s)", (request_id,))
    assert signed_callback(api, "SMoriginal63016", "undelivered", ErrorCode="63016").status_code == 200
    if stage == "admission":
        assert not fallback_events(db)
    else:
        events = fallback_events(db)
        assert len(events) == 1
        db("UPDATE customers SET sms_opt_in=FALSE WHERE id=(SELECT customer_id FROM service_requests WHERE id=%s)", (request_id,))
        assert process_outbox_batch() == 1
        assert db("SELECT status FROM sms_log WHERE id=%s", (events[0]["payload"]["fallback_log_id"],)) == [{"status": "SKIPPED_OPT_OUT"}]
    assert not provider_capture.calls


def test_recovery_does_not_strip_another_roles_template_prefix(
    api, db, scenario, provider_capture
):
    provider_capture.activate()
    configure_rules(api)
    original_whatsapp(api, db, scenario, "agent", "customer_booking")
    assert signed_callback(api, "SMoriginal63016", "undelivered", ErrorCode="63016").status_code == 200
    assert not fallback_events(db)
