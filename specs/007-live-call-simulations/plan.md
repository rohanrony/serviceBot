# Implementation Plan: Tiered live call simulations

**Date**: 2026-10-17 | **Spec**: [spec.md](spec.md)

## Summary
A separate Python CLI owns campaign setup, sequential ElevenLabs execution, budget
admission, observable evidence and cleanup. The product code is copied, not changed.
A loopback app runs normal lifespan workers; a small authenticated callback gateway
exposes only voice tools and signed provider callbacks through a user-supplied tunnel.

## Technical Context
Python 3.11+, stdlib/Decimal/httpx/psycopg2, existing Playwright. JSON catalog/config,
private local manifests and append-only billing-period ledger. Offline pytest tests
capture provider HTTP boundaries. Browser tests exercise the evidence reader against
the existing real portal. No new application schema or application endpoint.

## Constitution Check
I: one runner owner and existing booking owner. II: read-back assertions and no ambiguous
write retries. III: credentials by environment, masked reports and owned cleanup.
IV: failing contract tests first; offline tests; browser evidence tested in e2e/.
V: truthful pass/failed/blocked/incomplete and separate live/phone acceptance.
Pre-design and post-design gates pass. No extension hooks file is configured.

## Project Structure
live_simulations/: catalog, config/budget, provider, runtime/fixtures, evidence, runner, CLI.
tests/live_simulations/: offline contracts; e2e/test_live_simulation_evidence.py: browser.
specs/007-live-call-simulations/: specification, decisions, contracts, tasks, validation.

## Implementation Decisions
prepare creates an owned database and source snapshot. serve runs that snapshot plus a
route-restricted gateway. run uses these processes, checks explicit agent target and
settings, creates provider tests, polls results, meters actual cost and checks evidence.
Setup is explicit to permit initial Google OAuth/WhatsApp enrollment before paid runs.
Generic checks support SQL, portal, Google events, Twilio callbacks and Gmail inbox.
Scenario-specific fixture/assertion recipes are versioned; deployment-specific account
secrets and unusual external fault arrangements are explicit local bindings. Missing
bindings are blocked before paid work, not silently mocked or passed.

## Validation
Trace requirements FR-001–012 to T001–T017. Offline tests cover budget/quota integrity,
HTTP contracts, ambiguous writes, interrupted cleanup, masking, scenario completeness,
real persistence checks, CLI no-live behavior and browser reload evidence. Run full
relevant suites and converge. No paid acceptance until explicitly launched.

## Isolation details reconciled during implementation

Each campaign creates a new owned agent identity from the designated reference;
reference agents and shared tools are never patched. Preserve platform settings,
pin an enabled HMAC test webhook to the isolated tunnel, block configured initiation
hooks, and verify the clone by reading it back before running tests. Initially the
app has no recovery-agent ID; live execution pins it to the owned clone only.

Allocate persistent reservation ID blocks under the stable artifact root. Observe
native Google calendar HTTP mutations without replacing responses, so non-persisted
admin events also have exact ownership records. Unknown or unfinished effects block
fixture resets and cleanup. Keep operational email receiver identity separate from
the synthetic customer address. Reverify monthly billing identity and account
headroom before every paid conversation.

## Runnable workflow extension

`run_live_simulations.sh` resolves the repository root and invokes the existing
Python CLI's `workflow` operation. `live_simulations/workflow.py` composes existing
preview/prepare/seed/running/run/report owners; it owns no parallel ledger or state.
New live setup requires a terminal; prepared run IDs permit noninteractive execution.
A project skill exposes the same tier parameter without duplicating runner logic.
Validation covers each tier, preview isolation, setup ordering, interruption,
noninteractive guard, existing-run forwarding, argument validation and shell entry.

## Combined test entrypoint
The existing run_tests.sh --verify branch parses live-tier/config/run-id into
separate Bash arrays. Both offline layers still run; failure skips live execution.
On success it invokes run_live_simulations.sh with --tier/--live and optional
config/run-id. Captured subprocess tests copy the entrypoint and replace only its
pytest/live executables, proving dispatch without paid or external operations.

## Standard agent compatibility
Read the configured reference independent of its display name. Fetch each shared
ID with the documented GET /v1/convai/tools/{id}; compare materialized definitions
when present and clear references only on the copied configuration. No-op workflow
recognition is bounded to one start node, no edges/subgraphs/actions. Add captured
provider contracts and verify against the actual reference with read-only calls.

