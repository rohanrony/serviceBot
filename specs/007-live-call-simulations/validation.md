# Implementation validation

Date: 2026-10-17. Scope: `live_simulations/`, its offline and E2E contracts,
and feature documentation. The original `docs/LIVE_CALL_SIMULATION_BRIEF.md`
was retained unchanged. No existing product source was edited.

## Executed checks

| Check | Result |
| --- | --- |
| `./run_tests.sh --file tests/live_simulations` | 45 passed |
| `./run_tests.sh --all --junitxml=scratch/live-simulation-unit-results.xml --tb=short` | 575 passed; 12 existing dependency/application deprecation warnings |
| `./run_tests.sh --e2e --junitxml=scratch/live-simulation-e2e-results.xml --tb=short` | 260 passed |
| `./run_tests.sh --e2e -k live_simulation --tb=short` | 2 passed, 258 deselected; repeated after adding booking-time read-back coverage |
| Cached Ruff `check --select F,E9 live_simulations tests/live_simulations e2e/test_live_simulation_evidence.py` | passed |

The full E2E run loaded its test module before the final booking-time assertion
was added. The subsequent focused browser run validates that stronger assertion.
Full offline results include the final quota and evidence-retention changes.
Machine-readable full-suite results are in the ignored `scratch/` paths above.

## Changed contracts and evidence

- Catalog completeness: 50 personas/recipes, cumulative 6/16/50 selection,
  dependency expansion and subset reporting.
- Admission: Decimal budgets, 20% reserve, unknown/duplicate settlement, live
  monthly reset/headroom checks and interrupted paid submission ledger.
- Provider: captured modern create/run/poll/cancel interfaces, no automatic
  ambiguous write retries, owned cloned agent and retryable recorded deletion.
- Callback isolation: explicit post-call webhook selection and destination,
  enabled/HMAC verification, preserved platform settings, initiation-hook rejection.
- Runtime: actual owned temporary loopback database initialization, source-secret
  exclusion, persistent reservation sequence allocation and ownership-gated drop.
  Actual app and gateway subprocess startup exercised with no provider credentials.
- Ingress: local tool token, route allowlist, callback signature-byte forwarding,
  controlled pre-tool failure and lost response after actual operation.
- Evidence: required versus forbidden tools, failed results, receiver/content
  checks, actual portal reload and API/database agreement, missing reservation
  detection, calendar ownership observation and unchanged HTTP responses.
- Interrupted evidence collection records a cleanup blocker and retains the report.

Red phases included missing modules, budget boundary behavior, provider isolation
methods, quota checks, native observation and actual browser row evidence. Later
assertions were strengthened without dropping failed conditions. A suspected
booking-time type mismatch was ruled out by the actual schema/browser contract;
that field remains covered in E2E.

## Artifact analysis and final convergence

Prerequisites resolve `specs/007-live-call-simulations`; no extension hooks file
is configured. All 12 functional requirements and 5 buildable success criteria
have implementation and task coverage. Three user stories, five constitution
principles and the six isolation details in the reconciled plan were reviewed.
Task IDs T001–T017 remain stable; all implementation tasks are complete.

Convergence findings were routed to implementation: retryable cleanup and
ambiguous creations (T011), fixture/effect evidence boundaries (T012), browser and
interrupted-billing coverage (T013), durable IDs/native Google observation (T014),
callback isolation (T015), per-case billing revalidation (T016), and booking-time
browser coverage (T017). The final assessment found no remaining actionable gap
in the specified harness scope. Final convergence appended no further tasks.

Graph tools were unavailable in this session. Current bounded source reads and
searches supplied the evidence; no graph generation/coverage claim is made.

## Operational acceptance still required

No paid ElevenLabs conversations, real calls, calendar writes or external
notifications were launched during implementation. Captured provider tests are
not live delivery evidence. Configure the dedicated reference agent, registered
HMAC webhook/secret, tunnel, current verified monthly allowance/estimates,
allowlisted receivers and connected test Google/Twilio accounts before live use.

Advanced external failure cases require explicit ready bindings and additional
state checks; absence blocks the campaign rather than passing or mocking them.
Unsupported product behavior remains a simulation finding, not a product change.
C50 requires genuine signed post-call history evidence and cannot pass from a
simulation transcript alone. Full coverage also needs handset attestation.
Real audio/phone acceptance is a separate opt-in, separately budgeted release gate.

Admission is conservative and sequential; it cannot impose an exact provider-side
cutoff on already-running or delayed-billed work. Retention is an explicit 30-day
operator policy, not an automatic evidence purge. Keep the usage ledger and ID
allocation registry when removing completed-cleanup run folders.

