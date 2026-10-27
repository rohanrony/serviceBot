"""Manual staff selection through the real portal, HTTP and disposable database."""

import pytest
from playwright.sync_api import expect

from e2e.test_workflows import book, request_by_id

PORTAL = "/api/v1/portal"


def configure_intake(api):
    response = api.post(
        f"{PORTAL}/config",
        json={"business_profile": {"industry": "Consulting", "intake_fields": []}},
    )
    assert response.status_code == 200


def set_manual_selection(api, enabled):
    response = api.post(
        f"{PORTAL}/gmail-config",
        json={
            "gmail_enabled": False,
            "gmail_sender": "",
            "gmail_recipient": "admin@example.test",
            "enable_agent_selection": enabled,
        },
    )
    assert response.status_code == 200, response.text


def open_new_request(page, live_server):
    page.goto(f"{live_server}/portal/#dashboard")
    page.locator("#btn-new-request").click()
    expect(page.locator("#sr-modal")).to_be_visible()
    page.locator("#sr-cust-name").fill("Manual Staff Selection")
    page.locator("#sr-cust-phone").fill("5550100099")
    page.locator("#sr-service-type").select_option("Oil Change")
    page.locator("#sr-issue-desc").fill("Manual selection regression")


def save_request(page):
    page.locator("#sr-save-btn").click()
    with page.expect_response(
        lambda response: response.request.method == "POST"
        and response.url.endswith("/service-requests")
    ) as saved:
        page.locator("#confirm-modal-yes").click()
    assert saved.value.status == 201, saved.value.text()
    expect(page.locator("#sr-modal")).not_to_be_visible()
    return saved.value.json()["request_id"], saved.value.request.post_data_json


@pytest.mark.parametrize("scheduled", [False, True], ids=["unscheduled", "appointment"])
def test_manual_agent_selection_persists_with_and_without_appointment(
    page, live_server, api, db, scenario, scheduled
):
    configure_intake(api)
    set_manual_selection(api, False)
    page.goto(f"{live_server}/portal/#config/gmail")
    page.locator("#enable-agent-selection").check()
    with page.expect_response(
        lambda response: response.request.method == "POST"
        and response.url.endswith("/gmail-config")
    ) as saved_config:
        page.locator('#gmail-config-form button[type="submit"]').click()
    assert saved_config.value.status == 200
    config = api.get(f"{PORTAL}/gmail-config").json()
    assert config["enable_agent_selection"] is True
    page.reload()
    expect(page.locator("#enable-agent-selection")).to_be_checked()

    open_new_request(page, live_server)
    page.locator("#sr-booking-date").fill(scenario["date"])
    with page.expect_response(
        lambda response: "/available-slots?" in response.url
    ) as initial_availability:
        page.locator("#sr-check-slots-btn").click()
    assert initial_availability.value.status == 200
    selector = page.locator("#sr-agent-select")
    expect(selector).to_be_visible()
    expect(selector).to_be_enabled()
    selector.select_option("2")
    expect(page.locator("#sr-slots-dropdown")).to_have_value("")
    expect(page.locator("#sr-slots-dropdown option")).to_have_count(1)
    if scheduled:
        with page.expect_response(
            lambda response: "/available-slots?" in response.url
            and "staff_agent_id=2" in response.url
        ) as availability:
            page.locator("#sr-check-slots-btn").click()
        assert availability.value.status == 200
        chosen = scenario["start"].strftime("%Y-%m-%d %H:%M:%S")
        expect(
            page.locator(f'#sr-slots-dropdown option[value="{chosen}"]')
        ).to_have_count(1)
        page.locator("#sr-slots-dropdown").select_option(chosen)

    # Declining confirmation preserves the selected agent and all durable state.
    before = {
        table: db(f"SELECT * FROM {table} ORDER BY id")
        for table in (
            "customers", "vehicles", "service_request_audit_log",
            "service_requests", "appointment_reservations",
            "outbox_notifications", "mock_calendar_slots",
        )
    }
    page.locator("#sr-save-btn").click()
    page.locator("#confirm-modal-no").click()
    expect(selector).to_have_value("2")
    assert before == {
        table: db(f"SELECT * FROM {table} ORDER BY id") for table in before
    }
    request_id, payload = save_request(page)
    assert payload["service_request"]["staff_agent_id"] == 2
    stored = request_by_id(api, request_id)
    assert stored["staff_agent_id"] == 2
    reservations = db(
        "SELECT staff_agent_id, status FROM appointment_reservations "
        "WHERE service_request_id = %s",
        (request_id,),
    )
    if scheduled:
        assert stored["booking_time"] == chosen
        assert reservations == [{"staff_agent_id": 2, "status": "ACTIVE"}]
    else:
        assert payload["service_request"]["booking_time"] is None
        assert stored["booking_time"] is None
        assert reservations == []
        for table in ("outbox_notifications", "mock_calendar_slots"):
            assert db(f"SELECT * FROM {table} ORDER BY id") == before[table]
    assert (
        db("SELECT * FROM service_requests WHERE id = 1")
        == before["service_requests"]
    )
    page.reload()
    row = page.locator(f'.edit-sr-btn[data-id="{request_id}"]').locator(
        "xpath=ancestor::tr"
    )
    expect(row).to_contain_text("Morgan E2E")


