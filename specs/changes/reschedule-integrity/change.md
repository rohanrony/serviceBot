# Reschedule integrity and duration truthfulness

Route: bug fix. Restore established atomic booking and truthful-confirmation rules.
Base: c25e99f, isolated branch fix/multiservice-reschedule-integrity-20261020.

## Diagnosis

Read-only production evidence collected 2026-10-20 approximately 15:53-16:00 UTC.
Window: 15:20-16:00 UTC (11:20-noon America/New_York). Latest call
conv_9101m5czfw2ten0v9w3vjde4m0w4 started 15:39:43 UTC, lasted 570 seconds.
Private provider payloads are outside Git in a mode-0700 temporary directory.

The initial lookup already returned appointment 71 as a generic Repair appointment:
60 minutes, no service snapshot, no visit group, with the two exact requested
catalogue labels only in issue_description. It was created 2026-10-19 18:51 UTC,
before the corrected multi-service parser was deployed that evening. The live
Render deployment is b496089af1d088e0285c139577156349e8851395, finished
2026-10-20 04:05 UTC; the parser fix is present in the inspected current source.

The call obtained catalogue estimates of 90 and 120 minutes, checked availability
for those labels, then rescheduled the old request to 2026-10-21 14:00. The domain
preserved its existing 60-minute duration and single technician. The tool returned
success without any saved duration or component receipts. A subsequent lookup
again returned 60 minutes. The agent nevertheless asserted the full 210 minutes
was reserved and invented an initial check-in explanation.

Confirmed causes: pre-fix data persisted without repair; rescheduling did not reject
this inconsistent service scope; response omitted authoritative capacity details;
the model substituted a catalogue quote for saved state even after contrary read-back.
This is not evidence that notifications shortened a correct reservation.

## Contracts

- AC1: A generic legacy appointment whose description exactly names multiple
  catalogue services cannot be silently moved as one generic appointment. Reject
  before mutation; preserve requests, reservations, segments, slots, audit and outbox.
  No automatic reinterpretation, split, replacement booking or production data repair.
- AC2: Reschedule success requires exact True plus fresh owned request/reservation/
  segment evidence for every selected visit member. Preserve service identity,
  snapshotted duration and relative offsets. Return actual component windows and
  total saved service minutes; provider projection/delivery remains unverified.
- AC3: Appointment lookup summaries state recorded duration. Catalogue duration is
  an estimate, never proof of reserved capacity. Report mismatches honestly and
  offer advisor review with explicit consent; never invent a check-in explanation.

## Verification

Red: 11 focused unit cases fail on the intended false-success or missing-receipt
assertions before application changes. Database/browser Red is recorded separately.
Green: 15 focused unit and 10 HTTP/database/browser/provider-worker regressions
passed, including both Chromium reload cases. Another 96 existing voice, ownership,
phone and notification tests passed with realistic persistence-boundary fixtures.
Complete final `./run_tests.sh --verify`: **2,416 unit/integration and 689 E2E
cases passed**, zero failures/errors/skips; both exits 0. The E2E total includes
Chromium journeys. Static validation passed 335 Python files, 8 shell files and
application JavaScript. Diff checks, the project acceptance-matrix validator,
collected test IDs and maintained live scenario references also passed.

Local review: no remaining actionable findings in this bounded change. Inspected
transaction rollback, preserved service snapshots/relative offsets, complete native
segments, no duplicate retries, queued component windows, and privacy-safe failure
responses. The guard intentionally targets generic legacy Repair rows with complete
canonical multi-service descriptions; it is not a migration or broad historical
free-text reinterpretation. Actual agent speech and provider delivery remain Live
pending until the candidate and prompt are published and RS01-RS03 run under
separate authorization with resolved estimates/cap.

Offline: verified. Live: pending. Committed/Pushed: no. Merged: no. Deployed: no.
No exact committed-candidate publication gate was run because publication was not
requested; these are local worktree results.

The initial full run exposed a pre-existing closing-time fixture error in
`test_book_appointment_vehicle_resolution_and_no_overwrite`: it selected slots for
60 minutes but booked a 90-minute service. Reproduced on clean c25e99f. The test-only
correction selects slots for the longest service; every booking assertion remains.
The corrected individual baseline test passes.

Coverage: AC1-AC3 in neighboring `test-coverage.yaml`; maintained manual provider
acceptance cases RS01-RS03 in `live-scenarios.json`. The fixed C01-C50 campaign is
unchanged. No live scenario execution or spending is authorized.

## Operational limits

No production writes, provider changes, paid simulations, commit, push, merge or
deployment are authorized. Existing appointment 71 remains incorrect and needs a
separate reviewed repair with both specialists' current capacity checked. Read-only
call history and application rows prove the incident, not repaired live delivery.

Graph evidence: indexing was attempted but the MCP allowed-root boundary rejected
this repository. Structural claims were checked against exact source instead.
