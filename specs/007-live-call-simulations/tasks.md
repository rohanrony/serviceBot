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
- [x] T055 Refresh deployed/provider readiness and execute the authorized C01–C06 campaign once within the 8,160-credit ceiling; retain functional/evidence/cost outcomes and any unresolved acceptance or local repair work.

  Attempt retained: run `51ffab47f72f4cba9483a6e8ecaf11ba` stopped after failed
  C01; C02–C06 were blocked. Settled spend 634 credits, no unsettled usage.
  This remained open at that point. Later targeted recoveries below completed the functional cases; the consumed authorization was not replayed.

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
- [x] T062 Obtain a reviewed paid execution plan after deployed corrections and caller readiness, retain the consumed authorization and failed run, and complete outstanding live cases without treating offline or conversation smoke as native delivery acceptance.

## Authorized completion implementation

- [x] T063 Regress and implement a strictly nonmutating read_only option for native caller verification, including unknown profiles.
- [x] T064 Regress and implement explicit ID/name binding verified by the fresh native read-only tool, preserving full baseline rows and default ambiguity rejection.
- [x] T065 Regress and implement newly approved continuation provenance, settled-ancestor ledger validation and aggregate Budget.spent admission/reporting; preserve old manifests and reuse/ambiguity guards.
- [x] T066 Analyze, run focused and complete offline suites, publish verified changes, then execute the reviewed credit-efficient deployed campaign and browser/native-delivery checks; converge any further findings.

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
- [x] T072 Execute only necessary authorized recovery cases after the current campaign settles, retain all prior/current charges and failures, verify native/browser effects, then converge.

T070 focused evidence: 11 intended failures before implementation, then 120 captured-provider contracts passed. Private logs: `scratch/live-campaign-20261018/recovery-{red,green}.log`. The first continuation retained C01 max-turn truncation and 633 credits; C04/C05/C06 then passed functional checks at 612/437/420 credits respectively. Its total 2,102 plus the ancestor 634 equals 2,736 campaign credits; all charges settled.

T071 complete gate: 785 unit/integration + 311 E2E passed, zero failures/errors/skips (`scratch/deployed-completion-20261018/final-v4-offline.log` and full retained XML). After import/context-manager cleanup, 120 focused deployed-harness contracts passed again; Ruff reports zero remaining issues in the changed harness files. Stable deployed application commit remains `ebc906a1` during the paid recovery; this change affects the local harness only.

## Resume the already owned appointment

- [x] T073 Analyze FR-033 ownership, fresh-state and passed-dependency boundaries.
- [x] T074 Regress and implement verified owned-state seeding for an explicitly authorized failed/blocked suffix, preserving all current negative, budget and ancestry contracts; run complete verification.
- [x] T075 After the notification-claim repair, run only C02/C03 on owned booking 50 with a changed target date, retain all earlier outcomes and validate native/browser effects.

Second recovery retained: `ef0ecb10e7d84f5f81e312bc334afea8`; C01 passed (609 credits) and created owned booking 50. C02 native identity/count/time-change/baseline checks all passed, but evaluation failed an unsupported sent-text claim (376 credits); C03 blocked. Total 985, aggregate 3,721 campaign credits, no unsettled usage. The owned appointment remains active at October 27 10:00 for a guarded suffix recovery after the prompt fix. No repeated creation or API reset is planned.

T074 focused evidence: 134 deployed-harness contracts passed, including deliberately redacted saved evidence and a captured C02/C03 flow that reuses the owned ID without C01 creation. Complete gate: 811 unit/integration + 317 E2E passed, zero failures/errors/skips. The suffix preview selects only C02/C03, retains 3,721 prior campaign credits and admits 1,800 estimated credits within the unchanged reserve/ceiling.

## Final operational acceptance (external prerequisites)