## Calendar readiness permission probe
Preflight checks the resource used by booking: GET calendars/{id}/events with
maxResults=1 and fields=kind. Calendar metadata requires additional scopes absent
from the app's event grant. This check reads no event content and makes no write;
actual creation and notification delivery remain live acceptance criteria.

## Deployed smoke execution (FR-016–018)
Add `live_simulations/deployed.py`, dispatched by the existing workflow before
local Runtime construction. Reuse runner.preview, Budget, campaign_lock,
current_remaining and the existing usage-ledger schema/root. An artifact-only
manifest records target=deployed; it cannot be loaded as an isolated Runtime.
The adapter uses GET health/portal config/staff/bookings; only copied agent tool
URLs and campaign-owned provider tests issue business mutations. Require a unique
existing enabled HMAC webhook to the selected deployment. No deployment writes
for fixtures/setup/cleanup. Only C01–C06 have deployed lifecycle assertions; other cases/setup profiles
are blocked in preflight before paid work. Minimal cases assert exact counts/times and preservation
of baseline records. Provider evaluation plus API checks are separately recorded
from unavailable acceptance evidence; missing observers always yield incomplete.
Use --check for aggregated readiness errors without provider writes. Templates
contain designated contacts but no secrets or unverified billing assertions.
Offline contracts cover routing, recipient isolation, tier membership, URL checks,
ambiguous writes, ledger safety, lifecycle evidence and retained artifacts. No
product browser flow changes; existing isolated browser evidence stays unchanged.

## FR-019/020 extension
Keep the deployed adapter as workflow owner. Add an opt-in baseline policy and a single-case calibration planner in deployed.py, using Budget with an explicit credit ceiling only for calibration. The ordinary preview and default tier admission remain unchanged. Reject full selections, dependencies, repetitions and nonfresh scenarios in calibration. Read the same quota/reset as a separate headroom check without setting verified_credit_units. Cap copied agent output and scenario turns. Persist baseline and calibration scope in the manifest; check original rows before every paid submission and afterwards. Preserve real caller context and isolate newly observed IDs for lifecycle checks.

No schema, UI or browser journey changes. Offline contracts exercise opted-in baseline preservation, default rejection, altered/missing original rows, one-case successful execution, calibration scope/budget validation, no-resource preview and actual overspend/ambiguous-write retention. Run the complete tests/live_simulations suite; existing browser observer code is unchanged. Reconcile original requirements' 1/2/5 percent limits with the explicit FR-020 exception only.

## FR-021/022 reference fidelity
Extend the existing deployed GET-only readiness loop with /api/v1/portal/secrets, consuming only elevenlabs_agent.display_value. Reject mismatch without changing remote data. Record configured reference identity in the private manifest. Use the existing read-back verified owned agent as the authority for deployed test execution; make provider.run's override optional and omit the JSON field when absent. The isolated runner's existing explicit override remains unchanged. Tests cover matching/missing/different/unreadable active identity, zero writes in readiness, provider payload omission, explicit override compatibility and existing ambiguous-write behavior. No application route, browser journey, schema or production saved-agent change. Run the complete offline simulation module suite, then one C01 calibration with the active reference and the existing private budget.

FR-023: Render a copied deployed scenario and replace only its explicit isolated-catalog pricing criterion with a requirement to retrieve live catalog facts and quote the returned price/duration before booking. Keep all other criteria, input scenarios and isolated catalog untouched. Regress exact criterion preservation and original-catalog immutability in test_deployed.py before implementation.

## Verification repair plan (2026-10-17)

Keep lifecycle evidence in the deployed adapter. Parse booking times using the
configured business timezone for naive values; compare instants and require a
real old-to-new time change for C02/C05. Correct the evidence label without changing
pending-booking semantics. Add captured failing regression tests before changes;
run complete simulation contracts and full offline verification after integration.
No schema, public CLI or product browser changes are required.

The orchestrator alone owns paid submissions and records baseline invocation IDs,
new campaign membership and aggregate usage in an ignored session artifact. Reuse
the existing durable ledger/lock and existing tier guards. Never create a fresh
campaign to evade an unsettled charge or bypass the admitted budget.

## Authorized campaign ceiling (FR-024)

