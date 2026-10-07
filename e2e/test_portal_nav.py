import re

from playwright.sync_api import Page, expect


def test_portal_loads_with_default_dashboard(page: Page, live_server: str):
    """Verifies that visiting /portal/ loads successfully into Dashboard Overview."""
    page.goto(f"{live_server}/portal/")

    # Wait for page title and header
    expect(page.locator("#current-view-title")).to_contain_text("Dashboard")

    # Ensure dashboard section is active
    dashboard_view = page.locator("#dashboard-view")
    expect(dashboard_view).to_be_visible()
    expect(dashboard_view).to_have_class("view-section active")

    # Check sidebar presence and active nav
    dashboard_nav = page.locator('.nav-item[data-tab="dashboard"]')
    expect(dashboard_nav).to_have_class("nav-item active")


def test_navigation_switches_all_tabs(page: Page, live_server: str):
    """Verifies that clicking each navigation link switches the active view and updates titles."""
    page.goto(f"{live_server}/portal/")

    tabs = [
        ("sms-inbox", "sms-inbox-view", "SMS"),
        ("services", "services-view", "Services"),
        ("knowledge", "knowledge-view", "Knowledge"),
        ("config", "config-view", "Config"),
        ("dashboard", "dashboard-view", "Dashboard"),
    ]

    for tab_name, view_id, expected_title_keyword in tabs:
        nav_item = page.locator(f'.nav-item[data-tab="{tab_name}"]')
        expect(nav_item).to_be_attached()
        nav_item.click()

        # Target section must become active
        target_view = page.locator(f"#{view_id}")
        expect(target_view).to_be_visible()
        expect(target_view).to_have_class("view-section active")

        # Header title should reflect tab change
        expect(page.locator("#current-view-title")).to_contain_text(
            expected_title_keyword
        )


def test_sidebar_collapse_toggle(page: Page, live_server: str):
    """Verifies that the sidebar collapse toggle button hides and reveals the sidebar."""
    page.goto(f"{live_server}/portal/")

    app_container = page.locator(".app-container")
    collapse_btn = page.locator("#sidebar-collapse-btn")

    expect(collapse_btn).to_be_visible()
    collapse_btn.click()
    expect(app_container).to_have_class(re.compile(r"\bsidebar-hidden\b"))

    # Header sidebar toggle expands it back
    expand_btn = page.locator("#sidebar-toggle-btn")
    expand_btn.click()
    expect(app_container).not_to_have_class(re.compile(r"\bsidebar-hidden\b"))


def test_responsive_mobile_viewport(page: Page, live_server: str):
    """Verifies that on mobile viewport (375x667), layout adapts and sidebar toggle works."""
    page.set_viewport_size({"width": 375, "height": 667})
    page.goto(f"{live_server}/portal/")

    # On mobile, header and title should remain visible
    expect(page.locator("#current-view-title")).to_be_visible()

    # Toggle button in header should be clickable
    toggle_btn = page.locator("#sidebar-toggle-btn")
    expect(toggle_btn).to_be_visible()
    toggle_btn.click()

    # Sidebar should open on mobile
    sidebar = page.locator("#app-sidebar")
    expect(sidebar).to_be_visible()
