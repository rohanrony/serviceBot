"""Offline HTTP and operator contracts for the single-admin auth feature."""

import os
import hashlib
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event, Lock
import subprocess
import sys
import warnings
from pathlib import Path
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient


EMAIL = " Admin.Auth@Example.Test "
PASSWORD = "synthetic-admin-password"
ORIGIN = "http://testserver"


def test_render_runtime_keeps_proxy_allowlist_platform_managed():
    root = Path(__file__).resolve().parents[1]
    content = (root / "render.yaml").read_text(encoding="utf-8")
    assert "env: python" in content
    assert "startCommand: uvicorn serviceBot.main:app" in content
    # Render's Python runtime owns FORWARDED_ALLOW_IPS; do not pin an app-level
    # wildcard or manually parse forwarded headers inside the service.
    assert "key: FORWARDED_ALLOW_IPS" not in content


def test_https_asgi_scheme_sets_secure_session_cookie(auth_client, admin_credentials):
    from serviceBot.main import app
    from fastapi.testclient import TestClient

    client = TestClient(app, base_url="https://testserver", client=("198.51.100.1", 1234))
    response = client.post(
        "/api/v1/auth/login",
        json={"email": EMAIL, "password": PASSWORD},
        headers={"Origin": "https://testserver"},
    )
    assert response.status_code == 200
    assert "; secure" in response.headers["set-cookie"].lower()


def test_raw_forwarded_headers_do_not_override_asgi_scheme(auth_client, admin_credentials):
    response = auth_client.post(
        "/api/v1/auth/login",
        json={"email": EMAIL, "password": PASSWORD},
        headers={
            "Origin": ORIGIN,
            "X-Forwarded-Proto": "https",
            "X-Forwarded-For": "198.51.100.25",
        },
    )
    assert response.status_code == 200
    assert "; secure" not in response.headers["set-cookie"].lower()


def test_login_throttle_isolated_by_asgi_client_ip(admin_credentials):
    from serviceBot.main import app

    first_ip = TestClient(app, client=("198.51.100.10", 1234))
    second_ip = TestClient(app, client=("198.51.100.11", 1234))
    for _ in range(5):
        failed = first_ip.post(
            "/api/v1/auth/login",
            json={"email": EMAIL, "password": "incorrect synthetic"},
            headers={"Origin": ORIGIN},
        )
        assert failed.status_code == 401
    throttled = first_ip.post(
        "/api/v1/auth/login",
        json={"email": EMAIL, "password": PASSWORD},
        headers={"Origin": ORIGIN},
    )
    allowed = second_ip.post(
        "/api/v1/auth/login",
        json={"email": EMAIL, "password": PASSWORD},
        headers={"Origin": ORIGIN},
    )
    assert throttled.status_code == 401 and allowed.status_code == 200


def test_password_verification_work_is_bounded_per_process(admin_credentials, monkeypatch):
    from serviceBot.main import app
    from serviceBot.services import admin_auth

    lock = Lock()
    max_verifiers_entered = Event()
    all_acquisitions_attempted = Event()
    release_verification = Event()
    start_requests = Barrier(17)
    active = 0
    maximum = 0
    acquisition_attempts = 0
    real_limiter = admin_auth._HASH_WORK

    class InstrumentedLimiter:
        def __enter__(self):
            nonlocal acquisition_attempts
            with lock:
                acquisition_attempts += 1
                if acquisition_attempts == 16:
                    all_acquisitions_attempted.set()
            real_limiter.acquire()
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            real_limiter.release()

    monkeypatch.setattr(admin_auth, "_HASH_WORK", InstrumentedLimiter())
    original_hasher = admin_auth._HASHER

    def delayed_verify(encoded_hash, password):
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
            if active == admin_auth.MAX_PASSWORD_WORKERS:
                max_verifiers_entered.set()
        assert release_verification.wait(timeout=10), "verification gate was not released"
        with lock:
            active -= 1
        return original_hasher.verify(encoded_hash, password)

    class InstrumentedHasher:
        def verify(self, encoded_hash, password):
            return delayed_verify(encoded_hash, password)

        def __getattr__(self, name):
            return getattr(original_hasher, name)

    monkeypatch.setattr(admin_auth, "_HASHER", InstrumentedHasher())

    def attempt(index):
        client = TestClient(app, client=(f"198.51.100.{index + 1}", 1234))
        start_requests.wait(timeout=10)
        return client.post(
            "/api/v1/auth/login",
            json={"email": EMAIL, "password": "incorrect synthetic"},
            headers={"Origin": ORIGIN},
        ).status_code

    with ThreadPoolExecutor(max_workers=16) as pool:
        futures = [pool.submit(attempt, index) for index in range(16)]
        start_requests.wait(timeout=10)
        assert max_verifiers_entered.wait(timeout=10)
        assert all_acquisitions_attempted.wait(timeout=10), "not all requests attempted password verification"
        assert maximum == admin_auth.MAX_PASSWORD_WORKERS
        assert maximum < 16
        release_verification.set()
        statuses = [future.result(timeout=20) for future in futures]
    assert statuses == [401] * 16


