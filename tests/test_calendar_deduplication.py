import pytest
from unittest.mock import patch, MagicMock
from serviceBot.services.gmail import delete_admin_calendar_event
from serviceBot.services.outbox_worker import _dispatch_outbox_event
from serviceBot.db.queries import reschedule_appointment


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


@patch("serviceBot.db.queries.get_service_required_fields")
@patch("serviceBot.db.queries.get_db_connection")
@patch("serviceBot.services.google_calendar.delete_agent_calendar_event")
@patch("serviceBot.services.gmail.delete_admin_calendar_event")
@patch("serviceBot.services.google_calendar.create_agent_calendar_event")
@patch("serviceBot.services.gmail.create_admin_calendar_event")
@patch("serviceBot.services.google_calendar.is_agent_free")
def test_reschedule_appointment_cleans_up_old_events(
    mock_free,
    mock_create_admin,
    mock_create_agent,
    mock_delete_admin,
    mock_delete_agent,
    mock_db_conn,
    mock_req_fields
):
    """Verify reschedule_appointment deletes old slot events for agent & admin before booking new slot."""
    mock_free.return_value = True
    mock_req_fields.return_value = {"duration_minutes": 60}

    # Setup DB cursor mocks
    mock_cursor = MagicMock()
    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_db_conn.return_value = mock_conn

    # Sequence of cursor.fetchone calls:
    # 1. Fetch old appointment row
    # 2. Fetch customer name
    # 3. Fetch issue description
    # 4. Fetch staff agent name
    mock_cursor.fetchone.side_effect = [
        {"booking_time": "2026-08-10 10:00:00", "staff_agent_id": 888, "service_type": "Oil Change", "customer_id": 888},
        {"name": "Reschedule Customer"},
        {"issue_description": "Routine Oil Change"},
        {"name": "Tech 888"}
    ]
    mock_cursor.fetchall.return_value = [
        {"id": 1, "slot_datetime": "2026-08-11 14:00:00", "staff_agent_id": 888, "is_booked": False}
    ]

    with patch("serviceBot.db.queries.dict_cursor") as mock_dict_cursor:
        mock_dict_cursor.return_value.__enter__.return_value = mock_cursor
        result = reschedule_appointment(888, "2026-08-11 14:00:00")

    assert result is True

    # Verify old event deletion was called for 2026-08-10 10:00:00
    mock_delete_agent.assert_called_once_with(888, "2026-08-10 10:00:00", duration_minutes=60)
    mock_delete_admin.assert_called_once_with("2026-08-10 10:00:00", duration_minutes=60)

    # Verify new event creation was called for 2026-08-11 14:00:00
    assert mock_create_agent.called
    assert mock_create_admin.called
