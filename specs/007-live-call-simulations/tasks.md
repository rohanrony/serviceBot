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
- [x] T091 Execute only C07–C16 against the deployed app within the approved ceiling, settle charges, inspect native/browser effects and clean owned test resources. Retain manual inbox as unverified and prepare only the later full delta without paid replay.

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
- [x] T094 Converge and run focused plus complete offline/browser validation for recovery and app fixes; after explicit publication approval, publish only the necessary validated repair and read back native behavior. Earlier no-push/no-deploy instructions remain in force while approval is pending.
- [x] T095 Continue the original C07–C16 execution only after every FR-042 proof and fresh readiness/budget gate passes; preserve the blocked zero-credit original attempt and settle/clean all owned effects.

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
- [x] T099 Converge and rerun focused and complete offline/API/browser validation, publish under the user's approval and verify deployed KB restoration, memory and latency before the unpaid continuation.

T098 evidence: two intended constructor-reuse failures preceded implementation; 27 focused FAQ/catalog contracts now pass. The reusable wrapper preserves default identity/configuration and384 dimensions, stays lazy for injected collections, and reopens a real persisted default collection with a deterministic captured encoder. Native Render Chroma1.5.9 matches local1.5.9; no real model download is used in offline tests. The complete gate is running for T099.

T099 local gate passed **975 unit/integration +348 E2E**, zero failures/errors/skips (`deployed-default-encoder-full-offline.log` and copied XML). Source convergence found no material FR047 gap; Ruff has zero introduced findings. Publication is authorized; native memory, upload latency and restoration remain required before T095.

Commit3dac44e is deployed live as dep-dbaj472vcj2c73aa92jg. Health/list read in
1.37/1.69seconds and effective config hash matches. The warm three-chunk upload
still took11.7seconds and the large upload disconnected after more than one
minute, with no OOM event and sampled memory375MB. The source repair is valid
but does not yet satisfy the native latency gate. No write retry or paid case.

- [x] T100 Analyze FR048, regress and implement encoder-local single-thread ONNX session options with unchanged upstream behavior and no global mutation; retain FR047 compatibility/reuse tests.
- [x] T101 Converge, rerun focused/full offline/API/browser gates, publish under existing approval, settle prior upload and verify actual native document restoration, memory and latency before T095.

T100 red/green: actual upstream cached model property first failed on thread counts0/0. The repaired encoder supplies1/1 only to its own session;28 focused tests pass, including unchanged path/provider filtering/optimization/logging, lazy shared default-compatible384-dimension encoder, existing collection reopen and rollback. Global runtime options remain untouched. Ruff has zero introduced findings; source is frozen for the complete gate.

T101 local gate passed **976 unit/integration +348 E2E**, zero failures/errors/skips (`deployed-single-thread-full-offline.log` and copied XML). No material FR048 source gap or introduced Ruff finding. The prior81.278second catalog upload is settled by native200/request0b096f86 and exactGEThash, with no retry. Publication is authorized; native performance remains the final prerequisite.

- [x] T102 Analyze FR049/050 and retain C08 paid failure; reconcile only request51 with exact provider/native identity proof and restore journaled calendar blocks, verifying preservation and settled effects.
- [x] T103 Regress and implement exact opening service binding for deployed medium C08/C11 and consistent literal vocabulary without changing lifecycle/ownership predicates.
- [x] T104 Regress and implement an explicit same-run never-submitted C09–C16 continuation after the settled prefix, aggregate spending/reserve and immutable numbered attempt evidence; no paid replay or replacement claim/resources.
- [x] T105 Converge, run focused/full offline/API/browser gates and continue only the original eight unused cases after all native prerequisites revalidate. Retain C08 failure and operator inbox gap.

T094/T099/T101 native gate is complete: c4b8ad9 deployed live as dep-dbaj8np42hec73dml1b0; all six preserved documents indexed with exact byte hashes. Catalog upload15.23seconds, current-instance sampled peak250,621,950bytes under512MiB, no new server_failed event. Health/list1.37/1.71seconds; effective config hash and every original business-row hash match. Exact retained clone/catalog, zero-submission proof, quota28325/reserve and designated WhatsApp window all pass. T095 begins only the original ten-case continuation under the same11250ceiling.

T102 cleanup is settled: providerresponsepair/hash and nativecustomer5/allowlistedphone prove newrequest51, originalIDs excluded. A nativeGoogleGET witnessed its actual event/start/end before cancellation. NormalcancelAPI51, reservation/projection/outbox settlement, exactslot849/850/851 restoration, nativeGoogledeletion and originalAPIbaselineallverified. Immutablepre-reconciliationarchiveandhashedreceipt remaininrun/reconciliation. C08failureisretained. T103 meaningfulRed10failed/1passed;54focusedcontractsnowGreen withcapturedprovider-createpayloads; Ruffclean. T104 recoveryremainsinprogress; nopaidreplay.

T104 released:392focusedharnesscontracts pass (29newremaining +363existing), with initial entrypoint/quota failures and four additional intended converge failures retained. Exact331/783providerbilling/provenance, native51settledcleanup, restoredslots, originalclaim/resources, untouchedsuffix and aggregatebudget/reportfailure are guarded. Ruffclean; sourceconvergencefoundnomaterialFR049/050gap. Completeoffline/API/browsergate isrunning beforepaidremainingcases.