@pytest.fixture
def auth_client():
    from serviceBot.main import app

    # Auth boundary cases must exercise the real dependency, unlike legacy tests.
    app.dependency_overrides.clear()
    with TestClient(app, client=("198.51.100.1", 1234)) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture
def admin_credentials():
    """Provision only through the documented hidden-prompt operator command."""
    env = os.environ.copy()
    env["PYTHON_DOTENV_DISABLED"] = "1"
    env["TEST_DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
    env["DATABASE_URL"] = os.environ["DATABASE_URL"]
    from serviceBot.db.connection import get_db_connection

    with get_db_connection() as conn, conn.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM public.admin_accounts")
        assert cursor.fetchone()[0] == 0, "auth cleanup must run before provisioning"

    from tests.admin_cli import run_admin_cli
    result = run_admin_cli("create-admin", [EMAIL, PASSWORD, PASSWORD], env)
    assert result.returncode == 0, result.stderr
    assert PASSWORD not in result.stdout + result.stderr
    return {"email": EMAIL.strip().casefold(), "password": PASSWORD}


def test_login_normalizes_email_creates_opaque_secure_session_and_no_store(auth_client, admin_credentials):
    response = auth_client.post(
        "/api/v1/auth/login",
        json={"email": EMAIL, "password": PASSWORD},
        headers={"Origin": ORIGIN},
    )
    assert response.status_code == 200
    assert response.json()["email"] == admin_credentials["email"]
    assert response.json()["csrf_token"]
    assert "no-store" in response.headers["cache-control"].lower()
    cookie = response.cookies.get("admin_session")
    assert cookie and PASSWORD not in cookie
    set_cookie = response.headers["set-cookie"].lower()
    assert "httponly" in set_cookie and "samesite=lax" in set_cookie
    assert "path=/" in set_cookie and "max-age=28800" in set_cookie
    assert auth_client.get("/api/v1/auth/session").status_code == 200
    dashboard = auth_client.get("/portal/", follow_redirects=False)
    assert dashboard.status_code == 200
    assert "no-store" in dashboard.headers["cache-control"].lower()
    from serviceBot.db.connection import get_db_connection
    with get_db_connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            "SELECT token_hash, created_at, expires_at FROM public.admin_sessions WHERE token_hash=%s",
            (hashlib.sha256(cookie.encode()).hexdigest(),),
        )
        session = cursor.fetchone()
    assert session is not None and session[0] != cookie
    assert session[2] - session[1] == timedelta(hours=8)


def test_cli_creates_first_admin_normalized_and_persists_argon2id_only(admin_credentials):
    from serviceBot.db.connection import get_db_connection

    with get_db_connection() as conn, conn.cursor() as cursor:
        cursor.execute("SELECT email, password_hash FROM public.admin_accounts")
        rows = cursor.fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "admin.auth@example.test"
    assert rows[0][1].startswith("$argon2id$")
    assert PASSWORD not in repr(rows)