Extend only the deployed adapter with `campaign_authorization` containing
`authorization_id` and `credit_ceiling`. Validate complete minimal selection and
one repetition before provider work; reject simultaneous calibration. Reuse the
existing Budget explicit ceiling, case estimates, verified-unit gate and reserve.
Keep manifest authorization and add its ID to charges in the existing ledger.
Under the existing campaign lock reject prior paid use of the same ID before
creating provider resources. Never relax the default tier or isolated path.

Captured tests cover scope rejection, preview/headroom/reserve, successful six-case
execution, retained spend/authorization evidence, unknown-charge behavior and
reuse rejection. No product browser or database schema change is required. Run
the complete offline verification gate before one paid campaign with the prepared
private config. Read-only readiness must be refreshed; retain its evidence and
campaign report rather than automatically rerunning failed paid cases.

## Returning-caller identity preservation (FR-025)

### Authorized completion extension (FR-026–028)

Add a nonmutating read_only option to the existing verify_caller_identity tool,
with regression tests including unknown-name profiles. Deployed readiness may
verify an explicit customer ID/name binding through that native tool and use its
exact name even when other profiles share the normalized phone. The complete
baseline comparison remains unchanged. No new endpoint or state owner.

For a newly approved follow-up, continue authorization provenance via an ancestor
run ID, not by replaying a consumed run. Validate its manifest and all matching
ledger charges under the shared lock, reject unsettled/pending/inconsistent
history, seed Budget.spent from ancestor charges and retain aggregate spend in
preview, admission, manifest and reports. Existing one-campaign authorization
reuse rejection remains. Captured tests must prove prior spend is not omitted.
Per-case estimates retain measured C01 provenance and conservative margins.
Validate offline before any new paid submission. Parent owns all external writes.

For FR-029 replace global networkidle in the recent-feature settings helper with
fresh relevant response waits and selected-pane observable readiness. Reproduce
with a deliberately pending same-origin noncritical request, while preserving
actual staff create/edit and reload assertions. This is harness synchronization,
not an application timeout change or a provider retry. Re-run the complete browser
suite and preserve the failed full-run trace and corrected result.

For FR-030 extract the existing browser-route policy into a pure test-support
helper, retaining loopback allow/external deny behavior. Capture the known local
QR gateway with a small valid PNG before its redirect can escape interception.
Regress real helper calls with mocked routes: QR fulfilled without continuation,
ordinary loopback continued, external requests aborted. Red must not contact any
external provider. The deployed app QR route remains unchanged and is tested
separately as native browser evidence.

T068 implementation uses `e2e/browser_network.py` as the fixture's single route
policy. The exact loopback QR gateway returns a captured transparent PNG;
ordinary loopback requests continue to the application and external requests
abort. Pure mocked routes verify the PNG signature, dimensions, chunk checksums
and compressed image data without opening provider connections. A browser
contract verifies a local PNG response without redirects alongside native agent
API data. These captures prove offline isolation, not live QR functionality.

Derive the persona name from the read-only scoped baseline before creating any
owned provider resource. For an opted-in nonempty baseline require exactly one
consistent nonblank customer name; ambiguous or absent names fail closed. Supply
that name to both rendered scenarios and dynamic variables without a run suffix.
Keep all original fields in the baseline equality check. Add a captured intake
provider that mirrors native profile updates and proves original rows survive,
plus missing/conflicting-name admission tests and explicit mutation detection.
This is a local harness repair. No saved-agent patch, deployment, profile
restoration, cleanup or automatic paid replay is included.

## Eight-turn truncation and targeted recovery

Observed native C01 stopped at the eight-turn limit immediately after accurate catalog quotation and consent request, without a booking. Keep that failed run and its settled 633 credits. Raise only deployed minimal recipe turn allowance to 12 so explicit acceptance and the native booking can occur. Preserve isolated scenario definitions and all evaluation/state checks.

For already authorized targeted retests, add an explicit recovery case selection within campaign_authorization, requiring continuation_of. Use normal dependency expansion, validate every selected case against the immediate final ancestor's failed/blocked results, reject prior functional passes and inconsistent/missing results, and keep fresh authorization reuse/fork/settlement checks. Sum ancestor spending in the existing Budget. Report selected coverage honestly; no paid call is retried inside a run. Plan admission with conservative estimates for the new turn allowance before submission.

Analysis: FR-032 is an explicit recovery exception to ordinary FR-024 all-six selection; unchanged normal campaigns, calibration, isolated recipes and CLI requested/repeat rejection retain their existing contracts. Recovery case selection is `campaign_authorization.recovery_cases`; it must depend on a final immediate ancestor and expand normal lifecycle prerequisites. Revalidate eligibility under the existing lock before resource creation. No prior functional success is eligible for another paid submission.