T105 full local gate passed **1016 unit/integration +348 E2E**, zero failures/errors/skips (`deployed-remaining-full-offline.log` and copied XML). No material FR049/050 source gap. The original two charges remain settled1114; request51cleanup and all native preservation checks pass. The next standard workflow submits only C09–C16 after fresh locked admission; C08isnotreplayed. Providerwait300seconds, same scenario turn limits/cap.

- [x] T106 Analyze FR051/052; reconcile request52's observed completed cancellation and preserve unknown-operation/attempt3 evidence, native positive calendar witness and original rows.
- [x] T107 Regress and implement a deterministic owned-clone-only canonical-service/prebooking-quote policy revision, prompt-only preservation/idempotence and safe observed update; protected agent unchanged.
- [x] T108 Regress and implement untouched C10–C16 recovery after the longer settled prefix, revision/receipt/archive proofs and aggregate2019spend, preserving failures and no-replay safeguards; add sanitized mutation diagnostics.
- [x] T109 Converge, run full offline/API/browser validation, verify the owned policy revision and resume only untouched C10–C16 within original11250ceiling. Retain C08/C09 failures and pending native inbox verification.

T106 reconciliation settled with zero native mutations: exact owned request52, cancelled native state, released reservations, delivered projections, Google event deleted, hashed attempt3 archive and receipt. Original rows unchanged; native delivery audit verifies 14 signed WhatsApp receipts. C09 paid quote failure retained. T107 pure policy/diagnostics focused gate passed63; owned update awaits fresh complete gate.

T108 released:416 focused recovery/harness contracts passed, including24 new unsubmitted contracts; meaningful Red entrypoint/source-chain/actual-manifest-shape evidence retained. Ruff clean. Bounded source convergence found no material FR051/052 gap. Complete offline/API/browser gate is running before the owned-clone update or further paid execution.

T109 complete offline gate passed1049unit/integration+348E2E, zero failures/errors/skips. Automatic approval review rejected the persistent owned-clone PATCH under the earlier saved-agent restriction; no provider write/admission/newcharge occurred. Specific owned-clone prompt approval is pending. The exact desired source/prompt hashes, policy implementation, preserved original state and 2019settledcredits remain retained. T107/T109 native steps stay unfinished.

- [x] T110 Analyze FR053–055 and reconcile C10's unknown cancellation using native row/calendar proof, preserving attempt4 and original failed receipt.
- [x] T111 Regress and scope quote criteria to new appointment conversations; add bounded native mutation timeout and elapsed diagnostics with unknown-write stops.
- [x] T112 Regress and implement monotonic untouched-suffix continuation after the four-charge prefix and full native/admission/revision proof, without paid replay or a replacement claim.
- [x] T113 Converge, run full offline/API/browser gate, then execute only C11–C16 within the original11250ceiling; retain prior provider failures and inbox gap.

T110 reconciliation settled: immutable attempt4 archive and canonical hashes prove both native fixture creates53/54. Native54 cancellation confirmed without retry; normalcleanupcancelled53once. Both reservations/projections settled, Googledeleted, originalAPIbaselineunchanged. ProviderC10failed481 and originalcriterion remainpreserved. T111 meaningfulRed13fail/7pass;83focusedcontractsGreen/Ruffclean. No remaining paid cases submitted.

T112 released244pureofflinecontracts including17newmonotonic; Red progressiongap retained, Ruffclean. All prioradmissions/archives and strictlyincreasedpaidprefix prove only C11–C16 untouched; C10twoIDfixtureprovenance remainsboundtoexactcreates. Same2500aggregateprefix/5400futureestimate and original11250cap. Full offline gate isrunning beforemorepaid work.

T113 full offline/API/browser gate passed1086unit/integration+348E2E, zero failures/errors/skips; bounded sourceconvergence foundno materialFR053-055 gaps. Same2500settledprefix and no paidreplays; next onlyC11–C16 afterfreshlockednativeadmission.

- [x] T114 Regress and repair C12 callback browser oracle to match the actual portal fields; preserve original evidence and validate separately without paid replay.

- [x] T115 Regress and expose authoritative linked-visit metadata from existing lookup without changing selected-component reschedule semantics.
- [x] T116 Regress and prepare separately versioned single-anchor linked-visit prompt correction, retaining old policy/failure provenance and awaiting external action approval.
- [x] T117 Diagnose and reconcile C16's rejected native setup without paid submission or blind retry; preserve exact operation and attempt5.

- [x] T118 Regress and repair superseded calendar historical-event retirement without stale upserts or active-event deletion; reconcile the exact owned orphan with conditional Google deletion and preserve all evidence.

- [x] T119 Regress and prepare the explicit linked repair admission contract for C15 sample2+C16 sample1, with no external action until scoped user approval.

T115–119 local evidence: 11 linked metadata DB/API contracts, 37 policy contracts,
17 calendar ordering/retirement E2E contracts and 187 repair/continuation contracts
pass. The original canonical policy bytes remain unchanged. Native C16 setup is
settled rejected_no_effect; the exact orphan is conditionally deleted once, with
all owned requests51–62 cancelled, Google effects absent/deleted, 74 signed
delivery callbacks and original business hashes unchanged. The supplemental
repair approval remains false; neither linked policy revision, app deployment,
C15 sample2 nor C16 sample1 has been executed. The combined final gate and
separate read-only C12 browser receipt were required before the final gate below.

