"""Offline provider contracts for durable calendar projection identity."""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from serviceBot.services import google_calendar
from serviceBot.services.google_calendar import create_agent_calendar_event


@pytest.fixture
def provider():
    with patch.object(google_calendar, "get_user_google_credentials", return_value={
        "access_token": "synthetic-provider-token",
        "granted_scopes": {"https://www.googleapis.com/auth/calendar.events"},
    }) as credentials, patch.object(google_calendar, "load_config", return_value={}):
        yield credentials


@pytest.mark.parametrize("patch_status, expected", [(200, True), (201, True), (403, False), (500, False)])
def test_existing_projection_receives_current_fields(provider, patch_status, expected):
    with patch.object(google_calendar.httpx, "post", return_value=MagicMock(status_code=409)), \
         patch.object(google_calendar.httpx, "patch", return_value=MagicMock(status_code=patch_status)) as update:
        result = create_agent_calendar_event(
            7, "Customer", "Combined inspection", "New additional issue",
            "2026-06-25 10:00:00", duration_minutes=90, external_event_id="durableevent123",
        )

    assert result is expected
    update.assert_called_once()
    assert update.call_args.args[0] == "https://www.googleapis.com/calendar/v3/calendars/primary/events/durableevent123"
    payload = update.call_args.kwargs["json"]
    assert payload["end"]["dateTime"] == "2026-06-25T11:30:00-04:00"
    assert "New additional issue" in payload["description"]
    assert "Combined inspection" in payload["description"]
    assert update.call_args.kwargs["params"] == {"sendUpdates": "all"}


def test_existing_projection_patch_transport_failure_is_not_success(provider):
    with patch.object(google_calendar.httpx, "post", return_value=MagicMock(status_code=409)), \
         patch.object(google_calendar.httpx, "patch", side_effect=httpx.ConnectError("offline failure")):
        assert create_agent_calendar_event(
            7, "Customer", "Inspection", "Issue", "2026-06-25 10:00:00",
            external_event_id="durableevent123",
        ) is False


@pytest.mark.parametrize("status, expected", [(200, True), (204, True), (404, True), (410, True), (403, False), (500, False)])
def test_delete_projection_uses_only_exact_durable_identity(provider, status, expected):
    with patch.object(google_calendar.httpx, "delete", return_value=MagicMock(status_code=status)) as delete, \
         patch.object(google_calendar, "fetch_agent_events") as scan:
        assert google_calendar.delete_agent_calendar_event_by_id(7, "durableevent123") is expected
    delete.assert_called_once_with(
        "https://www.googleapis.com/calendar/v3/calendars/primary/events/durableevent123",
        headers={"Authorization": "Bearer synthetic-provider-token", "Content-Type": "application/json"},
        timeout=10.0,
    )
    scan.assert_not_called()


@pytest.mark.parametrize("event_id", [None, ""])
def test_delete_projection_requires_identity_before_provider_access(provider, event_id):
    with patch.object(google_calendar.httpx, "delete") as delete:
        assert google_calendar.delete_agent_calendar_event_by_id(7, event_id) is False
    provider.assert_not_called()
    delete.assert_not_called()


def test_delete_projection_requires_write_scope(provider):
    provider.return_value["granted_scopes"] = {"https://www.googleapis.com/auth/calendar.readonly"}
    with patch.object(google_calendar.httpx, "delete") as delete:
        assert google_calendar.delete_agent_calendar_event_by_id(7, "durableevent123") is False
    delete.assert_not_called()


@pytest.mark.parametrize("failure", ["credentials", "delete"])
def test_delete_projection_provider_failure_is_retryable(provider, failure):
    if failure == "credentials":
        provider.side_effect = google_calendar.GoogleAuthException("disconnected")
    with patch.object(google_calendar.httpx, "delete", side_effect=httpx.ConnectError("offline failure")):
        assert google_calendar.delete_agent_calendar_event_by_id(7, "durableevent123") is False
