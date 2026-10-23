"""Browser actions with durable read-back for the new administration features."""

import json
import re
from contextlib import ExitStack
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import pytest
from playwright.sync_api import Error as PlaywrightError, expect

from e2e.test_notification_workflows import configure_rules, process, signed_callback
from e2e.test_notification_workflows import (
    provider_capture as captured_provider_fixture,
)
from e2e.test_workflows import PORTAL, book, booking_payload, request_by_id

provider_capture = captured_provider_fixture


def open_settings(page, live_server, tab):
    # Deep links avoid overlapping initial dashboard/staff reloads while editing.
    # Navigation clicks are independently exercised in test_portal_workflows.py.
    # Leave the document first: an identical hash can be same-document navigation,
    # and a goto followed immediately by reload can capture an aborted response.
    page.goto("about:blank")
    config_endpoint = "/portal/sms/config" if tab == "sms-config" else "/portal/config"
    with ExitStack() as waits:
        loaded_config = waits.enter_context(page.expect_response(
            lambda response: response.request.method == "GET" and response.url.endswith(config_endpoint)
        ))
        if tab == "staff":
            loaded_staff = waits.enter_context(page.expect_response(
                lambda response: response.request.method == "GET" and response.url.endswith("/portal/agents")
            ))
        page.goto(f"{live_server}/portal/#config/{tab}", wait_until="domcontentloaded")
    assert loaded_config.value.status == 200
    config = loaded_config.value.json()
    expect(page.locator(f'.config-subtab-pane[data-subtab-pane="{tab}"]')).to_be_visible()
    if tab == "staff":
        assert loaded_staff.value.status == 200
        agents = loaded_staff.value.json()
        if agents:
            for agent in agents:
                expect(page.locator(f'#staff-agent-selector option[value="{agent["id"]}"]')).to_contain_text(agent["name"])
        else:
            expect(page.locator("#staff-agent-selector")).to_contain_text("No agents available")
        expect(page.locator("#staff-bhours-start")).to_have_value(str(config.get("business_hours_start", 7)))
        expect(page.locator("#staff-bhours-end")).to_have_value(str(config.get("business_hours_end", 18)))
    elif tab == "business":
        expect(page.locator("#business-timezone")).to_have_value(config["business_timezone"])
    elif tab == "intents":
        expect(page.locator("#prompt-first-message")).to_have_value(config.get("first_message") or "")


def test_settings_reload_reads_updated_staff_with_pending_background_request(
    page, live_server, api
):
    pending = []
    page.route("**/__e2e_noncritical_pending", lambda route: pending.append(route))
    page.add_init_script("""
        document.addEventListener('DOMContentLoaded', () => {
            window.__pendingBackground = fetch('/__e2e_noncritical_pending');
        });
    """)
    page.set_default_timeout(5000)
    try:
        created = api.post(f"{PORTAL}/agents", json={
            "name": "Pending Background Staff", "role": "Technician",
            "email": "pending@example.test", "phone_number": "+15550100099",
        })
        assert created.status_code == 201, created.text
        agent_id = created.json()["id"]
        open_settings(page, live_server, "staff")
        expect(page.locator(f'#staff-agent-selector option[value="{agent_id}"]')).to_contain_text("Pending Background Staff")
        saved = api.put(f"{PORTAL}/agents/{agent_id}", json={"name": "Persisted Despite Pending"})
        assert saved.status_code == 200, saved.text
        assert api.get(f"{PORTAL}/agents/{agent_id}").json()["name"] == "Persisted Despite Pending"
        open_settings(page, live_server, "staff")
        assert pending, "The regression must exercise a noncritical request that remains open"
        expect(page.locator(f'#staff-agent-selector option[value="{agent_id}"]')).to_contain_text("Persisted Despite Pending")
    finally:
        for route in pending:
            try:
                route.abort()
            except PlaywrightError:
                # A full document reload already aborts its preceding fetch.
                pass


def test_browser_create_edit_staff_persists_after_reload(page, live_server, api):
    open_settings(page, live_server, "staff")
    page.locator("#new-agent-name").fill("Casey Browser")
    page.locator("#new-agent-role").fill("Technician")
    page.locator("#new-agent-email").fill("casey@example.test")
    page.locator("#new-agent-phone").fill("+15550100099")
    with page.expect_response(
        lambda r: r.request.method == "POST" and r.url.endswith("/portal/agents")
    ) as created:
        page.locator('#add-agent-form button[type="submit"]').click()
    assert created.value.status == 201
    agent_id = created.value.json()["id"]
    page.locator("#staff-agent-selector").select_option(str(agent_id))
    page.locator("#edit-agent-profile-btn").click()
    expect(page.locator("#edit-agent-name")).to_have_value("Casey Browser")
    page.locator("#edit-agent-name").fill("Casey Updated")
    with page.expect_response(
        lambda r: r.request.method == "PUT" and r.url.endswith(f"/agents/{agent_id}")
    ) as edited:
        page.locator('#edit-agent-form button[type="submit"]').click()
    assert edited.value.status == 200
    assert api.get(f"{PORTAL}/agents/{agent_id}").json()["name"] == "Casey Updated"
    open_settings(page, live_server, "staff")
    expect(
        page.locator(f'#staff-agent-selector option[value="{agent_id}"]')
    ).to_contain_text("Casey Updated (Agent)")


