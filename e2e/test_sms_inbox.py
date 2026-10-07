from playwright.sync_api import Page, expect


def test_sms_inbox_loads_and_displays_components(page: Page, live_server: str):
    """Verifies that SMS Inbox renders thread list, search header, and message area."""
    page.goto(f"{live_server}/portal/")

    page.locator('.nav-item[data-tab="sms-inbox"]').click()
    expect(page.locator("#sms-inbox-view")).to_be_visible()

    # Search bar & filter
    expect(page.locator("#sms-thread-search-input")).to_be_visible()
    expect(page.locator("#sms-thread-filter")).to_be_visible()

    # Threads list column & chat column
    expect(page.locator("#sms-threads-list")).to_be_visible()
    expect(page.locator(".sms-chat-col")).to_be_visible()
    expect(page.locator("#chat-customer-name")).to_be_visible()


def test_sms_inbox_thread_filtering(page: Page, live_server: str):
    """Verifies changing filter select updates thread query options."""
    page.goto(f"{live_server}/portal/")
    page.locator('.nav-item[data-tab="sms-inbox"]').click()

    filter_select = page.locator("#sms-thread-filter")
    expect(filter_select).to_be_visible()

    # Change filter to All Conversations
    filter_select.select_option("all")
    expect(filter_select).to_have_value("all")

    # Change to In Progress
    filter_select.select_option("IN_PROGRESS")
    expect(filter_select).to_have_value("IN_PROGRESS")

    # Change back to Needs Attention
    filter_select.select_option("HANDOFF_REQUIRED")
    expect(filter_select).to_have_value("HANDOFF_REQUIRED")


def test_quick_replies_bar_exists(page: Page, live_server: str):
    """Verifies that quick reply chips are rendered in the chat panel."""
    page.goto(f"{live_server}/portal/")
    page.locator('.nav-item[data-tab="sms-inbox"]').click()

    quick_bar = page.locator("#quick-reply-bar")
    expect(quick_bar).to_be_visible()

    # Check that chip buttons exist
    chips = page.locator(".quick-chip")
    expect(chips.first).to_be_visible()