The authorized six deployed conversation/API cases now have passing functional
outcomes across retained ancestry; no single-run full-tier/native-acceptance pass
is claimed. C01: `ef0ecb10e7d84f5f81e312bc334afea8`; C02/C03:
`1c4f1d50a9054e958dc091198f2100f3`; C04/C05/C06:
`b6f5f34da20441db9a8e83bee701cf15`. Every failed attempt and charge is retained.
Aggregate campaign credits: 4,527; all retained tests including older calibrations:
5,520; no unsettled charges. Five owned bookings are cancelled, all reservations
and calendar projections released/deleted, no pending reminders/outbox work,
and original records are unchanged. Latest complete offline gate: 811 unit and
317 E2E, no failures/errors/skips. Thirty unique WhatsApp messages for current
owned lifecycle checks are natively delivered.

- [x] T076 Confirm receipt in the designated Gmail inbox. The user confirmed receiving both WhatsApp messages and emails on 2026-10-18. This supplies operator receipt confirmation; the authorized Gmail account remains send-only and its native inbox read still returns 403. Preserve the original incomplete run manifests and do not infer a physical-audio or full 50-case acceptance pass from this confirmation.
- [ ] T077 Complete owner/provider prerequisites for unrestricted production messaging: the US SMS sender returns 30034 until A2P registration, and WhatsApp remains a Sandbox requiring enrollment/open reply windows or approved production templates. Current test-handset WhatsApp delivery is verified; do not equate it with unrestricted production delivery.
- [ ] T078 Reconnect the expired system Gmail OAuth grant through the owner login flow. The connected designated technician account currently sends successfully as fallback; do not replace the system credential with a different person's token.

No further paid ElevenLabs submissions are needed for these provider/account
prerequisites. Full 50-case isolated and physical audio release gates remain
outside the approved deployed six-case campaign; their assertions are not relabeled
as passed. Final native/provider/browser evidence is retained under
`scratch/deployed-completion-20261018/`.

## Differential medium stage (2026-10-18)

The user explicitly defers T077/T078 and requests medium C07–C16 now, followed
by only C17–C50 for a later full stage. Earlier passed cases must not be replayed.
T076 is complete by operator receipt confirmation. Deferred production setup is
not an excuse to mutate accounts or weaken the new isolated acceptance checks.

- [x] T079 Reconcile FR-034–036, the existing subset selector, scope/fixture/budget contracts and parent source analysis before implementation. Graph MCP tools are unavailable; retain exact-source fallback limitations.
- [x] T080 Regress linked native fixture row counts and missing C10/C12/C14/C15 durable-state checks with real owned PostgreSQL fixtures; implement fixes without external provider traffic.
- [x] T081 Regress and implement exact-range isolated stage authorization, preview/admission, manifest/ledger provenance, single-use and unknown-charge/reuse guards; preserve cumulative defaults and deployed restrictions.
- [ ] T082 Validate every selected medium setup prerequisite before paid work, including two designated specialist/calendar bindings and the selected email evidence mode. Prepare isolated infrastructure and private config using approved recipients; leave production messaging and system Gmail deferred.
- [x] T083 Analyze/converge all changes, run focused and complete offline/browser verification, retain red/green and full results, then prepare the reviewed ten-case live plan and credit ceiling.
- [ ] T084 Execute only authorized C07–C16 after readiness and stage budget pass; retain original six passing cases as provenance, settle every charge, verify case-specific native/browser effects, and clean only owned resources. Prepare the later full delta C17–C50 without paid replay or an unapproved full-stage submission.

T080/T081 evidence: 14 intended authorization failures before implementation,
then 24 focused authorization/campaign contracts passed; linked/native fixture
regressions first failed 11 contracts and then passed all 13. The complete current
offline gate passed 827 unit/integration and 330 E2E tests, zero failures/errors/
skips. Evidence is retained under `scratch/medium-delta-20261018/` as
`stage-{red,green}.*`, `fixtures-{red,green}.log`, `full-offline.log` and copied full
XML. A bounded source converge found no remaining FR-034 implementation blocker.
No new paid submissions have occurred. The current designated Google account is
technician 7 (the email supplied by the user); a shared-account fixture choice or
independent second account, receiving-inbox verification method, and the reviewed
new-stage ceiling remain unresolved setup decisions. T077/T078 remain deferred.

The user subsequently approved the proposed 11,250-credit ceiling, designated
the Davidson Gmail account as the second technician, retained the app's existing
Edvenswa admin recipient, and selected manual receipt with native inbox evidence
pending. Revalidate both named accounts; shared-account alias support is no longer
needed. Keep the older readiness observations as history.