Final FR056–060 gate passed **1207 unit/integration +353 E2E**, zero failures,
errors or skips (`linked-repair-full-offline-v2.log`, copied XML and immutable
`linked-repair-full-offline-gate.json`). The first combined gate's8 stale
calendar-lock test-double failures and353 passing E2E results remain archived.
The repaired doubles execute the real projection lock and retirement logic
through captured SQL rows; original deletion/status/failure assertions remain.
Bounded source convergence has no material finding and lint has zero introduced
findings. C12's separate deployed read-only browser check passed on retained
cancelled request56, with the original paid evidence/PNG hashes unchanged and
no replay (`c12-repaired-native-browser-receipt.json`).

- [x] T120 Obtain scoped approval, publish/deploy the frozen reviewed backend/harness repair, verify preserved KB/configuration and deployed linked metadata, apply/read back the second owned-clone policy revision, then execute only C15 sample2 and C16 sample1 under the original11250 aggregate ceiling. Preserve all historical failures and verify native settlement/cleanup; no uncertain write or charge retry.

T120: d3b298b is deployed live as dep-dbalm8flk1mc73d0uph0. All6KB documents restored/indexed exactly; configuration and original business hashes match. Owned linked policy19b6b658... observed; protected reference unchanged. C15sample2 passed503credits and C16sample1 passed521credits, each with one anchor mutation and two lookups. Additional1024; medium aggregate6421; no unsettled charges. Native audit confirms all16owned requests cancelled, all recorded Google events deleted/absent, all recorded Twilio delivered and98signed callbacks. The catalog listing timeout was read-only; archived before normal owned cleanup removed47–49 without paid replay. All11provider test definitions and owned clone are removed. Original C15 receipt/evidence/PNG remain byte-identical to attempt5 archive. Raw stage remains incomplete/failed history; native receiving inbox remains unverified under the operator choice.

- [x] T121 Prepare the consistent production prompt/settings proposal under FR-061 with fixed-point/policy-preservation regressions, exact tracked candidate, full gate and before/after hashes. No production mutation or paid conversation.
- [x] T122 Only after explicit scoped approval, publish the reviewed production prompt with [skip render], apply one normal-settings prompt update to the verified primary target, and read back exact prompt/config/behavior preservation. Retain intent/failure evidence and do not retry an ambiguous update.

T121: The frozen final gate passed **1,212 unit/integration +353 E2E**, with zero failures, errors or skips; all 309 frozen source hashes match. Five focused regressions and Ruff passed. Separate bounded review found no actionable finding. Candidate SHA256 `204af40283c4290426b3252d09da207654ceb3f535379790f96f7619c581fffd` preserves both exact tested policies and the tracked recording/callback safeguards; native/alternate formatting and return to native are stable. The complete combined prompt is not claimed paid-tested. Fresh read-only preparation verified the primary target alone, all 47 existing config keys and unchanged source behavior. Exact prompt-only settings payload and before/after hashes are retained in `production-policy-proposal/settings-proposal.json`. Production promotion is unapproved, no write intent exists, and no additional paid conversation was run.

T122 completion supersedes the preceding pre-execution approval status: explicit approval received, exact five-file package merged as308ee04 with [skip render], one normal settings POST returned200, and two independent read-backs verified exact app/primary-agent prompt and all other settings. No extra paid conversation; Render's existing backend deployment remained live. Private completion receipt: `production-policy-proposal/production-promotion-completion.json`.

## Remaining full delta: native admission and ownership

- [x] T123 Prepare the per-case C17–C50 deployed fixture/evidence/cleanup contracts, fresh read-only budget/provider readiness and exact single-handset limitations under FR-062. Preserve all previous case results and charges.
- [x] T124 Regress and repair exact customer-owned target admission for cancel/reschedule/consolidation under FR-063 in `serviceBot/api/telephony.py`, with meaningful no-mutation assertions in `tests/test_voice_mutation_ownership.py` and PostgreSQL/HTTP contracts in `e2e/test_voice_mutation_ownership.py`.
- [x] T125 Implement full-stage prerequisite and native-case contracts with deterministic failure and coverage tests in `live_simulations/deployed_full.py` and `tests/test_deployed_full_contracts.py`. Do not claim native capability from a ready flag, a local gateway fault or simulated provider evidence.
- [x] T126 Converge the implemented scope, run focused and complete offline/browser gates, and prepare a concrete publication/deployment and full-only budget proposal. Real recipient/time/operator prerequisites remain explicit; do not spend before the reviewed ceiling is approved.
- [ ] T127 Execute only admitted C17–C50 once after complete readiness and approved budget, settle each real charge/effect and clean only owned fixtures. Retain all historical failures, ambiguous-write stops and native acceptance gaps.

## Phase 24: Convergence — remaining native full mechanisms

Bounded FR-062/063 assessment: the local ownership repair and full planning
contracts do not complete full execution. The initial source-owned adapter implemented15
offline fixture paths; Phase26 and C31 below bring that to18. All34 actual full live cases remain unrun. The following
unbuilt work is required before T127, with product/provider/operator prerequisites
preserved rather than converted into passing flags.

