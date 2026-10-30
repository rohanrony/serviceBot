# Quickstart: Admin email and password authentication

## Provision the administrator

1. Deploy the application code and apply its PostgreSQL migrations.
2. In the trusted application runtime, run `python -m serviceBot.auth_admin create-admin` and enter the admin email plus a strong password at the hidden prompts.
3. Share the email/password with the admin through the team's secure credential-sharing channel. Do not put them in source control, deployment logs, or this feature record.
4. Open the deployed site root, sign in, and use Admin Config → Account Security to change the password when desired.

The supported Render Python runtime supplies trusted proxy metadata used to identify HTTPS and client IP. For any other deployment mode, configure Uvicorn's trusted proxy list for the actual edge proxy before exposing the app; application code intentionally ignores raw client-supplied forwarding headers.

If access is lost, run `python -m serviceBot.auth_admin reset-password` in the trusted runtime. The command revokes existing sessions.

## User journey

- `/` serves the login page.
- Successful login creates a server-side eight-hour session and routes the browser to `/portal/`.
- Logout or expiry returns the browser to `/`.
- Admin API writes include the CSRF token returned by `/api/v1/auth/session` in `X-CSRF-Token`.

## Offline validation

- Run focused auth/service/API tests first; they use synthetic credentials and disposable local PostgreSQL.
- Run browser acceptance tests for login, dashboard access, logout, and password change.
- Run `./run_tests.sh --verify` without any `--live-tier` option for the complete offline unit/integration and E2E suites. Do not use production credentials or provider calls for this feature.
