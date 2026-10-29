# Feature Specification: Single-admin email and password authentication

**Feature Branch**: `014-admin-email-auth`
**Created**: 2026-10-29
**Status**: Draft
**Input**: Add a simple, database-backed email/password login for the admin app, a clean login at the site root, and password change in Admin Config.

## User Scenarios & Testing

### User Story 1 - Sign in to the admin portal (Priority: P1)

The administrator opens the site, signs in with their email and password, and reaches the existing dashboard. Unauthenticated visitors see the login page rather than the dashboard.

**Why this priority**: It gates customer, appointment, configuration, and integration data already exposed through the admin portal.
**Independent Test**: Send unauthenticated and authenticated HTTP requests, then complete a browser login journey against an isolated database.

**Acceptance Scenarios**:

1. **Given** an initialized admin account, **When** the admin submits its valid email and password at `/`, **Then** the portal opens and the browser has an authenticated session.
2. **Given** an unauthenticated browser, **When** it requests `/portal/`, **Then** it is sent to the login page and admin API requests return an unauthorized response without data.
3. **Given** an invalid email or password, **When** the admin submits credentials, **Then** login fails with the same generic message and creates no session.
4. **Given** an expired or revoked session, **When** the browser requests a protected page or API, **Then** it is sent to login or receives an unauthorized API response.

### User Story 2 - Initialize and recover the admin account (Priority: P1)

The developer creates the single admin account through an operator-only command and securely shares the initial credentials with the administrator. The developer can use an operator-only reset command if access is lost.

**Why this priority**: The system needs a controlled way to provision the first credential without public signup or a claimable first-run page.
**Independent Test**: Run account-management commands against a disposable database and verify only password hashes persist and no credential is printed or logged.

**Acceptance Scenarios**:

1. **Given** an empty database, **When** the operator creates an admin account, **Then** the email is stored normalized and only an Argon2id password hash is persisted.
2. **Given** an existing admin account, **When** the operator tries to create another account, **Then** the command refuses without changing the account or sessions.
3. **Given** a lost password, **When** the operator resets the single admin password, **Then** the new hash is stored and every prior session is revoked.
4. **Given** any CLI success or failure, **When** output is inspected, **Then** no plaintext password appears in output, logs, shell arguments, or database fields.

### User Story 3 - Change the password in Admin Config (Priority: P1)

The authenticated administrator can change the password later from an Account Security section in the existing Admin Config screen.

**Why this priority**: The administrator needs a self-service way to replace the developer-shared credential.
**Independent Test**: Change the password through the HTTP endpoint and browser, verify the new credential works after re-login, and verify old sessions and credentials no longer work.

**Acceptance Scenarios**:

1. **Given** a valid session, **When** the admin submits the current password and a valid matching new password and confirmation, **Then** the hash is updated and the browser is returned to login.
2. **Given** an incorrect current password, mismatched confirmation, or invalid new password, **When** the change is submitted, **Then** the request fails and neither password nor sessions change.
3. **Given** a successful password change, **When** any prior session is reused, **Then** it is rejected; a new login with the new password succeeds.

### Edge Cases

- Email comparison is case-insensitive and ignores surrounding whitespace; duplicate normalized admin email/account creation is rejected.
- Repeated failed login attempts are throttled without revealing whether an email exists.
- Login and unsafe cookie-authenticated requests from a missing or foreign `Origin` are rejected.
- Browser-authenticated state-changing requests without a valid CSRF token are rejected.
- A database or session-store error fails closed for protected admin pages and APIs.
- Forwarded scheme and client-address metadata are trusted only after the configured ASGI proxy has normalized it; application code does not accept raw client-supplied forwarding headers as identity.
- The Google OAuth callback remains accessible without the admin cookie only when its existing OAuth state validation succeeds.
- Existing `/api/v1/portal/internal/*` simulation endpoints retain their own bearer-token checks; they do not gain cookie-only access.
- Telephony webhooks, voice tool ingress, cron endpoints, `/health`, and Render log ingestion retain their existing ingress/authentication contracts.
- The portal configuration response never returns passwords, password hashes, OAuth tokens, client secrets, or API keys.