## Resume an owned settled lifecycle

The first targeted recovery created owned booking 50 successfully; C02 then rescheduled it with all native state checks passing but failed for unsupported notification wording. Retain that failure. Resume only C02/C03 against proven owned 50 after prompt repair, with a fresh later target date. Validate ownership from the ancestor recorded evidence (not its baseline), current row and caller identity before resource creation; preserve all other rows. Seed previous/group IDs so identity/time-change checks remain strict. Never replay passed C01 or callback scenarios.

## Differential stages and medium fixture verification (FR-034–036)

Keep `select_cases` and the existing `--cases` interface. Explicit medium IDs
C07–C16 and future full IDs C17–C50 have no paid prerequisite chain. Retain prior
minimal evidence as read-only provenance; it is not a new isolated result and
does not turn a subset into a complete native-acceptance tier. The deployed
adapter remains limited to C01–C06. Use the owned isolated Runtime, native fixture
owner, tunnel gateway, source snapshot and dedicated database for new scenarios.

Add bounded isolated stage authorization at the runner's existing preview,
campaign lock and Budget integration points. Its exact tier/range/one-repeat
scope and single-use ID must be verified before provider resource creation and
recorded in every paid intent. Do not reuse deployed campaign authorizations,
inflate monthly allowance, omit the global unsettled ledger, or count historical
spend as new stage spending. Keep normal unconfigured limits unchanged.

Reproduce linked fixture row-count rejection with a real disposable PostgreSQL
database and captured external providers, then repair the fixture contract.
Strengthen C10/C12/C14/C15 SQL checks for the named business outcomes and prove
negative states are rejected. Validate all selected setup requirements before
paid work, including two specialist bindings for split/linked profiles. No
production staff/configuration writes or system Gmail reconnection are part of
this work. Existing strict native notification evidence remains required.
Use ACTIVE `appointment_reservations.starts_at/ends_at` as the timing authority
for contiguity and exact linked starts. Native creation leaves nullable legacy
request timing fields empty; a valid reservation must not fail solely because
that cache is unset. Keep exact per-request duration and missing-reservation
rejection. Real native creation and rescheduling regressions cover both paths;
negative tests corrupt the authoritative reservation, not only a legacy cache.

Test layers: focused captured authorization/admission/reuse/unknown-charge
contracts; real-database fixture/check regressions; existing browser evidence
tests; then complete offline unit/integration and E2E gate before live execution.
Only the parent executes external actions or paid submissions. Missing account,
receiving inbox permission or reviewed stage budget remains a disclosed setup
prerequisite; do independent preparation while awaiting it.

For FR-037 add an explicit operator email evidence mode to the isolated runner.
Keep native mode unchanged and all scenarios' required_evidence intact. In
operator mode omit only the receiver-token/profile read during preflight; record
the original receiving-inbox assertion as `passed: false`, `status: unverified`,
with a clear reason during outcome collection. Separate functional checks from
that pending assertion when classifying a case. A passing functional conversation
with pending inbox evidence has raw status `incomplete`; any other failed check
remains failed. Reports expose both statuses and pending evidence. Default
native mode still requires a valid receiver binding and actual matching inbox
content. Add captured preflight/outcome/classification/CLI-report regressions,
then rerun focused and complete gates. Do not copy the expired system sender
grant into the isolated app or use user receipt from the earlier minimal stage
as evidence for new messages.

## Deployed medium stage (FR-038–041)

Keep `deployed.execute` as the paid lifecycle owner. Extend shared stage planning
with an explicit trusted target argument; isolated callers retain their original
guard, and deployed support accepts only the exact medium range. Reuse
`claim_stage` under the existing campaign lock, before native fixture changes or
provider clone creation. The existing unused authorization ID is retained.

Add a bounded `deployed_medium` adapter with this integration boundary:

- `readiness(config, client, cases, baseline)` returns setup problems without
  mutating business data; validate explicit owned catalog and staff bindings,
  scoped database access, allowlisted receivers and case prerequisites.
- `Adapter.prepare_catalog()` creates planned, uniquely named catalog items
  through native APIs only after the run has claimed its authorization under
  the campaign lock. Validate the resulting exact bindings before clone/billing.
  There is no separate prepared claim or new claim reuse. Setup failure retains
  its intent and consumes this one-use authorization. FR-042 permits only a
  separately gated completion of the same unpaid execution and its resources.
