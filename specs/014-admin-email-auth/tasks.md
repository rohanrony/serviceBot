# Tasks: Single-admin email and password authentication

**Input**: `spec.md`, `plan.md`, `data-model.md`, `contracts/`, and `test-coverage.yaml`.

## Phase 1: Setup

**Purpose**: Add the password-hashing dependency needed by tests and implementation.

- [x] T001 Add `argon2-cffi` to `requirements.txt` and install/import it in the test virtualenv; the supported service runtime remains Python 3.11.

## Phase 2: Foundational tests and persistence

**Purpose**: Author and collect every changed contract before changing application behavior; then add shared schema and auth primitives required by all stories.

- [x] T002 [P] Add migration apply/schema/RLS/rollback assertions for `0013_admin_auth` in `tests/test_migrations.py`.
- [x] T003 [P] Add all unit/service/API/CLI/config success, failure, and invariant tests for `tests/test_admin_auth.py` and `tests/test_portal_config.py`, including password policy, session expiry/revocation, trusted ASGI scheme/client IP, raw-header spoof resistance, Origin/CSRF, throttling and bounded hash concurrency, safe serialization, CLI redaction/reset, and transactional change; keep imports collection-safe while planned modules are absent.
- [x] T004 [P] Add browser tests for login, dashboard access, logout/expiry, password change, and rejected credentials in `e2e/test_admin_auth.py`, with test-only isolated admin/session setup in `e2e/conftest.py`.
- [x] T005 Update `tests/conftest.py` so unrelated legacy portal tests explicitly override the auth dependency and auth boundary tests clear that override.
- [x] T006 Collect actual pytest node IDs into every applicable row in `test-coverage.yaml`, run the new tests before application behavior changes, and record intended Red evidence in `test-coverage.yaml`.
- [x] T007 Add `serviceBot/db/migrations/0013_admin_auth.sql`, `serviceBot/db/migrations/0013_admin_auth.down.sql`, and `serviceBot/db/migration_verification/0013_admin_auth.sql`; enforce singleton admin, session digests/expiry/revocation, failed-login rate data, RLS, and least-privilege grants.
- [x] T008 Implement shared email normalization, Argon2id hash/verify/rehash, bounded hash concurrency, IP throttle-before-verify, opaque token/CSRF digests, database session lookup/expiry/revocation, and transactional persistence in `serviceBot/services/admin_auth.py`.

## Phase 3: User Story 1 - Sign in to the admin portal (Priority: P1) 🎯 MVP

**Goal**: Root login grants a revocable session and gates the dashboard/API without changing unrelated ingress contracts.
**Independent test**: With an admin row in disposable PostgreSQL, verify successful/failed login, protected route denial, route exceptions, secret-safe config, and the root-to-dashboard browser journey.

- [x] T009 [US1] Implement login, session, and logout endpoints in `serviceBot/api/auth.py` with exact-origin validation, generic failures, cookie flags, CSRF token delivery, and `Cache-Control: no-store`.
- [x] T010 [US1] Apply the database session and CSRF dependencies to admin-only routes in `serviceBot/api/portal.py`; keep the Google OAuth callback on its state-validated public route and `/internal/*` on its existing bearer-token checks.
- [x] T011 [US1] Register auth routes and protect `/portal/` and `/portal/index.html` while serving the required non-sensitive static assets in `serviceBot/main.py`.
- [x] T012 [US1] Narrow `/api/v1/portal/config` to safe UI fields and exclude credentials in `serviceBot/api/portal.py`.
- [x] T013 [US1] Add the clean root login UI and in-memory session/CSRF handling in `serviceBot/static/login.html`, `serviceBot/static/login.css`, and `serviceBot/static/login.js`.
- [x] T014 [US1] Update `e2e/conftest.py` so existing dashboard browser/API fixtures authenticate through the real login API; keep `e2e/test_admin_auth.py` unauthenticated until each login journey signs in.

