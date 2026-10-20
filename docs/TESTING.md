# Testing VoiceService

Use this guide to run the checks. The complete journey checklist and feature
matrix are in [the E2E test plan](../e2e/TEST_PLAN.md). Product fixes are separate
from test maintenance; unmet requirements remain ordinary failures.

## Setup and first run

Use Python 3.13 and local PostgreSQL. The database role needs `CREATEDB`; the
connection URL must use loopback and a database name ending in `_test`. The
named database need not exist. Both harnesses create and drop only their own
randomly named databases; the supplied database is never reset.

```bash
python3 -m venv .venv  # only if the environment does not exist
.venv/bin/python -m pip install -r requirements.txt -r e2e/requirements.txt
.venv/bin/python -m playwright install chromium
export TEST_DATABASE_URL=postgresql://127.0.0.1/voice_service_test

./run_tests.sh --verify
./run_tests.sh --browser --e2e-headed
```

Use your local PostgreSQL username/port if needed. No production credentials or
prestarted application server are required. Fixtures start the local HTTP server.
The runner also works when invoked by absolute path from another directory.

## Select a run

| Command | What runs |
| --- | --- |
| `./run_tests.sh --all` | All unit/integration tests |
| `./run_tests.sh --e2e` | All acceptance contracts, including real browser journeys |
| `./run_tests.sh --browser` | Only cases using the real browser page fixture |
| `./run_tests.sh --browser --e2e-headed` | Browser journeys in a visible window |
| `./run_tests.sh --e2e-contracts` | HTTP/worker acceptance contracts without browser startup |
| `./run_tests.sh --features` | Recent features and permanent defect regressions |
| `./run_tests.sh --verify` | Unit/integration then complete E2E in separate processes, even if the first fails |

Additional pytest arguments are forwarded:

```bash
./run_tests.sh --features -k 'tag or timezone' --tb=short
./run_tests.sh --file e2e/test_multiservice_contracts.py -x
./run_tests.sh --browser --e2e-headed -k recording
./run_tests.sh --all -k cancellation
.venv/bin/python -m pytest e2e --collect-only -q
```

Run `tests/` and `e2e/` separately: mixed collection is rejected because their
database lifecycles differ. Do not use xdist/`-n`; worker-parallel isolation is
not established. Concurrency cases manage their own competing operations.

## Results and failure debugging

Failures return nonzero; requirements are not skipped or marked expected-failure.
Read [KNOWN_FAILURES.md](../e2e/KNOWN_FAILURES.md) for the observed defect inventory.
The runner writes JUnit reports under `scratch/`: `unit-results.xml`,
`e2e-results.xml`, `browser-results.xml`, `contract-results.xml` and
`feature-results.xml`. Each selection replaces its report; pass
`--junitxml=scratch/my-run.xml` to retain a named run.

Failed browser cases save `failure.png`, `trace.zip` and `console.json` under
`scratch/e2e-artifacts/run-<time>-<id>/<case>/`. Open a trace with:

```bash
.venv/bin/python -m playwright show-trace scratch/e2e-artifacts/<run>/<case>/trace.zip
```

Traces include DOM snapshots, requests and screenshots using synthetic data.
The old `e2e/screenshots/` files are historical. For an API failure, rerun the
exact pytest node with `-v` and inspect its response and durable-state assertions.

## Test boundaries and isolation

E2E keeps routes, validation, transactions, reservations, local calendar capacity,
reminder generation, outbox workers and persistence real. Each case gets fresh
synthetic PostgreSQL records and temporary config/KB files. Browser writes are
checked through fresh API reads and document reloads. Clock tests patch the
central timezone clock as well as its consumers, rather than validators.

Provider calls are mocked or captured. Notification tests can use the real
Twilio SDK with fake credentials, captured HTTP and signed synthetic callbacks.
Google OAuth/token requests and ElevenLabs config sync are captured. Google
events default to a successful empty calendar, and dedicated cases substitute
busy/unavailable calendars. Knowledge file/chunk logic uses an in-memory Chroma
boundary. External sockets and unexpected HTTP are blocked; browser external
assets are aborted. Production workers do not start under pytest: tests invoke
worker cycles explicitly.

Legacy unit tests retain their existing service mocks and one seeded database
per session. They do not claim per-test database independence; new cases need
explicit reset/setup/cleanup. Exact developer config/prompt paths are redirected
to temporary files for old hardcoded readers. The harness does not read `.env`
and replaces inherited provider credentials with synthetic values. No shared
database sessions are terminated and no setup failures are swallowed.

## Add or improve coverage

1. Identify the requirement in [TEST_PLAN.md](../e2e/TEST_PLAN.md), the feature
   spec or [ACCEPTANCE.md](../e2e/ACCEPTANCE.md). Define its observable outcome.
