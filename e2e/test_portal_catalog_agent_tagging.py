from playwright.sync_api import Page, expect


def test_portal_catalog_agent_tagging_e2e(page: Page, live_server: str, api):
    """
    E2E Test for User Story 1:
    Verifies that the Portal Services Catalog displays Assigned Technicians,
    allows tagging specific staff agents in the Add Service form,
    and reflects the tagged badges upon saving.
    """
    # 1. Fetch available staff agents via API
    agents_res = api.get("/api/v1/portal/staff-agents")
    assert agents_res.status_code == 200, agents_res.text
    staff_agents = agents_res.json()
    assert len(staff_agents) >= 1, "At least one staff agent must exist for E2E tagging test"
    target_agent = staff_agents[0]
    target_agent_id = target_agent["id"]
    target_agent_name = target_agent["name"]

    # 2. Navigate to portal and click Services tab
    page.goto(f"{live_server}/portal/")
    page.locator('.nav-item[data-tab="services"]').click()
    expect(page.locator("#services-view")).to_be_visible()

    # 3. Verify the catalog table renders the 'Assigned Technicians' header
    expect(page.locator("#services-table")).to_be_visible()
    expect(page.locator("#services-table thead")).to_contain_text("Assigned Technicians")

    # 4. Fill Add Service form with an assigned agent
    test_service_name = "E2E Tagged Brake Overhaul"
    page.locator("#new-service-name").fill(test_service_name)
    page.locator("#new-service-desc").fill("Complete hydraulic caliper service with assigned specialist.")
    page.locator("#new-service-price").fill("$250 - $350")
    page.locator("#new-service-duration").fill("90")

    # Wait for the agent checkboxes container to render
    agents_list_container = page.locator("#new-service-agents-list")
    expect(agents_list_container).to_be_visible()

    # Check the checkbox for the target agent
    checkbox = agents_list_container.locator(f'input[type="checkbox"][value="{target_agent_id}"]')
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
    assert target_agent_id in created_payload.get("assigned_agent_ids", [])

    # 6. Verify the new service appears in the catalog table with the assigned agent badge
    page.reload()
    page.locator('.nav-item[data-tab="services"]').click()
    expect(page.locator("#services-view")).to_be_visible()

    services_body = page.locator("#services-list-body")
    expect(services_body).to_contain_text(test_service_name)
    expect(services_body).to_contain_text(target_agent_name)
