from playwright.sync_api import Page, expect


def test_service_requests_table_renders_rows(page: Page, live_server: str):
    """Verifies that the dashboard service requests table loads seeded rows and action buttons."""
    page.goto(f"{live_server}/portal/")

    # Wait for the table rows to populate (replacing the loading row)
    rows = page.locator("#service-requests-list tr")
    page.wait_for_function(
        "() => document.querySelectorAll('#service-requests-list tr').length > 0 && "
        "!document.querySelector('#service-requests-list td')?.textContent.includes('Loading')"
    )

    # Must have rows rendered
    count = rows.count()
    assert count > 0, "Expected at least 1 service request row in the table"

    # First row must have status and agent selectors and action buttons
    first_row = rows.first
    expect(first_row.locator(".status-select-badge")).to_be_visible()
    expect(first_row.locator(".agent-select-badge")).to_be_attached()
    expect(first_row.locator(".edit-sr-btn")).to_be_visible()
    expect(first_row.locator(".details-sms-log-btn")).to_be_visible()


def test_details_sms_log_drawer_opens_and_closes(page: Page, live_server: str):
    """Verifies that clicking 'Details' opens the slide-out drawer with appointment details."""
    page.goto(f"{live_server}/portal/")

    # Wait for table ready
    page.wait_for_function(
        "() => document.querySelectorAll('#service-requests-list tr').length > 0 && "
        "!document.querySelector('#service-requests-list td')?.textContent.includes('Loading')"
    )

    # Click Details button on the first row
    first_details_btn = page.locator(
        "#service-requests-list tr .details-sms-log-btn"
    ).first
    first_details_btn.click()

    # Drawer should activate
    drawer = page.locator("#sms-log-drawer")
    expect(drawer).to_have_class("drawer active")
    expect(page.locator("#sms-log-drawer-subtitle")).to_contain_text("Appointment #")

    # Close drawer
    close_btn = page.locator("#close-sms-log-drawer-btn")
    expect(close_btn).to_be_visible()
    close_btn.click()

    expect(drawer).not_to_have_class("drawer active")


def test_edit_sr_modal_opens_and_closes(page: Page, live_server: str):
    """Verifies that clicking 'Edit' opens the SR modal with populated fields and closes cleanly."""
    page.goto(f"{live_server}/portal/")

    page.wait_for_function(
        "() => document.querySelectorAll('#service-requests-list tr').length > 0 && "
        "!document.querySelector('#service-requests-list td')?.textContent.includes('Loading')"
    )

    first_edit_btn = page.locator("#service-requests-list tr .edit-sr-btn").first
    first_edit_btn.click()

    # Modal should be visible
    modal = page.locator("#sr-modal")
    expect(modal).to_be_visible()
    expect(page.locator("#sr-modal-title")).to_contain_text("Edit Service Request")

    # Customer name should be populated and disabled
    cust_name_input = page.locator("#sr-cust-name")
    expect(cust_name_input).to_be_visible()
    expect(cust_name_input).to_be_disabled()

    # Close modal
    close_btn = page.locator("#close-sr-modal-btn")
    close_btn.click()
    expect(modal).not_to_be_visible()


def test_status_change_with_confirmation_dialog(page: Page, live_server: str, api):
    """A successful status PATCH survives a new backend read and page reload."""
    page.goto(f"{live_server}/portal/")

    page.wait_for_function(
        "() => document.querySelectorAll('#service-requests-list tr').length > 0 && "
        "!document.querySelector('#service-requests-list td')?.textContent.includes('Loading')"
    )

    # Accept any browser confirm dialogs
    page.on("dialog", lambda dialog: dialog.accept())

    first_status_select = page.locator(
        "#service-requests-list tr .status-select-badge"
    ).first
    current_status = first_status_select.input_value()

    # Pick a different status to toggle
    target_status = "confirmed" if current_status != "confirmed" else "in_progress"
    with page.expect_response(
        lambda r: (
            r.request.method == "PATCH" and r.url.endswith("/service-requests/1/status")
        )
    ) as saved:
        first_status_select.select_option(value=target_status)
    assert saved.value.status == 200
    assert saved.value.json()["success"] is True
    request = next(
        row
        for row in api.get("/api/v1/portal/service-requests").json()
        if row["id"] == 1
    )
    assert request["status"] == target_status
    page.reload()

    # Wait for the select value to match target_status
    expect(first_status_select).to_have_value(target_status)


def test_filter_service_requests_by_search(page: Page, live_server: str):
    """Verifies that typing into the search filter filters matching requests in the table."""
    page.goto(f"{live_server}/portal/")

    page.wait_for_function(
        "() => document.querySelectorAll('#service-requests-list tr').length > 0 && "
        "!document.querySelector('#service-requests-list td')?.textContent.includes('Loading')"
    )

    search_input = page.locator("#filter-sr-search")
    expect(search_input).to_be_visible()

    # Filter by a string unlikely to exist to verify filtered state
    search_input.fill("NonExistentCustomerNameXYZ999")

    rows = page.locator("#service-requests-list tr")
    expect(rows.first).to_contain_text("No matching service requests")

    # Clear filter to restore rows
    search_input.fill("")
    expect(rows.first).not_to_contain_text("No matching service requests")