2. Add the lowest useful unit/API test and a real browser test for changed browser
   journeys. Reuse isolated fixtures and synthetic data.
3. For writes, assert fresh durable state; for rejection, compare related state
   before/after. For notifications, drive action through queue/worker to captured
   provider request and callback; a queued row alone is partial evidence.
4. Cover success, boundaries, failed saves/dependencies and relevant races. Advance
   `freeze_business_clock`; do not sleep or replace domain validators.
5. Run focused tests, relevant full suites and affected browser journeys. Retain
   failing requirement tests when product fixes are separate, then update the
   coverage map/failure inventory with observed results.

Application behavior changes follow [SPECKIT_WORKFLOW.md](SPECKIT_WORKFLOW.md).
Test maintenance does not authorize product changes, live messages or deployment.
Before publication, use the exact-commit gate in [MERGE_READINESS.md](MERGE_READINESS.md):
`./scripts/verify_change.sh --base <target-ref> --head <commit-sha>`. Focused runs and old
JUnit files do not establish publication readiness. Store acceptance obligations in the
feature's `test-coverage.yaml` before implementation and review assertion quality afterward.

## Multi-service booking regression contracts

The reported brake/suspension visit must retain the full catalogue labels, create
one linked appointment per selected technician, and reserve 90 then 120 minutes.
The tests use the actual voice HTTP routes, booking service, disposable PostgreSQL,
outbox worker and Chromium. Only external provider boundaries are replaced.

| Requirement | Evidence |
| --- | --- |
| Preserve punctuation within catalogue names and reject ambiguous matches | `tests/test_canonical_service_names.py` covers delimiters, longest labels, order, duplicates and unmatched remainders. |
| Resolve all services through either booking tool, including intake with only issue text | `e2e/test_canonical_multiservice_booking.py` reads linked rows, canonical component snapshots, technician IDs, reservation spans, every 15-minute segment and both queued effect payloads. |
| Reject a blocked or unverifiable second technician without saving the first appointment | The same acceptance module compares requests, reservations, segments, outbox, vehicles and local calendar slots before/after. Disconnection and provider exceptions must produce an explicit unconfirmed outcome without leaking provider diagnostics. |
| Prevent duplicate bookings on same-call retries | Cross-tool retries must preserve the complete saved visit and leave all scheduling/effect state unchanged. Repeated services must be rejected rather than silently removed. |
| Notify customers with the saved service windows | A booking drives the real queue, worker and Twilio SDK to captured HTTP. Each service's customer message must name its technician and correct start/end times; another worker pass must send nothing again. A rejected booking must dispatch no confirmation. |
| Show the recorded outcome after a browser reload | The successful browser journey looks up both services, checks availability, books via HTTP, and verifies both technician rows and windows. A rejected calendar lookup leaves no requested visit visible after reload. |
| Preserve existing lifecycle and race contracts | `e2e/test_multiservice_contracts.py`, `e2e/test_grouped_service_components.py` and the session-outcome suites retain concurrency, closing boundaries, reschedule, cancellation, selected-service removal and retry coverage. |

Run the isolated layers separately so their database lifecycles stay independent:

```bash
./run_tests.sh --file tests/test_canonical_service_names.py tests/test_booking_confirmation_guard.py tests/test_session_booking_outcomes.py tests/test_db_queries.py tests/test_multiservice_duration_consistency.py tests/test_multi_service_scheduling.py tests/test_service_agent_availability_and_timezone.py tests/test_truthful_voice_outcomes.py tests/test_transactional_booking.py tests/live_simulations/test_runtime.py tests/test_grouped_visit_agent_policy.py
./run_tests.sh --file e2e/test_canonical_multiservice_booking.py e2e/test_intake_catalog_identity.py e2e/test_multiservice_contracts.py e2e/test_grouped_service_components.py e2e/test_truthful_portal_availability.py e2e/test_session_booking_outcomes.py
./run_tests.sh --file e2e/test_canonical_multiservice_booking.py -m browser
```

These files are discovered by the normal `tests/` and `e2e/` runners, including
`--verify`. Render's current bare `pytest` build command discovers `tests/` only;
passing that build does not establish browser acceptance. Captured provider
acceptance and outbox completion do not prove handset delivery, live OAuth/calendar
health, or that the deployed voice model speaks the failure guidance correctly.
Those remain separate live acceptance checks.

## Additional engines and live acceptance

Chromium is default. Explicitly install and run other engines if needed:

```bash
.venv/bin/python -m playwright install firefox webkit
./run_tests.sh --browser --e2e-browser firefox
./run_tests.sh --browser --e2e-browser webkit
```

Installation is not evidence that an engine's tests passed. Real phone calls,
message delivery, OAuth accounts, model conversation quality, retrieval quality,
migration/restart/load and accessibility have separate instructions and evidence
requirements in [TEST_PLAN.md](../e2e/TEST_PLAN.md).
