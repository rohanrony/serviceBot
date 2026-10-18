"""Tests for the asynchronous, idempotent Google Calendar projection."""

import importlib
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from serviceBot.services.outbox_worker import _dispatch_outbox_event


@pytest.fixture(autouse=True)
def captured_projection_lock(monkeypatch):
    # Provider-boundary unit tests; real row locks/state validation live in E2E.
    cursor = MagicMock()
    @contextmanager
    def locked(*args):
        yield cursor
    monkeypatch.setattr('serviceBot.services.outbox_worker._locked_calendar_projection', locked, raising=False)
    return cursor


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
@patch("serviceBot.services.outbox_worker.delete_agent_calendar_event_by_id", return_value=True, create=True)
def test_calendar_projection_creates_a_deterministic_provider_event_and_marks_created(
    delete_event, create_event, set_status, captured_projection_lock
):
    _dispatch_outbox_event("calendar_projection", request_id=17, payload=_payload())

    delete_event.assert_called_once_with(agent_id=3, event_id="servicebot41202610150930")
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
    set_status.assert_called_once_with(17, 41, "CREATED", "servicebot41202610151030", cursor=captured_projection_lock)


@patch("serviceBot.services.outbox_worker._set_calendar_projection_status")
@patch("serviceBot.services.outbox_worker.create_agent_calendar_event", return_value=False)
@patch("serviceBot.services.outbox_worker.delete_agent_calendar_event_by_id", return_value=True, create=True)
def test_calendar_projection_failure_raises_so_the_outbox_retries(delete_event, create_event, set_status):
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
    ) as post, patch.object(google_calendar.httpx, "patch") as update:
        post.return_value = MagicMock(status_code=409, text="already exists")
        update.return_value = MagicMock(status_code=200)
        assert google_calendar.create_agent_calendar_event(
            agent_id=7,
            customer_name="Ada",
            service_type="Oil Change",
            issue_description="Routine service",
            slot_datetime_str="2026-10-15 10:30:00",
            external_event_id="servicebot41202610151030",
        ) is True

    assert post.call_args.kwargs["json"]["id"] == "servicebot41202610151030"
    assert update.call_args.args[0].endswith("/servicebot41202610151030")
    assert update.call_args.kwargs["json"]["end"] == post.call_args.kwargs["json"]["end"]


@pytest.mark.parametrize("action", ["delete", "upsert"])
@pytest.mark.parametrize("outcome", [False, RuntimeError("provider unavailable")])
def test_calendar_delete_failure_cannot_mark_success_or_create_replacement(action, outcome):
    payload = {**_payload(), "action": action}
    if action == "delete":
        expected_agent, expected_id = 7, payload["calendar_event_id"]
    else:
        payload["old_calendar_event_id"] = "owned-old-event"
        expected_agent, expected_id = 3, "owned-old-event"
    with patch("serviceBot.services.outbox_worker.delete_agent_calendar_event_by_id", create=True) as delete, \
         patch("serviceBot.services.outbox_worker.create_agent_calendar_event") as create, \
         patch("serviceBot.services.outbox_worker._set_calendar_projection_status") as status:
        if isinstance(outcome, Exception):
            delete.side_effect = outcome
        else:
            delete.return_value = outcome
        with pytest.raises(RuntimeError):
            _dispatch_outbox_event("calendar_projection", request_id=17, payload=payload)
        delete.assert_called_once_with(agent_id=expected_agent, event_id=expected_id)
        status.assert_not_called()
        create.assert_not_called()


def test_calendar_delete_uses_only_recorded_event_identity(captured_projection_lock):
    payload = {**_payload(), "action": "delete", "calendar_event_id": "owned-source-event"}
    with patch("serviceBot.services.outbox_worker.delete_agent_calendar_event_by_id", return_value=True, create=True) as delete, \
         patch("serviceBot.services.outbox_worker.delete_agent_calendar_event") as range_delete, \
         patch("serviceBot.services.outbox_worker._set_calendar_projection_status") as status:
        _dispatch_outbox_event("calendar_projection", request_id=17, payload=payload)
        delete.assert_called_once_with(agent_id=7, event_id="owned-source-event")
        range_delete.assert_not_called()
        status.assert_called_once_with(17, 41, "DELETED", "owned-source-event", cursor=captured_projection_lock)


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
