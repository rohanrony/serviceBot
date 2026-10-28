# Portal loading responsiveness

Status: implementation in progress; permanent Red observed, post-fix Green and full offline verification pending.
Route: bug fix. Restore responsive reads and filtering without changing booking, assignment,
notification, catalog identity or timeframe semantics. No full spec/plan/tasks cycle is needed.

## Workspace and authorization

- Worktree: `/Users/rohanroy/Coding/voiceService/.worktrees/portal-loading-responsiveness`
- Branch: `codex/portal-loading-responsiveness`
- Starting base: `c7b4d4ee37d89e322033b5bd34fb2c664fbd6539`
- Scope directory: `specs/changes/portal-loading-responsiveness`
- The user explicitly authorized implementation in this isolated worktree, including permanent
  Red/Green regressions and offline validation. Commit, publication, merge, deployment and live
  provider actions remain outside this authorization.
- Preserve unrelated work in the primary checkout. Stay in this worktree through implementation
  and subsequent Codex review. Do not change the source checkout's branch or feature pointer.

## Established diagnosis

Evidence was collected on 2026-10-27 from the deployed `serviceBot` Render service in workspace
ADS, service `srv-d98r46ucjfls73f5lsgg`, deployment `dep-dbfooom417fc73de7fg0`, at the starting
base above. Supabase project `gwpviameuxfnaupxahhe` is in Canada Central; Render is in Oregon.
The relevant application files match the deployed commit. Existing unrelated dirty changes
were not used as the implementation base.

| Observation | Evidence and limit |
| --- | --- |
| Timeframe changes reload the entire dashboard serially | `serviceBot/static/app.js`: change handler calls `loadDashboardData`; it awaits stats, all calls, then all service requests before filtering requests. The data endpoints receive no timeframe or limit here. |
| Filtering can use already loaded data | `applyCallsFilter` and `applyServiceRequestsFilter` operate on `allCalls`/`allRequests`. Open operational requests intentionally remain visible regardless of timeframe. |
| The reported approximately five-second UI wait is credible but not exactly reproduced | Render emitted a recent chain spanning approximately 3.74 seconds from first server request start to final completion. One chain used 0.49 s stats + 0.49 s calls + 1.48 s requests in server processing. These are not complete click-to-paint measurements. A later HTTP replay was cancelled before obtaining results. |
| Hidden analytics can add four requests | An isolated Node VM executed the actual navigation function and the two actual change listeners with stub DOM/loaders. Dashboard alone invoked dashboard; Analytics -> Dashboard and Analytics -> Services invoked both dashboard and analytics. `activeConfigSubtab` remembers Analytics after navigation. This is a local reproduction, not proof that it caused the reported five seconds. |
| Catalog first display waits for staff | `loadServicesData` awaits `/agents` before starting `/services`. Recent server timings: staff 1.12-1.39 s, then services approximately 0.31 s. Services already include assigned-agent IDs/names; staff supply editing controls. |
| Catalog SQL is small | Database statement statistics, cumulative since 2026-07-22: services average 0.198 ms; service-agent mapping average 1.117 ms. These are historical means, not a fresh complete request profile. |
| Service-request SQL is not the main observed wait | Fresh read-only EXPLAIN: 66 rows, planning 3.258 ms, execution 13.144 ms. The snapshot had zero missing durations, zero active escalations and two distinct assigned staff phones. Other data can exercise additional existing enrichment paths. |
| Read enrichment repeats DB round trips | `/agents` checks WhatsApp once per staff member. `_load_service_requests` memoizes exact phones within one response but still borrows nested connections for unique phones. |
| Several sibling reads block the event loop | Stats, calls, services, agents and analytics use synchronous psycopg2 inside async handlers. Service-request listing already uses `run_in_threadpool`; preserve that existing protection. |

Diagnostic bounds: Render app-log windows were limited to relevant GET paths between
15:28 and 16:18 UTC, with pages capped at 100. Targeted windows used for the cited sequences
reported no remaining page; no claim is made about all production logs. DB reads used read-only
transactions/connections and a five-second statement timeout. No production rows, credentials,
transcripts or contact details are fixtures in this record. An earlier snapshot had eight DB
connections and no visible lock waits; this does not prove ongoing absence of contention.
The graph service excluded this repository from allowed roots and coverage was unavailable;
bounded direct source reads were used instead.

## Acceptance contracts