- `Adapter(campaign, client).arrange(case, values)` returns the adapted case and
  its fixture request IDs. Persist fixture intent before each native API call;
  retain exact created IDs and original calendar-slot values.
- `Adapter.checks(case, values, before, after)` evaluates narrowly scoped native
  request/reservation data and journals attributable new IDs. Case names map to
  exact test catalog names; catalog duration drives strict complete/contiguous
  visit checks. Existing customer records remain protected by the deployed
  baseline comparison as well as native identity checks.
- `Adapter.cleanup_case()` cancels only recorded requests through native tools
  and restores only recorded test calendar blocks. Unknown responses require
  reconciliation. Cleanup failure blocks subsequent paid cases; no global SQL
  reset is accessible. Raw provider and failure evidence remains retained.
- Calendar block setup admits only future AVAILABLE slots with no ACTIVE
  reservation. Re-read exact ID/state immediately before each PATCH and
  restoration. An intervening change or reservation stops cleanup rather than
  overwriting the slot. Catalog cleanup removes only journaled items after all
  owned booking/provider effects settle; retain blockers if native deletion
  cannot preserve the booking audit.

Use three uniquely named test-owned catalog items for oil, second same-technician
service and split-specialist service. Their normal API qualification bindings
establish the intended profiles without changing existing catalog records or
assignments. Bind the owner's Davidson grant to a new deployed technician only
after verifying the exact account, Google client and encryption owner. Retain
that designated account connection; remove only temporary test catalog fixtures
after their bookings and provider effects settle. Keep provider credentials in
memory through Bun; remote DB access is read-only for outcome checks.

No app deployment or tunnel is needed for this harness change. Native tool URLs
and HMAC callback remain on the existing deployment. Browser/native calendar and
notification follow-up evidence must remain distinguishable from raw campaign
scope; operator inbox remains explicitly unverified. Retain the previous local
gate, add focused captured/native fixture regressions, then rerun the complete
offline gate before the first deployed paid invocation.

The initial deployed medium branch requires explicit operator email mode;
unsupported native inbox verification must reject during planning before claim,
fixture changes or billing. Existing isolated native and deployed minimal paths
keep their defaults. Regress this default-mode admission boundary explicitly.

## Explicit unpaid continuation (FR-042)

Add an explicit workflow continuation switch, rejected for every target/tier
except the same claimed deployed medium run. Admission belongs under the same
campaign lock. Do not broadly relax `Campaign` attempted-run protection or clear
its flags. Validate the immutable original blocked attempt and exact ledger
claim; require zero charge entries, provider tests/invocations or any historical
test-create intent, no ambiguous/pending operation and no case fixture effects.
Read back the existing clone fingerprint and every journaled service binding;
reuse them without creation. Validate all normal readiness gates against owned
catalog definitions while preserving the original baseline. Archive the original
manifest/reports with hashes, then append a numbered continuation record before
proceeding. Preserve budget/reserve/unknown guards and exact-once paid selection.
Tests must prove every disqualifying condition rejects before mutation or paid
work, and a read-only failure before case arrangement can resume exactly once
without changing the claim or resource counts. Complete the full offline gate
again before using this recovery path.

## Native defects found by live setup (FR-043–044)

Use a shared process `RLock` in `serviceBot.services.rag` around collection
initialization, embedding add/query and the complete catalog synchronization
snapshot. The current deployment runs one Uvicorn process; do not claim a
cross-process guarantee. A file replacement operation retains the prior exact
chunk IDs until replacement indexing succeeds, then removes those IDs. Write a
temporary text file and atomically publish it after successful vector replacement;
on embedding failure keep the original file/index. Exercise concurrency with
events and a captured embedding boundary rather than real model downloads.

Keep `get_service_requests` async and await `run_in_threadpool` for its synchronous
implementation. Skip candidate lookup only for a reliably parsed past booking
start in business time; keep every original row, future/unknown-time behavior,
filters and fields. Regress a blocked candidate lookup with a health request
and browser read-back before deployment. Memoize the existing WhatsApp
connectivity lookup per exact phone within one list response, eliminating
repeated nested database reads for the same technician without cross-request
staleness. Regress duplicate and distinct phone behavior. These actual application
fixes require explicit publication approval followed by a validated deployment.
The earlier no-push/no-deploy instruction remains in force while that approval
is pending; local artifact changes do not grant it. Production messaging and
system Gmail deferrals remain in effect.

