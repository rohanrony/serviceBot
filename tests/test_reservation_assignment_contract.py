"""Regression coverage for portal staffing over durable reservations."""

import datetime as dt_mod
import uuid
from unittest.mock import patch

import serviceBot.db.queries as queries
from serviceBot.db.connection import dict_cursor, get_db_connection
from serviceBot.services.booking import BookingService


def _future_business_time() -> str:
    candidate = dt_mod.date.today() + dt_mod.timedelta(days=75)
    while candidate.weekday() > 4:
        candidate += dt_mod.timedelta(days=1)
    return f"{candidate.isoformat()} 10:00:00"


def test_reassignment_moves_the_local_reservation_and_fails_closed_on_provider_error():
    token = uuid.uuid4().hex[:10]
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                "INSERT INTO customers (name, phone) VALUES (%s, %s) RETURNING id;",
                (f"Reservation Assignment {token}", f"+1555{token[:7]}"),
            )
            customer_id = cursor.fetchone()["id"]
            cursor.execute(
                """
                INSERT INTO vehicles (customer_id, make, model, year)
                VALUES (%s, 'Honda', 'Civic', 2020);
                """,
                (customer_id,),
            )
            cursor.execute(
                """
                INSERT INTO staff_agents (name, role, email)
                VALUES (%s, 'Technician', %s)
                RETURNING id;
                """,
                (f"Original {token}", f"original-{token}@example.test"),
            )
            original_agent_id = cursor.fetchone()["id"]
            cursor.execute(
                """
                INSERT INTO staff_agents (name, role, email)
                VALUES (%s, 'Technician', %s)
                RETURNING id;
                """,
                (f"Replacement {token}", f"replacement-{token}@example.test"),
            )
            replacement_agent_id = cursor.fetchone()["id"]
            conn.commit()

    receipt = BookingService().reserve_or_create(
        customer_id=customer_id,
        service_request_id=None,
        appointment_datetime=_future_business_time(),
        service_type="Oil Change",
        vehicle_details={"make": "Honda", "model": "Civic", "year": 2020},
        issue_description="Reservation-assignment regression test.",
        booking_type="appointment",
        duration_minutes=60,
        requested_agent_id=original_agent_id,
    )

    with patch(
        "serviceBot.services.google_calendar.fetch_agent_events",
        side_effect=RuntimeError("provider unavailable"),
    ):
        agents = queries.get_available_agents_for_request(receipt.request_id)

    assert agents
    assert all(agent["is_available"] is False for agent in agents)
    assert all(agent["reason"] == "Calendar state unavailable" for agent in agents)

    updated = queries.assign_staff_agent_to_service_request(
        receipt.request_id,
        replacement_agent_id,
    )
    assert updated["staff_agent_id"] == replacement_agent_id

    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                """
                SELECT staff_agent_id
                FROM appointment_reservations
                WHERE service_request_id = %s AND status = 'ACTIVE';
                """,
                (receipt.request_id,),
            )
            reservation = cursor.fetchone()
            cursor.execute(
                """
                SELECT DISTINCT ars.staff_agent_id
                FROM appointment_reservation_segments ars
                JOIN appointment_reservations ar ON ar.id = ars.reservation_id
                WHERE ar.service_request_id = %s;
                """,
                (receipt.request_id,),
            )
            segment_agents = {row["staff_agent_id"] for row in cursor.fetchall()}
            cursor.execute(
                """
                SELECT payload ->> 'notification_event' AS notification_event
                FROM outbox_notifications
                WHERE request_id = %s AND event_type = 'booking_notification'
                ORDER BY id DESC
                LIMIT 1;
                """,
                (receipt.request_id,),
            )
            notification = cursor.fetchone()

    assert reservation["staff_agent_id"] == replacement_agent_id
    assert segment_agents == {replacement_agent_id}
    assert notification["notification_event"] == "RESCHEDULED_REASSIGNED"

def test_date_slot_lookup_fails_closed_on_provider_error():
    target_date = _future_business_time().split()[0]

    with patch(
        "serviceBot.services.google_calendar.fetch_agent_events",
        side_effect=RuntimeError("provider unavailable"),
    ):
        assert queries.get_available_slots_for_date(target_date) == []
