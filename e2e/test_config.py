import re

from playwright.sync_api import Page, expect


def test_notification_matrix_subtab_navigation(page: Page, live_server: str):
    """Verifies navigating to Config -> Notifications Config opens the Notification Matrix."""
    page.goto(f"{live_server}/portal/")

    # 1. Switch to Config tab
    page.locator('.nav-item[data-tab="config"]').click()
    expect(page.locator("#config-view")).to_be_visible()

    # 2. Click Notifications Config ribbon subtab
    page.locator('.config-ribbon-item[data-subtab="sms-config"]').click()
    sms_pane = page.locator("#sms-config-view")
    expect(sms_pane).to_be_visible()

    # 3. Check matrix table exists
    matrix_table = page.locator(".sms-matrix-table")
    expect(matrix_table).to_be_visible()
    expect(page.locator("#sms-matrix-rules-tbody")).to_be_visible()


def test_matrix_channel_switcher(page: Page, live_server: str):
    """Verifies switching between SMS, WhatsApp, and Email channel tabs in the matrix."""
    page.goto(f"{live_server}/portal/")
    page.locator('.nav-item[data-tab="config"]').click()
    page.locator('.config-ribbon-item[data-subtab="sms-config"]').click()

    # Wait for matrix table rows to load
    page.wait_for_selector("#sms-matrix-rules-tbody tr input.sms-matrix-cb")

    # Click WhatsApp button
    whatsapp_btn = page.locator('.matrix-channel-btn[data-channel="WHATSAPP"]')
    whatsapp_btn.click()
    expect(whatsapp_btn).to_have_class(re.compile(r"\bactive\b"))

    # Click Email button
    email_btn = page.locator('.matrix-channel-btn[data-channel="EMAIL"]')
    email_btn.click()
    expect(email_btn).to_have_class(re.compile(r"\bactive\b"))

    # Return to SMS
    sms_btn = page.locator('.matrix-channel-btn[data-channel="SMS"]')
    sms_btn.click()
    expect(sms_btn).to_have_class(re.compile(r"\bactive\b"))


def test_matrix_toggle_checkbox_updates_backend(page: Page, live_server: str, api):
    """Verifies that checking/unchecking a matrix rule updates state and persists."""
    page.goto(f"{live_server}/portal/")
    page.locator('.nav-item[data-tab="config"]').click()
    page.locator('.config-ribbon-item[data-subtab="sms-config"]').click()

    # Wait for checkboxes
    cb = page.locator(
        'input.sms-matrix-cb[data-event="BOOKING"][data-role="admin"]'
    ).first
    expect(cb).to_be_attached()

    initial_checked = cb.is_checked()
    # Toggle it
    with page.expect_response(
        lambda r: r.request.method == "PUT" and r.url.endswith("/sms/matrix-rules")
    ) as saved:
        cb.click()
    assert saved.value.status == 200
    rules = api.get("/api/v1/portal/sms/matrix-rules").json()
    rule = next(
        r
        for r in rules
        if r["event_type"] == "BOOKING"
        and r["recipient_role"] == "admin"
        and r["channel"] == "SMS"
    )
    assert rule["enabled"] is (not initial_checked)
    # Verify toggled state
    expect(cb).to_be_checked(checked=not initial_checked)

    # A fresh load must reconstruct the saved value; fixture teardown owns cleanup.
    page.reload()
    page.locator('.nav-item[data-tab="config"]').click()
    page.locator('.config-ribbon-item[data-subtab="sms-config"]').click()
    expect(cb).to_be_checked(checked=not initial_checked)