## Workflow extension validation

FR-013 adds `run_live_simulations.sh`, the Python `workflow` operation, guided
setup and `.agents/skills/live-simulations/SKILL.md`. Existing runtime, campaign,
ledger and evidence owners are reused. The current spec, plan, contract and tasks
were reconciled; 13 functional requirements now map to T001–T022. The extension
introduces no new product browser journey or application code change.

- `./run_tests.sh --file tests/live_simulations/test_workflow.py`: 15 passed.
  Each tier is exercised through both workflow composition and actual shell/CLI
  preview, including correct case counts. Guided setup stops before campaign
  execution. Noninteractive fresh setup blocks before resource creation.
  Interrupted setup retains its report and run ID. Previously attempted runs
  retain their original result. Explicit subsets/repeats reach the existing runner.
- Red phases: missing workflow module, followed by prior-result protection failure.
  The latter convergence finding became T022 and was fixed with its test retained.
- `./run_tests.sh --all --junitxml=scratch/live-simulation-workflow-unit-results.xml --tb=short`:
  **590 passed**, with 12 existing deprecation warnings.
- `./run_tests.sh --e2e -k live_simulation --tb=short`: **2 passed**, 258 deselected.
- Cached Ruff F/E9 check, `bash -n run_live_simulations.sh`, shell `--help` from a
  different working directory, and skill-creator `quick_validate.py`: passed.
- Final FR-013 convergence: no actionable remaining implementation gap. All
  T001–T022 tasks complete. Original live acceptance limitations still apply.

No paid provider interaction or external delivery was performed for this extension.

## Combined entrypoint regression fix (FR-014)

Reported failure: run_tests.sh --verify forwarded --live-tier into pytest, which
rejected it with exit 4 in both offline layers. Reproduced with captured shell
subprocesses: live options appeared at the wrong boundary and live dispatch was
absent. Added separate live-option parsing in the existing verify owner.

Twenty captured-shell regression cases validate minimal/medium/full dispatch,
unchanged pytest selector forwarding, config paths containing spaces, prepared
run IDs, preserved live exit status, both offline failure gates, default offline
behavior, malformed options, and rejection of non-executing pytest modes. The
first 11 behavioral tests failed before implementation; eight collection/help
contracts then failed before their convergence fix (T026).

Focused regression suite: 20 passed. Final full unit/integration suite: 610 passed
(12 pre-existing deprecation warnings). Bash syntax, Ruff F/E9, skill frontmatter
validation and git diff whitespace check passed. Existing unrelated trailing
spaces in run_tests.sh were preserved. No paid simulation or external delivery
was executed while validating this change. Live dispatch used a captured boundary.

The spec/plan/contracts and task coverage were reconciled for 14 functional
requirements. Current source was read directly because graph tools were unavailable.
The FR-014 review found the help/collection gap, appended T026, then verified its
regression fix; no further actionable implementation gap remains in this scope.

A combined validation attempt ran all tests successfully but its shell process
reported an EOF error after the suites because run_tests.sh had been edited
in place during execution. That command-level attempt is not counted as a clean
verification; the finished script was syntax-checked and rerun without edits.

Final unchanged `./run_tests.sh --verify --tb=short` completed with exit 0:
**610 unit/integration tests and 260 E2E tests passed**; both suite exits were 0.
All T001–T026 tasks are complete. No live stage was launched. The default private
simulation config was not present during validation; users must create/configure
it or provide --live-config before requesting live execution.

## Standard reference compatibility (FR-015)

The user authorized the existing standard ElevenLabs profile as the reference.
Live GET /agents succeeded for Davidson Car Care Service Agent. It exposes eleven
shared tools and a start-only empty workflow. The prior adapter rejected that
representation and the ordinary display name. Three regression contracts failed
first, then passed after read-only resolution and bounded no-op workflow support.
Nontrivial routing, inconsistent materialized tools and side-effect system tools
remain rejected. Source agents and shared tools are never renamed or patched.

Focused provider contracts: 12 passed. Full offline suite: **613 passed**, with
12 pre-existing warnings. Ruff F/E9 and diff checks passed. Actual read-only
resolution verified all eleven shared IDs against materialized definitions;
copied tools all targeted the isolated placeholder origin, shared references were
removed, and the original configuration stayed unchanged. No POST/PATCH/DELETE,
paid simulation or notification was issued. No product browser behavior changed.

Artifact reconciliation covers FR-015 with T027–T029; the final bounded convergence
review found no remaining implementation gap for standard read-only references.
Graph tools were unavailable; evidence came from current source and provider GETs.

