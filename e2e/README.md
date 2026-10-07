# E2E acceptance suite

The original 17 tests did **not** cover the app's functionality. They mostly
checked navigation and visible controls; several claimed persistence without
checking the backend. The expanded suite contains 215 cases using Chromium,
real HTTP, the app's domain services, and disposable PostgreSQL.

Read [COVERAGE.md](COVERAGE.md) for the review, known failing requirements, and
the remaining acceptance checklist for reimplementation. A green run alone
does not mean the entire product is covered.

Read [NOTIFICATIONS.md](NOTIFICATIONS.md) for the 31 action-to-provider-request
cases, four confirmed notification defects, and the separate live-delivery gate.
Read [ACCEPTANCE.md](ACCEPTANCE.md) for the requirement-to-test contract and
[KNOWN_FAILURES.md](KNOWN_FAILURES.md) for all 27 currently failing cases.

## Run

Install the application and browser test dependencies:

```bash
.venv/bin/python -m pip install -r requirements.txt -r e2e/requirements.txt
.venv/bin/python -m playwright install chromium
```

Start local PostgreSQL. The local database role needs `CREATEDB`; the supplied
database name must end in `_test`, and its host must be loopback.
The supplied database need not exist: its URL specifies connection parameters.
The harness connects to `postgres` to create its own uniquely named database.

```bash
TEST_DATABASE_URL=postgresql://localhost/voice_service_test ./run_tests.sh --e2e
TEST_DATABASE_URL=postgresql://localhost/voice_service_test ./run_tests.sh --e2e-headed
```

A custom local port or username can be included in `TEST_DATABASE_URL`.
Run E2E separately from the older `tests/` suite; collection rejects a mixed
run because the fixtures have different database lifecycles.

Direct and focused invocations:

```bash
.venv/bin/pytest e2e -q
.venv/bin/pytest e2e/test_workflows.py -q
.venv/bin/pytest e2e/test_notification_workflows.py -q
.venv/bin/pytest e2e/test_portal_workflows.py --e2e-headed -v
.venv/bin/pytest e2e -q --junitxml=scratch/e2e-review.xml
```

## What executes

| File | Evidence |
| --- | --- |
| `test_portal_nav.py` | Dashboard, primary tabs, sidebar, mobile layout |
| `test_appointments.py` | Request rows, drawers, modal, search, persisted status |
| `test_services.py` | Catalog and persisted service creation |
| `test_config.py` | Matrix navigation, channels, persisted rule change |
| `test_sms_inbox.py` | Inbox component smoke checks |
| `test_portal_workflows.py` | Request create/edit, catalog edit/delete, real thread filters, reply/resolve, configuration save, every subtab, knowledge file workflow, failed-save feedback |
| `test_workflows.py` | Booking concurrency/validation, reservation capacity, consent, reschedule, cancellation, assignment, staff/calendar CRUD, knowledge lifecycle, configuration, SMS state, call history/webhook replay |
| `test_integrations.py` | Signed provider requests, replay conflicts, SMS keywords/agent confirmation, delivery statuses, call-recovery pagination, cron auth, outbox/reminder/quiet-hours effects, secret masking, OAuth state |
| `test_voice_and_reporting.py` | Wrapped/flat voice intake, same-call updates, availability, provider failure, reporting counts/SLA/escalations, onboarding, Gmail settings |
| `test_notification_workflows.py` | Real lifecycle/voice actions through queue, worker, real Twilio SDK and captured HTTP; signed callbacks, suppression, retries, concurrency/recovery, generated reminders and quiet-hours release |
| `test_booking_contracts.py` | Exact lead-time and business-window boundaries, duration/contiguous capacity, busy/all-day calendars, consolidation atomicity/ownership, concurrent same-call intake, caller context, after-hours handoff |
| `test_reminder_contracts.py` | Frozen-clock horizon cadence, business-hour deadlines, DST, cutoff/morning grace, timeout/decline alerts, late confirmation, reassignment window, terminal suppression, generated reminder retry/backoff |
| `test_google_contracts.py` | Captured OAuth success/failure, encrypted persistence, single-use/expired/unissued state, token refresh/rotation/revocation and disconnect |
| `test_notification_edges.py` | Manual retry body/channel integrity, cross-channel partial delivery, opt-out after queueing, missing production credentials |

