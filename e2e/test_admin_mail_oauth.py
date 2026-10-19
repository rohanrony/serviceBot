"""Real browser/HTTP settings journeys with isolated Google send effects."""

import base64
import json
from email import message_from_bytes, policy

import httpx
import pytest
from playwright.sync_api import expect

PORTAL = "/api/v1/portal"


def open_mail(page, live_server):
    page.goto(f"{live_server}/portal/")
    page.locator('.nav-item[data-tab="config"]').click()
    with page.expect_response(lambda r: r.url.endswith("/gmail-config")):
        page.locator('.config-ribbon-item[data-subtab="gmail"]').click()


def test_legacy_settings_render_google_only_and_save_after_reload(
    page, live_server, api
):
    from serviceBot.api import portal

    config = portal.load_config()
    config.update(
        gmail_auth_type="app_password",
        gmail_password="old-password",
        gmail_smtp_server="smtp.example.test",
        gmail_smtp_port=587,
    )
    portal.save_config(config)
    open_mail(page, live_server)
    for selector in (
        "#gmail-auth-type",
        "#gmail-password",
        "#gmail-smtp-server",
        "#gmail-smtp-port",
        "#smtp-help-text",
    ):
        expect(page.locator(selector)).to_have_count(0)
    expect(page.locator("#gmail-oauth-status-badge")).to_have_text("Disconnected")
    expect(page.locator("#connect-gmail-btn")).to_be_visible()
    expect(page.locator("#oauth-help-text")).to_be_visible()
    page.locator("#gmail-recipient").fill("new-admin@example.test")
    page.locator("#gmail-enabled").check()
    page.locator("#enable-agent-selection").uncheck()
    with page.expect_response(
        lambda r: r.request.method == "POST" and r.url.endswith("/gmail-config")
    ) as saved:
        page.locator("#save-gmail-btn").click()
    assert saved.value.status == 200
    submitted = saved.value.request.post_data_json
    assert submitted["gmail_auth_type"] == "oauth2"
    assert (
        not {"gmail_password", "gmail_smtp_server", "gmail_smtp_port"}
        & submitted.keys()
    )
    stored = portal.load_config()
    assert (
        not {"gmail_password", "gmail_smtp_server", "gmail_smtp_port"} & stored.keys()
    )
    assert api.get(f"{PORTAL}/gmail-config").json()["gmail_auth_type"] == "oauth2"
    open_mail(page, live_server)
    expect(page.locator("#gmail-recipient")).to_have_value("new-admin@example.test")
    expect(page.locator("#gmail-enabled")).to_be_checked()
    expect(page.locator("#enable-agent-selection")).not_to_be_checked()


@pytest.mark.parametrize(
    "connected,result,status,message",
    [
        (True, True, 200, "Test email sent successfully!"),
        (True, False, 500, "Connection Test Failed:"),
        (False, True, 400, "Connect Gmail Account"),
    ],
)
def test_google_connection_status_and_truthful_test_result(
    page, live_server, monkeypatch, connected, result, status, message
):
    from serviceBot.api import portal
    from serviceBot.services.encryption import encrypt_key

    config = portal.load_config()
    config.update(
        gmail_sender="sender@example.test",
        gmail_recipient="admin@example.test",
        gmail_refresh_token=encrypt_key("isolated-refresh") if connected else "",
        gmail_access_token=encrypt_key("browser-access"),
        gmail_token_expires_at=4102444800,
    )
    portal.save_config(config)
    transport = httpx.Client._send_single_request
    requests = []

    def google_transport(self, request):
        if request.url.host != "gmail.googleapis.com":
            return transport(self, request)
        requests.append(request)
        return httpx.Response(
            200 if result else 403,
            json={"id": "accepted-test-message"}
            if result
            else {"error": "permission denied"},
            request=request,
        )

    monkeypatch.setattr(httpx.Client, "_send_single_request", google_transport)
    open_mail(page, live_server)
    expect(page.locator("#gmail-oauth-status-badge")).to_have_text(
        "Connected" if connected else "Disconnected"
    )
    with page.expect_response(lambda r: r.url.endswith("/gmail-config/test")) as tested:
        page.locator("#test-gmail-btn").click()
    assert tested.value.status == status
    expect(page.locator("#app-toast")).to_contain_text(message)
    expect(page.locator("#test-gmail-btn")).to_be_enabled()
    if connected:
        assert len(requests) == 1
        request = requests[0]
        assert request.method == "POST"
        assert request.url.path == "/gmail/v1/users/me/messages/send"
        assert request.headers["Authorization"] == "Bearer browser-access"
        raw = json.loads(request.content)["raw"]
        mail = message_from_bytes(base64.urlsafe_b64decode(raw), policy=policy.default)
        assert mail["To"] == "admin@example.test"
        assert "sender@example.test" in mail["From"]
        assert "Gmail Integration Test Email" in mail["Subject"]
        assert (
            "configured correctly"
            in mail.get_body(preferencelist=("html",)).get_content()
        )
    else:
        assert not requests