def test_cli_fails_closed_without_secure_tty():
    env = os.environ.copy()
    env["PYTHON_DOTENV_DISABLED"] = "1"
    result = subprocess.run(
        [sys.executable, "-m", "serviceBot.auth_admin", "reset-password"],
        input="",
        text=True,
        capture_output=True,
        env=env,
        timeout=10,
    )
    assert result.returncode != 0
    assert "Admin credential operation failed." in result.stderr
    assert "Can not control echo" not in result.stderr
    assert PASSWORD not in result.stdout + result.stderr


def test_cli_getpass_warning_fails_closed_without_revealing_input(monkeypatch, capsys):
    import serviceBot.auth_admin as auth_admin

    def visible_fallback(_prompt):
        warnings.warn("terminal echo cannot be disabled", getpass_warning_type())
        return PASSWORD

    def getpass_warning_type():
        import getpass

        return getpass.GetPassWarning

    monkeypatch.setattr(auth_admin.getpass, "getpass", visible_fallback)
    assert auth_admin.main(["reset-password"]) != 0
    output = capsys.readouterr()
    assert "Admin credential operation failed." in output.err
    assert "terminal echo cannot be disabled" not in output.err
    assert PASSWORD not in output.out + output.err


def test_password_hashing_uses_argon2id_and_enforces_minimum_length():
    from serviceBot.services.admin_auth import hash_password, normalize_email, verify_password

    encoded = hash_password(PASSWORD)
    assert encoded.startswith("$argon2id$")
    assert verify_password(encoded, PASSWORD)
    assert not verify_password(encoded, "another synthetic password")
    assert normalize_email(" Admin.Auth@Example.Test ") == "admin.auth@example.test"
    with pytest.raises(ValueError):
        hash_password("short")


@pytest.mark.parametrize("email,password", [("unknown@example.test", PASSWORD), (EMAIL, "wrong synthetic password")])
def test_unknown_and_wrong_password_have_same_generic_failure(auth_client, admin_credentials, email, password):
    headers = {"Origin": ORIGIN}
    unknown = auth_client.post("/api/v1/auth/login", json={"email": email, "password": password}, headers=headers)
    wrong = auth_client.post("/api/v1/auth/login", json={"email": EMAIL, "password": "wrong synthetic password"}, headers=headers)
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json() == wrong.json()
    assert PASSWORD not in unknown.text + wrong.text
    assert auth_client.get("/api/v1/auth/session").status_code == 401