A write is checked through the HTTP response and a fresh API read; browser
workflows also reload when persistence is part of the requirement. Negative
cases verify that rejected actions preserve the previous state.

## Isolation and evidence limits

- Every session creates `voice_e2e_<random>_test`. Only that database is reset
  between cases and dropped at teardown; the supplied database is never reset.
  Both hostname and address are pinned to loopback, including when libpq
  address overrides are present.
- Every case uses synthetic customers, staff, messages, and future Eastern
  business dates. It does not depend on developer seed data or prior runs.
- Configuration, system prompts, and knowledge files use pytest temporary
  directories. `.env` loading is disabled before app imports.
- Provider credentials are cleared. The legacy active-secret resolver is
  stubbed because it hardcodes the developer configuration path.
- Google event retrieval returns an explicitly empty provider calendar by
  default. Tests can substitute unavailable state. Local booking, reservation,
  availability, status, query, and worker logic remain real.
- Chroma storage is an in-memory collection boundary. Real FAQ chunking and
  deletion execute, but embeddings and generated answers are not evaluated.
- Twilio's existing test dispatch mode is used. `SENT` in these tests is a local
  simulation; signed delivery callbacks are tested separately.
  The notification workflow file deliberately bypasses mock-success only after
  installing fake credentials and a final HTTP capture. It asserts actual SDK
  requests and signed callback read-back; no request reaches the provider.
  The reminder and notification-edge files reuse this captured SDK boundary.
- Business-time scenarios replace clock reads, not validators or schedulers.
  PostgreSQL's clock remains real; queue recovery tests advance only the due
  timestamps of records generated by actual actions. No timing sleeps are used.
- Unexpected Python outbound HTTP/sockets fail; external browser assets are
  aborted. The voice-list response and call-recovery responses are synthetic.
- Production lifespan workers do not start under pytest. Tests invoke worker
  cycles or cron routes explicitly; deployment startup is a separate gate.
- Server shutdown is joined before fixture teardown. Failed browser cases save
  `failure.png` in that case's pytest temporary directory. The old
  `screenshots/` files are historical artifacts, not results from this run.

`scripts/validate_customer_flow.py` and `scripts/inspect_calls_history.py` are
separate live operational tools. They are not invoked by this suite and do not
supply E2E coverage evidence.

## Review validation

On 2026-10-06, the complete suite ran against a disposable PostgreSQL cluster
and local Chromium: **97 passed, 0 failed**. The three application defects described
in [COVERAGE.md](COVERAGE.md) (local reservation availability, cancellation capacity release,
and failed notification-matrix save feedback) have all been resolved and verified green.

On 2026-10-07, the expanded **128-case** suite ran in full: **124 passed,
4 failed**. The new 31-case notification file passed 27 cases and exposed four
implementation defects documented in [NOTIFICATIONS.md](NOTIFICATIONS.md).
They remain ordinary failures; no application fixes were made in this extension.
The machine-readable report is `scratch/e2e-review.xml`.

The subsequent test-only expansion on 2026-10-07 added 87 cases. The complete
**215-case** run produced **188 passed, 27 failed**, with no skips, expected
failures or fixture errors, in 66.34 seconds. Failing behavior is indexed in
[KNOWN_FAILURES.md](KNOWN_FAILURES.md). Application code was not changed.
Live conversation/retrieval, operational and provider-delivery gates remain
explicit in [ACCEPTANCE.md](ACCEPTANCE.md); no full-product certification is claimed.

Ruff lint/formatting, Python syntax parsing, and shell syntax checks passed.
Bandit and MyPy are not installed in this environment and were not run.
Existing deprecation warnings are in app code.
No live provider messages, phone calls, OAuth connections, or deployments were
performed.