**AC1 - Immediate timeframe filtering.** Once datasets are loaded, changing among 24h, 7d, 30d
and all filters both tables immediately from memory, without fetching calls/service requests.
Reset the affected table page to the first page. Preserve text/type/status filters and the
existing rule that open operational requests remain visible; historical rows retain the
existing updated/created/booking-date logic. Keep the current browser date interpretation;
timezone-rule changes are outside this repair.

**AC2 - Independent and truthful dashboard refresh.** Initial load and explicit Refresh start
the independent stats/calls/service-request reads without a serial waterfall. Each ready section
renders independently. Timeframe changes refresh totals separately. Failed background reads
retain usable prior data and expose a section-level error/stale state with retry; do not label
failed or unfinished Refresh as successful. Empty results are loaded data, not a cache miss.

**AC3 - Correct scope and latest response.** A timeframe change refreshes analytics only while
the analytics pane is actually visible. Leaving Analytics must not cause hidden analytics work
on Dashboard or Catalog. Rapid changes, repeated navigation and Refresh must not produce
unbounded duplicate reads or allow an older response to overwrite the latest selection/data.
Use per-resource in-flight ownership/generation checks or cancellation, with a bounded latest
refresh when needed. A mutation-triggered refresh must not reuse a pre-mutation in-flight GET.

**AC4 - Catalog display independent of staff controls.** Start services and staff reads
independently. Render service rows, including assigned-agent badges from the services response,
while staff is pending or failed. Keep staff-dependent add/edit controls visibly loading or
unavailable until valid staff data arrives; never interpret failure as an intentionally empty
staff list or silently submit cleared tags. A successful empty staff list is a distinct state
and permits the existing no-tag behavior. A failed services read exposes retry.

**AC5 - Fresh catalog data without blank waits.** A revisit may display cached service rows
immediately and revalidate them in the background, with one in-flight read per resource.
Invalidate/refetch after successful create/edit/delete/tag changes. Revalidate staff before
enabling tag editing on a revisit so deactivated staff are not selectable from a stale cache.
Old reads must not resurrect a deleted service or reverse newer edits. Failed/cancelled
mutations retain the saved values. Fresh API reads and full browser reload must show persisted
catalog IDs, duplicates, tags and removals correctly. Do not add server/process-wide data caches.

**AC6 - Bounded, nonblocking read enrichment.** Fetch the onboarded whitelist once per response
using the existing read connection/cursor for `/agents` and service-request listing. Preserve
exact-digit and existing last-ten-digit phone matching, null/empty inputs, onboarded-only
filtering and the unassigned-request null field. Read fresh DB state on each new request.
With assigned staff and no legacy-duration or candidate-provider enrichment, each endpoint
uses at most two business SELECTs: its base listing and one whitelist read, independent of row
count. Exclude existing liveness and transaction commands from this counter. Move the affected
synchronous read pipelines off the event loop using normal synchronous FastAPI handlers or
`run_in_threadpool`; keep response shapes, errors and parameters compatible. A held DB read on
any changed endpoint must not prevent `/health` completing within one second on loopback.

**AC7 - Measured UI budgets and preserved boundaries.** In headless Chromium on loopback with
100 synthetic requests, 100 calls, 46 services and two staff, measure 20 alternating timeframe
changes after initial load. Target p95 event-to-painted-table update <=250 ms while stats
responses are held. Catalog must paint <=250 ms after its own response is available while the
staff response remains held. Initial dashboard sections have the same <=250 ms post-response
paint budget while unrelated reads are held. Use browser performance timestamps and paint
frames, not sleeps. Retain samples, fixture size, engine/version and machine context. A deployed
latency claim requires a later target-specific read-only measurement; offline budgets do not
promise Internet or production performance. No loading/filtering/read optimization may cause
booking, configuration, catalog, notification or provider writes.

## Implementation sequence for the executor

1. Confirm workspace/branch/base and establish an isolated offline Python/browser/Postgres
   environment. Do not source/copy the primary checkout's `.env`, `.envrc`, credentials or data.
2. Add permanent browser regressions in a focused new `e2e/test_portal_loading_responsiveness.py`
   and lower-level/API regressions in appropriate existing files or a focused new test module.
   These are proposed file locations, not existing collected test IDs. Collect new IDs, fill
   every coverage gap and demonstrate intended Red failures before production-code edits.
3. Fix timeframe handling and section loading in `serviceBot/static/app.js`: immediate cached
   filters; separate totals; actual visible-view checks; independent reads; section failures;
   latest-response/in-flight ownership. Keep functions focused; no new frontend framework.
4. Decouple catalog table data from staff controls; add explicit loaded/loading/error state,
   background revalidation and mutation-safe invalidation. Preserve add/edit/delete/tag UX.
