"""Admin email saves survive an overlapping Google token refresh."""

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from serviceBot.api import portal
from serviceBot.main import app
from serviceBot.services import gmail
from serviceBot.services.encryption import decrypt_key, encrypt_key


@pytest.mark.test_layer("http")
@pytest.mark.parametrize("google_status", [200, 403])
def test_admin_email_save_survives_token_refresh(monkeypatch, tmp_path, google_status):
    monkeypatch.setattr(portal, "CONFIG_PATH", str(tmp_path / "config.json"))
    monkeypatch.setattr(portal, "SYSTEM_PROMPT_PATH", str(tmp_path / "system_prompt.txt"))
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
    client = TestClient(app)

    def google_response(url, **kwargs):
        assert url == "https://oauth2.googleapis.com/token"
        assert kwargs["data"] == {
            "client_id": "synthetic-client",
            "client_secret": "synthetic-secret",
            "refresh_token": "synthetic-refresh",
            "grant_type": "refresh_token",
        }
        # A successful admin save occurs after refresh took its snapshot but
        # before Google responds. No threads or timing sleeps are necessary.
        response = client.post(
            "/api/v1/portal/gmail-config",
            json={
                "gmail_enabled": True,
                "gmail_sender": "sender@example.test",
                "gmail_recipient": "new-admin@example.test",
                "gmail_routine_admin_copies_enabled": True,
            },
        )
        assert response.status_code == 200
        assert portal.load_config()["gmail_recipient"] == "new-admin@example.test"
        return httpx.Response(
            google_status,
            json={"access_token": "new-access", "expires_in": 3600}
            if google_status == 200
            else {"error": "invalid_grant"},
        )

    monkeypatch.setattr(gmail.httpx, "post", google_response)
    token = gmail.refresh_gmail_token()

    with open(portal.CONFIG_PATH, encoding="utf-8") as saved_file:
        stored = json.load(saved_file)
    fresh = client.get("/api/v1/portal/gmail-config")
    assert fresh.status_code == 200
    assert fresh.json()["gmail_recipient"] == "new-admin@example.test"
    assert stored["gmail_recipient"] == "new-admin@example.test"
    assert stored["gmail_routine_admin_copies_enabled"] is True
    assert stored["gmail_refresh_token"] == config["gmail_refresh_token"]
    assert stored["business_timezone"] == config["business_timezone"]
    if google_status == 200:
        assert token == "new-access"
        assert decrypt_key(stored["gmail_access_token"]) == "new-access"
        assert stored["gmail_token_expires_at"] > 1
    else:
        assert token is None
        assert stored["gmail_access_token"] == config["gmail_access_token"]
        assert stored["gmail_token_expires_at"] == 1
