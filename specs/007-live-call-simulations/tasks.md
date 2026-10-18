# Tasks: Tiered live call simulations

## Phase 1: Setup
- [x] T001 Capture accepted decisions and API research in specs/007-live-call-simulations/.

## Phase 2: US1 — Budgeted campaigns
- [x] T002 [US1] Write failing catalog, configuration and budget contracts in tests/live_simulations/test_core.py (FR-001–003).
- [x] T003 [US1] Implement catalog, config and budget in live_simulations/ (FR-001–003).

## Phase 3: US2 — Provider and evidence
- [x] T004 [US2] Write failing provider/evidence contracts in tests/live_simulations/test_provider.py and test_evidence.py (FR-004,007,008).
- [x] T005 [US2] Implement provider and outcome evidence in live_simulations/provider.py and evidence.py (FR-004,007,008).

## Phase 4: US3 — Runtime and ownership
- [x] T006 [US3] Write failing runtime, campaign, cleanup and browser contracts in tests/live_simulations/ and e2e/test_live_simulation_evidence.py (FR-005,006,009,010,012).
- [x] T007 [US3] Implement isolated runtime, gateway, fixtures and campaign ownership in live_simulations/ (FR-005,006,009,010).

## Phase 5: Acceptance and convergence
- [x] T008 Implement CLI, private config example and real-phone gate guide in live_simulations/__main__.py and docs/LIVE_SIMULATIONS.md (FR-002,011).
- [x] T009 Run focused/full relevant offline tests and browser evidence checks; record specs/007-live-call-simulations/validation.md (FR-012).
- [x] T010 Converge requirements, plan and implementation; resolve findings and update specs/007-live-call-simulations/tasks.md.

## Dependencies and strategy
T001 → T002 → T003 → T004 → T005 → T006 → T007 → T008 → T009 → T010.
Provider research was independently delegated; implementation remains sequential.
Every implementation stage follows failing contract tests. No paid acceptance here.

## Phase 6: Convergence
- [x] T011 Make provider cleanup retryable after 404/lost responses and persist ambiguous resource creation in live_simulations/provider.py and runner.py per FR-004/FR-009 (partial).
- [x] T012 Protect against case fixture leakage, unfinished side effects, mismatched caller bindings and missing state exports in live_simulations/runner.py per FR-005/FR-006/FR-009 (partial).
- [x] T013 Verify genuine browser status/API agreement and billing interruption with offline campaign integration tests in tests/live_simulations/ and e2e/test_live_simulation_evidence.py per FR-007/FR-012 (partial).

- [x] T014 Allocate persistent reservation ID ranges and observe real Google mutations, including non-persisted admin events, in live_simulations/runtime.py and app_server.py per FR-005/FR-009 (partial).

- [x] T015 Pin and verify dedicated native post-call webhook routing, preserve platform configuration, and block inherited initiation hooks in live_simulations/provider.py and runner.py (FR-004/FR-005).

## Phase 7: Convergence
- [x] T016 Recheck billing-period identity and remaining account allowance before every paid submission in live_simulations/runner.py per FR-003 (partial).

## Phase 8: Convergence
- [x] T017 Compare typed database booking times with fresh portal API timestamps and cover the actual field in e2e/test_live_simulation_evidence.py per FR-007/FR-012 (partial).

## Phase 9: Runnable workflow
- [x] T018 Define and analyze the FR-013 workflow contract and plan.
- [x] T019 Write failing workflow, tier-routing, interruption and executable-entrypoint tests in tests/live_simulations/test_workflow.py.
- [x] T020 Implement workflow composition, CLI operation and root shell command per FR-013.
- [x] T021 Add a project live-simulations skill and concise workflow guide; validate, analyze and converge FR-013.

## Phase 10: Convergence
- [x] T022 Reject previously attempted workflow runs before changing their manifest; regress shell preview routing for all tiers per FR-009/FR-010/FR-013 (partial).

## Phase 11: Combined verification
- [x] T023 Reconcile FR-014 spec/plan/contracts and reproduce option forwarding with captured shell tests.
- [x] T024 Consume live options in run_tests.sh --verify, preserve offline results and gate live dispatch.
- [x] T025 Validate combined command, document flags and converge FR-014.