@pytest.mark.parametrize("origin", [None, "https://foreign.example"])
def test_login_rejects_missing_or_foreign_origin(auth_client, admin_credentials, origin):
    headers = {} if origin is None else {"Origin": origin}
    response = auth_client.post("/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD}, headers=headers)
    assert response.status_code in (400, 401, 403)
    assert not response.cookies.get("admin_session")


def test_fifth_failure_throttles_before_hash_verification(auth_client, admin_credentials, monkeypatch):
    from serviceBot.services import admin_auth

    attempts = []
    original = admin_auth.verify_password
    def counted(*args, **kwargs):
        attempts.append(1)
        return original(*args, **kwargs)
    monkeypatch.setattr(admin_auth, "verify_password", counted)
    for _ in range(5):
        response = auth_client.post("/api/v1/auth/login", json={"email": EMAIL, "password": "incorrect synthetic"}, headers={"Origin": ORIGIN})
        assert response.status_code == 401
    before = len(attempts)
    response = auth_client.post("/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD}, headers={"Origin": ORIGIN})
    assert response.status_code == 401
    assert len(attempts) == before


def test_logout_requires_csrf_and_revokes_session(auth_client, admin_credentials):
    login = auth_client.post("/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD}, headers={"Origin": ORIGIN})
    assert login.status_code == 200
    csrf = login.json()["csrf_token"]
    denied = auth_client.post("/api/v1/auth/logout", headers={"Origin": ORIGIN})
    assert denied.status_code in (400, 403)
    response = auth_client.post("/api/v1/auth/logout", headers={"Origin": ORIGIN, "X-CSRF-Token": csrf})
    assert response.status_code == 204
    assert auth_client.get("/api/v1/auth/session").status_code == 401


def test_expired_revoked_and_unknown_sessions_fail_closed(auth_client, admin_credentials):
    from serviceBot.db.connection import get_db_connection

    for expiry_or_revoke in ("expired", "revoked"):
        login = auth_client.post(
            "/api/v1/auth/login",
            json={"email": EMAIL, "password": PASSWORD},
            headers={"Origin": ORIGIN},
        )
        assert login.status_code == 200
        token = auth_client.cookies.get("admin_session")
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        with get_db_connection() as conn, conn.cursor() as cursor:
            if expiry_or_revoke == "expired":
                cursor.execute(
                    "UPDATE public.admin_sessions SET created_at=CURRENT_TIMESTAMP - INTERVAL '2 seconds', expires_at=CURRENT_TIMESTAMP - INTERVAL '1 second' WHERE token_hash=%s",
                    (token_hash,),
                )
            else:
                cursor.execute(
                    "UPDATE public.admin_sessions SET revoked_at=CURRENT_TIMESTAMP WHERE token_hash=%s",
                    (token_hash,),
                )
        assert auth_client.get("/api/v1/auth/session").status_code == 401
        auth_client.cookies.clear()
    auth_client.cookies.set("admin_session", "unknown-opaque-token")
    assert auth_client.get("/api/v1/auth/session").status_code == 401
    assert auth_client.get("/api/v1/portal/config").status_code == 401


def test_password_change_checks_current_confirmation_and_revokes_sessions(auth_client, admin_credentials):
    from serviceBot.main import app

    first = auth_client.post("/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD}, headers={"Origin": ORIGIN})
    assert first.status_code == 200
    csrf = first.json()["csrf_token"]
    other_session = TestClient(app, client=("198.51.100.2", 1234))
    second = other_session.post("/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD}, headers={"Origin": ORIGIN})
    assert second.status_code == 200
    payload = {"current_password": PASSWORD, "new_password": "new-synthetic-password", "new_password_confirmation": "new-synthetic-password"}
    for bad_headers in ({"X-CSRF-Token": csrf}, {"Origin": "https://foreign.example", "X-CSRF-Token": csrf}, {"Origin": ORIGIN}):
        rejected = auth_client.post("/api/v1/auth/password", json=payload, headers=bad_headers)
        assert rejected.status_code in (400, 403)
    invalid = auth_client.post("/api/v1/auth/password", json={"current_password": "incorrect synthetic", "new_password": "new-synthetic-password", "new_password_confirmation": "new-synthetic-password"}, headers={"Origin": ORIGIN, "X-CSRF-Token": csrf})
    assert invalid.status_code in (400, 401, 422)
    valid = auth_client.post("/api/v1/auth/password", json={"current_password": PASSWORD, "new_password": "new-synthetic-password", "new_password_confirmation": "new-synthetic-password"}, headers={"Origin": ORIGIN, "X-CSRF-Token": csrf})
    assert valid.status_code == 204
    assert auth_client.get("/api/v1/auth/session").status_code == 401
    assert other_session.get("/api/v1/auth/session").status_code == 401
    old_login = auth_client.post("/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD}, headers={"Origin": ORIGIN})
    new_login = auth_client.post("/api/v1/auth/login", json={"email": EMAIL, "password": "new-synthetic-password"}, headers={"Origin": ORIGIN})
    assert old_login.status_code == 401 and new_login.status_code == 200


def test_login_and_password_reset_serialize_before_session_insert(admin_credentials, monkeypatch):
    from serviceBot.main import app
    from serviceBot.services import admin_auth

    verified_old_password = Event()
    finish_login = Event()
    reset_started = Event()
    original_verify = admin_auth.verify_password

    def pause_after_verification(encoded_hash, password):
        valid = original_verify(encoded_hash, password)
        if password == PASSWORD and valid:
            verified_old_password.set()
            assert finish_login.wait(timeout=10)
        return valid

    monkeypatch.setattr(admin_auth, "verify_password", pause_after_verification)

    def login():
        with TestClient(app, client=("198.51.100.21", 1234)) as client:
            response = client.post(
                "/api/v1/auth/login",
                json={"email": EMAIL, "password": PASSWORD},
                headers={"Origin": ORIGIN},
            )
            return response.status_code, response.cookies.get("admin_session")

    def reset():
        reset_started.set()
        admin_auth.reset_admin_password("race-new-password")

    with ThreadPoolExecutor(max_workers=2) as pool:
        login_future = pool.submit(login)
        assert verified_old_password.wait(timeout=10)
        reset_future = pool.submit(reset)
        assert reset_started.wait(timeout=10)
        reset_future.result(timeout=20)
        finish_login.set()
        status, token = login_future.result(timeout=20)

    assert status == 401
    assert not token
    # The login's session is revoked by the reset that serialized behind it.
    from serviceBot.db.connection import get_db_connection
    with get_db_connection() as conn, conn.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM public.admin_sessions WHERE revoked_at IS NULL")
        assert cursor.fetchone()[0] == 0


def test_protected_routes_and_distinct_auth_boundaries(auth_client, monkeypatch):
    from serviceBot import main

    monkeypatch.setattr(main, "CRON_SECRET", "synthetic-cron-secret")
    auth_client.cookies.set("admin_session", "synthetic-invalid-admin-cookie")
    assert auth_client.get("/health").status_code == 200
    cron = auth_client.post("/api/cron/outbox")
    assert cron.status_code == 401
    assert cron.json() == {"detail": "Unauthorized cron trigger"}
    assert auth_client.get("/api/v1/telephony/render-logs").status_code == 200
    malformed_voice = auth_client.post(
        "/api/v1/voice/tools",
        content=b"{",
        headers={"Content-Type": "application/json"},
    )
    assert malformed_voice.status_code == 422
    portal = auth_client.get("/portal/", follow_redirects=False)
    assert portal.status_code in (302, 303, 307)
    assert portal.headers["location"] == "/"
    for path in ("/portal//", "/portal//index.html"):
        alias = auth_client.get(path, follow_redirects=False)
        assert alias.status_code in (302, 303, 307)
        assert alias.headers["location"] == "/"
    assert auth_client.get("/portal/login.js").status_code == 200
    assert auth_client.get("/api/v1/portal/config").status_code == 401
    # OAuth callback remains subject to its existing state check, not cookie auth.
    callback = auth_client.get("/api/v1/portal/gmail/oauth/callback", follow_redirects=False)
    assert callback.status_code != 401
    # An invalid admin cookie never substitutes for internal bearer authorization.
    internal = auth_client.get("/api/v1/portal/internal/simulation-staff")
    assert internal.status_code in (401, 403)


def test_cli_refuses_duplicate_creation_and_reset_revokes_sessions(auth_client, admin_credentials):
    from serviceBot.main import app

    env = os.environ.copy()
    env["TEST_DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
    env["DATABASE_URL"] = os.environ["DATABASE_URL"]
    login = auth_client.post("/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD}, headers={"Origin": ORIGIN})
    assert login.status_code == 200
    second_session = TestClient(app, client=("198.51.100.3", 1234))
    second_login = second_session.post("/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD}, headers={"Origin": ORIGIN})
    assert second_login.status_code == 200
    from tests.admin_cli import run_admin_cli
    create = run_admin_cli("create-admin", [EMAIL, "replacement-secret-value", "replacement-secret-value"], env)
    assert create.returncode != 0
    assert PASSWORD not in create.stdout + create.stderr
    reset = run_admin_cli("reset-password", ["replacement-secret-value", "replacement-secret-value"], env)
    assert reset.returncode == 0
    assert "replacement-secret-value" not in reset.stdout + reset.stderr
    assert auth_client.get("/api/v1/auth/session").status_code == 401
    assert second_session.get("/api/v1/auth/session").status_code == 401
    old_login = auth_client.post("/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD}, headers={"Origin": ORIGIN})
    new_login = auth_client.post("/api/v1/auth/login", json={"email": EMAIL, "password": "replacement-secret-value"}, headers={"Origin": ORIGIN})
    assert old_login.status_code == 401 and new_login.status_code == 200
