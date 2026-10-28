# Portal loading responsiveness: implementation review

Date: 2026-10-27 UTC. Verdict: **Changes required; not Green.**

## Workspace and review scope

- Worktree: `/Users/rohanroy/Coding/voiceService/.worktrees/portal-loading-responsiveness`
- Branch: `codex/portal-loading-responsiveness`
- HEAD/base: `c7b4d4ee37d89e322033b5bd34fb2c664fbd6539`
- Reviewed uncommitted application changes: `serviceBot/static/app.js`,
  `serviceBot/static/index.html`, `serviceBot/api/portal.py`, `serviceBot/db/queries.py`.
- Reviewed tests: new `e2e/test_portal_loading_responsiveness.py` and changed
  `e2e/test_portal_read_responsiveness.py`, against AC1–AC7 in [change.md](change.md).
- Review used direct source inspection, existing failure artifacts, isolated Node VM probes
  executing the actual changed loader source, and two focused offline E2E tests. Graph coverage
  was unavailable. This is a bounded correctness review, not an exhaustive audit.
- Application code was not edited by the reviewer. This document and the handoff update were
  subsequently authorized by the user's request for a write-up. No commit, push, merge,
  deployment, restart or live provider call occurred. Ignore local `.specify/worktree.json`.

Line references describe the reviewed uncommitted files and may move after fixes. An unchanged
HEAD does not prove that the working patch or its verification evidence remains unchanged.

## Findings and required corrections

### F01 — P2: Mutation-triggered dashboard reloads reuse stale data

**Source:** `serviceBot/static/app.js:1587`; successful-save caller at line 5691, with other
reload callers around lines 5240 and 5321. **Contracts:** AC2, AC3 and persisted read-back.

`readDashboardResource` returns immediately when `state.loaded && !force`. Existing save/edit
and service-removal paths still call `loadDashboardData()` without invalidation or force.
After initial load, a successful save can close its modal and show success while the table
and counts retain prior data. A pre-mutation in-flight request can also be reused.

**Evidence:** an isolated source probe loaded requests, then invoked the default dashboard
reload. The second invocation fetched calls only; `requestsWereRefetched` was false.

**Correction:** invalidate affected resources after a successful mutation and obtain an
authoritative post-mutation read. An outstanding pre-mutation response must not become final
state. Keep coalescing for equivalent reads.

**Regression:** create/edit a request or remove a component; verify table/counts against fresh
API state and full browser reload. Hold a pre-save GET, complete the mutation and current
refresh, then release the old response: the saved state must remain visible.

### F02 — P2: Rapid timeframe changes retain older totals

**Source:** `serviceBot/static/app.js:1586` and lines 1588–1595. **Contracts:** AC1, AC3.

The in-flight promise is returned before checking the requested timeframe. Selecting `all`
while `24h` stats are pending neither invalidates that response nor queues `all`. Older totals
and their badge can replace the new selection. The generation guard cannot help when promise
reuse does not advance the generation.

**Evidence:** the source probe selected `24h`, immediately selected `all`, and observed only
`/api/v1/portal/stats?calls_timeframe=24h`; no latest-timeframe request was made.

**Correction:** key ownership by the requested resource/timeframe. Remember the latest selection,
discard obsolete responses, and use cancellation or one bounded queued refresh for changed keys.

**Regression:** hold the first stats response, change timeframe, complete responses in controlled
order, and verify final totals/badge match the latest selection. Include late failure as well
as late success and assert bounded request counts.

### F03 — P2: Visible Analytics no longer refreshes on timeframe changes

**Source:** `serviceBot/static/app.js:1553` and `loadAnalyticsView` around line 5936.
**Contract:** AC3.

The old analytics change listener was removed. The replacement only filters dashboard tables
and calls the dashboard stats loader; it never calls `loadAnalyticsView`. With Analytics visible,
the dashboard visibility guard also prevents the stats read. Charts and KPIs stay on the old
timeframe. The intended removal of hidden work must preserve visible analytics refresh.

**Correction:** route changes to the actually visible page. Also handle changed timeframe keys
while analytics is pending: unconditionally returning `analyticsPromise` can recreate F02.