## Phase 12: Convergence
- [x] T026 Reject non-executing pytest modes when live dispatch is requested, so help/collection success cannot unlock paid work, per FR-014 (partial).

## Phase 13: Standard reference profile
- [x] T027 Define and regress standard-agent name, shared-tool resolution and no-op workflow compatibility per FR-015.
- [x] T028 Implement read-only reference resolution and retain rejection of nontrivial workflows per FR-004/FR-005/FR-015.
- [x] T029 Validate actual standard reference without paid submission, document remaining account readiness and converge FR-015.

## Phase 14: Convergence
- [x] T030 Encode the owned database DSN as a PostgreSQL URI for the application, preserve loopback pinning and escaped credentials, and regress a real database-backed HTTP route per FR-005/FR-012 (partial).

- [x] T031 Remove harness folder arguments from application argv before importing app modules so pytest-named temporary folders cannot select a fallback test database or disable normal workers; retain real HTTP ownership regression per FR-005/FR-012 (partial).

## Phase 15: Convergence
- [x] T032 Replace the calendar metadata preflight with a bounded event-resource permission probe compatible with the authorized calendar.events scope; exclude event content and regress the exact request per FR-005/FR-012 (partial).

## Phase 16: Deployed smoke workflow
- [x] T033 Reconcile FR-016–018 specification, plan and operator decisions; analyze routing, ledger and evidence boundaries.
- [x] T034 Add offline regression contracts for deployed routing, tiers, safe preflight, native tool copies, lifecycle evidence and paid ambiguity.
- [x] T035 Implement artifact-only deployed workflow/check using existing budget ledger; retain isolated execution.
- [x] T036 Add deployed template, operator command and limitations; inspect changes and converge. Live execution is handed to the user; offline contracts are validated separately.

## Phase 17: Single-case calibration and returning caller
- [x] T037 [US1] Reconcile FR-019/020 spec, plan, research and configuration contract in specs/007-live-call-simulations/; analyze before code.
- [x] T038 [US2] Add failing returning-caller and baseline-mutation contracts in tests/live_simulations/test_deployed.py.
- [x] T039 [US1] Add failing single-case calibration budget, scope and execution contracts in tests/live_simulations/test_deployed.py.
- [x] T040 [US1] Implement explicit calibration ceilings in live_simulations/core.py and bounded deployed calibration/baseline observation in live_simulations/deployed.py.
- [x] T041 Document operational distinction in docs/LIVE_SIMULATIONS.md; validate complete live_simulations offline suite and converge FR-019/020.
- [x] T042 Run one explicitly authorized deployed C01 calibration using the prepared private config, retain actual usage/report and baseline comparison in scratch/live-simulations/.

Dependency: T037 → T038/T039 → T040 → T041 → T042. Implementation stays sequential.

## Phase 18: Convergence
- [x] T043 Regress and explicitly materialize the provider-observed default WhatsApp text behavior on copied agent configurations in live_simulations/deployed.py and tests/live_simulations/test_deployed.py per FR-004/FR-015/FR-020 (partial). Preserve rejection of every material setting change and source immutability.

## Phase 19: Deployed active reference fidelity
- [x] T044 Reconcile FR-021/022 analysis, contracts and plan in specs/007-live-call-simulations/ from current GET evidence.
- [x] T045 Add failing identity-readiness and owned-agent request contracts in tests/live_simulations/test_deployed.py and test_provider.py.
- [x] T046 Implement fail-closed active-reference readiness/provenance in live_simulations/deployed.py and optional provider.run override in live_simulations/provider.py.
- [x] T047 Validate complete offline simulation suite, lint and convergence; update docs/LIVE_SIMULATIONS.md with reference selection semantics.
- [x] T048 Correct the private reference to the deployed active agent and run one authorized C01 calibration; retain report, cost and API baseline evidence in scratch/live-simulations/.

Dependency: T044 → T045 → T046 → T047 → T048. Keep the failed wrong-reference run as evidence; no paid replay under its old ID.

