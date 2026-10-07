from playwright.sync_api import Page, expect


def test_services_catalog_renders(page: Page, live_server: str):
    """Verifies that visiting Services tab renders the services catalog table."""
    page.goto(f"{live_server}/portal/")

    page.locator('.nav-item[data-tab="services"]').click()
    expect(page.locator("#services-view")).to_be_visible()

    # Table body should exist
    services_body = page.locator("#services-list-body")
    expect(services_body).to_be_visible()


def test_add_new_service_flow(page: Page, live_server: str, api):
    """Verifies creating a new service item via the Add Service form."""
    page.goto(f"{live_server}/portal/")
    page.locator('.nav-item[data-tab="services"]').click()

    test_service_name = "E2E Synthetic Service"

    # Fill Add Service form
    page.locator("#new-service-name").fill(test_service_name)
    page.locator("#new-service-desc").fill(
        "Automated end-to-end synthetic service validation."
    )
    page.locator("#new-service-price").fill("$99 - $149")
    page.locator("#new-service-duration").fill("45")

    # Submit form
    with page.expect_response(
        lambda r: r.request.method == "POST" and r.url.endswith("/portal/services")
    ) as saved:
        page.locator('#add-service-form button[type="submit"]').click()
    assert saved.value.status == 201
    services = api.get("/api/v1/portal/services").json()
    created = next(s for s in services if s["name"] == test_service_name)
    assert created["duration_minutes"] == 45
    assert created["price_range"] == "$99 - $149"
    page.reload()
    page.locator('.nav-item[data-tab="services"]').click()

    # Verify the new service appears in the catalog table
    expect(page.locator("#services-list-body")).to_contain_text(test_service_name)