5. Batch request-scoped WhatsApp enrichment in `serviceBot/db/queries.py` and
   `serviceBot/api/portal.py`. Offload affected read handlers: stats, calls, services, agents
   and the four analytics wrappers. Reuse the service-request thread-pool pattern.
6. Run focused Red/Green checks, then the complete offline `./run_tests.sh --verify`.
   Review acceptance behavior, persisted reads, prohibited effects and removed assertions.
   Update this record, coverage and the execution handoff with exact evidence and working state.
7. Return the same worktree to Codex for read-only review. Publication is a separate stage.

Expected ownership: `serviceBot/static/app.js`, narrowly related UI markup/styles only when
needed for loading/error accessibility, `serviceBot/api/portal.py`, narrowly scoped helpers in
`serviceBot/db/queries.py`, relevant tests and this change directory. The executor is not alone
in the repository: preserve others' edits and adjust rather than reverting them.

Do not change connection pool sizing/liveness/transactions, schema/indexes, deployment regions,
worker counts, provider calls, qualification/calendar decisions, booking reservations or
timeframe business semantics. Do not add server-side pagination or redesign APIs in this fix.
If those become necessary, stop and revise the scope/design before implementation.

## Test strategy and evidence status

- Browser: hold/release routes rather than sleeping. Cover loaded-empty data, all timeframe
  values, operational/history visibility, retained filters, latest selection under reversed
  responses, Analytics -> Dashboard/Catalog, partial failures/retry, initial load independence,
  catalog with pending/failed/empty staff, revisit and create/edit/delete/tag invalidation.
- API/database: assert compatible JSON, one whitelist SELECT regardless of repeated/distinct
  phones, normalization parity, a fresh request seeing changed persisted onboarding state,
  no domain-table writes, and health completion while each changed read is held with Events.
  Keep the old future/unknown calendar behavior; do not remove candidate enrichment.
- Existing `test_listing_memoizes_whatsapp_status_per_exact_staff_phone_only` spies on the old
  helper. Update it to assert returned values, bounded reads and freshness without preserving
  obsolete helper-call counts or weakening the behavioral guarantee.
- Reuse catalog duplicate/tag, deactivation, failed-save and browser reload regressions.
  Both catalog tables/agent mappings and unrelated records must survive read/failure paths.
- Provider effects stay mocked/forbidden. No live simulation definition changes are needed
  because external semantics are unchanged. Keep existing provider/candidate regressions.
- Separate `tests/` and `e2e/` lifecycles. Do not collect/run both in one pytest invocation.

On the planning worktree, sanitized collection of four existing E2E files succeeded:
36 test IDs collected, zero executed. Relevant IDs are recorded in `test-coverage.yaml` as
baseline regression coverage only. No new behavioral tests were written during planning.
Permanent regression IDs and initial Red evidence are recorded in test-coverage.yaml. Intermediate execution exposed six failures; follow-up fixes were made but the final rerun stalled. Green timings, query counts and full offline suite remain pending.
The earlier isolated navigation-state probe passed three assertions against the unchanged
source; it is diagnostic evidence, not a replacement for the permanent browser regressions.
Planning validation checked YAML structure, AC1-AC7 presence, the 11 referenced baseline
functions, Markdown links/fences, new-file whitespace and exact workspace/branch/base identity.
The primary checkout's branch, HEAD and dirty-file status were rechecked and preserved.

Validation commands for execution (after offline setup, with synthetic environment only):

```bash
./run_tests.sh --file e2e/test_portal_loading_responsiveness.py --tb=short -q
./run_tests.sh --file e2e/test_portal_read_responsiveness.py --tb=short -q
./run_tests.sh --file e2e/test_portal_catalog_agent_tagging.py --tb=short -q
./run_tests.sh --file e2e/test_catalog_reads.py --tb=short -q
./run_tests.sh --file tests/test_portal_api.py --tb=short -q
./run_tests.sh --file tests/test_portal_updated_at_contract.py --tb=short -q
./run_tests.sh --verify --tb=short -q
```

Include any new lower-level file in focused validation. Provision the worktree's own `.venv`
and loopback disposable Postgres; they were not copied/started during planning. Never add live
flags to these commands. Offline behavior status is **pending**. Live-provider acceptance is
**not_required** for the proposed scope; post-deploy performance confirmation remains pending
and requires a separately authorized deployment/diagnostic stage. Committed/Pushed/Merged/
Deployed: **no** for this change.
