# Restore manual staff selection in new service requests

Route: bug fix. Restore the existing `enable_agent_selection` setting's browser behavior;
no new booking, assignment, authorization or provider semantics.

Publication workspace: `/Users/rohanroy/Coding/voiceService/.worktrees/manual-staff-agent-selection-publish`, branch `fix/manual-staff-agent-selection`,
base `origin/main` at `c04d72c8b237820ef72e7c5da2c5bf747327b54f`.
Original implementation started from `33e08f753b81df255dbdee43cd1f4b82d067b9b8` in `/Users/rohanroy/Coding/voiceService/.worktrees/manual-agent-without-appointment`.
The source checkout contains unrelated changes and is preserved.

## Diagnosis

The new-request handler in `serviceBot/static/app.js` fetches `/gmail-config`, reads
`enable_agent_selection`, populates `sr-agent-select`, uses it in availability lookups,
and submits `staff_agent_id`. `serviceBot/static/index.html` contains none of
`sr-agent-select`, `sr-agent-select-container` or `sr-auto-assign-text`; it always
displays automatic-assignment help. The setting therefore cannot expose the selector.
`BookingService.create_portal_request` already persists a requested staff agent without
a booking time and reserves the selected agent when a booking time is supplied.

The user clarified that "No" meant "check slot". The regression follows the reported
sequence: open a new request, enter a date, check availability, choose a staff agent,
then refresh availability for that agent. Saving without a selected slot and declining
the save confirmation are additional persistence/cancellation invariants.

Graph discovery was attempted: the project was absent from `list_projects` and indexing
was denied because the checkout is outside the graph service's allowed root. Coverage
lookup did not return; all diagnosis uses exact source fallback, not graph completeness.

## Acceptance and invariants

- AC1: A persisted enabled setting exposes active staff selection on new requests,
  including after choosing a date and checking slots. A saved request retains
  the chosen agent through a fresh API read and browser reload.
- AC2: With a returned appointment slot, availability and reservation use the chosen
  agent. Declining save confirmation leaves durable state unchanged and retains selection.
- AC3: A disabled setting retains automatic assignment and clears previous manual choices.
- AC4: Existing-request edits retain their saved staff agent for availability; a cancelled
  new-request choice must not leak into edits or later new requests.
- No appointment slot means no reservation, calendar capacity use or booking effects.
- Preserve existing date-first scheduling, consent rules and validated reassignment flow.

## Evidence

Regression: `tests/test_manual_agent_selection_markup.py` and six collected cases in
`e2e/test_manual_agent_selection.py`. The latter use real Chromium, HTTP and disposable
PostgreSQL with existing offline provider boundaries.

- Red: direct execution of the permanent markup unittest failed because the form has no
  `sr-agent-select`; retained at `scratch/manual-agent-markup-red.log`.
- Green: the same unittest passes after restoring the labeled, optional selector;
  `scratch/manual-agent-markup-green.log`. JavaScript syntax, Python compilation and diff
  checks pass.
- Implementation restores the setting-controlled dropdown; new requests clear previous
  choices and wait for fresh staff data. Edits preserve their saved agent; late configuration
  and staff-list responses are bounded by the modal generation.
- The full `TEST_DATABASE_URL=postgresql://127.0.0.1/voice_service_test ./run_tests.sh --verify`
  was attempted: 520 unit tests passed; 1,967 unit setup errors and 720 E2E setup errors
  resulted from sandbox-denied loopback PostgreSQL access (`Operation not permitted`).
  Reports: `scratch/manual-agent-verify.log`, `scratch/manual-agent-sandbox-unit.xml`,
  `scratch/manual-agent-sandbox-e2e.xml`. These are environment failures, not a passing application gate.
  The final loading-state refinement and its additional browser test followed this attempt;
  the final complete gate was therefore rerun in the authorized execution context below.
- A direct sandboxed Chromium launch also failed at macOS `bootstrap_check_in` permission checks.
  Elevated focused browser execution subsequently passed all six cases in 12.59 seconds;
  `scratch/manual-agent-focused.log` and `scratch/manual-agent-focused.xml`. These cover
  the clarified check-slot flow, scheduled and unscheduled persistence/reload, disabled
  setting, edit isolation, late responses and loading fresh staff choices. The first
  browser attempt had three fixture-validation failures (missing required mail-setting
  fields); its corrected settings payload passed. Final review then strengthened Cancel
  snapshots to include customers, vehicles and audit rows, and checked all new reservation
  rows/statuses; all strengthened assertions passed in the complete gate below.
- Static review found no remaining actionable issue in the bounded UI diff after adding
  modal/assignment isolation and clearing/disabling choices while staff data loads.
  No remaining actionable review findings in this scope.
- Complete final gate: `./run_tests.sh --verify --tb=short` exited 0. Unit/integration:
  2,487 passed (159.75s); E2E: 721 passed (343.59s), including all six browser regressions
  with the final cancellation/reservation assertions. Both reports contain zero failures,
  errors or skips. Reports: `scratch/unit-results.xml` and `scratch/e2e-results.xml`.
  `scratch/manual-agent-verification.json` records workspace, base HEAD, branch, test totals
  and final application/test SHA-256 hashes. Static syntax/diff and coverage validation pass.

Coverage: neighboring `test-coverage.yaml`. No live provider assertion changes, external
calls, publication or deployment are required for this DOM/control lifecycle fix.

Offline: verified for this uncommitted working tree. Live: not_required; this is a UI/control
lifecycle fix with unchanged provider contracts and no live provider effects claimed.
At the implementation handoff: uncommitted, unpushed, unmerged and undeployed.
Publication is now authorized for the selected fix branch; merge/deploy remain separate.

## Publication selection

Publish only the eight fix/test/record paths on `fix/manual-staff-agent-selection` from `c04d72c8b237820ef72e7c5da2c5bf747327b54f`.
The source parent `33e08f753b81df255dbdee43cd1f4b82d067b9b8` contains a separate prompt/RAG change and is
deliberately absent from this publication branch. The existing source checkout and
implementation worktree are preserved. The script query is advanced to `v=48` so
browsers load the corrected modal lifecycle with the restored HTML selector.

The implementation counts above describe the original source-base validation, not
a publication receipt. Before any push, `scripts/git_push_merge.sh` commits only the
selected paths, fetches the target and runs the complete exact-candidate verifier.
Its immutable head/base receipt is stored at
`scratch/verification/<head>-<base>/receipt.json`; the pre-push checks require it.
Final commit/push status is reported after that gate, without modifying the tested commit.

### Deterministic fixture needed by the publication gate

The first exact candidate `2c77923` retained the existing main-branch reminder test's
wall clock. Its fixed appointment (`2026-10-25 14:00`) had already passed, so the
assertion requiring future pending attempts failed: 1 failed, 2,479 unit tests passed.
All 719 E2E tests passed on this candidate, including all six manual-selection cases.
The failure is independent of manual staff selection; no application code changed here.
Retain the failed receipt under `scratch/verification/2c77923f92ffa5d646b9cc18fbf13de7bcfa4648-c04d72c8b237820ef72e7c5da2c5bf747327b54f/`.

Freeze only `sms_reminders.get_current_business_time` to `2026-10-24 10:00:00` during
booking and `10:00:30` during polling in the existing test. This is the same three-line
clock fixture correction already present in the original implementation base; the
unrelated prompt/RAG changes remain excluded. Keep every existing assertion for one
dispatch per recipient, SENT first attempts, PENDING future attempts and no duplicate
polling dispatch. Record this fixture contract as TEST-CLOCK-01 in the coverage matrix.
The corrected exact candidate must pass the complete publication gate before push.