- [ ] T128 Integrate the full adapter into the existing deployed workflow only after every selected native prerequisite is independently verified; add full-only authorization, retained common-ledger admission, per-case evidence, ambiguous-write recovery and owned cleanup regressions in `live_simulations/deployed.py` and `tests/test_deployed_full_preflight.py` (FR-062). Keep the current zero-effect live block until that implementation is complete.
- [x] T129 Resolve C25 grouping and C30 selective-removal requirements with the owner, then implement the agreed native domain/fixture contracts and exact durable regressions. Preserve the existing two-row C25 catalog expectation and default whole-group behavior; no assertion weakening (FR-062/065/066). Native use remains part of T127/T137.
- [ ] T130 Design and test bounded native C23/C35/C36/C37 calendar-failure, projection-recovery, lost-response and provider-rejection mechanisms in the full adapter, with exact ownership and genuine deployed/provider causal evidence. Local gateway faults cannot admit those cases (FR-062).
- [ ] T131 Establish actual C38–C41 unenrolled-recipient, closed-window, owned opt-out and quiet-hours prerequisites and restoration without changing deferred production messaging/Gmail configuration. The sole enrolled handset cannot be labeled unenrolled, and a simulated clock cannot prove a native elapsed boundary (FR-062).
- [ ] T132 Establish C33 distinct-customer ownership and C42–C45 correlated staff confirmation/decline/timeout/late-original-sender evidence. Respect handset4893 permission; same-number identities cannot prove a distinct phone or sender. Record required operator participation and real elapsed deadlines (FR-062/063).
- [ ] T133 Implement and test supported native C31 separated callbacks and C47 unavailable-human handoff fixtures/assertions, preserving honest outcomes and existing single domain owners (FR-062).
- [ ] T134 Implement genuine interrupted-invocation recovery for C48 and actual provider conversation/signed-callback/CRM provenance for C50. Seeded bookings or synthetic local signatures cannot substitute for those sources (FR-062).
- [ ] T135 After native mechanisms are ready, refresh full-only measured estimates, quota/units and recipient/time/account readiness; prepare the exact C17–C50 execution proposal and obtain a separately approved affordable ceiling. Keep manual inbox unverified and preserve medium6421-credit history (FR-062).

## Phase 25: Native instance-replacement repair

- [x] T136 Regress and implement normal startup catalog regeneration through the existing owner before readiness in `serviceBot/main.py`, preserving event-loop responsiveness, fail-closed startup, authored files/chunks and isolated test lifespan. Add focused startup and actual PostgreSQL/HTTP contracts; rerun the complete offline/browser gate (FR-064).
- [ ] T137 Prepare the exact reviewed publication/deployment proposal with fresh six-file preservation, current deployed/config/prompt/tool/schema hashes and full offline proof. After explicit approval of the expanded batch, publish/deploy the ownership/startup/grouped-visit repairs and additive migration; create and attach only the reviewed owned cancel-tool revision and synchronize the separately versioned grouped prompt to the primary agent. Restore only required preserved authored data, verify native migration/catalog/index/app-agent prompt/tool consistency and startup duration. Keep production messaging configuration and system Gmail work deferred (FR-061/063/064/065/066).

T123–T126/T136 local preparation passed1367unit/integration+385E2E tests with zero failures/errors/skips (`scratch/full-delta-20261019/full-offline-v4.log`, copied XML and source-frozen gate proof). Exact ownership rejection and startup failure preserve durable state; all new provider tests are captured offline. Independent source reviews found the Google traceback-context leak, which was fixed with three red/green regressions, and no remaining actionable finding in the implemented ownership/startup scope. Full native execution is not converged: T127–T135 and native publication/restoration T137 remain open. No C17–C50 paid submissions or native fixture mutations were made; medium remains11settledinvocations/6421credits.

## Phase 26: Owner-approved visit behavior

T129's product decisions are resolved: combine services per technician and support
selective removal. The final correction keeps the selected appointment start and
reduces its end; companion appointment times stay unchanged. Its implementation
work continues through the tasks below. The previous24-file proposal remains an
unapproved historical snapshot and must be superseded before any publication.

- [x] T138 Add the authoritative nullable component snapshot schema plus additive migration/verification/rollback; test-first group new appointment services per qualified technician while retaining callbacks and atomic admission in `serviceBot/services/booking.py`, `serviceBot/db/connection.py`, `serviceBot/db/queries.py`, focused tests and PostgreSQL contracts (FR-065).
- [x] T139 Test-first implement atomic consented exact selective removal in the existing booking owner, using snapshotted duration, fixed selected start, shortened end, released trailing capacity, preserved companions, last-service selected-only cancellation, idempotent safe rejection and outbox/audit rollback (FR-066).
- [x] T140 Expose component read-back and selective removal through voice and typed portal boundaries, retaining strict full-phone ID ownership and default whole-visit cancellation. Extend the static cancel-tool schema without executing provider sync; add boundary/HTTP regressions (FR-063/065/066).
- [x] T141 Add exact component selection/removal and reloaded outcome/notification-state browser coverage in the existing portal, with no false success on rejection or ambiguous response (FR-066).
- [x] T142 Prepare separately versioned prompt/tool proposals, adapt C25/C30 native fixtures without weakening original assertions, reconcile specification/data/contracts and converge; run an immutable complete offline/API/browser gate, then replace the exact publication/deployment proposal. Native schema/tool/prompt/deployment and paid execution remain separately gated (FR-062/065/066).

