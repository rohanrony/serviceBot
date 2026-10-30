# Research: Single-admin email and password authentication

**Date**: 2026-10-29

## Existing repository contracts

- FastAPI mounts the existing dashboard from `serviceBot/static/` at `/portal`; the root URL currently has no login page.
- Admin reads and mutations use `serviceBot/api/portal.py` under `/api/v1/portal`.
- Google OAuth completes through `/api/v1/portal/gmail/oauth/callback`; the callback uses an existing persisted `state` value and must remain reachable after an external provider redirect.
- Simulation routes under `/api/v1/portal/internal/*` have independent bearer-token checks. Telephony/voice routes, health, cron, and Render log ingestion are separate ingress surfaces.
- PostgreSQL schema changes use ordered SQL migrations with paired rollback scripts and verification SQL. E2E tests create disposable loopback PostgreSQL databases; unit/integration tests use their own disposable databases.
- The portal configuration read currently returns the full loaded configuration object. The response must be narrowed so credential fields cannot reach the browser.

## Password hashing

Use `argon2-cffi`'s high-level `PasswordHasher` API. Its current documentation says the defaults use Argon2id and a per-password random salt; hashes are self-describing, can be verified with `verify()`, and checked for upgrades with `check_needs_rehash()`. Keep the encoded hash in PostgreSQL and never store or log plaintext passwords. See [argon2-cffi API](https://argon2-cffi.readthedocs.io/en/stable/api.html) and [OWASP Password Storage Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html).

The documented default memory cost is 64 MiB per hash operation. Check the IP throttle before verification and cap simultaneous hash operations per process so unauthenticated requests cannot multiply that memory cost without bound.

## Session and CSRF design

Use a high-entropy opaque cookie token with only its SHA-256 digest stored in PostgreSQL. This server-side state makes logout, password changes, and operator resets revokeable without signing-key rotation. Set `HttpOnly`, `Secure` for HTTPS deployments, `SameSite=Lax`, `Path=/`, and an eight-hour server-enforced absolute expiry. Do not rely on cookie deletion alone to invalidate a stolen token. Use `Cache-Control: no-store` on authenticated pages and responses.

`SameSite=Lax` is defense in depth, not the CSRF control. Generate one unpredictable per-session synchronizer token, return it from the authenticated session endpoint, keep it in page memory, and require it in a custom header for unsafe authenticated requests. Validate `Origin` on login and unsafe cookie-authenticated requests. Do not put the session ID or CSRF token in URLs or local storage. See [OWASP Session Management](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html) and [OWASP CSRF Prevention](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html).

For this Render deployment, the ASGI server must see the public HTTPS scheme and actual client IP after the platform proxy. Render's Python runtime documents `FORWARDED_ALLOW_IPS=*`, while its load balancer terminates TLS and forwards to the app over HTTP. Use Uvicorn's normalized ASGI `request.url.scheme` and `request.client.host`; do not manually trust or parse raw forwarding headers in application code. A different deployment must configure only its actual proxy sources. See [Render environment variables](https://render.com/docs/environment-variables), [Render web services](https://render.com/docs/web-services), and [Uvicorn settings](https://www.uvicorn.org/settings/).

## Provisioning and account recovery

The user chose developer-managed provisioning and secure out-of-band credential sharing. Use an operator-only CLI with hidden password prompts rather than a public setup route or long-lived password environment variable. Creation must refuse to overwrite an existing account; reset must replace the hash and revoke all sessions. The browser does not force a password change at first login; the admin may change it from Admin Config.

## Decisions

- Use a single-account table with a singleton constraint; normalize email by trimming and case-folding before matching.
- Use database-backed sessions and fixed eight-hour expiry; revoke the current session on logout and all sessions on password change/reset.
- Protect the admin router with a shared FastAPI dependency so test applications can override it explicitly. Put the OAuth callback and existing bearer-token internal routes on separate routers so the exception boundary is visible in route registration.
- Protect the dashboard HTML routes and the complete admin API while serving non-sensitive static assets needed by login/dashboard pages.
- Rate-limit failed authentication to five attempts per client IP per rolling 15 minutes before running Argon2 verification; cap simultaneous password hash work per process. Return the same login response for unknown email and wrong password. Do not trust raw client-supplied forwarding headers; use the ASGI client address as configured by the trusted deployment proxy.
- Require a current password and matching confirmation for in-app password change. On success revoke existing sessions and require a fresh login.
- No live provider scenario is needed: this feature changes local admin authentication and does not change provider requests or external delivery behavior.
