# Application integration and minimal live validation

This integration combines the published escalated-assignment recovery and boundary tests,
validated reassignment dialog, OAuth-only mail, configurable business intake, canonical
multi-service booking/calendar handling, and exact catalog staff-membership repair.
Source commits: `4a1f6fa`, `ec8cce2`, `2512f84`, `525b3a6`, `b75ca1e`, `a0894a3`, `5140784`.
The validated reassignment dialog supersedes `acbfa28`; the earlier picker is not combined
with it. Shared conflicts retain the validated reservation owner, future-date calendar
fixture, dialog loading/retry/failure handling, and business-neutral labels.

The feature-verification workflow (`959d381` and `24fbdfc`), its hooks, CI, templates,
Spec-Kit changes, and uncommitted full-simulation/webhook work are excluded. Existing
`run_tests.sh --verify` runs the complete unit/integration and E2E suites. Browser journeys
are counted within E2E. No GitHub Actions checks or branch rules currently exist; their
introduction remains outside this integration.

## Updated acceptance

The application branches add observable API/database, migration, captured-provider, and
Chromium regression tests for the changed features. The expanded reassignment browser
boundaries use the current explicit dialog and POST endpoint while preserving unavailable
candidate, no-write, escalation recovery, notification, and reload assertions.

C01-C06 remain the complete minimal appointment/callback create/move/cancel selection.
Their live provider evaluators additionally check configured intake/terminology, failure
and unknown-calendar guidance, callback consent, saved scheduling outcomes, and exact
native evidence before claiming message delivery. Selection, one-pass behavior, credit
limits, ledger, booking preservation, and no-retry rules are unchanged.

This six-case suite is deployed conversation/API smoke. It does not establish live
supervisor reassignment, generic custom-intake mode, multi-specialist booking, Gmail inbox
receipt, handset delivery, native calendar persistence, or full native acceptance. Those
features retain their focused offline regression coverage and separate live requirements.
A successful smoke lifecycle can still report overall `incomplete` with missing evidence.

## Live readiness

Run preview and read-only `--check` against the prepared private config before paid work.
Use the existing shared usage ledger and preserve the designated customer's original
bookings. Never widen recipients, replace the customer identity, replay paid submissions,
or create a replacement campaign authorization merely to bypass readiness.
The retained six-case estimate is 6,528 credits; the ordinary minimal ceiling is 1% of the
monthly allowance. A larger one-pass ceiling requires explicit new user authorization;
previous campaign approval is consumed and is not reused. WhatsApp/email/application
model charges remain separate. Verify the exact merged deployment before any paid case.
