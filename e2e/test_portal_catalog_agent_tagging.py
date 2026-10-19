import pytest
from playwright.sync_api import Page, expect

PORTAL = "/api/v1/portal"


def catalog(page, live_server):
    page.goto(f"{live_server}/portal/")
    page.locator('.nav-item[data-tab="services"]').click()
    expect(page.locator("#services-list-body")).to_contain_text("Oil Change")


@pytest.mark.parametrize(
    "agent_ids", [[1], [1, 2], []], ids=["one", "multiple", "clear"]
)
def test_edit_service_tags_survive_backend_read_and_reload(
    page, live_server, api, agent_ids
):
    payload = {
        "name": "Oil Change",
        "description": "Routine",
        "price_range": "$79 - $119",
        "duration_minutes": 60,
        "agent_ids": [2],
    }
    assert api.put(f"{PORTAL}/services/1", json=payload).status_code == 200
    catalog(page, live_server)
    page.locator('.edit-service-btn[data-id="1"]').click()
    for agent_id in (1, 2):
        page.locator(
            f'#edit-service-agents-list input[value="{agent_id}"]'
        ).set_checked(agent_id in agent_ids)
    with page.expect_response(
        lambda r: r.request.method == "PUT" and r.url.endswith("/services/1")
    ) as response:
        page.locator('#edit-service-form button[type="submit"]').click()
    assert response.value.status == 200
    persisted = next(
        row for row in api.get(f"{PORTAL}/services").json() if row["id"] == 1
    )
    assert sorted(persisted["assigned_agent_ids"]) == agent_ids
    page.reload()
    page.locator('.nav-item[data-tab="services"]').click()
    row = page.locator("#services-list-body tr").filter(has_text="Oil Change")
    if not agent_ids:
        expect(row).to_contain_text("Any Available")
    for agent_id, name in ((1, "Taylor E2E"), (2, "Morgan E2E")):
        if agent_id in agent_ids:
            expect(row).to_contain_text(name)
        else:
            expect(row).not_to_contain_text(name)


def test_failed_tag_edit_keeps_saved_tags_and_shows_error(page, live_server, api):
    catalog(page, live_server)
    page.locator('.edit-service-btn[data-id="1"]').click()
    page.locator('#edit-service-agents-list input[value="1"]').check()
    page.route(
        "**/portal/services/1",
        lambda route: (
            route.fulfill(status=503, json={"detail": "Synthetic save failure"})
            if route.request.method == "PUT"
            else route.continue_()
        ),
    )
    page.locator('#edit-service-form button[type="submit"]').click()
    expect(page.locator(".toast").last).to_contain_text("Error updating service")
    assert api.get(f"{PORTAL}/services").json()[0]["assigned_agent_ids"] == []
    page.reload()
    page.locator('.nav-item[data-tab="services"]').click()
    expect(
        page.locator("#services-list-body tr").filter(has_text="Oil Change")
    ).to_contain_text("Any Available")


def test_deactivated_staff_are_absent_from_catalog_tag_controls(page, live_server, api):
    assert api.delete(f"{PORTAL}/agents/2").status_code == 200
    catalog(page, live_server)
    expect(page.locator('#new-service-agents-list input[value="1"]')).to_be_visible()
    expect(page.locator('#new-service-agents-list input[value="2"]')).to_have_count(0)
    page.locator('.edit-service-btn[data-id="1"]').click()
    expect(page.locator('#edit-service-agents-list input[value="2"]')).to_have_count(0)


def test_portal_catalog_agent_tagging_e2e(page: Page, live_server: str, api):
    """
    E2E Test for User Story 1:
    Verifies that the Portal Services Catalog displays Assigned Agents,
    allows tagging specific staff agents in the Add Service form,
    and reflects the tagged badges upon saving.
    """
    # 1. Fetch available staff agents via API
    agents_res = api.get("/api/v1/portal/agents")
    assert agents_res.status_code == 200, agents_res.text
    staff_agents = agents_res.json()
    assert len(staff_agents) >= 1, (
        "At least one staff agent must exist for E2E tagging test"
    )
    target_agent = staff_agents[0]
    target_agent_id = target_agent["id"]
    target_agent_name = target_agent["name"]

    # 2. Navigate to portal and click Services tab
    page.goto(f"{live_server}/portal/")
    page.locator('.nav-item[data-tab="services"]').click()
    expect(page.locator("#services-view")).to_be_visible()

    # 3. Verify the catalog table renders the 'Assigned Agents' header
    expect(page.locator("#services-view table")).to_be_visible()
    expect(page.locator("#services-view table thead")).to_contain_text(
        "Assigned Agents"
    )

    # 4. Fill Add Service form with an assigned agent
    test_service_name = "E2E Tagged Brake Overhaul"
    page.locator("#new-service-name").fill(test_service_name)
    page.locator("#new-service-desc").fill(
        "Complete hydraulic caliper service with assigned specialist."
    )
    page.locator("#new-service-price").fill("$250 - $350")
    page.locator("#new-service-duration").fill("90")

    # Wait for the agent checkboxes container to render
    agents_list_container = page.locator("#new-service-agents-list")
    expect(agents_list_container).to_be_visible()

    # Check the checkbox for the target agent
    checkbox = agents_list_container.locator(
        f'input[type="checkbox"][value="{target_agent_id}"]'
    )
    expect(checkbox).to_be_visible()
    checkbox.check()
    assert checkbox.is_checked()

    # 5. Submit form and verify 201 response
    with page.expect_response(
        lambda r: r.request.method == "POST" and r.url.endswith("/portal/services")
    ) as saved_resp:
        page.locator('#add-service-form button[type="submit"]').click()

    assert saved_resp.value.status == 201
    created_payload = saved_resp.value.json()
    assert created_payload["name"] == test_service_name
    persisted = next(
        service
        for service in api.get("/api/v1/portal/services").json()
        if service["id"] == created_payload["id"]
    )
    assert persisted["assigned_agent_ids"] == [target_agent_id]

    # 6. Verify the new service appears in the catalog table with the assigned agent badge
    page.reload()
    page.locator('.nav-item[data-tab="services"]').click()
    expect(page.locator("#services-view")).to_be_visible()

    services_body = page.locator("#services-list-body")
    expect(services_body).to_contain_text(test_service_name)
    expect(
        services_body.locator("tr").filter(has_text=test_service_name)
    ).to_contain_text(target_agent_name)
