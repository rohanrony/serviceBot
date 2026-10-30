# Implementation Plan: Single-admin email and password authentication

**Branch**: Existing `integrate/recent-prior-changes-20261027` (no branch switch)  
**Date**: 2026-10-29  
**Spec**: [spec.md](spec.md)

## Summary

Introduce a single-admin, PostgreSQL-backed authentication service with Argon2id password hashes, revocable server-side sessions, a root login page, and a password change form in Admin Config. Require authentication for the admin dashboard and its API while keeping OAuth callback and existing bearer-token simulation boundaries separate. Do not deploy or provision production credentials as part of this change.

## Technical Context

**Language/Version**: Python 3.11, plain JavaScript, HTML, CSS  
**Primary Dependencies**: FastAPI, psycopg2, `argon2-cffi`  
**Storage**: PostgreSQL (migrations and rollback SQL)  
**Testing**: pytest unit/integration tests; Playwright browser E2E over HTTP and disposable PostgreSQL  
**Target Platform**: Linux service on Render, local offline test environment  
**Project Type**: FastAPI web service with static admin frontend  
**Performance Goals**: No new latency SLO; login hashing stays synchronous to the user flow and must not block unrelated async routes.  
**Constraints**: One admin only; no public signup or email recovery; hidden interactive CLI prompts; no provider requests, production DB changes, or live deployment.  
**Scale/Scope**: One admin identity, multiple revocable browser sessions, existing admin portal API surface.

### Constitution Check

**Pre-design**: Passes Principles I–V. The new `admin_auth` service owns password/session state; failed auth has no protected effects; credentials stay hashed and out of logs; tests cover HTTP, database, migration, and browser boundaries offline; no voice/provider behavior changes.

**Post-design**: Passes Principles I–V. Shared admin access is enforced by one session/CSRF dependency. Admin account and sessions are durable, reset/password change revokes sessions transactionally, and PostgreSQL failure denies access. OAuth callback state and token-protected simulation APIs retain their distinct authorization. Unit fixtures may override the guard for unrelated legacy route tests; new auth tests explicitly remove that override, and E2E uses real sessions.

## Architecture and Data Flow

1. `serviceBot/auth_admin.py` provides `create-admin` and `reset-password` operator commands. Hidden prompts validate input; the service writes an Argon2id hash and never emits plaintext.
2. `serviceBot/services/admin_auth.py` owns email normalization, password hash/verification, login throttling, database session create/read/revoke, and the CSRF token check.
3. `serviceBot/api/auth.py` exposes login, current-session, logout, and password-change routes. A cookie contains a random opaque token; PostgreSQL stores only its digest and expiry. `/session` supplies the per-session CSRF token to same-origin JavaScript.
4. Apply a shared `require_admin` and `require_csrf` dependency to the admin portal router. Move the Google OAuth callback to a public router with its current `state` validation, and keep `/internal/*` simulation routes on their bearer-token router. Keep telephony/voice ingress, cron, health, and Render log ingestion outside admin-cookie auth.
5. `serviceBot/main.py` serves the clean login at `/`, protects `/portal/` and `/portal/index.html`, and serves the non-sensitive static assets needed by login and dashboard pages. Unauthenticated HTML requests redirect to `/`; APIs return JSON `401`.
6. Add the Account Security card within the existing Admin Config pane. Password-changing requests send the current password, new password, matching confirmation, and `X-CSRF-Token`; successful updates revoke all sessions and require sign-in again.
7. Narrow `/api/v1/portal/config` to safe values consumed by the admin UI; never serialize raw secrets from `load_config()`.

## Data and API Contracts

