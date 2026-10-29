"""Real browser/HTTP settings journeys with isolated Google send effects."""

import base64
import json
import threading
from concurrent.futures import ThreadPoolExecutor
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
    expect(page.locator("#gmail-routine-admin-copies-enabled")).not_to_be_checked()
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
    expect(page.locator("#oauth-help-text")).not_to_be_visible()
    page.locator("#gmail-recipient").fill("new-admin@example.test")
    page.locator("#gmail-enabled").check()
    page.locator("#gmail-routine-admin-copies-enabled").check()
    page.locator("#enable-agent-selection").uncheck()
    with page.expect_response(
        lambda r: r.request.method == "POST" and r.url.endswith("/gmail-config")
    ) as saved:
        page.locator("#save-gmail-btn").click()
    assert saved.value.status == 200
    submitted = saved.value.request.post_data_json
    assert submitted["gmail_auth_type"] == "oauth2"
    assert submitted["gmail_routine_admin_copies_enabled"] is True
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
    expect(page.locator("#gmail-routine-admin-copies-enabled")).to_be_checked()
    expect(page.locator("#enable-agent-selection")).not_to_be_checked()


@pytest.mark.test_layer("browser")
def test_admin_email_save_survives_background_refresh_and_page_reload(
    page, live_server, api, monkeypatch
):
    from serviceBot.api import portal
    from serviceBot.services import gmail
    from serviceBot.services.encryption import decrypt_key, encrypt_key

    config = portal.load_config()
    config.update(
        gmail_enabled=True,
        gmail_recipient="old-admin@example.test",
        gmail_sender="sender@example.test",
        gmail_client_id=encrypt_key("synthetic-client"),
        gmail_client_secret=encrypt_key("synthetic-secret"),
        gmail_refresh_token=encrypt_key("synthetic-refresh"),
        gmail_access_token=encrypt_key("old-access"),
        gmail_token_expires_at=1,
    )
    portal.save_config(config)
    waiting_for_google = threading.Event()
    release_google = threading.Event()
    refresh_requests = []

    def google_response(url, **kwargs):
        assert url == "https://oauth2.googleapis.com/token"
        refresh_requests.append(url)
        waiting_for_google.set()
        assert release_google.wait(timeout=30), "Admin save did not finish"
        return httpx.Response(
            200, json={"access_token": "new-access", "expires_in": 3600}
        )

    monkeypatch.setattr(gmail.httpx, "post", google_response)
    open_mail(page, live_server)
    with ThreadPoolExecutor(max_workers=1) as executor:
        refreshed = executor.submit(gmail.refresh_gmail_token)
        try:
            assert waiting_for_google.wait(timeout=10)
            page.locator("#gmail-recipient").fill("new-admin@example.test")
            with page.expect_response(
                lambda r: r.request.method == "POST"
                and r.url.endswith("/gmail-config")
            ) as saved:
                page.locator("#save-gmail-btn").click()
            assert saved.value.status == 200
            expect(page.locator("#app-toast")).to_contain_text(
                "Gmail configuration saved successfully!"
            )
            assert portal.load_config()["gmail_recipient"] == "new-admin@example.test"
        finally:
            release_google.set()
        assert refreshed.result(timeout=10) == "new-access"

    assert len(refresh_requests) == 1
    stored = portal.load_config()
    assert stored["gmail_recipient"] == "new-admin@example.test"
    assert decrypt_key(stored["gmail_access_token"]) == "new-access"
    assert stored["gmail_refresh_token"] == config["gmail_refresh_token"]

    # Model a Free Render restart restoring the filesystem's old config file.
    reset_config = portal.load_config()
    reset_config["gmail_recipient"] = "old-admin@example.test"
    portal.save_config(reset_config)

    assert api.get(f"{PORTAL}/gmail-config").json()["gmail_recipient"] == (
        "new-admin@example.test"
    )
    open_mail(page, live_server)
    expect(page.locator("#gmail-recipient")).to_have_value("new-admin@example.test")


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
        business_name="Davidson CarCare",
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
        assert mail["From"] == "Davidson CarCare <sender@example.test>"
        assert mail["Subject"] == "[Davidson CarCare] Gmail Integration Test Email"
        html_content = mail.get_body(preferencelist=("html",)).get_content()
        plain_content = mail.get_body(preferencelist=("plain",)).get_content()
        assert "configured correctly" in html_content
        assert "Davidson CarCare" in html_content
        assert "BayFull" not in html_content
        assert "serviceBot" not in html_content
        assert "Davidson CarCare" in plain_content
        assert "BayFull" not in plain_content
        assert "serviceBot" not in plain_content
    else:
        assert not requests
