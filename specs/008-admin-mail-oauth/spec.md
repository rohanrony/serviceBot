# Feature Specification: OAuth-only admin mail

**Created**: 2026-10-19
**Status**: Accepted for local implementation
**Input**: "for admin mail, can we remove the legacy auth?"

## User Scenarios & Testing

### User Story 1 - Configure admin mail with Google (Priority: P1)

An administrator uses the existing Google connection to configure and test mail without choosing an authentication method or entering an app password.

**Why this priority**: Removes obsolete configuration and its delivery path.
**Independent Test**: Open Admin Mail, save preferences, reload, and test mail using an isolated provider.

**Acceptance Scenarios**:
1. Given old app-password settings, opening Admin Mail shows Google connection status and help with no SMTP controls. Saving and reloading preserves recipient, enabled state, and manual agent selection.
2. Given a connected account, a test sends through Google and reports success only on a successful send. A disconnected account or provider failure displays an actionable error.
3. Given a request selecting legacy or unknown authentication, saving or testing rejects it without changing configuration or sending mail.

### User Story 2 - Deliver notifications through Google (Priority: P1)

Existing booking and admin notifications use Google authentication even when older configuration contains a legacy selector.

**Why this priority**: Removing the selector must also remove the executable legacy path.
**Independent Test**: Exercise notification delivery with synthetic OAuth and SMTP boundaries.

**Acceptance Scenarios**:
1. Given old or missing auth settings, notifications use the existing Google delivery paths and never open an SMTP connection.
2. Given disabled mail or missing addresses, delivery returns failure without a provider call. Admin Google failure retains the existing connected staff-account fallback and reports failure if none can send.

### Edge Cases

- Old stored passwords are ignored and removed when admin mail settings are saved; existing Google credentials remain intact.
- A blank sender in settings preserves the account identity established by Google authorization.
- Omitted authentication selector uses Google. Unknown selectors and submitted SMTP fields are rejected.
- No deployment, real email, account disconnection, or credential revocation is included.

## Requirements

### Functional Requirements

- **FR-001**: Admin Mail MUST show only the Google connection flow, status, recipient preferences, and applicable help.
- **FR-002**: Settings reads MUST identify Google authentication and omit SMTP settings/password indicators. Saves MUST reject unsupported auth or SMTP fields, preserve OAuth credentials and unrelated preferences, and remove stored SMTP configuration on successful save.
- **FR-003**: Connection tests MUST use Google only, reject disconnected accounts, and report provider failure truthfully.
- **FR-004**: Booking and admin delivery MUST remove SMTP use, including when old configuration selects it, and retain current Google account routing/fallback.
- **FR-005**: Focused offline service/API tests and browser acceptance tests MUST cover these changed contracts before completion.

### Key Entities

- Admin mail preferences: enabled state, sender identity, recipients, agent-selection preference, existing Google credentials.

## Success Criteria

### Measurable Outcomes

- **SC-001**: Admin Mail offers zero app-password or SMTP inputs on fresh and legacy configurations.
- **SC-002**: All supported save/test/delivery scenarios use Google authentication; unsupported requests have zero writes or sends.
- **SC-003**: Preferences survive reload and failed delivery never displays a success result.

## Assumptions

- "Legacy auth" means the SMTP App Password option currently labelled Legacy in Admin Mail.
- Existing Google OAuth configuration and staff-account fallback remain the supported integration.
- Live acceptance and deployment are separate from local implementation.