**Regression:** active Analytics changes load/render the selected values; rapid changes keep
the newest values. Preserve Analytics -> Dashboard/Catalog checks for no hidden analytics GETs.
This finding is source-backed; no fresh browser Analytics reproduction was run in this review.

### F04 — P2: Old staff responses overwrite fresh catalog staff

**Source:** `serviceBot/static/app.js:1681` and lines 1692–1695. **Contracts:** AC3, AC5.

`invalidateCatalog` clears the staff promise reference and permits a new request, but the old
completion handler remains able to assign `cachedStaffAgents`, mark it loaded, and update
controls. A late old response can restore stale/deactivated staff after fresh data is displayed.

**Evidence:** a source probe completed the newer request with staff ID 2, then completed the
older request with ID 1. The final cache contained the older ID 1. These were synthetic values;
this does not establish an incident involving any production staff member.

**Correction:** give staff reads generation/key ownership. Guard success, error and finally
handlers so superseded requests cannot overwrite data or clear a newer in-flight promise.

**Regression:** hold old staff data, invalidate/revalidate, complete new data, then release old
data. Only current active staff may be selectable; current controls and saved tags must survive.

### F05 — P2: Call-history refresh failures have no visible Retry control

**Source:** `serviceBot/static/app.js:1591` and line 1602; the table around
`serviceBot/static/index.html:311` has no `calls-read-status` node. **Contract:** AC2.

The error handler targets a missing status container. `setReadStatus` silently returns when
the node is absent, leaving retained rows without the promised error/recovery UI.

**Evidence:** the focused browser rerun failed at
`e2e/test_portal_loading_responsiveness.py:233`: Retry count expected 1, observed 0.
This is a concrete failing result, not merely a stalled test runner.

**Correction:** add accessible calls error/stale status and a working section retry. Retain
saved rows. Align the test with that deliberate UI location: Retry need not be inside the
table, and the test must not rely on an unrelated toast happening to be visible.

**Regression:** fail calls only; assert its error and Retry, retained rows, no premature success,
successful retry, new rows and error clearance. Cover initial-load failure as well as refresh.

### F06 — P2: Create Service accepts unknown staff state as empty assignments

**Source:** `serviceBot/static/app.js:1871`–1882 and staff loading around line 1679.
**Contract:** AC4.

The create handler only checks its submit button's disabled state. Staff loading does not
disable that button or guard submission with `catalogStaffStatus`. While staff is pending or
failed, the empty checkbox query can become `agent_ids: []`. Unknown state is treated as an
intentional untagged service. This is source-backed; no create-service reproduction was run.

**Correction:** explicitly disable and guard staff-dependent create/edit submission while
staff is unknown/loading/failed. Successful empty data is a distinct valid state that permits
the existing no-tag behavior. Preserve entered form values through retry.

**Regression:** pending and failed staff reads cannot cause assignment POST/PUT; successful
retry enables safe editing; a successful empty staff list permits deliberate untagged creation.
Failed/cancelled mutations must preserve saved catalog state.

### F07 — P2: The reversed-response regression never creates a response race

**Source:** `e2e/test_portal_loading_responsiveness.py:262`–282. **Contract:** AC3 evidence.

`test_dashboard_latest_calls_response_wins_when_requests_finish_in_reverse` releases one
pending payload named `latest`, then asserts `stale` is absent. It never supplied a stale
payload or completed a newer response before an older response. It cannot prove its name's
contract or catch the missing generation behavior in F01/F02/F04.

**Correction:** retain a separate one-request coalescing test if useful. Add genuine stale-key
and mutation-invalidation tests with controlled ordering. Complete the current response first,
release the old response last, and assert visible/cache/persisted state stays current.

## Verification actually performed

The reviewer ran the following using synthetic loopback PostgreSQL, Chromium and offline
provider mocks. Test database provisioning is disposable and separate from production.

