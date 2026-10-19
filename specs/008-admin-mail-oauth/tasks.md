# Tasks: OAuth-only admin mail

## Phase 1: Setup
- [x] T001 Define requirements, acceptance criteria and scope in specs/008-admin-mail-oauth/spec.md.

## Phase 2: Foundation
- [x] T002 Verify source/config/test boundaries and document contracts in specs/008-admin-mail-oauth/plan.md and contracts/admin-mail.md.

## Phase 3: User Story 1 — Admin Mail settings
**Independent test**: Legacy settings render Google-only controls; save/reload persists preferences; connected/disconnected/provider-failed tests report correct results.
- [x] T003 [US1] Add failing validation, read/save and connection-test contracts in tests/test_gmail_oauth_only.py and browser journeys in e2e/test_admin_mail_oauth.py (FR-001–003, FR-005).
- [x] T004 [US1] Remove legacy API fields/defaults, validate Google-only requests and clean obsolete stored values in serviceBot/api/portal.py and serviceBot/config.json (FR-002–003).
- [x] T005 [US1] Remove legacy controls/handlers and display Google status/help in serviceBot/static/index.html and serviceBot/static/app.js (FR-001).
- [x] T006 [US1] Reconcile superseded Gmail API/subtab tests and e2e/test_voice_and_reporting.py while preserving OAuth encryption/masking and round-trip assertions (FR-002–003, FR-005).

## Phase 4: User Story 2 — Google notification delivery
**Independent test**: Legacy/missing selectors cannot use SMTP; Google routes, disabled/missing input behavior, fallback success and failure remain covered.
- [x] T007 [US2] Add failing notification routing/failure contracts in tests/test_gmail_oauth_only.py (FR-004–005).
- [x] T008 [US2] Remove SMTP helper/routing from serviceBot/services/gmail.py and reconcile tests/test_gmail_service.py and tests/test_sla_escalation_admin_email.py (FR-004).

## Phase 5: Validation and handoff
- [x] T009 Reconcile docs/specs/api_spec.md and run focused mail/service/API suites, affected browser/API acceptance and static validation per specs/008-admin-mail-oauth/quickstart.md (FR-005).
- [x] T010 Review all requirements, plan and tasks with convergence; record evidence in specs/008-admin-mail-oauth/validation.md.

## Dependencies and execution
T001 → T002 → T003 → T004/T005 → T006; T007 precedes T008; T009 follows both stories and T010 follows validation. All failing tests are added/run before application changes. T003 browser and service contracts can be prepared independently; execute serially in the shared checkout. Both stories are required for removal; no partial UI-only MVP. No agents or external actions are needed.

## Phase 6: Test sufficiency review
- [x] T011 Strengthen tests/test_gmail_oauth_only.py to preserve Google client credentials and assert failed booking delivery never selects SMTP or claims success (FR-002, FR-004).
- [x] T012 Exercise actual mail encoding and authentication in e2e/test_admin_mail_oauth.py by capturing only the Google HTTP transport; add persisted system/staff routing and provider-failure contracts in e2e/test_admin_mail_delivery.py (FR-003–005).
- [x] T013 Validate the exact admin-mail branch independently from other pending issues, then reconcile specs/008-admin-mail-oauth/validation.md and run convergence again (FR-005).
