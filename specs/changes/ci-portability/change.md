# CI portability regressions discovered by PR 6

Scope: finish the authorized workflow merge without bypassing the full-suite gate. These are
bounded fixes to established behavior and test isolation; no new feature specification or
active-feature selection is needed. PR: https://github.com/rohanrony/serviceBot/pull/6.

## Evidence and causes

The first hosted run (39350284586, integration candidate
30e45e6ca89b24fedf0f0f579f2c7d263266ffeb) retained 1,950 passing/3 failing unit tests and
607 passing/2 failing/20 setup-error E2E cases. The complete gate and aggregate failed.

Reproducing locally with UTC host/database time and password-authenticated disposable
PostgreSQL produced the same three unit failures, two E2E failures and observer setup error:
- Legacy tests mixed host-local date/now with the configured business clock.
- The portal returned only naive wall-clock booking fields; Chromium in UTC interpreted
  them as UTC before formatting in the business zone, showing 06:00 for a 10:00 booking.
- An aware as-of timestamp was compared against a naive business cutoff; PostgreSQL's UTC
  session conversion caused escalation before the actual deadline.
- psycopg2 connection.dsn masks passwords. Reusing it for the read-only simulation observer
  failed authentication. A direct synthetic-credential probe confirmed this behavior.

## Fix and contracts

Preserve existing booking_time/start/end wall-clock fields and persisted reservations. Add
explicit booking_start_iso/booking_end_iso instants and prefer them in the booking table.
Normalize aware cutoff-query inputs into business wall-clock time before the SQL comparison.
Do not change cutoff duration or dispatch provider effects.

Freeze legacy test clocks and derive due/expected times from them. Pin isolated verifier
runtime and default browser fixtures to UTC; explicitly exercise UTC and Los Angeles browsers.
Use the fixture-owned authenticated database URL for the real read-only observer, preserving
its database ownership and read-only checks. No production credentials or state are involved.

## Red and Green

Before application fixes, the expanded browser/deadline regressions produced 4 failures and
1 pass; the isolated-runtime UTC regression failed. Existing CI failures and local reproductions
are retained in downloaded CI evidence and scratch logs.

Focused Green: 46 unit/gate cases and 62 E2E cases passed under UTC and password authentication.
The browser cases assert fresh API timestamps, both technicians/windows and reload persistence.
Deadline cases retain just-before and exact-boundary assertions for business/UTC/naive inputs.
Retry backoff is strengthened to exact frozen-clock equality. No skip/xfail or weakened
assertion was introduced.

The final committed candidate must receive a new complete local receipt and current CI and
Codex review. Prior 4c9386d evidence does not authorize publishing these new source changes.

Live acceptance: not required for the new clock/serialization and fixture contracts. Provider
request/response shapes and effects are unchanged; no live-provider verification or deployment
is claimed. Existing provider acceptance obligations remain separate.

## Coverage reference correction

Release verification of `a45a4e4` completed 2,401 unit/integration tests and 679 E2E tests
without failures or skips, then rejected CI-AC3's obsolete C23 node identifier. C23 now has
separate successful cleanup and external-change refusal tests. Map CI-AC3 to both collected
tests so the authenticated read-only observer and cleanup contracts remain represented.
This corrects metadata only; application behavior and test assertions are unchanged.
Validate the references against the retained complete collection manifests and obtain a
new exact-candidate verification receipt before publication.