- [x] T085 Regress and implement FR-037 operator email mode with separate functional/incomplete acceptance outcomes, preserving default native inbox checks and every other failure. Validate before continuing T082–T084.

Current final offline evidence: 841 unit/integration and 334 E2E tests passed,
with zero failures, errors or skips (`full-v3-offline.log` and copied XML).
The 38 focused operator/authorization/campaign contracts and 17 native fixture
contracts passed. Final Ruff validation and `git diff --check` are clean. Source
converge found no remaining FR-034/037 blocker; graph coverage remains unknown
because the graph tools are unavailable. No medium paid invocation has occurred.

T082 remains open for the Davidson account's owner Google consent, the exact
Edvenswa admin address, and public gateway readiness. The synthetic KB was indexed
through the isolated app's native upload endpoint. Automatic approval review
rejected the test-token request to the task-owned tunnel; explicit approval is
pending. System DNS also cannot currently resolve that tunnel's hostname. Manual
email receipt is approved, with native inbox evidence retained as unverified.

## Deployed-only medium correction (2026-10-18)

The latest user instruction supersedes local live execution. All owned local
live servers, OAuth helper and ngrok were stopped; no medium charge occurred.
The native deployed app is healthy, and its Edvenswa recipient already matches.
Both grants are verified, but Davidson still needs its deployed binding. Earlier
T082/T084 local setup is retained as history and superseded for live execution.

- [x] T086 Reconcile FR-038–041, deployed adapter boundaries, ownership/budget/data preservation contracts and test tasks; analyze before implementation.
- [x] T087 Regress and implement target-explicit medium stage planning, one-use claims, native origin fidelity and deployed runner adapter integration while preserving minimal/isolated restrictions.
- [x] T088 Regress and implement native test-owned deployed fixture setup, case-specific scoped request/reservation checks, ambiguity stops and owned cleanup; never expose isolated reset actions to deployment.
- [x] T089 Prepare the designated deployed Davidson connection and unique catalog definitions; verify both calendars, all reachable recipients, existing customer identity and whole-stage setup without paid submissions. Native catalog creation belongs to locked T091 execution after the one-use authorization claim.
- [x] T090 Analyze/converge the deployed medium changes; run focused and full offline/browser verification and retain exact evidence.
- [ ] T091 Execute only C07–C16 against the deployed app within the approved ceiling, settle charges, inspect native/browser effects and clean owned test resources. Retain manual inbox as unverified and prepare only the later full delta without paid replay.

T087–T089 current evidence: 164 deployed/stage contracts, 42 deployed fixture
unit contracts and six native PostgreSQL/API/browser contracts passed. Captured
regressions cover exact customer identity, independent case date overrides,
future slot admission, immediate per-slot ownership rechecks, partial effects
and unknown responses. Bounded source convergence resolved both reported
slot/date findings. The standard deployed whole-stage `--check` returned
`problems: []`, selecting only C07–C16 with a 9,000-credit admission estimate and
11,250 ceiling. Both designated calendars are connected as staff 7 and 11; the
admin address is verified. Original business-row hashes are unchanged. These
are prerequisites, not paid conversation results; the new full offline gate is
now complete: 914 unit/integration and 340 end-to-end tests passed, zero failures,
errors or skips. The first full gate exposed a nested Playwright session in the
new observer; its regression now keeps the existing browser session active and
the observer owns a separate browser thread. Retained first-run failures are not
overwritten. Final evidence: `deployed-full-v2-offline.log`, copied XML and
`deployed-current-offline-gate.json` under `scratch/medium-delta-20261018/`.