## Phase 27: Separated callbacks and native convergence

- [x] T143 Implement the source-owned C31 separated-callback fixture through existing native voice/domain mechanisms, with actual availability/policy prerequisites, exact canonical/specialist/15-minute reservation/15-minute gap/projection/cleanup regressions and captured-provider HTTP/PostgreSQL contracts. Preserve the full-stage live block and all native acceptance gaps (FR-062, partial local completion of T133).
- [ ] T144 Resolve C41's expected deferred notification against the existing voice/customer quiet-hours bypass before implementing its native fixture. Preserve the owner's deferral of production messaging work; real waiting alone cannot establish queue/release under that bypass. Keep shared-phone customer-opt-out and distinct-staff-sender limitations explicit (FR-062, T131/T132).

The first expanded complete gate retained three genuine stale-contract failures:
one migration inventory and two per-service row-count expectations. The fixes add
the exact0007 forward/rollback/verification contract and preserve service identity,
total durations, linked metadata and capacity while asserting approved grouped
snapshots. Scoped migration3 and multiserviceHTTP/browser15 tests pass. Independent
source reviews found no further actionable issue in those changes, the scoped
tool/prompt proposal or C31. The final combined gate and expanded publication
proposal below remain required; no full case or native fixture has run.

Final expanded local gate passed **1458 unit/integration +440 E2E**, with zero
failures, errors or skips (`scratch/full-delta-20261019/full-offline-v6.log`,
copied XML and `full-offline-v6-gate.json`); every frozen source hash is unchanged.
New Python files have zero Ruff findings and modified files introduce none against
HEAD; JavaScript syntax and diff whitespace checks pass. Independent bounded
reviews found no remaining actionable issue in the implemented scope. C25/C30/C31
fixture contracts have104 focused and11 captured-provider HTTP/PostgreSQL tests;
these are included in the complete gate, not additional live cases.

Fresh read-only checks confirm deployed d3b298b, six preserved KB files, unchanged
other settings, approved oil-change price79–119, primary prompt204af4 and21,904
available credits. The deployed app prompt remains the earlier a9454a instance
snapshot and the new component column/migration0007 are absent. The expanded
local proposal in `scratch/full-delta-20261019/review-proposal-v6/` supersedes the
old24-file proposal and requires explicit approval before publication, deployment,
schema application, owned tool creation/attachment or new saved-primary prompt.
No native write or paid submission occurred in this phase; ledger hash and medium
11 settled invocations/6421credits remain unchanged, with zero C17–C50 entries.
All34 native full cases and receiving-inbox verification remain unverified.
T127–T137's unfinished native work and T144 remain open; the full draft30,600-credit
estimate/38,250 reserve ceiling is an unapproved assumption above current balance.

## Phase 28: Memory warning and approved release amendment

The owner explicitly approved the48-file functional deployment package, published
as ec46e20 with skip-render. Before a deployment trigger they warned about the
Free service's memory limit. The latest observed Render OOM was22:49:30UTC on the
prior instance, while current sampled idle use is about185MiB/512MiB. Deployment
remains held for the bounded availability-request repair below. The complete
1458+440 v6 gate remains historical proof for that published source, not proof of
the forthcoming amendment or native memory safety.

- [x] T145 Regress and repair eager portal agent-availability requests with on-demand pointer/keyboard loading, in-flight deduplication, serialized requests, preserved option/assignment behavior, stale-control safety and explicit failure retry. Add actual held-request browser contracts and retain selective-removal coverage; rerun complete validation and prepare/publish the exact reviewed technical amendment under the approved functional-release scope (FR-067).
- [x] T146 Deploy the approved functional repair plus reviewed memory amendment once; verify terminal live commit, additive schema, preserved business data/KB/configuration, current derived catalog/index, native startup duration and sampled memory/failure history before primary tool/prompt changes. Retain ambiguous-write stops and full paid-stage prerequisites (FR-063–067, native portion of T137).

Predeployment inspection incident: a private metadata helper changed a pooled
session's default to read-only. A held transaction observed backend597204 with
default on/source session/configured reset off, restored only that default with
RESET and verified off on the same backend. No business rows or role/database
settings changed. Observed worker-error checks after02:39:57UTC found no further
read-only failures; retain `readonly-session-recovery-v6.json`. Native inspectors
now use explicit BEGIN READ ONLY/ROLLBACK and close, without session-default changes.

The bounded load amendment passed29 focused browser tests and the complete frozen
v7 gate: **1458 unit/integration +447 E2E**, zero failures/errors/skips. All301
source hashes remain unchanged. Seven added browser contracts prove zero eager
availability calls, shared maximum-one fetch, deduplication with live subscribers,
closed/stale control safety, explicit retry and exact chosen-agent PATCH. A minimal
static select reproduces headless Chromium's keyboard-popup commit limitation;
focus/key loading and no automatic mutation are verified, while OS popup commit
is not claimed. Ruff, JavaScript syntax and whitespace checks pass; independent
bounded source review found no actionable finding. The exact five-file amendment
is retained in `scratch/full-delta-20261019/review-amendment-v7/` and continues the
owner-approved functional release and explicit memory-repair continuation. Native
deployment, observed memory and primary tool/prompt completion remain T146.

### T130/T133 isolated truthful-outcome preparation (base6b8aca5)