Operational acceptance remains blocked: the current standard key returns HTTP 401
missing_permissions specifically for user_read on /v1/user/subscription. Private
configuration now references standard exported credential variable names only,
without storing their values. Account permission, verified allowance/estimates,
local database, tunnel/test webhook and designated test delivery setup must be
completed before minimal paid execution can be claimed. Existing DATABASE_URL is
not loopback and was not used as an owned/resettable test database.

## Runtime launch fixes from actual account setup (T030/T031)

A real Google-auth-url request returned HTTP 500: the harness exported a keyword
libpq DSN while the application connection pool accepts PostgreSQL URI strings.
The strengthened subprocess test also exposed that a pytest-named artifact path
in argv selected the app's fallback local test database. The original health-only
check had missed both behaviors. The actual launch failure and then two failing
contracts were retained before the fixes.

The harness now percent-encodes URI credentials/parameters while retaining the
owned database name and pinned loopback address. The application launcher parses
its harness arguments, then supplies neutral argv before importing the app so
artifact paths cannot select a different database or disable normal workers.
No existing application source was changed.

Validation: 9 focused runtime tests passed; full offline suite **614 passed**;
focused browser evidence **2 passed**; Ruff F/E9 and diff checks passed. Actual
non-pytest setup now returns HTTP 200 with an empty service-request list from the
owned database, and the Google authorization URL endpoint returns HTTP 200.
T030/T031 convergence is complete. No paid conversation or notification was sent.

The specified customer/agent phone and selected Gmail/calendar account were saved
only in ignored private configuration and seeded into the owned runtime. A source
read found no existing Google authorization for that exact account. A private
Google consent handoff was prepared; user sign-in/consent remains pending.
Automatic approval review rejected a new authenticated public-tunnel probe because
it would transmit the generated gateway token through ngrok. No workaround was
attempted; explicit user approval was requested. The local setup portal remains
running for the selected Google connection. Live acceptance is still incomplete.

### T032: Calendar scope mismatch
The user completed consent. Owned staff account and selected receiving Gmail
identity verified; Gmail profile/inbox checks returned 200. calendars/primary
metadata returned 403, while calendars/primary/events?maxResults=1&fields=kind
returned 200 using the same authorized token. Google documentation confirms the
scope distinction. Added the exact preflight request regression, observed failure
for metadata URL, then changed only the runner permission probe. Encrypted sender
credentials were configured only in the existing owned app snapshot.
WhatsApp metadata shows the last inbound message at 2026-10-16T20:28:21Z; its
24-hour session has expired. A fresh user message is required. Ngrok token approval
and budget unit/estimate verification remain pending; no paid submission occurred.
T032 validation: `.venv/bin/python -m pytest tests/ -q` passed 615 tests with
12 existing warnings; `git diff --check` passed. Ruff is unavailable in this
virtualenv, so no new Ruff success is claimed. Source AST parsing passed.
Convergence: the event probe uses the application's granted scope, excludes event
content, and preserves all other preflight gates. No browser flow changed.


## Deployed smoke extension — FR-016–018 (2026-10-17)

- Updated the existing feature spec/plan/tasks (T033–T036) for the user-selected
  deployed app and operator-run handoff. No graph tools were available; inspected
  exact workflow/provider/core and portal endpoint source instead.
- Analysis: all three new requirements map to tasks; default isolated guarantees
  remain intact. Deployed mode is explicitly conversation/API smoke with incomplete
  full acceptance, and C07–C50 require their isolated assertions/fixtures. No implicit
  technician choice or recipient edits; allowlists remain preflight gates.
- Red: 18 new contracts failed for missing deployed module/routing after running
  with local socket access. Initial sandbox-only attempt failed at DB setup and
  was not used as the functional Red evidence.
- Green: `./run_tests.sh --file tests/live_simulations/test_deployed.py --tb=short`
  passed 23 tests, including a captured complete six-case lifecycle and ambiguous
  paid POST that remained unsettled and was never repeated.
- Relevant complete suite:
  `./run_tests.sh --file tests/live_simulations --tb=short` passed **108 tests**,
  one existing Starlette/httpx warning. Includes default/combined workflow regressions.
- Cached offline Ruff F/E9 checks passed for deployed.py, workflow.py, __main__.py
  and test_deployed.py. `git diff --check` passed. Offline shell preview selects
  C01–C06 and truthfully returns budget_unverified (exit 2) with the private config.
