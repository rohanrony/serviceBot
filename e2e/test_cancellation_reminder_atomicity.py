"""Cancellation and pending reminders share one real database transaction."""

from contextlib import contextmanager

import pytest

from e2e.test_workflows import book


def arrange_reminders(db, request_id):
    for status in ("PENDING", "SENT"):
        db(
            "INSERT INTO sms_reminders (appointment_id, recipient_type, recipient_phone, reminder_type, scheduled_at, status) VALUES (%s, 'customer', '+15550100001', %s, NOW(), %s)",
            (request_id, "2h" if status == "PENDING" else "24h", status),
        )


def cancel(entry, request_id, *, cursor_factory=None):
    from serviceBot.db.queries import update_service_request_status
    from serviceBot.services.booking import BookingService

    if entry == "booking_service":
        service = BookingService(**({"cursor_factory": cursor_factory} if cursor_factory else {}))
        return service.cancel(request_id=request_id, customer_consent_obtained=True, triggered_by="customer")
    return update_service_request_status(request_id, "cancelled", triggered_by="customer")


@pytest.mark.parametrize("entry", ["booking_service", "status_update"])
def test_cancellation_persists_reminder_state_without_separate_helper(api, db, scenario, monkeypatch, entry):
    from serviceBot.services import sms_reminders

    request_id = book(api, scenario)
    arrange_reminders(db, request_id)

    def unavailable_helper(*args, **kwargs):
        raise RuntimeError("separate reminder connection unavailable")

    monkeypatch.setattr(sms_reminders, "update_or_cancel_appointment_reminders", unavailable_helper)
    cancel(entry, request_id)
    assert db("SELECT status FROM service_requests WHERE id=%s", (request_id,)) == [{"status": "cancelled"}]
    assert db("SELECT status FROM sms_reminders WHERE appointment_id=%s ORDER BY id", (request_id,)) == [
        {"status": "CANCELLED"}, {"status": "SENT"},
    ]


def state(db, request_id):
    return {
        "request": db("SELECT * FROM service_requests WHERE id=%s", (request_id,)),
        "reservation": db("SELECT * FROM appointment_reservations WHERE service_request_id=%s ORDER BY id", (request_id,)),
        "segments": db("SELECT * FROM appointment_reservation_segments ORDER BY reservation_id, segment_start"),
        "slots": db("SELECT * FROM mock_calendar_slots ORDER BY id"),
        "outbox": db("SELECT * FROM outbox_notifications ORDER BY id"),
        "reminders": db("SELECT * FROM sms_reminders ORDER BY id"),
        "audit": db("SELECT * FROM service_request_audit_log ORDER BY id"),
    }


@pytest.mark.parametrize("entry", ["booking_service", "status_update"])
def test_reminder_write_failure_rolls_back_entire_cancellation(api, db, scenario, monkeypatch, entry):
    from serviceBot.db import queries
    from serviceBot.db.connection import dict_cursor

    request_id = book(api, scenario)
    arrange_reminders(db, request_id)
    before = state(db, request_id)

    class FailingReminderCursor:
        def __init__(self, cursor):
            self.cursor = cursor

        def execute(self, sql, params=None):
            if "UPDATE SMS_REMINDERS" in " ".join(str(sql).upper().split()):
                raise RuntimeError("injected reminder write failure")
            return self.cursor.execute(sql, params)

        def __getattr__(self, name):
            return getattr(self.cursor, name)

    @contextmanager
    def failing_cursor(connection):
        with dict_cursor(connection) as cursor:
            yield FailingReminderCursor(cursor)

    if entry == "status_update":
        monkeypatch.setattr(queries, "dict_cursor", failing_cursor)
    with pytest.raises(RuntimeError, match="injected reminder write failure"):
        cancel(entry, request_id, cursor_factory=failing_cursor)
    assert state(db, request_id) == before