## Bounded KB indexing and responsive uploads (FR-045–046)

The existing collection add receives every 500-character chunk together; the
installed default ONNX embedder internally permits batches of 32. Submit one
chunk per add while retaining the shared lock for the complete replacement.
Journal generated new IDs locally and delete exactly those IDs on a later-batch
failure; preserve the previous index until all adds succeed. This bounds batch
size, without claiming that offline tests prove a specific deployed memory peak.
Include IDs of a failed add that may already have persisted; prove add-then-raise
rollback and surface rollback failures explicitly.

Move upload's synchronous KB replacement into a threadpool helper. Use the
existing atomic temporary-file publication pattern and `replace_text`, preserving
the API/response and old file/chunks on embedding failure. Regress bounded large
input and hold the same shared lock until final file publication; regress
concurrent same-filename index/file consistency. Regress partial batch failure
and unrelated-document protection, plus native held-index health responsiveness
and upload/download browser behavior. Validate
actual memory and settled indexing after approved deployment before continuing
paid calls; deployment approval is currently pending after automatic review
enforced the earlier no-push/no-deploy instruction.

## Reuse the default embedding model (FR-047)

The user explicitly approved publication; commit 62fc3d5 is deployed and native
booking-list latency is 2.31 seconds. Keep that authorization for necessary
repairs. The bounded catalog upload settled with matching bytes but took 126.3
seconds and lost its client connection. Reconcile it without another upload.

Keep a single lazy ONNX instance behind a default-compatible embedding wrapper,
shared across FAQService owners under the existing lock. Preserve Chroma's
`default` name and empty configuration and keep the same MiniLM encoder. Prove
reuse across adds and queries and compatibility when reopening an existing
default collection using a deterministic captured encoder. Retain bounded adds,
rollback and upload responsiveness tests. Rerun the full gate and publish the
small validated repair under the existing approval. Native serial restoration,
memory/latency read-back and the unchanged FR-042 proof precede any paid case.

## Bound encoder CPU threads (FR-048)

Keep the upstream ONNX embedding object. Give only that object's `ort` reference
an instance-local forwarding facade whose `SessionOptions()` factory sets intra
and inter operation thread counts to one. Forward provider enumeration, session
construction, graph optimization and all other runtime attributes unchanged.
Do not copy the upstream model loader or monkeypatch the imported runtime.
Regress that the encoder receives bounded options while an unrelated runtime
session keeps its defaults, and retain existing lazy/shared/default-collection
contracts. Official primary reference:
https://onnxruntime.ai/docs/performance/tune-performance/threading.html
This is a testable performance hypothesis; actual upload completion and latency,
not the option values alone, admit paid simulation. Settle the prior disconnected
upload before another deployment/restoration. Repeat the full offline gate and
publish under the existing explicit approval.

## Exact simulator service binding and unused remainder (FR-049–050)

Put literal owned-service instructions at the start of deployed medium scenarios;
explicitly add the missing appointment service to C08 and reinforce C11 while retaining each
case's conversation order and selected visit. Keep callback C12 service-free.
Use captured provider-create payload regressions and preserve strict quote and
native ownership checks. Do not change the saved production agent or catalog.

Add an explicit remaining-cases workflow path for the existing run. Under the
campaign lock prove the exact settled paid prefix and never-submitted suffix,
archive the prior attempt/reconciliation, validate all retained resources and
native preservation, and admit only C09–C16 with aggregate spending1114already
counted. No new claim, authorization, clone or catalog; no paid prefix replay.
Keep FR042's zero-submission recovery restrictions intact. Number attempts and
reports without dropping historical C08 failure. Regression-test every unsafe
prefix/suffix, pending creation/unknown charge, changed resource, unsettled
business effect and repeated admission. Full offline/API/browser validation
precedes the remaining paid work. This harness change needs no app deployment.

## Owned prompt repair and untouched C10–C16 (FR-051–052)

Create a deterministic prompt-only policy transformation in an ordinary helper
module, with literal canonical-name propagation, pre-mutation quote/consent and
legacy single/multi tool guidance. Tests prove idempotence and that every
non-prompt field is identical. Snapshot the original prompt and fingerprints;
revise only the manifest-owned clone after all billing/business effects settle.
Use an intent journal and native GET verification, preserving unknown-write
stops and the protected original agent. Production promotion requires separate
review/authorization; no production agent mutation is part of this repair.