def test_disabled_setting_does_not_reuse_previous_manual_choice(page, live_server, api, db):
    configure_intake(api)
    open_new_request(page, live_server)
    selector = page.locator("#sr-agent-select")
    expect(selector).to_be_visible()
    selector.select_option("2")
    page.locator("#sr-cancel-btn").click()
    set_manual_selection(api, False)
    page.locator("#btn-new-request").click()
    expect(page.locator("#sr-auto-assign-text")).to_be_visible()
    expect(selector).not_to_be_visible()
    expect(selector).to_have_value("")
    page.locator("#sr-cust-name").fill("Automatic Assignment")
    page.locator("#sr-cust-phone").fill("5550100099")
    page.locator("#sr-service-type").select_option("Oil Change")
    page.locator("#sr-issue-desc").fill("No manual assignment")
    request_id, payload = save_request(page)
    assert payload["service_request"]["staff_agent_id"] is None
    assert request_by_id(api, request_id)["staff_agent_id"] is None
    assert db("SELECT id FROM appointment_reservations") == []
    assert db("SELECT id FROM outbox_notifications") == []


def test_edit_availability_uses_saved_agent_after_manual_create_is_cancelled(
    page, live_server, api, scenario
):
    configure_intake(api)
    request_id = book(api, scenario, agent=1)
    open_new_request(page, live_server)
    selector = page.locator("#sr-agent-select")
    expect(selector).to_be_visible()
    selector.select_option("2")
    page.locator("#sr-cancel-btn").click()
    page.locator(f'.edit-sr-btn[data-id="{request_id}"]').click()
    expect(selector).not_to_be_visible()
    with page.expect_response(
        lambda response: "/available-slots?" in response.url
    ) as availability:
        page.locator("#sr-check-slots-btn").click()
    assert "staff_agent_id=1" in availability.value.url
    assert "staff_agent_id=2" not in availability.value.url
    page.locator("#sr-cancel-btn").click()
    assert request_by_id(api, request_id)["staff_agent_id"] == 1
    page.locator("#btn-new-request").click()
    expect(selector).to_be_visible()
    expect(selector).to_be_enabled()
    expect(selector).to_have_value("")


def test_late_manual_selection_config_cannot_expose_selector_in_edit(
    page, live_server, api, scenario
):
    configure_intake(api)
    request_id = book(api, scenario, agent=1)
    page.goto(f"{live_server}/portal/#dashboard")
    expect(page.locator(f'.edit-sr-btn[data-id="{request_id}"]')).to_be_visible()
    held = []
    page.route("**/portal/gmail-config", lambda route: held.append(route))
    with page.expect_request(lambda request: request.url.endswith("/gmail-config")):
        page.locator("#btn-new-request").click()
    page.locator("#sr-cancel-btn").click()
    page.locator(f'.edit-sr-btn[data-id="{request_id}"]').click()
    with page.expect_response(lambda response: response.url.endswith("/gmail-config")) as loaded:
        held[0].fulfill(json={"enable_agent_selection": True})
    loaded.value.finished()
    # Allow the completed response to be applied and rendered, without a timed sleep.
    page.evaluate(
        "() => new Promise(resolve => "
        "requestAnimationFrame(() => requestAnimationFrame(resolve)))"
    )
    expect(page.locator("#sr-agent-select")).not_to_be_visible()
    expect(page.locator("#sr-agent-select")).to_be_disabled()
    with page.expect_response(lambda response: "/available-slots?" in response.url) as available:
        page.locator("#sr-check-slots-btn").click()
    assert "staff_agent_id=1" in available.value.url
    assert request_by_id(api, request_id)["staff_agent_id"] == 1


def test_reopened_request_waits_for_fresh_staff_choices(page, live_server, api):
    configure_intake(api)
    open_new_request(page, live_server)
    selector = page.locator("#sr-agent-select")
    selector.select_option("2")
    page.locator("#sr-cancel-btn").click()
    held = []
    page.route("**/portal/agents", lambda route: held.append(route))
    with page.expect_request(lambda request: request.url.endswith("/agents")):
        page.locator("#btn-new-request").click()
    expect(selector).to_be_disabled()
    expect(selector).to_have_value("")
    expect(selector.locator('option[value="2"]')).to_have_count(0)
    held[0].fulfill(json=[{"id": 1, "name": "Taylor E2E", "role": "Technician"}])
    expect(selector).to_be_enabled()
    expect(selector.locator('option[value="1"]')).to_have_count(1)
    expect(selector.locator('option[value="2"]')).to_have_count(0)
    expect(selector).to_have_value("")
