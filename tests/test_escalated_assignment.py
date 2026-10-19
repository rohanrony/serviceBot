"""Service regression: recovery persists before notification workers run."""

from datetime import datetime, timedelta
from uuid import uuid4

import pytest

from serviceBot.db.connection import dict_cursor, get_db_connection
from serviceBot.db.queries import assign_staff_agent_to_service_request
from serviceBot.services import booking, google_calendar, timezone_service


@pytest.fixture
def assignment_case(monkeypatch):
    from serviceBot.api import portal

    current = datetime(2030, 1, 7, 10, tzinfo=timezone_service.get_business_zoneinfo())
    now = current.replace(tzinfo=None)
    start = datetime(2030, 1, 9, 14, 30, tzinfo=current.tzinfo).replace(tzinfo=None)

    class ClockMeta(type):
        def __instancecheck__(cls, value):
            return isinstance(value, datetime)

    class Clock(datetime, metaclass=ClockMeta):
        @classmethod
        def now(cls, tz=None):
            return current.astimezone(tz) if tz else now

    import datetime as datetime_module
    from types import SimpleNamespace

    clock_module = SimpleNamespace(**vars(datetime_module))
    clock_module.datetime = Clock
    monkeypatch.setattr(booking, "dt_mod", clock_module)
    monkeypatch.setattr(timezone_service, "now_in_business_tz", lambda: current)
    monkeypatch.setattr(google_calendar, "fetch_agent_events", lambda *a, **kw: [])
    config = portal.load_config()
    config["reassignment_confirmation_window_minutes"] = 23
    monkeypatch.setattr(portal, "load_config", lambda: config)
    token = uuid4().hex[:12]
    with get_db_connection() as conn, dict_cursor(conn) as cursor:
        cursor.execute(
            "INSERT INTO customers (name, phone) VALUES (%s, %s) RETURNING id",
            (f"Recovery {token}", token),
        )
        customer_id = cursor.fetchone()["id"]
        cursor.execute(
            "INSERT INTO staff_agents (name, role) VALUES (%s, 'Technician'), (%s, 'Technician'), (%s, 'Technician') RETURNING id",
            (f"Old {token}", f"New {token}", f"Other {token}"),
        )
        old_agent, new_agent, other_agent = [row["id"] for row in cursor.fetchall()]
        cursor.execute(
            "INSERT INTO service_requests (customer_id, staff_agent_id, service_type, booking_type, booking_time, duration_minutes) VALUES (%s, %s, %s, 'appointment', %s, 60) RETURNING id",
            (customer_id, old_agent, f"Recovery {token}", str(start)),
        )
        request_id = cursor.fetchone()["id"]
    booking.BookingService().reserve_existing(
        request_id=request_id, appointment_datetime=start, requested_agent_id=old_agent
    )
    with get_db_connection() as conn, dict_cursor(conn) as cursor:
        cursor.execute(
            "UPDATE service_requests SET escalation_status='escalated', escalation_reason='DELIVERY_FAILED', confirmation_cutoff_at=%s WHERE id=%s",
            (now - timedelta(minutes=1), request_id),
        )
    return {
        "request_id": request_id,
        "customer_id": customer_id,
        "old_agent": old_agent,
        "new_agent": new_agent,
        "other_agent": other_agent,
        "now": now,
        "start": start,
        "service_type": f"Recovery {token}",
    }


def test_assignment_recovers_escalation_with_configured_window(assignment_case):
    case = assignment_case
    request_id, old_agent, new_agent, now = (
        case["request_id"],
        case["old_agent"],
        case["new_agent"],
        case["now"],
    )

    result = assign_staff_agent_to_service_request(request_id, new_agent)

    with get_db_connection() as conn, dict_cursor(conn) as cursor:
        cursor.execute(
            "SELECT staff_agent_id, escalation_status, escalation_reason, confirmation_status, confirmation_cutoff_at FROM service_requests WHERE id=%s",
            (request_id,),
        )
        row = dict(cursor.fetchone())
        cursor.execute(
            "SELECT payload FROM outbox_notifications WHERE request_id=%s AND event_type='booking_notification' ORDER BY id DESC LIMIT 1",
            (request_id,),
        )
        notification = cursor.fetchone()["payload"]
    assert row == {
        "staff_agent_id": new_agent,
        "escalation_status": "reassigned",
        "escalation_reason": None,
        "confirmation_status": "pending_agent_confirmation",
        "confirmation_cutoff_at": now + timedelta(minutes=23),
    }
    assert result["escalation_status"] == row["escalation_status"]
    assert notification["notification_event"] == "REASSIGNED"
    assert notification["agent_id"] == new_agent
    assert notification["old_agent_id"] == old_agent


