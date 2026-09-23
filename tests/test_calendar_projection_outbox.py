"""Tests for the asynchronous, idempotent Google Calendar projection."""

import importlib
from unittest.mock import MagicMock, patch

import pytest

from serviceBot.services.outbox_worker import _dispatch_outbox_event


def _payload():
    return {
        "reservation_id": 41,
        "agent_id": 7,
        "old_agent_id": 3,
        "old_booking_time_str": "2026-10-15 09:30:00",
        "calendar_event_id": "servicebot41202610151030",
        "booking_type": "appointment",
        "booking_time_str": "2026-10-15 10:30:00",
        "duration_minutes": 60,
        "details": {
            "customer_name": "Ada Lovelace",
            "service_type": "Oil Change",
            "issue": "Routine service",
        },
    }


@patch("serviceBot.services.outbox_worker._set_calendar_projection_status")
@patch("serviceBot.services.outbox_worker.create_agent_calendar_event", return_value=True)
@patch("serviceBot.services.outbox_worker.delete_agent_calendar_event", return_value=True)
def test_calendar_projection_creates_a_deterministic_provider_event_and_marks_created(
    delete_event, create_event, set_status
):
    _dispatch_outbox_event("calendar_projection", request_id=17, payload=_payload())

    delete_event.assert_called_once_with(3, "2026-10-15 09:30:00", duration_minutes=60)
    create_event.assert_called_once_with(
        agent_id=7,
        customer_name="Ada Lovelace",
        service_type="Oil Change",
        issue_description="Routine service",
        slot_datetime_str="2026-10-15 10:30:00",
        duration_minutes=60,
        booking_type="appointment",
        external_event_id="servicebot41202610151030",
    )
    set_status.assert_called_once_with(17, 41, "CREATED", "servicebot41202610151030")


@patch("serviceBot.services.outbox_worker._set_calendar_projection_status")
@patch("serviceBot.services.outbox_worker.create_agent_calendar_event", return_value=False)
def test_calendar_projection_failure_raises_so_the_outbox_retries(create_event, set_status):
    with pytest.raises(RuntimeError, match="did not confirm"):
        _dispatch_outbox_event("calendar_projection", request_id=17, payload=_payload())

    create_event.assert_called_once()
    set_status.assert_not_called()


def test_google_event_creation_uses_the_requested_id_and_treats_retry_conflict_as_success():
    from serviceBot.services import google_calendar

    google_calendar = importlib.reload(google_calendar)
    with patch.object(
        google_calendar,
        "get_user_google_credentials",
        return_value={
            "access_token": "token",
            "granted_scopes": {"https://www.googleapis.com/auth/calendar.events"},
        },
    ), patch.object(google_calendar, "load_config", return_value={}), patch.object(
        google_calendar.httpx, "post"
    ) as post:
        post.return_value = MagicMock(status_code=409, text="already exists")
        assert google_calendar.create_agent_calendar_event(
            agent_id=7,
            customer_name="Ada",
            service_type="Oil Change",
            issue_description="Routine service",
            slot_datetime_str="2026-10-15 10:30:00",
            external_event_id="servicebot41202610151030",
        ) is True

    assert post.call_args.kwargs["json"]["id"] == "servicebot41202610151030"


def test_legacy_google_availability_fails_closed_on_unknown_provider_state():
    from serviceBot.services import google_calendar

    with patch.object(
        google_calendar,
        "get_user_google_credentials",
        return_value={"access_token": "token", "granted_scopes": set()},
    ):
        assert google_calendar.is_agent_free(7, "2026-10-15 10:30:00") is False

    with patch.object(
        google_calendar,
        "get_user_google_credentials",
        return_value={
            "access_token": "token",
            "granted_scopes": {"https://www.googleapis.com/auth/calendar.events"},
        },
    ), patch.object(google_calendar.httpx, "get", side_effect=RuntimeError("network unavailable")):
        assert google_calendar.is_agent_free(7, "2026-10-15 10:30:00") is False
