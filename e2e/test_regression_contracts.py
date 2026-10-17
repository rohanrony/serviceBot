"""Regression requirements; application fixes are intentionally separate."""

from datetime import timedelta

import pytest

from e2e.test_google_contracts import google_transport as captured_google_fixture
from e2e.test_notification_workflows import configure_rules, process
from e2e.test_notification_workflows import (
    provider_capture as captured_provider_fixture,
)
from e2e.test_workflows import (
    PORTAL,
    book,
    booking_payload,
    edit_payload,
    request_by_id,
)

google_transport = captured_google_fixture
provider_capture = captured_provider_fixture


def test_oauth_omitted_state_never_exchanges_code(api, db, google_transport):
    response = api.get(
        f"{PORTAL}/gmail/oauth/callback", params={"code": "synthetic-code"}
    )
    assert response.status_code in {200, 400, 403}
    assert not google_transport["calls"], (
        "Omitted state must be rejected before contacting Google"
    )
    assert not db("SELECT agent_id FROM user_google_accounts")


@pytest.mark.parametrize("failure", ["unknown", "exception"])
def test_unknown_calendar_cannot_commit_booking(
    api, db, scenario, monkeypatch, failure
):
    from serviceBot.services import google_calendar

    def unavailable(*args, **kwargs):
        if failure == "exception":
            raise RuntimeError("Synthetic calendar unavailable")

    monkeypatch.setattr(google_calendar, "fetch_agent_events", unavailable)
    response = api.post(f"{PORTAL}/service-requests", json=booking_payload(scenario))
    assert response.status_code in {409, 503}, response.text
    assert not db("SELECT id FROM appointment_reservations")
    assert not db("SELECT id FROM outbox_notifications")


def test_distinct_reschedules_each_notify_customer(api, scenario, provider_capture):
    provider_capture.activate()
    configure_rules(api, roles=("customer",))
    request_id = book(api, scenario)
    process(api)
    provider_capture.calls.clear()
    for index in (1, 2):
        start = scenario["start"] + timedelta(hours=index)
        response = api.put(
            f"{PORTAL}/service-requests/{request_id}",
            json=edit_payload(scenario, booking_time=start.isoformat()),
        )
        assert response.status_code == 200, response.text
        process(api)
        assert len(provider_capture.calls) == index, (
            "A distinct committed reschedule is not a retry of the previous event"
        )
        assert (
            request_by_id(api, request_id)["booking_time"]
            .replace("T", " ")
            .startswith(start.strftime("%Y-%m-%d %H:%M"))
        )


def test_disabled_initial_notifications_prevent_dispatch(
    api, scenario, provider_capture
):
    provider_capture.activate()
    configure_rules(api, roles=("customer", "agent"))
    assert (
        api.post(
            f"{PORTAL}/config", json={"initial_notification_enabled": False}
        ).status_code
        == 200
    )
    assert api.get(f"{PORTAL}/config").json()["initial_notification_enabled"] is False
    book(api, scenario)
    process(api)
    assert not provider_capture.calls, (
        "The saved notification switch must affect dispatch"
    )