## Clarifications

### Session 2026-10-29

- Q: How should the first admin account be created? → A: The developer creates it manually and securely shares the credentials with the admin; no public first-run setup page.
- Q: What should visitors see at the site root? → A: A clean login page, followed by the dashboard after login.
- Q: Must the admin change the shared initial password at first login? → A: No; the admin may change it later in Admin Config.

## Requirements

### Functional Requirements

- **FR-001**: The site root MUST show an email/password login page. A successful login MUST grant access to the existing admin dashboard at `/portal/`.
- **FR-002**: The system MUST support exactly one admin account in v1. It MUST NOT offer public signup or a public first-run account-claim flow.
- **FR-003**: An operator-only CLI MUST create the first admin account and reset its password. Passwords MUST be entered without echo, MUST NOT appear in command arguments or output, and MUST NOT be stored in plaintext.
- **FR-004**: Passwords MUST be hashed with Argon2id and satisfy a minimum length of 12 characters. The first login MUST NOT force a password change.
- **FR-005**: Admin Config MUST provide password change requiring the current password, a new password, and a matching confirmation. A successful change MUST revoke all sessions.
- **FR-006**: Admin UI pages and all administrative `/api/v1/portal/*` routes MUST require a valid database-backed session, except the Google OAuth callback, which MUST validate its existing state, and `/api/v1/portal/internal/*`, which MUST retain its own token checks.
- **FR-007**: Sessions MUST use a random opaque token in an HttpOnly, SameSite=Lax cookie, Secure when the trusted ASGI request scheme is HTTPS, expire after eight hours, and be revocable in PostgreSQL. Raw tokens MUST NOT be stored in the database.
- **FR-008**: Login and state-changing requests authenticated by cookies MUST require same-origin validation; state-changing requests MUST also require a valid CSRF token. Login failures MUST return generic errors and be rate-limited to five failed attempts per ASGI-resolved client IP in a rolling 15-minute window before password-hash verification. Concurrent password-hash work MUST be bounded per process. Application code MUST NOT trust raw client-supplied forwarding headers for the source address or scheme.
- **FR-009**: Logout MUST revoke the current session and clear its cookie. Expired, unknown, or revoked session tokens MUST NOT authorize requests.
- **FR-010**: `/api/v1/portal/config` MUST return only its safe configuration fields and MUST omit secrets and credentials, including OAuth tokens, client secrets, and API keys.
- **FR-011**: The new auth behavior MUST NOT change the existing security/ingress contracts of telephony/voice endpoints, Google OAuth callback, token-protected simulation endpoints, cron routes, `/health`, or Render log ingestion.
- **FR-012**: Automated tests MUST cover service, database/migration, HTTP, and browser contracts offline with synthetic credentials; no live provider operation is required for this feature.

### Key Entities

- **Admin account**: The single normalized login email, Argon2id password hash, timestamps, and account identifier.
- **Admin session**: A hash of an opaque browser token, creation and expiry times, and revocation state.
- **Login attempt window**: Failed attempts associated with the client IP and timestamp for throttling; attempted emails and passwords are not retained.

## Success Criteria

### Measurable Outcomes

- **SC-001**: Every admin page and data/configuration route denies access without an active authenticated session.
- **SC-002**: The admin can sign in with the developer-provisioned email/password and reach the dashboard; the session expires no later than eight hours after creation.
- **SC-003**: A password change can be completed in Admin Config and requires re-login; the previous password and all prior sessions are rejected afterward.
- **SC-004**: Unauthenticated and authenticated configuration responses contain no secret values or password material.
- **SC-005**: Focused tests and the full offline unit/integration and browser E2E suites pass without external provider calls.

## Assumptions

- The developer provisions and securely shares the initial password outside the application; the app does not transmit it by email or chat.
- The Render Python runtime's trusted proxy metadata supplies the public scheme and client address; any other deployment MUST configure its ASGI server to trust only its actual proxy layer.
- Password reset remains an operator action; no public forgot-password or email recovery flow is included.
- Login email changes and multiple admins are out of scope for v1.
- Admin login covers the existing operational dashboard and its data APIs; service ingress paths retain their existing authentication rules.
