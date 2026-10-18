"""Portal gear icons must parse and render without SVG path errors."""

from playwright.sync_api import expect


def test_portal_configuration_gear_paths_render_without_parse_errors(page, live_server):
    svg_errors = []

    def capture_console(message):
        text = message.text
        if message.type == "error" and ("<path>" in text or "SVG" in text):
            svg_errors.append(text)

    page.on("console", capture_console)
    page.goto(f"{live_server}/portal/", wait_until="networkidle")
    config = page.locator('a[data-tab="config"]')
    expect(config.locator("svg")).to_be_visible()
    config.click()
    notifications = page.locator('button[data-subtab="sms-config"]')
    expect(notifications.locator("svg")).to_be_visible()
    assert svg_errors == [], svg_errors
    for icon in (config, notifications):
        assert icon.locator("path").evaluate("path => path.getTotalLength()") > 0