- [x] Regress explicit unknown calendar/capacity outcomes, preserve verified slots
  and known impossible plans, propagate safe unknown results through voice/graph,
  and remove invented lead-time suggestions after observation failure.
- [x] Regress all voice handoff aliases and preserve summaries while returning
  honest live-transfer unavailability without implicit callback/provider effects.
- [x] Complete isolated focused acceptance:57 unit contracts and46 real local
  PostgreSQL/HTTP contracts pass. New19 unit/5 HTTP tests cover truthful outcomes;
  red/green logs are retained in the isolated snapshot scratch/truthful-repair/.
- [ ] Independent source review and root-controlled application after the primary
  release freeze. These local repairs do not complete native C23/C47 admission,
  T130's recovery mechanisms or T133's remaining fixture/evidence work;
  production messaging/Gmail stay deferred.

### Verified native release completion (T146 / native portion of T137)

Root verified commit `6b8aca5c5b71b0d72ef4323abb52bfb828df2317` live in
`dep-dbapiis9v7es739eic60`, schema0007, the46-service derived catalog/index,
preserved business/configuration/authored KB, and the primary agent's owned
`tool_3901m596epasejm9cpnrydybye2a` and promptSHA256
`c6f23f3ec6872e473d00cf53b8ad546a74746cae1f349540203b76c2ebd23267`.
Exact completion evidence is `scratch/full-delta-20261019/native-release-v7-completion.json`
(SHA256 `e879e893e8ac134187d609b53c0c18ba4129bbb63a1b1aca87169562a7173af9`);
final GET-only verification exited0, all301 source hashes were preserved, and
unrelated provider behavior and the original source tool were preserved. This
completes the native publication/restoration/primary-promotion portion of T137;
remaining full-stage acceptance and prerequisites are not completed by deployment.
The original native-release-v6 receipt remains immutable historical evidence.

Observed memory was462299140bytes (about441MiB) in the04:23:30UTC snapshot.
Root's later read-only calendar checks for technicians7/11 succeeded at04:35UTC;
a04:37UTC sample peaked468983800bytes (about447MiB). No `server_failed` events
were observed through04:31:10UTC. These bounded observations establish neither a
sustained stability claim nor a model RSS bound. All34 C17–C50 cases remain unrun,
with zero new paid submissions/credits; production messaging/system Gmail remain
deferred and T127–T135/T144 prerequisites remain open.

### Expanded isolated C23 portal/qualification acceptance (v2)

- [x] Fail closed on strict catalog/service-ID/membership lookup errors while
  preserving successful mappingless/uncataloged contracts and inactive-only tags.
- [x] Regress and repair portal capacity-query failure and unknown-provider
  outcomes, normalized SPACE/T VARCHAR capacity comparisons and synthetic
  TIMESTAMP compatibility. No arbitrary legacy text-to-timestamp cast is used.
- [x] Clear current stale choices/time/consent on unknown/network failure and
  ignore late form/modal responses, errors and finally blocks. Manual slot checks
  share T145's existing single calendar queue and preserve record metadata when
  optional type/duration/agent controls are absent from the actual HTML.
- [x] Focused isolated acceptance passes87 unit contracts +53 HTTP/PostgreSQL
  contracts +31 browser contracts. New tests comprise35 unit,12 HTTP and10 browser
  cases. A legacy closing-hours fixture now supplies explicit qualifications and
  empty capacity rows; all original90-minute/closing/no17:00 assertions remain.
- [ ] Fresh independent v2 source review and root-controlled application/full gate.

The v1 patch/manifest and genuine failure logs remain retained. These truthful
outcome changes exist only in the isolated snapshot, not in the verified6b8aca5
native deployment. They grant no native C23/C47 acceptance or paid authority.

### T134 partial source component: C48 cancellation lifecycle

- [x] Add an unwired controller for an already journaled C48 invocation; require
  exact run/case/attempt/agent/test/invocation, immutable baseline fingerprint and
  new native booking/reservation/capacity evidence before cancellation.
- [x] Persist exclusive/fsynced one-way intent before a single cancel POST; resume
  with bounded GETs only, including ambiguous cancellation, crash and timeout.
- [x] Require actual terminal cancelled run, known provider credits, preserved
  native booking and paired executed HTTP booking/result with exact returned
  appointment/reservation. Preserve common ledger ownership and actual settlement.
- [x] Add CI-discovered deterministic synthetic unit contracts for ownership,
  seeded/unrelated effects, races, fsync/observation failure, concurrency,
  no-retry reconciliation, receipt provenance and actual-credit uncertainty.
  Standard pytest passes166 new controller contracts plus22 unchanged full-stage
  contracts (188 total); Ruff passes for both new Python files. All data is synthetic.
- [x] Reproduce and repair external `SimulationError` diagnostic retention and
  boolean/float equality across all18 native ID positions; retain genuine Red logs,
  positive integer1 control, exact attempt identity and unchanged booking footprints.
- [ ] Wire a reviewed native observer/preparation journal and runner integration;
  retain C48 unsupported until this exists. No capability flags may bypass it.
- [ ] Separately approve and reserve measured preparation+recovery cost before
  paid preparation, then obtain genuine interrupted and recovery conversation,
  Google/delivery/no-duplicate evidence. All34 full-native cases remain unrun.