def _request_state(request_id):
    with get_db_connection() as conn, dict_cursor(conn) as cursor:
        result = {}
        for name, statement in {
            "request": "SELECT * FROM service_requests WHERE id=%s",
            "reservations": "SELECT * FROM appointment_reservations WHERE service_request_id=%s ORDER BY id",
            "segments": "SELECT s.* FROM appointment_reservation_segments s JOIN appointment_reservations r ON r.id=s.reservation_id WHERE r.service_request_id=%s ORDER BY s.segment_start",
            "slots": "SELECT * FROM mock_calendar_slots WHERE service_request_id=%s ORDER BY id",
            "outbox": "SELECT * FROM outbox_notifications WHERE request_id=%s ORDER BY id",
            "audit": "SELECT * FROM service_request_audit_log WHERE request_id=%s ORDER BY id",
            "reminders": "SELECT * FROM sms_reminders WHERE appointment_id=%s ORDER BY id",
        }.items():
            cursor.execute(statement, (request_id,))
            result[name] = [dict(row) for row in cursor.fetchall()]
        return result


def test_concurrent_reassignments_cannot_claim_the_same_agent_capacity(
    assignment_case, monkeypatch
):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from serviceBot.services.booking import BookingConflictError

    case = assignment_case
    with get_db_connection() as conn, dict_cursor(conn) as cursor:
        cursor.execute(
            "INSERT INTO service_requests (customer_id, staff_agent_id, service_type, booking_type, booking_time, duration_minutes) VALUES (%s, %s, %s, 'appointment', %s, 60) RETURNING id",
            (
                case["customer_id"],
                case["other_agent"],
                case["service_type"],
                str(case["start"]),
            ),
        )
        second_id = cursor.fetchone()["id"]
    booking.BookingService().reserve_existing(
        request_id=second_id,
        appointment_datetime=case["start"],
        requested_agent_id=case["other_agent"],
    )
    with get_db_connection() as conn, dict_cursor(conn) as cursor:
        cursor.execute(
            "UPDATE service_requests SET escalation_status='escalated', escalation_reason='AGENT_DECLINED', confirmation_cutoff_at=%s WHERE id=%s",
            (case["now"] - timedelta(minutes=1), second_id),
        )
    ids = (case["request_id"], second_id)
    before = {request_id: _request_state(request_id) for request_id in ids}
    boundary = Barrier(2)

    def available(agent_id, *_args, **_kwargs):
        if agent_id == case["new_agent"]:
            # Force both transactions past the availability read before either
            # claims capacity. No timing sleeps or guessed scheduling order.
            boundary.wait(timeout=10)
        return []

    monkeypatch.setattr(google_calendar, "fetch_agent_events", available)

    def assign(request_id):
        try:
            assign_staff_agent_to_service_request(request_id, case["new_agent"])
            return "assigned", request_id
        except BookingConflictError:
            return "conflict", request_id

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(assign, ids))
    assert sorted(status for status, _ in results) == ["assigned", "conflict"]
    winner = next(request_id for status, request_id in results if status == "assigned")
    loser = next(request_id for status, request_id in results if status == "conflict")
    assert _request_state(loser) == before[loser]
    after = _request_state(winner)
    assert after["request"][0]["staff_agent_id"] == case["new_agent"]
    assert after["request"][0]["escalation_status"] == "reassigned"
    assert len(after["reservations"]) == 1
    assert len(after["segments"]) == 4
    assert {row["staff_agent_id"] for row in after["segments"]} == {case["new_agent"]}
    assert [row["segment_start"] for row in after["segments"]] == [
        case["start"] + timedelta(minutes=offset) for offset in range(0, 60, 15)
    ]