- Convergence: reviewed FR-016–018 against the new module, CLI dispatch, templates,
  documentation and 23 captured contracts; no remaining implementation gaps within
  this declared smoke scope. Existing isolated evidence behavior is unchanged.
- No new product browser journey or application endpoint was added. No browser
  acceptance or live provider run was executed for this extension; no deployment
  configuration, appointment, calendar, message or standard agent was changed.
- Operational gates still open: verified billing units/upper estimates; deployed
  notification recipients must match the designated contacts; current WhatsApp
  enrollment/window. The new `--check` command exposes readiness to the operator.

## FR-019/020 returning caller and one-case calibration
- Analysis: two changed contracts map to T037–T042; no critical ambiguity or artifact conflicts after documenting the independent single-case exception to FR-003. No changed browser journey, schema or application service. Graph MCP tools are unavailable in this session, so relevant exact source and tests were read directly; no graph completeness claim.
- Red: `python -m pytest --confcutdir=tests/live_simulations tests/live_simulations/test_deployed.py -q --tb=short` produced 16 intended failures and 23 passes before implementation. An earlier invocation inherited application-wide conftest and was blocked on sandbox loopback access; this is not regression evidence.
- Green: same focused command passes 39/39. Full `tests/live_simulations` run: 122 passed, 2 sandbox-blocked runtime tests. Complete runtime module rerun with loopback access: 9/9 passed, covering both blocked contracts. All 124 unique contracts pass across these runs.
- Cached Ruff `check --select F,E9` passes for core.py, deployed.py and test_deployed.py; py_compile and git diff --check pass.
- Converge: FR-019 baseline opt-in/default rejection, post-observation and pre-submission original-record comparisons, unchanged lifecycle identity checks, real booking context; FR-020 one selected fresh case/minimal/one-repeat validation, numeric/provenance validation, independent Budget ceiling/reserve, output/turn limits, shared ledger/unknown charge stop, scoped manifest and missing acceptance evidence all verified. No remaining implementation findings; T042 is separate authorized operational execution. No ordinary tier credit assertion or cap was relaxed.

### Read-back convergence iteration 2
The first live attempt (66ec63c0e64b49818bb63db077d9060f) created an owned agent but submitted no paid invocation. Read-back differed because the provider materialized `agent.text_behavior_overrides.whatsapp` with null verbosity/output_format/interaction_budget and disable_max_duration=true, while the reference returned null. Direct GET-only inspection confirmed the precise fields. T043 regresses that exact provider behavior (red: one intended failure), sends the observed default explicitly on copies, preserves the original reference and rejects a false disable_max_duration setting. Focused deployed contracts now pass 40/40; Ruff F/E9 passes. Convergence iteration 2 has no further implementation findings. The first attempt and owned resource remain retained; a new run is allowed because no paid submission occurred.

### Authorized single live calibration result
T042 executed C01 once in run 38cdbb2e9e72449d8a034e77fdce8396 after read-only preflight returned no problems. Provider and functional result: failed, 323 settled credits (203 LLM + 120 platform), provider price breakdown $0.064840635, within the independent 1500-credit ceiling. The agent verbally confirmed a new appointment without tool calls in the provider transcript; fresh API observations found no new booking. Existing customer records unchanged: passed. No paid retry, resource cleanup, deployment edit or business-data cancellation was performed. The failed scenario is a product/agent finding under FR-010, not an implementation task to silently change production behavior. The evaluator's isolated-catalog pricing comparison remains unverified against deployed catalog facts. See scratch/live-simulations/38cdbb2e9e72449d8a034e77fdce8396/review.md.

Final convergence: all T037–T043 tasks completed, no remaining harness implementation findings across two iterations. Full acceptance stays incomplete by declared scope; the live C01 functional failure is retained as a separate agent follow-up. No commit, push or deploy.

## Active deployed reference fidelity follow-up (FR-021–023)
- Current GET evidence: private config selected agent_7801m3pyjmz4e6tt0mjpwydwreex (63-character custom prompt); deployed portal actively uses agent_2501ktmjf3pee2as55y9vx3gdpge (22920-character booking prompt, 11 native tools, same deployed origin). The earlier false-confirmation sample did not test that active deployed agent. No evidence establishes who changed the former reference.
- Plan/tasks analysis: active identity guard, provenance, owned saved-configuration execution, and deployed-only catalog evaluation are scoped harness changes; no saved agent, application UI/schema or production prompt rewrite. FR-021→T044–T046; FR-022→T045–T046; FR-023→T049. No critical artifact conflicts.
- Red: focused provider/deployed tests initially had 11 expected failures and 47 passes. Deployed-catalog test separately failed importing the missing helper before implementation.
- Green: focused modules 59/59; complete offline suite `python -m pytest --confcutdir=tests/live_simulations tests/live_simulations -q --tb=short` 132/132 with owned loopback access. Ruff F/E9, py_compile and diff whitespace checks pass. One existing Starlette deprecation warning.
- Convergence: matching/missing/mismatched/unreadable active identity, GET-only behavior and key metadata exclusion, clone request without redundant override, explicit override backward compatibility, reference manifest identity, unchanged isolated catalog and retained other criteria checked. No remaining implementation findings. No browser journey changes. Private config reference corrected; read-only live preflight returns no problems. T048 is the separately authorized live retest.