```bash
env -i PATH=/usr/local/bin:/usr/bin:/bin HOME=/Users/rohanroy TMPDIR=/private/tmp \
  PYTHON_DOTENV_DISABLED=1 PYTHONDONTWRITEBYTECODE=1 TESTING=1 LOG_FILE= \
  TEST_DATABASE_URL=postgresql://postgres@127.0.0.1:55432/voice_service_test \
  .venv/bin/python -m pytest \
  e2e/test_portal_loading_responsiveness.py::test_failed_dashboard_refresh_retains_rows_and_does_not_report_success \
  e2e/test_portal_loading_responsiveness.py::test_agent_and_request_whatsapp_enrichment_is_batched_and_fresh \
  -q --tb=short -p no:cacheprovider
```

Result: **1 failed, 1 passed in 5.95 seconds**.

- Refresh recovery failed: expected one Retry control, found zero.
- The standard-fixture WhatsApp batching/freshness case passed, including its query-count
  assertions. This does not establish all phone-normalization cases or all AC6 invariants.
- Browser failure evidence:
  `scratch/e2e-artifacts/run-20261027-150544-c3b3123e/test_failed_dashboard_refresh_retains_rows_and_does_not_report_success-9d896993/`
- Three isolated probes reproduced F01, F02 and F04 against the actual loader source. They
  are diagnostic evidence, not permanent browser regressions or production measurements.
- `git diff --check` passed. Workspace, branch, HEAD and dirty-file status were rechecked.
- Full focused suite, full `./run_tests.sh --verify --tb=short -q`, all AC1–AC7 contracts,
  trustworthy paint timings and comprehensive query-budget evidence remain **pending**.
- Live-provider acceptance remains **not_required** for unchanged provider semantics. Deployed
  performance confirmation is a separate pending diagnostic after authorized deployment.
- Committed/Pushed/Merged/Deployed: **no** for this change.

## Paste-ready implementation follow-up

```text
Resume in /Users/rohanroy/Coding/voiceService/.worktrees/portal-loading-responsiveness,
branch codex/portal-loading-responsiveness, base
c7b4d4ee37d89e322033b5bd34fb2c664fbd6539. Preserve existing work; do not reset/switch branches.

Read the constitution and specs/changes/portal-loading-responsiveness/
{change.md,test-coverage.yaml,execution-handoff.md,review.md}.
Resolve F01–F07 in review.md with permanent failing regressions before behavior changes.
Stay within AC1–AC7; preserve booking, provider, phone-matching and connection-pool semantics.
Use held/reversed responses, fresh persisted read-back, explicit loading/error/empty states,
and bounded request/query assertions. Do not weaken tests or substitute syntax/partial passes
for Green. You are not alone in the repository; preserve and accommodate others' edits.

Run focused loading tests and adjacent catalog/read/persistence/browser regressions, then
complete ./run_tests.sh --verify --tb=short -q offline. Keep tests/ and e2e/ as separate
lifecycles. Retain actual performance samples and query results. Update the coverage matrix,
handoff and finding dispositions with real test IDs and outcomes.

Return the same worktree for Codex re-review with HEAD, git status, remaining gaps and
separate Offline/Live status. Do not claim completion with relevant verification pending.
Do not copy/source production credentials/data, make live provider calls, commit, push,
merge, deploy, restart services or launch additional agents without separate authorization.
```

## Implementation follow-up (2026-10-27)

The executor addressed F01–F07 in the working tree and added permanent race/recovery coverage:

- F01: successful request mutations invalidate dashboard generations, abort pre-mutation reads,
  and start fresh reads. `test_pre_mutation_request_read_cannot_overwrite_successful_create`
  holds the old list response until after the persisted create is rendered.
- F02: stats reads are keyed by timeframe, obsolete fetches are aborted, and generation/timeframe
  guards prevent stale rendering. `test_dashboard_latest_timeframe_stats_response_wins_when_requests_finish_in_reverse`
  releases the newer response first and the older response last.
- F03: the shared timeframe handler refreshes Analytics only when that pane is visible; analytics
  request batches are keyed/aborted. `test_visible_analytics_refreshes_for_latest_timeframe`
  checks the latest visible KPI after older responses finish late.
- F04: staff reads use generation ownership for success, error and finally handling.
  `test_superseded_staff_response_cannot_replace_revalidated_staff` verifies the fresh staff list
  remains selectable after a held old response completes.