- [x] T092 Analyze FR-042 same-run unpaid continuation, then regress and implement explicit admission, immutable prior-attempt evidence, resource reuse and all unsafe-state rejections. No replacement authorization or additional capacity is permitted.
- [x] T093 Regress and implement FR-043/044: serialize shared embedding/catalog publication, retain the prior index on replacement failure, offload blocking list work and omit past-start candidate provider lookups. Preserve future behavior, row/filter contracts and messaging settings; include native API/browser responsiveness tests.
- [ ] T094 Converge and run focused plus complete offline/browser validation for recovery and app fixes; after explicit publication approval, publish only the necessary validated repair and read back native behavior. Earlier no-push/no-deploy instructions remain in force while approval is pending.
- [ ] T095 Continue the original C07–C16 execution only after every FR-042 proof and fresh readiness/budget gate passes; preserve the blocked zero-credit original attempt and settle/clean all owned effects.

T092/T093 red/green evidence: the initial unpaid-continuation contracts failed
eight intended checks, then all 363 harness tests and 40 focused continuation
checks passed. Native repair validation passed 74 relevant unit and 13 native
API/browser tests, including captured concurrent embedding, real Chroma with
deterministic embeddings, failure preservation, business-time eligibility and
held-provider health responsiveness. Bounded source convergence found no critical
FR-042–044 blocker. New test files are lint clean; legacy product files have zero
introduced Ruff findings. Complete recovery gate and deployment remain T094.

The complete recovery gate now passes 966 unit/integration and 345 end-to-end
tests, zero failures/errors/skips. Evidence: `deployed-recovery-full-offline.log`,
copied XML and `deployed-recovery-offline-gate.json`. Native deployment read-back
and actual continuation remain pending; no medium conversation has been charged.

- [x] T096 Regress and implement FR-045/046 for the confirmed native OOM: one-chunk embedding adds with exact-attempt rollback, safe KB upload replacement and threadpool responsiveness. Retain native OOM event and every failed restoration attempt; no native retry or paid simulation against the unrepaired indexing path.
- [x] T097 Analyze/converge the OOM/upload repair, rerun focused and complete offline/API/browser gates, refresh the reviewable patch and preserve publication approval as pending. Actual deployed memory/index read-back remains required after deployment is approved.

T096/T097 evidence: six intended bounded-batch/publication unit failures and
native held-upload/late-failure regressions preceded implementation. Fifty focused
unit and 57 native API/browser workflow tests passed. The complete current gate
passed **972 unit/integration + 348 E2E**, zero failures/errors/skips
(`deployed-kb-bounded-full-offline.log` and copied XML). Bounded source convergence
found no material FR-045/046 gap; new tests are lint clean and legacy files have
zero introduced findings. Native OOM event `evt-dbagtv942hec739a9j60` and the
failed restoration remain retained. Health recovered automatically; all five
authored document byte hashes remain intact, while the generated catalog needs
rebuilding. No medium test submission or credit was consumed. Automatic approval
review rejected push/deployment under the earlier no-publish instruction;
T094/T095 and deployed memory/index/live acceptance remain pending explicit approval.

The user explicitly approved publication. Commit 62fc3d5 was pushed, merged and
deployed as dep-dbait5bm8hqs73bfifng. Native list latency is 2.31 seconds; baseline,
clone, catalog ownership and zero-paid-continuation proofs pass. Bounded upload
avoids the observed OOM, but the large catalog took 126.3 seconds and disconnected
the client. Native HTTP 200 and the exact downloaded hash settle that write.

- [x] T098 Analyze FR-047, regress and implement a shared lazy default-compatible ONNX encoder; prove existing collection compatibility and reuse across owners/adds/queries without real model downloads. Preserve bounded batches and rollback.
- [ ] T099 Converge and rerun focused and complete offline/API/browser validation, publish under the user's approval and verify deployed KB restoration, memory and latency before the unpaid continuation.

T098 evidence: two intended constructor-reuse failures preceded implementation; 27 focused FAQ/catalog contracts now pass. The reusable wrapper preserves default identity/configuration and384 dimensions, stays lazy for injected collections, and reopens a real persisted default collection with a deterministic captured encoder. Native Render Chroma1.5.9 matches local1.5.9; no real model download is used in offline tests. The complete gate is running for T099.

T099 local gate passed **975 unit/integration +348 E2E**, zero failures/errors/skips (`deployed-default-encoder-full-offline.log` and copied XML). Source convergence found no material FR047 gap; Ruff has zero introduced findings. Publication is authorized; native memory, upload latency and restoration remain required before T095.
