"""Real browser authentication journey against disposable PostgreSQL."""


def test_root_login_opens_dashboard_and_logout_revokes_session(
    anonymous_page, admin_auth_credentials, live_server
):
    page = anonymous_page
    page.goto("/")
    assert page.locator("input[type=email]").is_visible()
    page.locator("input[type=email]").fill(admin_auth_credentials["email"])
    page.locator("input[type=password]").fill(admin_auth_credentials["password"])
    page.locator("button[type=submit]").click()
    page.wait_for_url("**/portal/**")
    assert page.locator("body").is_visible()
    page.goto("/api/v1/auth/session")
    assert '"authenticated":true' in page.locator("body").inner_text().replace(" ", "")
    page.goto("/portal/")
    logout = page.get_by_role("button", name="Log out")
    logout.click()
    page.wait_for_url(live_server + "/")
    page.locator("#email").wait_for(state="visible")
    page.goto("/portal/")
    assert page.url.endswith("/")
    assert page.locator("#email").is_visible()


def test_rejected_credentials_do_not_open_dashboard(anonymous_page, admin_auth_credentials):
    page = anonymous_page
    page.goto("/")
    page.locator("input[type=email]").fill(admin_auth_credentials["email"])
    page.locator("input[type=password]").fill("invalid synthetic password")
    page.locator("button[type=submit]").click()
    assert page.locator("input[type=password]").is_visible()
    assert "/portal/" not in page.url


def test_expired_session_redirects_to_login(anonymous_page, admin_auth_credentials):
    page = anonymous_page
    import hashlib

    from serviceBot.db.connection import get_db_connection

    page.goto("/")
    page.locator("input[type=email]").fill(admin_auth_credentials["email"])
    page.locator("input[type=password]").fill(admin_auth_credentials["password"])
    page.locator("button[type=submit]").click()
    page.wait_for_url("**/portal/**")
    token = next(cookie["value"] for cookie in page.context.cookies() if cookie["name"] == "admin_session")
    digest = hashlib.sha256(token.encode()).hexdigest()
    with get_db_connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            """UPDATE public.admin_sessions
               SET created_at = now() - interval '2 seconds',
                   expires_at = now() - interval '1 second'
               WHERE token_hash = %s""",
            (digest,),
        )
    page.goto("/portal/")
    assert page.locator("input[type=email]").is_visible()


def test_password_change_requires_relogin_and_new_password_works(anonymous_page, admin_auth_credentials):
    page = anonymous_page
    page.goto("/")
    page.locator("input[type=email]").fill(admin_auth_credentials["email"])
    page.locator("input[type=password]").fill(admin_auth_credentials["password"])
    page.locator("button[type=submit]").click()
    page.wait_for_url("**/portal/**")
    page.get_by_role("link", name="Config").click()
    page.get_by_role("button", name="Admin Config").click()
    assert page.get_by_label("Current password").is_visible()
    page.get_by_label("Current password").fill(admin_auth_credentials["password"])
    page.get_by_label("New password", exact=True).fill("synthetic-browser-password-v2")
    page.get_by_label("Confirm new password").fill("synthetic-browser-password-v2")
    page.get_by_role("button", name="Change password").click()
    page.wait_for_url("**/")
    page.locator("input[type=email]").fill(admin_auth_credentials["email"])
    page.locator("input[type=password]").fill("synthetic-browser-password-v2")
    page.locator("button[type=submit]").click()
    page.wait_for_url("**/portal/**")