T134 remains open, including C50 provenance. This isolated source component made
zero native/provider requests and incurred zero credits. It does not change the
frozen main26-file proposal or deferred production messaging/system Gmail scope.

### Bounded convergence: repeat-booking truthfulness and cost phases

- [x] T147 Reproduce and repair both cached-session booking branches under FR-068;
  require current full-phone ownership and active native reservation read-back,
  safe false/exception/unknown outcomes, no create fallback, preserved cache,
  actual grouped duration and no duplicate effects for exact-time repeats.
- [x] T148 Correct the full read-only cost preview for C48's additional recovery
  phase, reject invalid/missing recovery estimates without inventing a full total,
  retain overrides/reserve and native blocks. Genuine14-red/10-green baseline
  became28 focused passes plus22 existing full contracts. Independent bounded
  source review found no actionable finding; main remained unchanged at that point.
- [x] T149 Independently review the exact follow-up, apply only reviewed files,
  rerun one complete offline unit/integration/API/browser gate, preserve all
  failures and prepare an immutable expanded review package.
- [ ] T150 Publish/deploy the exact expanded package only after scoped approval;
  verify served code, preserved business/configuration state and bounded Render
  memory/failure evidence. Keep T127-T135 native full execution and its separate
  affordable paid-stage approval open; do not replay prior minimal/medium cases.

### Root combined verification of the expanded follow-up

T147-T149 local implementation, bounded reviews and source-frozen verification are complete. The final root gate passed 1815 unit/integration + 543 API/browser tests with zero failures, errors or skips. Prior v11 retained four unit fixture failures and 543 passing API/browser tests; the two legacy fixture files now preserve all six original tests/assertions while providing owned state and isolated per-test session caches. No production guard was relaxed.

The expanded 34-file immutable proposal is review-proposal-v10/manifest.json. T150 remains pending scoped publication/deployment approval. All34 native full cases remain unrun; no new credits were spent and T127-T135/paid prerequisites remain open. Offline counts do not establish native acceptance.

## Phase 30: Offline fixture completion before live acceptance

T150 was subsequently approved and deployed as 074939e / dep-dbb2e0vbtjjs7393ul30.
The immutable native-release-v10-completion receipt records core preservation,
the explained pre-deploy reminder activity, and bounded memory/browser evidence.
The owner now requests local fixes first and live execution later.

- [x] T151 [P] Implement and behavior-test C23 authenticated owned service/staff
  creation and atomic noncascading cleanup with signed exact identities, reference
  races, changed/missing resources and disabled/unauthorized no-effect contracts.
- [x] T152 [P] Complete C48 preparation/interruption/recovery coordinator with
  immutable baselines, both-phase reserve, exact invocation binding, durable
  submission intents, common-ledger settlement and no-duplicate read-back tests.
- [x] T153 [P] Add C35/C36/C37 causal native observers and C50 authenticated HTTP
  ingress audit/read-back, with captured transport, direct/sync rejection, callback
  replay, migration verification and rollback coverage.
- [x] T154 Integrate available offline mechanisms and explicit external-condition
  gates into shared full-case planning/adapter paths; test missing, stale, foreign
  or fabricated observations and retain all native/paid admission boundaries.
- [x] T155 Independently review the integrated patch, fix actionable findings,
  run focused and complete offline/API/browser verification, and record precise
  source completion versus remaining operational requirements. No publish, deploy,
  paid run, real fixture mutation or production messaging work in this phase.

## Phase 31: Convergence

Bounded current-scope review of FR-062/SC-003/SC-004 found four partial
integration/lifecycle gaps. No paid/native outcome is inferred from this review.

- [x] T156 Preserve the business timezone through actual C48 coordinator
  preparation; reject ambiguous/nonexistent local times and test the real
  preparation boundary per FR-062 (partial).
- [x] T157 Require C50 independent Google/message provider evidence in addition
  to authenticated history and exact native booking, propagate required evidence
  and manual/unverified receiving-inbox state through the special executor path,
  and reject a history-only or local-flags-only success per SC-003 (partial).
- [x] T158 Capture a genuine per-case pre-request baseline and prevent prior
  retained/canceled campaign requests from being re-registered as current-case
  effects; retain current-case canceled effects for owned cleanup per FR-062 and
  SC-004 (partial).
- [x] T159 Respect a sequence's uncalled initial value when binding a fresh
  request; recheck discovered reference schema after cleanup locks and reject
  intervening foreign-key/cascade attachments, with disposable-DB regressions per
  SC-004 (partial).

### Offline implementation boundary

All34 C17-C50 identifiers now have source-owned dispatch/observer paths. This is
not native readiness or a successful full campaign. At the v15 boundary, genuine
C50 session billing had no compiled verified-contract reader: the default returned
unknown and full admission deliberately blocked. Phase32 completes that code path
without independently verifying the real account unit contract. Its accounting contract must be verified
and integrated before live work; approving a numeric ceiling alone cannot remove
that gate. Receiving-inbox proof remains unverified under the approved manual
receipt mode. Distinct customer/technician sender identity, an actually unenrolled
recipient, real provider-window timestamps, human replies, elapsed escalation
deadlines and C41's deferred quiet-hours policy remain independent prerequisites.
No current source capability flag, synthetic receipt or prior minimal/medium
approval can replace them. Existing native/paid acceptance tasks remain open.