def test_browser_deactivation_preserves_booking_and_exposes_escalation(
    page, live_server, api, db, scenario
):
    request_id = book(api, scenario)
    open_settings(page, live_server, "staff")
    page.locator("#staff-agent-selector").select_option("1")
    page.on("dialog", lambda dialog: dialog.accept())
    with page.expect_response(
        lambda r: r.request.method == "DELETE" and r.url.endswith("/agents/1")
    ) as removed:
        page.locator("#delete-agent-profile-btn").click()
    assert removed.value.status == 200
    assert request_id in removed.value.json()["escalated_service_request_ids"]
    row = request_by_id(api, request_id)
    assert row["escalation_status"] == "escalated"
    assert row["escalation_reason"] == "AGENT_DEACTIVATED"
    assert db("SELECT is_active FROM staff_agents WHERE id=1")[0]["is_active"] is False
    assert db(
        "SELECT id FROM appointment_reservations WHERE service_request_id=%s AND status='ACTIVE'",
        (request_id,),
    )
    open_settings(page, live_server, "staff")
    expect(page.locator('#staff-agent-selector option[value="1"]')).to_have_count(0)
    page.locator('.nav-item[data-tab="dashboard"]').click()
    expect(page.locator("#service-requests-list")).to_contain_text("Alex E2E")


def test_dismissed_staff_delete_keeps_profile(page, live_server, api):
    open_settings(page, live_server, "staff")
    page.locator("#staff-agent-selector").select_option("1")
    page.on("dialog", lambda dialog: dialog.dismiss())
    page.locator("#delete-agent-profile-btn").click()
    assert any(row["id"] == 1 for row in api.get(f"{PORTAL}/agents").json())
    open_settings(page, live_server, "staff")
    expect(page.locator('#staff-agent-selector option[value="1"]')).to_have_count(1)


@pytest.mark.parametrize(
    "timezone", ["America/Chicago", "America/Phoenix", "America/Los_Angeles"]
)
def test_business_timezone_save_controls_runtime_and_survives_reload(
    page, live_server, api, timezone
):
    from serviceBot.services import quiet_hours, timezone_service

    open_settings(page, live_server, "business")
    page.locator("#business-timezone").select_option(timezone)
    page.locator('#business-profile-form button[type="submit"]').click()
    with page.expect_response(
        lambda r: r.request.method == "POST" and r.url.endswith("/portal/config")
    ) as saved:
        page.locator("#business-save-confirm-btn").click()
    assert saved.value.status == 200
    assert api.get(f"{PORTAL}/config").json()["business_timezone"] == timezone
    assert timezone_service.get_business_zoneinfo().key == timezone
    local = datetime(2030, 7, 10, 22, tzinfo=ZoneInfo(timezone))
    assert quiet_hours.is_in_quiet_hours(
        now_dt=local,
        config={
            "quiet_hours_enabled": True,
            "quiet_start_time": "21:00",
            "quiet_end_time": "08:00",
        },
    )
    open_settings(page, live_server, "business")
    expect(page.locator("#business-timezone")).to_have_value(timezone)


def test_browser_business_hours_save_changes_booking_boundary(
    page, live_server, api, scenario
):
    open_settings(page, live_server, "staff")
    page.locator("#staff-bhours-start").fill("8")
    page.locator("#staff-bhours-end").fill("17")
    with page.expect_response(
        lambda r: r.request.method == "POST" and r.url.endswith("/portal/config")
    ) as saved:
        page.locator('#staff-bhours-form button[type="submit"]').click()
    assert saved.value.status == 200
    config = api.get(f"{PORTAL}/config").json()
    assert (config["business_hours_start"], config["business_hours_end"]) == (8, 17)
    rejected = api.post(
        f"{PORTAL}/service-requests",
        json=booking_payload(
            scenario, start=scenario["start"].replace(hour=16, minute=30)
        ),
    )
    assert rejected.status_code == 400
    accepted = api.post(
        f"{PORTAL}/service-requests",
        json=booking_payload(scenario, start=scenario["start"].replace(hour=16)),
    )
    assert accepted.status_code == 201
    open_settings(page, live_server, "staff")
    expect(page.locator("#staff-bhours-start")).to_have_value("8")
    expect(page.locator("#staff-bhours-end")).to_have_value("17")