- Add migration `0013_admin_auth.sql`, its `.down.sql`, and migration-verification SQL. Account row is constrained to one admin; session rows contain token/CSRF digests, UTC creation/expiry/revocation times; failed-attempt rows support a rolling 15-minute per-IP limit. Apply RLS and revoke browser-facing roles consistently with existing sensitive migrations.
- Add `POST /api/v1/auth/login`, `GET /api/v1/auth/session`, `POST /api/v1/auth/logout`, and `POST /api/v1/auth/password` as defined in [contracts/auth-http.md](contracts/auth-http.md). No public setup endpoint.
- Session cookie: HttpOnly, SameSite=Lax, Secure on HTTPS, Path `/`, fixed eight-hour absolute expiry. Server lookup is authoritative. Logout expires one row; password change and operator reset revoke every row. Add `Cache-Control: no-store` to authenticated HTML and API responses.
- Password hash: `argon2-cffi.PasswordHasher()` defaults (Argon2id, random salt); validate minimum 12 characters. Rehash after successful verification if parameters change.
- Login: normalize email case/whitespace; perform comparable hash work for unknown accounts; generic failure response; block after five failed attempts per client IP inside 15 minutes, before Argon2 verification. Cap simultaneous hash work per process. Use the ASGI client address as supplied by the trusted deployment proxy, not an untrusted raw forwarding header.
- Proxy boundary: derive client IP and public scheme only from Uvicorn's normalized ASGI `request.client.host` and `request.url.scheme`; application code must not parse client-supplied `X-Forwarded-*` headers. The existing Render Python runtime provides `FORWARDED_ALLOW_IPS=*` behind its web-service edge. Other deployment modes must configure the ASGI server to trust only their actual proxy layer; do not copy Render's wildcard setting to a directly reachable server.
- CSRF: random per-session synchronizer token delivered by `/session`, retained only in browser memory, and required in `X-CSRF-Token` on unsafe admin/authenticated requests. Validate `Origin` on login and unsafe requests; SameSite is defense in depth.
- Operator CLI: hidden prompt, `create-admin` refuses if an account exists, `reset-password` updates only the hash and revokes sessions, both use the configured application PostgreSQL connection and emit redacted status only.

## Test and Coverage Strategy

- Create/update `test-coverage.yaml` before code implementation; author tests before application code, collect actual pytest node IDs, then replace placeholders in the matrix before the implementation task.
- Unit/database tests cover normalization, hash/verify/rehash, fixed expiry, revocation, rollback, rate limits, and operator create/reset invariants.
- HTTP tests cover each auth endpoint, cookie flags, missing/invalid/expired sessions, CSRF failures, throttling, protected route boundaries, OAuth state exception, and safe config serialization.
- Preserve existing unit/integration tests using an explicit dependency override in `tests/conftest.py`; auth boundary tests clear it. Update `e2e/conftest.py` to create a test admin and authenticate the existing dashboard/API fixtures. New auth E2E uses an unauthenticated browser context for actual login/logout/password change.
- Migration coverage verifies apply, schema shape, privilege/RLS contract, and rollback on a disposable database. Provider/live scenarios are `not_required`: no external provider behavior changes.
- Run focused tests during Red → Green → Refactor, then `./run_tests.sh --verify` with synthetic credentials and no live tier. Do not commit, push, merge, or deploy.

## Project Structure

```text
serviceBot/
  auth_admin.py
  api/auth.py
  api/portal.py
  main.py
  services/admin_auth.py
  static/login.html, login.css, login.js
  static/index.html, app.js, style.css
  db/migrations/0013_admin_auth.sql (+ down migration)
  db/migration_verification/0013_admin_auth.sql
tests/
  test_admin_auth.py
  test_migrations.py (auth migration assertions)
  conftest.py (isolated dependency override)
e2e/
  test_admin_auth.py
  conftest.py (real test-account login)
specs/014-admin-email-auth/
  spec.md, plan.md, research.md, data-model.md, quickstart.md
  contracts/, checklists/, test-coverage.yaml, tasks.md
```

## Phases

1. Complete auth-specific unit/API/browser tests and actual test-coverage IDs; observe intended Red failures.
2. Implement the migration, hash/session service, and operator CLI; verify persisted hashes and transactional revocation.
3. Add auth endpoints, route dependencies, callback/internal router boundaries, and secret-safe config output.
4. Add root login and Admin Config password change; authenticate dashboard E2E fixtures.
5. Run focused suites, independent validation, root review, and convergence; correct any findings in fresh implementation/validation loops.

## Complexity Tracking

No constitution exception. The auth service is the single owner for account/session state; no new runtime service, external auth provider, or deployment target is introduced.
