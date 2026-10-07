"""Real OAuth handlers and encrypted persistence; Google HTTP is captured only."""

import time
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from e2e.test_workflows import PORTAL

CALENDAR = "https://www.googleapis.com/auth/calendar.events"
GMAIL = "https://www.googleapis.com/auth/gmail.send"


@pytest.fixture
def google_transport(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "e2e-google-client")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "e2e-google-secret")
    original = httpx.Client._send_single_request
    capture = {
        "calls": [],
        "token": {
            "access_token": "synthetic-access",
            "refresh_token": "synthetic-refresh",
            "expires_in": 3600,
            "scope": f"openid email {CALENDAR} {GMAIL}",
        },
        "status": 200,
    }

    def send(self, request):
        if request.url.host not in {
            "oauth2.googleapis.com",
            "openidconnect.googleapis.com",
        }:
            return original(self, request)
        capture["calls"].append(request)
        if request.url.host == "oauth2.googleapis.com":
            assert request.method == "POST" and request.url.path == "/token"
            return httpx.Response(
                capture["status"], json=capture["token"], request=request
            )
        assert request.method == "GET" and request.url.path == "/v1/userinfo"
        assert request.headers["Authorization"] == "Bearer synthetic-access"
        return httpx.Response(
            200,
            json={
                "sub": "synthetic-google-account",
                "email": "e2e@example.test",
                "name": "Google Display Name",
            },
            request=request,
        )

    monkeypatch.setattr(httpx.Client, "_send_single_request", send)
    return capture


def authorize(api, action="calendar"):
    response = api.get(f"{PORTAL}/agents/1/google/auth-url", params={"action": action})
    assert response.status_code == 200, response.text
    return parse_qs(urlparse(response.json()["auth_url"]).query)["state"][0]


def callback(api, state):
    return api.get(
        f"{PORTAL}/gmail/oauth/callback",
        params={"code": "synthetic-code", "state": state},
    )


@pytest.mark.parametrize(
    "action,title", [("calendar", "Calendar Connected!"), ("gmail", "Gmail Connected!")]
)
def test_oauth_success_encrypts_tokens_and_updates_public_status(
    api, db, google_transport, action, title
):
    from serviceBot.services.encryption import decrypt_key

    state = authorize(api, action)
    response = callback(api, state)
    assert response.status_code == 200 and title in response.text
    row = db("SELECT * FROM user_google_accounts WHERE agent_id=1")[0]
    assert row["access_token"] != "synthetic-access"
    assert decrypt_key(row["access_token"]) == "synthetic-access"
    assert decrypt_key(row["refresh_token"]) == "synthetic-refresh"
    assert row["expires_at"] > time.time()
    assert not db("SELECT state FROM oauth_states WHERE state=%s", (state,))
    status = api.get(f"{PORTAL}/agents/1/google/status").json()
    assert status["is_connected"] is True and status["email"] == "e2e@example.test"
    assert CALENDAR in status["scopes"] and GMAIL in status["scopes"]
    assert "synthetic-access" not in str(status)
    assert db("SELECT name FROM staff_agents WHERE id=1")[0]["name"] == "Taylor E2E"
    form = parse_qs(google_transport["calls"][0].content.decode())
    assert form["grant_type"] == ["authorization_code"]
    assert form["code"] == ["synthetic-code"]
    assert form["client_id"] == ["e2e-google-client"]
    assert form["redirect_uri"][0].endswith(f"{PORTAL}/gmail/oauth/callback")


def test_oauth_state_is_single_use(api, google_transport):
    state = authorize(api)
    assert "Calendar Connected!" in callback(api, state).text
    google_transport["calls"].clear()
    assert "Authentication Failed" in callback(api, state).text
    assert not google_transport["calls"]


@pytest.mark.parametrize(
    "state_kind", ["expired", "unknown", "legacy_agent", "missing"]
)
def test_oauth_rejects_untrusted_state_before_provider_exchange(
    api, db, google_transport, state_kind
):
    state = authorize(api)
    if state_kind == "expired":
        db(
            "UPDATE oauth_states SET created_at=NOW()-INTERVAL '16 minutes' WHERE state=%s",
            (state,),
        )
    elif state_kind == "unknown":
        state = "not-issued-by-server"
    elif state_kind == "legacy_agent":
        state = "agent_1"
    else:
        state = ""
    response = callback(api, state)
    assert response.status_code in {200, 400, 403}
    assert not google_transport["calls"], (
        "Unissued, missing or expired state must not exchange a code"
    )
    assert not db("SELECT agent_id FROM user_google_accounts")


