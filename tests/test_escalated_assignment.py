"""Service regression: recovery persists before notification workers run."""

from datetime import datetime, timedelta
from uuid import uuid4

from serviceBot.db.connection import dict_cursor, get_db_connection
from serviceBot.db.queries import assign_staff_agent_to_service_request
from serviceBot.services import booking, google_calendar, timezone_service


def test_assignment_recovers_escalation_with_configured_window(monkeypatch):
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
            "INSERT INTO staff_agents (name, role) VALUES (%s, 'Technician'), (%s, 'Technician') RETURNING id",
            (f"Old {token}", f"New {token}"),
        )
        old_agent, new_agent = [row["id"] for row in cursor.fetchall()]
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