@pytest.fixture
def elevenlabs_capture(scenario, monkeypatch):
    calls = []
    monkeypatch.setenv("ELEVENLABS_API_KEY", "synthetic-key")
    monkeypatch.setenv("ELEVENLABS_AGENT_ID", "synthetic-agent")
    original = httpx.AsyncClient._send_single_request

    async def capture(self, request):
        if request.url.host == "api.elevenlabs.io" and request.method == "PATCH":
            calls.append(json.loads(request.content))
            return httpx.Response(
                200, json={"agent_id": "synthetic-agent"}, request=request
            )
        return await original(self, request)

    monkeypatch.setattr(httpx.AsyncClient, "_send_single_request", capture)
    return calls


def test_recording_disclosure_greeting_persists_and_syncs_from_browser(
    page, live_server, api, elevenlabs_capture
):
    open_settings(page, live_server, "intents")
    expect(page.locator("#prompt-first-message")).to_have_value(
        re.compile("recorded", re.IGNORECASE)
    )
    greeting = (
        "Hello from E2E Garage. This conversation will be recorded. How can I help?"
    )
    page.locator("#prompt-first-message").fill(greeting)
    with page.expect_response(
        lambda r: r.request.method == "POST" and r.url.endswith("/portal/config")
    ) as saved:
        page.locator("#save-intents-btn").click()
    assert saved.value.status == 200
    assert api.get(f"{PORTAL}/config").json()["first_message"] == greeting
    assert (
        elevenlabs_capture
        and elevenlabs_capture[-1]["conversation_config"]["agent"]["first_message"]
        == greeting
    )
    open_settings(page, live_server, "intents")
    expect(page.locator("#prompt-first-message")).to_have_value(greeting)


def test_failed_greeting_save_keeps_backend_value(page, live_server, api):
    original = api.get(f"{PORTAL}/config").json()["first_message"]
    open_settings(page, live_server, "intents")
    page.locator("#prompt-first-message").fill("Unsaved greeting")
    page.route(
        "**/portal/config",
        lambda route: (
            route.fulfill(status=503, json={"detail": "Synthetic unavailable storage"})
            if route.request.method == "POST"
            else route.continue_()
        ),
    )
    page.locator("#save-intents-btn").click()
    expect(page.locator(".toast").last).to_contain_text("Error saving configuration")
    assert api.get(f"{PORTAL}/config").json()["first_message"] == original
    open_settings(page, live_server, "intents")
    expect(page.locator("#prompt-first-message")).to_have_value(original)


def test_browser_booking_to_captured_delivery_and_visible_log(
    page, live_server, api, scenario, provider_capture
):
    provider_capture.activate()
    configure_rules(api, roles=("customer",))
    page.goto(f"{live_server}/portal/")
    page.locator("#btn-new-request").click()
    for selector, value in (
        ("#sr-cust-name", "Alex Browser"),
        ("#sr-cust-phone", "+15550100001"),
        ("#sr-veh-make", "Toyota"),
        ("#sr-veh-model", "Camry"),
        ("#sr-veh-year", "2020"),
        ("#sr-issue-desc", "Oil filter replacement"),
    ):
        page.locator(selector).fill(value)
    page.locator("#sr-service-type").select_option("Oil Change")
    page.locator("#sr-booking-date").fill(scenario["date"])
    page.locator("#sr-check-slots-btn").click()
    page.locator("#sr-slots-dropdown").select_option(scenario["start"].strftime("%Y-%m-%d %H:%M:%S"))
    page.locator("#sr-save-btn").click()
    with page.expect_response(
        lambda r: (
            r.request.method == "POST" and r.url.endswith("/portal/service-requests")
        )
    ) as created:
        page.locator("#confirm-modal-yes").click()
    assert created.value.status == 201
    request_id = created.value.json()["request_id"]
    assert not provider_capture.calls
    process(api)
    assert len(provider_capture.calls) == 1
    call = provider_capture.calls[0]
    assert "Camry" in call["Body"] and "Oil filter replacement" in call["Body"]
    assert signed_callback(api, call["sid"], "delivered").status_code == 200
    page.reload()
    page.locator(f'.details-sms-log-btn[data-id="{request_id}"]').click()
    page.locator('.details-tab-btn[data-tab="sms"]').click()
    expect(page.locator("#sms-log-drawer")).to_contain_text(
        re.compile("delivered", re.IGNORECASE)
    )
    assert any(
        row["status"] == "DELIVERED"
        for row in api.get(f"{PORTAL}/sms/logs/appointment/{request_id}").json()["logs"]
    )