### Active-reference live retest
T048 completed one new C01 run, 26aa2d535ea349ae8bb39fcbc36d14a6. Actual reference identity is recorded and matches the deployed portal. The provider transcript shows a successful real get_customer_appointments tool request/result. There was no false confirmation in this sample and no new booking; eight turns expired before completing vehicle intake. Opening recording disclosure was missing. Actual usage 544 settled credits (409 LLM/135 platform), price breakdown $0.1086179875. Original caller records unchanged passed. No further paid replay, cleanup, saved agent mutation or deployment.

The earlier wrong-reference attribution is corrected in its retained review.md. Several current replies were partial and interrupted=false; the 256-token copied-agent limit is a candidate cause, not proven by finish-reason evidence. Do not infer complete booking correctness from this sample. Full acceptance remains failed/incomplete and requires a separately configured adequate-duration test and disclosure correction; current FR-020 intentionally bounds calibration to eight turns/256 tokens. FR-010 keeps product acceptance findings visible without silently rewriting saved agents.

Final bounded convergence: FR-021/022/023 implemented with 132 passing offline contracts and no remaining harness implementation gaps. All T044–T049 tasks completed. This does not mark live C01 or the minimal tier passed.

## Full verification and budget gate (2026-10-17)

T050 evidence regressions passed after intended Red; complete final offline run passes 703 unit/integration and 283 E2E. T051 readiness/reporting is complete: C01–C06 remains over the approved budget, zero new paid invocations and credits. No guard was bypassed or production reference changed. See scratch/overnight-20261017/report.md and specs/001-booking-confirmation-history/validation-2026-10-17.md for the repair/convergence evidence. No remaining harness implementation findings in T050/T051; live acceptance is incomplete.

## Authorized full minimal campaign ceiling (2026-10-18)

FR-024 reconciles the explicit user approval for one 8,160-credit C01–C06 pass. T052/T053 Red: 15 intended failures in captured scope/budget/reuse contracts; Green: complete deployed module 73 passed. Cached Ruff F/E9 and diff whitespace checks pass. Analysis maps FR-024 to T052–T055 and retains default tier, calibration, reference fidelity, baseline/recipient, billing/headroom and unknown-charge guarantees. Convergence found no remaining implementation gap in the scoped authorization. The new private config preserves the original authorization ID across execution attempts; no paid submission has occurred yet at this checkpoint. Complete offline gate and paid results follow in scratch/live-campaign-20261018/.

## Actual paid result and identity repair (2026-10-18)

The pre-campaign gate passed 722 unit/integration and 283 E2E tests. Authorized run
`51ffab47f72f4cba9483a6e8ecaf11ba` then failed C01 and blocked C02–C06, costing
634 settled credits with no unsettled usage. It created booking 46; native greeting
lacked recording disclosure, and a synthetic caller name changed 16 original
joined names. Fresh audit found no other original booking-field mutation.

FR-025/T056–T058: spec/plan/tasks were reconciled before implementation. Captured
native-profile Red 13 failed/66 passed, Green 82 passed. Existing names are reused
without a run suffix; missing/conflicting names block before provider setup;
strict full-row baseline mutation detection remains. Fresh read-only deployed
check confirms the current caller's two name groups block readiness. The separate
catalog intake repair is covered by feature 006 T047–T049.

Final offline command passed 731 unit/integration and 289 E2E tests, zero
failures/errors/skips. Follow-up Ruff F/E9 and whitespace checks passed. No
remaining implementation gap was found in these repaired paths. Live T055 is
still open; operational findings are routed to T059–T062 rather than marked
complete: authorized deployment, saved greeting correction, guarded profile
restoration/caller identity resolution, then a reviewed paid execution plan.

No remote correction, cleanup, publication or paid replay was performed. Exact
review artifacts and evidence: scratch/live-campaign-20261018/report.md. Historical
no-paid-work checkpoints above are superseded by this actual result.