Reconcile request52's already-completed cancellation with exact native identity,
reservation/projection/outbox and Google deletion proof; preserve the original
unknown operation immutably before marking its outcome observed. Add sanitized
operation diagnostics without logging credentials or response/customer bodies.
Generalize the existing recovery checks for the exact next unused suffix
C10–C16 and the longer settled prefix, retaining every prior admission/archive,
failure and aggregate credit. Verify the prompt revision against both the
original source and observed owned clone. Run focused/full offline/API/browser
gates before resuming; no local app/tunnel or protected-agent edits.

## Accurate existing-visit evaluation and settled suffix progress (FR-053–055)

C10's native selected/unselected booking checks passed, but the provider quote criterion was wrongly appended to a reschedule-only case. Scope quote evaluation to new appointment cases C07/C08/C09/C11/C13/C14, keeping service names and every other assertion unchanged. Preserve the original paid result.

The cleanup diagnostic proves a client ReadTimeout. Native logs show the same cancellation returned 200 in1.48seconds after the client wait; reconcile its exact native state before any retry. Use a bounded native mutation timeout and safe elapsed diagnostics; provider billing calls retain their own timeout. Do not infer a backend failure or redeploy from this client symptom.

Validate the original immutable admission chain, four terminal charges (2500), all owned effects and the observed prompt revision before C11–C16. Require strictly shorter untouched suffix progress, durable creation intent and archive history under the same lock. Repeated admission with no newly settled prefix, paid replay, changed resources, unknown usage and unresolved cleanup must block. Run full offline/API/browser gates before any further paid work.

## Callback browser observation (FR-056)

C12 provider and persisted callback checks passed, but its browser oracle compared service_type Repair to the portal's displayed issue description and Callback badge (app.js824). Add issue_description to the fixed read-only native row query and use exact rendered callback identity while retaining owned selector/status checks and appointment assertions. Test malformed/missing/mismatched issue/type data. Do not change the portal or paid result. Current running attempt retains its loaded observer; apply and validate the repair separately after its evidence is retained.

## Authoritative linked-visit metadata and single-anchor policy (FR-057–058)

C15's two concurrent component reschedules correctly applied selected-component domain anchoring, producing an incorrect caller visit start. Do not change that domain contract. Expose linked-visit metadata in existing appointment lookup and preserve separate/unlinked appointments. Add a separate prompt policy version, retaining v1 for historical fingerprint proof. Use authoritative group metadata to choose the earliest component, mutate once and verify all returned member times before claiming success. Regress linked/unlinked/callback/cancelled-companion and duplicate-group paths. Prepare a reviewable tested app/prompt correction before requesting native deployment/persistent-agent/failed-retest approval.

## Historical calendar-event retirement (FR-059)

C15 generated two successive moves; the stale intermediate A-to-B projection skipped both B upsert and A deletion. Later B-to-C and cancellation only retired B/C, leaving owned reservation43 eventA busy and blocking C16 despite clean native slots. Separate recorded old-event retirement from obsolete upsert admission, retaining ordering locks and protection for every current active identity. Verify with captured calendar state and real PostgreSQL ordering regressions. Journal and reconcile the exact existing owned orphan independently; do not retry C16 setup before proof.

## Consistent production policy promotion (FR-061)

C15 sample2 and C16 sample1 passed provider and functional checks with one anchor mutation and two lookups each. Their additional1024credits settle the medium aggregate at6421. Owned catalog/provider resources are removed and all original data hashes match; historical failures and native inbox uncertainty remain retained.

The native app settings prompt and saved primary-agent prompt already differ. A normal settings save applies existing business-hours/lead-time formatters, so direct promotion of the clone prompt would not make the settings source consistent. Prepare a tracked prompt/settings candidate with the byte-identical tested policy sections, formatted with read-only native operational settings. Preserve the tracked recording disclosure and explicit callback lead-time rule; use a configured-lead-time reference in the follow-up sentence so alternate settings cannot leave an obsolete numeric rule. These base safeguards differ from the saved-agent simulation base; do not call the complete candidate a paid-tested prompt. Prove fixed-point formatting and policy preservation through deterministic offline regressions, then rerun the complete gate. Read-back proves the normal sync targets only the intended primary agent and preserves its existing name. Prepare prompt-only settings payload and before/after behavior/config hashes; require separate production/publication approval and no paid test rerun.