## Phase 20: Deployed catalog assertion fidelity
- [x] T049 Regress and implement deployed-only live-catalog pricing criteria in tests/live_simulations/test_deployed.py and live_simulations/deployed.py per FR-023. Preserve isolated recipes and every other criterion; complete before T047/T048 final validation and live submission.

## Phase 21: Verification repairs

- [x] T050 Reproduce no-op rescheduling and equivalent timestamp evidence errors, then compare business-zone instants and accurately label persisted booking evidence per FR-017.
- [x] T051 Run complete offline suites and deployed readiness, enforce existing tier budgets plus the user session ceiling, retain reports and converge; report any unaffordable live scenarios as incomplete per FR-003/010/017/018.

## Phase 22: Authorized deployed campaign

- [x] T052 Reconcile FR-024 authorization, plan and analysis, then add failing captured budget/scope/reuse and complete-campaign contracts.
- [x] T053 Implement the opt-in deployed campaign ceiling and durable one-campaign authorization using the existing Budget/ledger/lock; retain default limits and ambiguity gates per FR-024.
- [x] T054 Validate focused and complete offline suites, document the config contract and converge FR-024.
- [ ] T055 Refresh deployed/provider readiness and execute the authorized C01–C06 campaign once within the 8,160-credit ceiling; retain functional/evidence/cost outcomes and any unresolved acceptance or local repair work.

  Attempt retained: run `51ffab47f72f4cba9483a6e8ecaf11ba` stopped after failed
  C01; C02–C06 were blocked. Settled spend 634 credits, no unsettled usage.
  This remains open for live acceptance; the consumed authorization is not replayed.

## Phase 23: Live failure follow-up

- [x] T056 Reproduce native profile-name updates with captured provider tests, retaining strict baseline comparisons and adding missing/conflicting-name admission cases per FR-025.
- [x] T057 Preserve existing caller identity in scenario and dynamic context before provider resource creation; keep synthetic names for new callers per FR-025.
- [x] T058 Run focused and complete offline suites, converge, and retain the failed C01, blocked cases, settled spend and exact read-only mutation audit. Prepare concrete deployed corrections for review without applying them or replaying paid work.

## Operational follow-up outside local-fix authorization

The 2026-10-18 user approval now authorizes T059–T062. Keep existing failed
evidence and the aggregate 8,160-credit limit; resolve implementation prerequisites
below before paid execution.

- [x] T059 After explicit publication authorization, deploy the local application repairs with migration 0006 and verify the deployed version/readiness.
- [x] T060 After explicit saved-agent authorization, apply only the prepared active-agent first-message patch and verify fresh provider read-back preserves prompt/tools and includes the recording disclosure.
- [x] T061 After explicit data-restoration authorization, restore the one changed caller profile using retained pre/post identity guards; decide the disposition of retained test booking 46 separately. Resolve the designated caller's two original name groups before paid work.
- [ ] T062 Obtain a reviewed paid execution plan after deployed corrections and caller readiness, retain the consumed authorization and failed run, and complete outstanding live cases without treating offline or conversation smoke as native delivery acceptance.

## Authorized completion implementation

- [x] T063 Regress and implement a strictly nonmutating read_only option for native caller verification, including unknown profiles.
- [x] T064 Regress and implement explicit ID/name binding verified by the fresh native read-only tool, preserving full baseline rows and default ambiguity rejection.
- [x] T065 Regress and implement newly approved continuation provenance, settled-ancestor ledger validation and aggregate Budget.spent admission/reporting; preserve old manifests and reuse/ambiguity guards.
- [ ] T066 Analyze, run focused and complete offline suites, publish verified changes, then execute the reviewed credit-efficient deployed campaign and browser/native-delivery checks; converge any further findings.

- [x] T067 Reproduce settings networkidle failure with controlled pending noncritical traffic; wait for fresh relevant responses and visible populated controls, preserve persistence assertions, then run complete browser verification per FR-029.

- [x] T068 Regress and capture the offline QR image boundary before redirect, preserving ordinary loopback traffic and external denial; verify the complete offline suite without provider dependencies per FR-030.
  - Focused Red: `./run_tests.sh --file tests/test_e2e_browser_network.py` failed the QR continuation contract (1 failed, 7 passed); no provider transport was invoked. Focused Green: 8 passed. Evidence: `scratch/deployed-completion-20261018/offline-qr-{red,green}.log`. Complete verification remains the parent gate.
  - Browser Green: QR capture/no redirect with native agent API plus both staff readiness/persistence regressions passed (3 passed). Evidence: `scratch/deployed-completion-20261018/offline-qr-browser-green.log`.