## Phase 4: User Story 2 - Initialize and recover the admin account (Priority: P1)

**Goal**: Developer/operator can create the single account and reset it securely outside the public web surface.
**Independent test**: Run CLI subprocesses against disposable PostgreSQL; inspect output, argv, persisted hashes, account count, and session revocations.

- [x] T015 [US2] Implement `python -m serviceBot.auth_admin create-admin` with hidden prompts, normalization, 12-character minimum, and refuse-overwrite behavior in `serviceBot/auth_admin.py`.
- [x] T016 [US2] Implement `python -m serviceBot.auth_admin reset-password` in `serviceBot/auth_admin.py`; atomically replace the hash, revoke every session, and redact all output.

## Phase 5: User Story 3 - Change the password in Admin Config (Priority: P1)

**Goal**: Authenticated admin can change the password later and must sign in again after all sessions are revoked.
**Independent test**: Change through the protected API and Admin Config browser form; verify old sessions/password fail and new credentials work after reload/re-login.

- [x] T017 [US3] Implement the protected password-change endpoint in `serviceBot/api/auth.py`; require current password, matching 12-character new password, same-origin and CSRF checks, then atomically update hash and revoke all sessions.
- [x] T018 [US3] Add the Account Security form to `serviceBot/static/index.html`, `serviceBot/static/app.js`, and `serviceBot/static/style.css`; clear client auth state and return to login after success.

## Phase 6: Polish and cross-cutting verification

**Purpose**: Review every mapped contract, complete full offline verification, and converge until there are no actionable gaps.

- [x] T019 Review and complete every acceptance row in `specs/014-admin-email-auth/test-coverage.yaml` with actual collected IDs, Red/Green commands and results, meaningful invariants, omitted-layer reasons, and independent review evidence.
- [x] T020 Run focused auth service, API, migration, CLI, and browser E2E tests; record commands and outcomes in `specs/014-admin-email-auth/test-coverage.yaml`.
- [ ] T021 Run `./run_tests.sh --verify` with synthetic credentials and no live tier; record Offline status/evidence and Live `not_required` reason in `specs/014-admin-email-auth/test-coverage.yaml`. Partial only: unit/integration passed, but the broader E2E scheduling journey stalled after HTTP 201 headers while reading its response body, so full verification remains incomplete.
- [x] T022 Resolve findings from independent Luna implementation/validation iterations and root review against `spec.md`, `plan.md`, `checklists/security.md`, and all mapped test IDs; repeat until tests pass and no actionable finding remains.
- [x] T023 Restore `.specify/feature.json` to its original `specs/013-business-neutral-portal` pointer and confirm unrelated tracked and untracked workspace state remains untouched.

## Dependencies and execution order

- Phase 1 enables test collection and hashing.
- Phase 2 tests (T002–T006) must be authored, collected, mapped to actual IDs, and run red before migration or application behavior (T007–T008).
- User Story 1 (Phase 3) depends on the schema and shared auth primitives (Phase 2).
- User Story 2 (Phase 4) and User Story 3 (Phase 5) depend on the shared persistence/hash/session primitives (Phase 2); they are intentionally executed after US1 to avoid conflicting edits to shared auth service and API files.
- Phase 6 depends on all three stories.

## Parallel opportunities

- T002, T003, and T004 touch separate test areas and may be authored independently; T005 is separate test-fixture work but must be integrated before collecting tests.
- No application behavior tasks are marked parallel because the stories share the auth service, API router, migration, and fixtures.

## Implementation strategy

1. Complete setup and the shared test-first gate.
2. Complete US1 as the MVP, then test the login and protected dashboard independently.
3. Complete US2 operator provisioning/recovery, then US3 Admin Config password change.
4. Run focused suites during each phase, then full offline verification and independent validation/root-review loops.
5. Do not commit, push, merge, deploy, or run live-provider operations.