### Final offline verification and bounded convergence

`./run_tests.sh --verify` passed 2100 unit/integration and569 API/browser tests
with zero failures, errors or skips. The source-frozen final gate is
`scratch/full-delta-20261019/full-offline-v15-gate.json`: all344 runtime/test
source hashes remained unchanged. v13/v14 retain earlier passing test results
but are not final gates because fixes/lint edits occurred during those runs.
The earlier eight-failure unit run and genuine focused Red logs remain retained.

Independent bounded reviews and the root implementation/convergence pass repaired
the recorded timezone, provider-evidence, prior-case discovery, sequence and
reference-race findings. Neutral provider schema defaults, nullable transcript
turns and ordinary non-simulation booking SQL retain regression coverage. No
actionable defect remains in the reviewed, available offline phase. This is not
convergence of the deferred native campaign or proof that all production behavior
has passed. All changes remain local and uncommitted; no deployed/provider
mutation, new paid submission or ElevenLabs credit usage occurred in this phase.

## Phase 32: C50 compiled accounting completion

- [x] T160 Add failing exact-total, unknown-charge, admission quota and persisted
  reconciliation regressions per FR-069 and the C50 accounting contract.
- [x] T161 Implement the strict compiled native total reader and source-default
  execute/reconcile wiring; retain account-specific verification gates and
  current monthly quota/tier checks before new effects per FR-069.
- [x] T162 Review accounting invariants and captured REST/socket/Budget evidence,
  fix actionable findings, and record the actual validation/publication boundary.

Real account-specific native billing equivalence remains an external prerequisite;
these tasks do not set real verification flags or authorize paid execution.

Phase32 bounded review: strict terminal total parsing, immutable original account
contract, under-lock fresh quota/tier checks, downward-only headroom, exact-zero/
failed-charge settlement, source-default execution/recovery and outer once-only
Budget settlement retain captured-provider regression coverage. 64 new expected
Red failures preceded implementation; focused reader/session/native/adapter/causal/
Budget contracts pass with no skipped or expected-failure cases. Independent
requirements/provider-source and runtime reviews found no actionable in-scope
finding. The source models do not establish the real account's native credit
equivalence; no real verification flag was enabled and no provider calls were made.
Full offline execution and publication verification remain separate gates; the
other chat's verifier/CI workflow must reach main before scoped publication.

## Phase 33: PR 7 review repairs

- [x] T163 Add failing C33 pre-submission foreign identity and drift regressions;
  bind read-only snapshots without adopting foreign bookings (FR-070).
- [x] T164 Add failing C48 shared-ledger ceiling and pending-recovery regressions;
  scope ceilings to the run and poll the same recovery handle with bounded
  attempts and a retained continuation binding (FR-070).
- [x] T165 Cover the supported deployed C50 management command and implement
  GET-only native reconciliation with exact authority and ledger aggregation
  (FR-069/070).
- [ ] T166 Review all four PR findings, run fresh exact-candidate full offline
  verification and hosted CI, resolve review threads and publish/merge the
  authorized branch. Preserve deferred deployment and native acceptance.

Phase33 focused evidence: C33/native/conditions and C48 together pass160 tests;
C50 session/credit contracts pass105 tests. Expected Red failures preceded all
four fixes, including three database-independence regressions from independent
review. Source re-review found no remaining actionable issue. Exact-candidate
verification, hosted CI and publication are tracked by T166 and PR7; no new paid
session or production mutation was performed.

### Second hosted review findings

- [x] T167 Reject successful management status while exact native usage remains
  unsettled; preserve ledger/manifest state and cover pending, unknown cost,
  provider failure and mismatched settlement (FR-070).
- [x] T168 Compose real PostgreSQL projection reads with transition validation
  across UTC/non-UTC session timezones; preserve timestamp timezone information
  according to its database writer convention (FR-070).

The 0d556f0 exact-candidate and hosted gates passed2348unit/integration+658API/
browser tests (108browser subset). Hosted Codex review then found T167/T168;
that candidate was not merged. Fresh source evidence and review are required.

### Third hosted review: retained-intent recovery

- [x] T169 Recover committed C35/C36 control responses through private-nonce,
  authenticated GET proof; retain mutation guards and exact blocker provenance
  through create/disarm/cleanup uncertainty (FR-071).
- [x] T170 Journal C23's original response/mapping atomically, recover create and
  cleanup through authenticated GET, and add migration0011 immutability,
  verification and guarded rollback. Reject intervening full mapping edits.
- [x] T171 Normalize operational timestamps by actual business/UTC/database
  writer conventions and reject naive guesses; retain ambiguous confirmed_at as
  wall-clock text without timing claims (FR-071).
- [x] T172 Recover ambiguous C48 handles into their exact phase journals and
  expose phase/fixture continuation through deployed management without replay.
  Preserve billing totals, native-pending state and separate recovery authority.

The 31f1b40 local and hosted gates passed2358unit/integration+658API/browser
tests, but its hosted review identified T169-T172 before merge. Expected Red
regressions covered committed-response loss, phase journal recovery and the
timezone writer mismatch. Independent source review additionally found mapping
drift and missing-trigger verification, both repaired with Red/Green tests.
Integrated focused validation passed320 tests; full exact-candidate verification,
hosted review and publication remain T166. No live calls or deployment occurred.