Operational evidence (2026-10-18): T059 deployed `cf3db1ba` on Render `dep-dba57gm7bikc73ea3bs0`; migration 0006 and native read-only identity were verified. T060 patched only the saved first message with fresh provider read-back. T061 restored customer 5, preserved all 25 original portal rows, cancelled only owned booking 46 and verified its Google cancelled tombstone. The two historical name groups remain intact; the explicit native-verified ID/name binding supplies caller identity without rewriting history. Private evidence: `scratch/deployed-completion-20261018/{approved-corrections-result,deployment-verification,google-accounts-native-audit}.json`.

T067/T068 complete offline gate: 771 unit/integration and 311 E2E tests passed, zero failures/errors/skips (`scratch/deployed-completion-20261018/final-v3-offline.log` and retained full XML). After import-spacing lint cleanup, all 8 browser-network contracts passed again; new modules pass Ruff. Native API C02–C06 recovery on owned requests 47/48 passed with full original-row preservation; that evidence does not reclassify the retained failed C01 or establish LLM acceptance.

## Authorized targeted retest after measured truncation

- [x] T069 Analyze FR-031/032 across spec, plan and existing authorization/ledger contracts; retain the failed eight-turn C01 evidence.
- [x] T070 Regress deployed-only 12-turn scenarios and explicit settled failed/blocked recovery subsets, including dependency expansion, passed-case rejection, missing/inconsistent history, reserve and no-fork/reuse guards.
- [x] T071 Implement the bounded recipe/recovery planning changes without mutating source scenarios, old manifests or normal isolated/tier semantics; run focused and complete offline validation.
- [ ] T072 Execute only necessary authorized recovery cases after the current campaign settles, retain all prior/current charges and failures, verify native/browser effects, then converge.

T070 focused evidence: 11 intended failures before implementation, then 120 captured-provider contracts passed. Private logs: `scratch/live-campaign-20261018/recovery-{red,green}.log`. The first continuation retained C01 max-turn truncation and 633 credits; C04/C05/C06 then passed functional checks at 612/437/420 credits respectively. Its total 2,102 plus the ancestor 634 equals 2,736 campaign credits; all charges settled.

T071 complete gate: 785 unit/integration + 311 E2E passed, zero failures/errors/skips (`scratch/deployed-completion-20261018/final-v4-offline.log` and full retained XML). After import/context-manager cleanup, 120 focused deployed-harness contracts passed again; Ruff reports zero remaining issues in the changed harness files. Stable deployed application commit remains `ebc906a1` during the paid recovery; this change affects the local harness only.

## Resume the already owned appointment

- [x] T073 Analyze FR-033 ownership, fresh-state and passed-dependency boundaries.
- [x] T074 Regress and implement verified owned-state seeding for an explicitly authorized failed/blocked suffix, preserving all current negative, budget and ancestry contracts; run complete verification.
- [ ] T075 After the notification-claim repair, run only C02/C03 on owned booking 50 with a changed target date, retain all earlier outcomes and validate native/browser effects.

Second recovery retained: `ef0ecb10e7d84f5f81e312bc334afea8`; C01 passed (609 credits) and created owned booking 50. C02 native identity/count/time-change/baseline checks all passed, but evaluation failed an unsupported sent-text claim (376 credits); C03 blocked. Total 985, aggregate 3,721 campaign credits, no unsettled usage. The owned appointment remains active at October 27 10:00 for a guarded suffix recovery after the prompt fix. No repeated creation or API reset is planned.

T074 focused evidence: 134 deployed-harness contracts passed, including deliberately redacted saved evidence and a captured C02/C03 flow that reuses the owned ID without C01 creation. Complete gate: 811 unit/integration + 317 E2E passed, zero failures/errors/skips. The suffix preview selects only C02/C03, retains 3,721 prior campaign credits and admits 1,800 estimated credits within the unchanged reserve/ceiling.
