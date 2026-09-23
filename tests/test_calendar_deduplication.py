import datetime as dt_mod
import pytest
from unittest.mock import patch, MagicMock
from serviceBot.services.gmail import delete_admin_calendar_event
from serviceBot.services.outbox_worker import _dispatch_outbox_event
from serviceBot.db.connection import dict_cursor, get_db_connection
from serviceBot.db.queries import book_appointment, reschedule_appointment


def _next_business_date() -> dt_mod.date:
    candidate = dt_mod.date.today() + dt_mod.timedelta(days=1)
    while candidate.weekday() > 4:
        candidate += dt_mod.timedelta(days=1)
    return candidate



@patch("serviceBot.services.gmail.get_gmail_access_token")
@patch("httpx.get")
@patch("httpx.delete")
def test_delete_admin_calendar_event(mock_delete, mock_get, mock_token):
    """Verify delete_admin_calendar_event queries primary calendar and issues DELETE request for matching events."""
    mock_token.return_value = "dummy_admin_token"

    mock_get_res = MagicMock()
    mock_get_res.status_code = 200
    mock_get_res.json.return_value = {
        "items": [
            {
                "id": "admin_event_123",
                "summary": "serviceBot Booking - John Doe (Mathew Tan)",
                "status": "confirmed"
            },
            {
                "id": "unrelated_event_456",
                "summary": "Doctor Appointment",
                "status": "confirmed"
            }
        ]
    }
    mock_get.return_value = mock_get_res

    mock_del_res = MagicMock()
    mock_del_res.status_code = 204
    mock_delete.return_value = mock_del_res

    result = delete_admin_calendar_event("2026-08-10 10:00:00", duration_minutes=60)
    assert result is True

    # Verify GET parameters
    assert mock_get.called
    get_args, get_kwargs = mock_get.call_args
    assert get_kwargs["headers"]["Authorization"] == "Bearer dummy_admin_token"

    # Verify DELETE request was issued ONLY for the matching serviceBot event
    assert mock_delete.called
    del_args, del_kwargs = mock_delete.call_args
    assert "admin_event_123" in del_args[0]


@patch("serviceBot.services.outbox_worker.delete_agent_calendar_event")
@patch("serviceBot.services.outbox_worker.delete_admin_calendar_event")
@patch("serviceBot.services.outbox_worker.create_agent_calendar_event")
@patch("serviceBot.services.outbox_worker.create_admin_calendar_event")
@patch("serviceBot.services.outbox_worker.send_booking_notification")
@patch("serviceBot.services.outbox_worker.send_admin_notification")
def test_outbox_agent_reassignment_cleans_up_old_events(
    mock_send_admin_notif,
    mock_send_booking_notif,
    mock_create_admin,
    mock_create_agent,
    mock_delete_admin,
    mock_delete_agent
):
    """Verify outbox agent_reassignment event deletes both old agent & old admin calendar events."""
    payload = {
        "old_agent_id": 1,
        "old_agent_name": "Rohan Roy",
        "new_agent_id": 2,
        "new_agent_name": "Mathew Tan",
        "new_agent_email": "mathew@example.com",
        "booking_time_str": "2026-08-10 10:00:00",
        "details": {
            "customer_name": "Test Customer",
            "service_type": "Oil Change",
            "issue": "Routine Service",
            "phone": "+15550001111"
        }
    }

    _dispatch_outbox_event("agent_reassignment", 101, payload)

    # Verify old events were deleted
    mock_delete_agent.assert_called_once_with(1, "2026-08-10 10:00:00")
    mock_delete_admin.assert_called_once_with("2026-08-10 10:00:00")

    # Verify new events were created
    assert mock_create_agent.called
    assert mock_create_admin.called


@patch("serviceBot.services.gmail.create_admin_calendar_event")
@patch("serviceBot.services.google_calendar.create_agent_calendar_event")
@patch("serviceBot.services.google_calendar.delete_agent_calendar_event")
def test_reschedule_appointment_queues_calendar_reconciliation(
    delete_agent, create_agent, create_admin
):
    """A successful reschedule commits local state and queues provider work without inline calls."""
    date = _next_business_date()
    first_slot = f"{date.isoformat()} 10:00:00"
    second_slot = f"{date.isoformat()} 12:00:00"

    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                "INSERT INTO customers (name, phone) VALUES ('Reschedule Contract', '+15550119999') RETURNING id;"
            )
            customer_id = cursor.fetchone()["id"]
            cursor.execute(
                "INSERT INTO vehicles (customer_id, make, model, year) VALUES (%s, 'Honda', 'Civic', 2020);",
                (customer_id,),
            )

    appointment_id = book_appointment(customer_id, None, first_slot, "Oil Change")
    assert reschedule_appointment(appointment_id, second_slot) is True

    create_agent.assert_not_called()
    create_admin.assert_not_called()
    delete_agent.assert_not_called()

    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                """
                SELECT event_type,
                       payload ->> 'old_booking_time_str' AS old_booking_time,
                       payload ->> 'notification_event' AS notification_event
                FROM outbox_notifications
                WHERE request_id = %s
                ORDER BY id;
                """,
                (appointment_id,),
            )
            events = cursor.fetchall()

    assert [row["event_type"] for row in events] == [
        "calendar_projection", "booking_notification",
        "calendar_projection", "booking_notification",
    ]
    assert events[-2]["old_booking_time"] == first_slot
    assert events[-1]["notification_event"] == "RESCHEDULED"