def test_provider_exchange_failure_cannot_mark_agent_connected(
    api, db, google_transport
):
    google_transport.update(status=400, token={"error": "invalid_grant"})
    assert "Token Exchange Failed" in callback(api, authorize(api)).text
    assert not db("SELECT agent_id FROM user_google_accounts")
    assert api.get(f"{PORTAL}/agents/1/google/status").json()["is_connected"] is False


@pytest.mark.parametrize("rotate", [False, True])
def test_expired_access_token_refresh_preserves_or_rotates_refresh_token(
    api, db, google_transport, rotate
):
    from serviceBot.services.encryption import decrypt_key
    from serviceBot.services.google_calendar import get_user_google_credentials

    assert "Calendar Connected!" in callback(api, authorize(api)).text
    db(
        "UPDATE user_google_accounts SET expires_at=%s WHERE agent_id=1",
        (time.time() - 120,),
    )
    google_transport["calls"].clear()
    token = {"access_token": "fresh-access", "expires_in": 3600}
    if rotate:
        token["refresh_token"] = "rotated-refresh"
    google_transport["token"] = token
    credentials = get_user_google_credentials(1)
    expected = "rotated-refresh" if rotate else "synthetic-refresh"
    assert (
        credentials["access_token"] == "fresh-access"
        and credentials["refresh_token"] == expected
    )
    assert CALENDAR in credentials["granted_scopes"]
    row = db("SELECT * FROM user_google_accounts WHERE agent_id=1")[0]
    assert (
        decrypt_key(row["refresh_token"]) == expected
        and decrypt_key(row["access_token"]) == "fresh-access"
    )
    form = parse_qs(google_transport["calls"][0].content.decode())
    assert form["refresh_token"] == ["synthetic-refresh"] and form["grant_type"] == [
        "refresh_token"
    ]
    google_transport["calls"].clear()
    assert get_user_google_credentials(1)["access_token"] == "fresh-access"
    assert not google_transport["calls"], (
        "Unexpired credentials should not refresh again"
    )


def test_revoked_refresh_token_fails_closed_without_overwriting_credentials(
    api, db, google_transport
):
    from serviceBot.services.google_calendar import (
        GoogleAuthException,
        get_user_google_credentials,
    )

    assert "Calendar Connected!" in callback(api, authorize(api)).text
    db("UPDATE user_google_accounts SET expires_at=0 WHERE agent_id=1")
    before = db(
        "SELECT access_token, refresh_token FROM user_google_accounts WHERE agent_id=1"
    )[0]
    google_transport.update(
        status=400,
        token={"error": "invalid_grant", "error_description": "Authorization revoked"},
    )
    with pytest.raises(GoogleAuthException, match="revoked"):
        get_user_google_credentials(1)
    assert (
        db(
            "SELECT access_token, refresh_token FROM user_google_accounts WHERE agent_id=1"
        )[0]
        == before
    )


def test_disconnect_removes_tokens_and_other_staff_is_unchanged(
    api, db, google_transport
):
    from serviceBot.services.google_calendar import (
        GoogleAuthException,
        get_user_google_credentials,
    )

    assert "Calendar Connected!" in callback(api, authorize(api)).text
    other = api.get(f"{PORTAL}/agents/2/google/status").json()
    assert api.post(f"{PORTAL}/agents/1/google/disconnect").json()["success"] is True
    assert not db("SELECT agent_id FROM user_google_accounts WHERE agent_id=1")
    assert api.get(f"{PORTAL}/agents/1/google/status").json()["is_connected"] is False
    assert api.get(f"{PORTAL}/agents/2/google/status").json() == other
    with pytest.raises(GoogleAuthException, match="not connected"):
        get_user_google_credentials(1)
    assert api.post(f"{PORTAL}/agents/999999/google/disconnect").status_code == 404