- F05: the calls section has an accessible status/retry control. The regression retains old rows,
  fails a refresh, retries, and observes replacement rows after success.
- F06: create and edit submissions are blocked while staff is unknown/loading/failed; create is
  visibly disabled, and loading/error replaces cached checkboxes with a local retry control.
- F07: the inaccurate one-response test was replaced by the real reverse-timeframe response race.

Focused verification after these changes: the six previously failing race cases passed (`6 passed
in 8.31s`); the final loading/error staff cases passed (`2 passed in 3.91s`). Earlier in the same
focused run, 32 cases passed and six failed before fixes; those six were then rerun successfully.
`node --check`, Python compilation, coverage YAML parsing and `git diff --check` passed. The
complete `./run_tests.sh --verify --tb=short -q` run is still pending; a prior attempt was
interrupted after its unit suite began so its partial dots are not counted as verification.
The seven finding dispositions are implementation-level only until complete offline verification
and independent review finish. The AC7 paint test passed in the focused run, but its timing samples
were captured by pytest and not retained in this record, so numeric evidence remains pending.

## Complete-run follow-up

`./run_tests.sh --verify --tb=short -q` completed with 735 E2E passes and three E2E failures, plus
three unit/integration failures. Two unit failures were existing customer-history date/fixture
expectations outside this portal scope. The third expected the `/agents` handler's final SQL call
to contain `is_active`; request-scoped WhatsApp batching now adds a second whitelist query, so that
assertion was updated to inspect all executed queries. Its isolated unit rerun is pending.

The three E2E failures were test synchronization: two catalog edits ran before the asynchronous
drawer/staff revalidation completed, and one staff-error assertion ran before the drawer opened.
Condition-based waits were added. Those three cases passed on rerun (`3 passed in 5.30s`). No final
full-suite pass is claimed; the two unrelated unit failures remain. Two independent read-only
reviews found no remaining source findings after the staff controls were corrected.

## Remaining unit-test follow-up (2026-10-27)

The updated `test_get_staff_agents_filters_out_inactive_agents` assertion was rerun against the
isolated worktree and passed (`1 passed in 1.72s`). The only known full-suite failures left are the
two customer-history tests listed above. Both use a confirmed appointment dated `2026-10-25`, while
the test run date is `2026-10-27`, but still expect that appointment to be upcoming. This makes the
fixtures time-dependent and stale. Fix the tests by freezing/injecting a deterministic application
clock (preferred) or constructing appointment timestamps relative to the controlled test clock;
keep assertions that one appointment is upcoming and that inbound variables include Battery
Replacement/Kia Forte. Do not weaken the behavior assertions. Rerun both tests, then the unit suite
and full offline runner; the two customer-history failures are not yet verified fixed.

## Customer-history fixture clock fix (2026-10-27)

The two date-sensitive customer-history failures were reproduced before the fix. Both tests now patch
`timezone_service.now_in_business_tz` to a fixed business date of `2026-10-20`, so the `2026-10-25`
appointment remains upcoming and the August appointment remains past regardless of run date. The
original upcoming-count and Battery Replacement/Kia Forte inbound assertions remain. Post-fix test
execution is not verified: the restricted run failed test setup with loopback PostgreSQL `Operation
not permitted`, and the escalated invocation returned no output. Python compilation and `git diff
--check` passed; rerun both tests and full offline verification once test-database access is available.

## Final validation and independent review (2026-10-27)

The fixed-clock tests passed in isolation (`2 passed, 3 deselected in 1.32s`). The final
`./run_tests.sh --verify --tb=short -q` completed successfully: unit/integration exit 0 and E2E
`738 passed in 290.67s`. The run made no live provider calls. An independent read-only review found
no functional issue in the clock helper or its two patches; it confirmed the configured business
timezone keeps October 25 upcoming and August 11 past. The reviewer noted stale pending-validation
text, which is updated in this record and the handoff. The code graph was unavailable for this
worktree (not indexed and outside the indexer's allowed roots); the reviewer read the exact source.
AC7 browser budget assertions passed in E2E, but printed timing samples were not retained.
