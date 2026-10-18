# Feature Specification: Tiered live call simulations

**Created**: 2026-10-17
**Status**: Approved for implementation
**Input**: Approved conversation plan and docs/LIVE_CALL_SIMULATION_BRIEF.md.

## User Scenarios & Testing

### US1 — Cheap repeatable campaigns (P1)
An engineer previews then explicitly launches a minimal, medium or full campaign.
Given a monthly allowance, budgets are 1%, 2%, 5% per invocation. Preview has no
network traffic or provider mutations. Missing quota/rates blocks paid execution.
Selected subsets never count as complete tiers. Every failure survives retries.

### US2 — Conversations with observed outcomes (P1)
Synthetic callers exercise appointment and staff-callback lifecycles through the
actual agent, local application, portal, calendars, WhatsApp and email. Each case
has setup, caller behavior, expected/forbidden actions, assertions and cleanup.
Fresh reads and reloads, rather than agent speech, determine success.

### US3 — Isolation and recovery (P1)
A campaign owns its disposable local database, runtime files, test-agent resources,
provider events and ledger. It cannot modify production agents or non-owned data.
An interruption leaves a durable resumable evidence/cleanup record.

### Edge cases
Unknown usage, quota rollover, ambiguous provider POST timeout, failed dependencies,
missing receiver proof, orphan calendar effects, replayed tools, interrupted cleanup,
unsupported voice capabilities and simulation/webhook differences remain visible.

## Requirements
- **FR-001**: Version 50 cases with cumulative membership 6/16/50 and requirement IDs.
- **FR-002**: Expose plan, run and cleanup operations; live execution requires --live.
- **FR-003**: Enforce conservative sequential admission against 1/2/5% monthly budgets,
  with 20% reserve, current remaining allowance, one repetition by default and a
  per-billing-period actual-usage ledger. Unknown charges stop further submissions.
- **FR-004**: Use current create/run/poll/cancel interfaces; never retry ambiguous writes.
- **FR-005**: Isolate source snapshot, configuration, KB and loopback PostgreSQL; keep
  real lifespan workers enabled. Only a designated test agent targets the tunnel.
- **FR-006**: Validate caller context, tool URLs/auth, allowlists, calendar access,
  WhatsApp readiness and receiving inbox before any paid conversation.
- **FR-007**: Capture tool request/results and check state, ownership, reservations,
  outbox, reloaded portal, real Google events, WhatsApp status callbacks and email receipt.
- **FR-008**: Separate provider delivery from handset confirmation, controlled faults
  from native effects, and simulation traces from native call-history evidence.
- **FR-009**: Persist redacted reports/provenance and all failures for 30 days; cleanup
  only recorded run-owned resources and report unfinished cleanup.
- **FR-010**: Fail/incomplete/blocked are never passes; dependent cases cannot run
  against failed setup. App defects remain findings, not automatic product changes.
- **FR-011**: Document a separate opt-in, separately budgeted real-phone release gate.
- **FR-012**: Offline tests exercise runner contracts and real browser read-back with
  provider boundaries captured; no paid runs or external deliveries during development.

### Key Entities
Scenario, Campaign, Budget, BillingPeriod, Fixture, ResourceManifest, Check, Evidence.

## Success Criteria
- **SC-001**: Every catalog case has observable acceptance conditions and tier assignment.
- **SC-002**: Preview and default automated tests cause zero external effects.
- **SC-003**: Every accepted campaign has evidence for all selected required checks.
- **SC-004**: No resource outside a campaign manifest is removed by cleanup.
- **SC-005**: Actual usage and incomplete coverage are always reported.

## Clarifications
Default isolated acceptance uses a local application with public tunnel; deployed
smoke uses the explicit FR-016–018 exception. Staff callback lifecycle; WhatsApp and email;
monthly ElevenLabs allowance is budget basis, per invocation; minimal uses real effects;
automated provider/inbox proof plus handset spot-check; phone smoke is separate.

## Assumptions
One repetition, explicit runtime credentials, synthetic fixtures and designated test
receivers. The standard ElevenLabs workspace may supply the read-only reference. Test-only controlled faults are labeled. Live baseline requires account
setup and is not evidence supplied by this implementation's offline validation.

## Workflow entrypoint extension

- **FR-013**: Provide one executable workflow with a `--tier minimal|medium|full`
  parameter (minimal default). Default execution previews offline; `--live`
  prepares a new runtime, guides account setup in an interactive terminal,
  stops setup processes, runs the selected campaign and prints retained report
  and cleanup locations. An explicit prepared `--run-id` supports unattended use.
  Keep existing budget, ownership, repeat/subset and live authorization semantics.
  Interrupted setup retains its run ID and cleanup instructions. No automatic
  cleanup removes evidence. Provide a discoverable agent workflow for the same CLI.

## Combined verification extension
- **FR-014**: `./run_tests.sh --verify --live-tier minimal|medium|full` consumes
  live options itself, runs both offline layers, then launches the selected live
  workflow only if both pass. Without a live tier it remains offline. Accept
  `--live-config PATH` and `--live-run-id UUID`; preserve pytest options unchanged.
  Reject malformed live options before starting suites and preserve live exit status.

## Standard reference profile
- **FR-015**: Permit the configured standard agent as a read-only reference. Resolve
  shared tools through GET, reject inconsistent materialized definitions, and copy
  them inline with isolated URLs. Accept a start-only empty workflow as equivalent
  to no workflow; nontrivial routing remains blocked. Never rename/patch the source.

## Deployed execution extension

- **FR-016**: Support `workflow --target deployed` against the explicitly configured
  HTTPS `deployed_url`. Do not prepare/start/reset local or deployed databases,
  reconfigure deployed staff/Gmail, create a tunnel, or patch the reference agent.
  Use the selected cumulative catalog and the same budget ledger/admission rules.
  Read-only preflight verifies health, all reachable notification recipients, an
  empty active-booking baseline for the designated customer and real tool/webhook
  destinations. Create only campaign-owned ElevenLabs resources.
- **FR-017**: Support the minimal appointment/callback lifecycle through native
  deployed tools with fresh API observations and baseline preservation. Reject
  cases lacking deployed state assertions (C07–C50) or needing fixture mutation/fault
  injection before paid submission; list
  their IDs without silently reducing the requested tier. Preserve isolated mode
  for complete medium/full fixture coverage. Report missing database, browser,
  calendar, signed callback and inbox evidence as incomplete acceptance, even
  when provider evaluation and API lifecycle checks succeed. Deployed execution
  is a conversation/API smoke run, never a substitute for isolated acceptance.
- **FR-018**: Provide a checked-in deployed config template using standard exported
  credential bindings, with no guessed credit units/estimates, plus a read-only
  `--check` operation and terminal run instructions. Retain interrupted reports,
  never retry ambiguous submissions, and keep deployment data/events on cleanup.

### Clarifications (2026-10-17)
User selected https://servicebot-w6hm.onrender.com, requested test updates and will
execute in a new terminal. No technician was selected from the pending question.
Preflight therefore checks every reachable technician destination; it does not
choose or silently edit a technician. Configured observers and billing estimates
remain operator prerequisites. Production-target authorization applies only to
synthetic conversations and the designated test recipients.

## Single-case calibration and returning caller (2026-10-17)
- **FR-019**: Explicit `preserve_existing_bookings: true` permits the same designated caller with existing active requests. Snapshot its records, supply real existing-booking context, check the baseline before paid submission and after observations, and fail if any original request changes or disappears. Default empty-baseline readiness stays unchanged. Never reset or cancel existing records.
- **FR-020**: An explicit deployed `calibration` configuration permits exactly one requested fresh C01 or C04 case, minimal tier, one repetition, under an independently declared credit ceiling, a positive case upper estimate, and a prior sample run ID. Retain the 20 percent reserve, live monthly-period/headroom check, shared ledger and no-retry rules. This exploratory calibration does not assert subscription-to-simulation unit equivalence, relax ordinary tier limits, or count as a complete tier. Cap agent output at 256 tokens and case turns at eight. Report ceiling, estimate, actual credits, prior sample provenance and incomplete native acceptance. Missing or invalid budgets fail before paid work.

Accepted user scope: retain 4242704893, preserve existing bookings, use the 126-credit two-turn sample to inform one new minimal case. One eight-turn estimate with a 2x sample margin is 1008 credits; separate calibration ceiling 1500 credits, admission limit 1200. These are exploratory estimates, not guaranteed provider cutoffs. No automatic second paid test or cleanup.

## Deployed reference fidelity follow-up
- **FR-021**: Deployed readiness must read the portal's active non-secret ElevenLabs agent identity and reject a missing, unreadable or different configured reference before any provider mutation or paid submission. Record reference identity in the run manifest. Do not automatically patch any saved production/reference agent or synchronize portal settings to make a test pass. A failed simulation of another reference is not evidence about the deployed active agent.
- **FR-022**: After the owned clone's full native configuration is verified, invoke deployed tests against that persisted clone without a redundant inline configuration override that clears registered tool IDs. Preserve its registered tool references and unchanged prompt; normal explicit provider overrides remain supported for other callers. Capture regression coverage for the exact run-tests request and the selected owned agent.

Investigation: the former reference prompt is the 63-character custom test sentence, while the deployed active agent is different and has a 22920-character booking prompt plus 11 native tools. The portal application config contains a 23176-character prompt; do not silently synchronize these two prompts. The current API uses tool_ids; inline tools are deprecated. Scope is harness/reference fidelity, not a production prompt rewrite.

- **FR-023**: Deployed pricing evaluation must require retrieval and accurate quotation of price/duration from the deployed tools/knowledge base before booking. Do not impose the isolated fixture's fixed dollar amounts on a different live catalog. Preserve all other success criteria and the original catalog; native delivery evidence remains separately incomplete.

## Verification clarifications (2026-10-17)

FR-017 lifecycle evidence compares parsed booking instants, interpreting naive
timestamps in the configured business timezone. Equivalent ISO representations
must agree. A reschedule must preserve identity and change the previous booking
time to the requested new time; a no-op is not successful rescheduling. Pending
requests remain valid persisted bookings; evidence must not call them confirmed.

The user authorized complete offline suites plus deployed C01–C06 smoke, local
repairs, designated test notifications and a 2,200-credit aggregate session ceiling.
Existing tier ceilings/reserve and unknown-charge stops remain enforced. Saved
agents and deployed application settings are not changed. Full acceptance and any
live work that cannot fit the conservative budget remain incomplete.

## Authorized six-case campaign (2026-10-18)

- **FR-024**: An explicit `campaign_authorization` configuration permits exactly
  one complete deployed minimal C01–C06 pass, with no subset or repetition, under
  its declared positive credit ceiling and nonblank authorization ID. It is
  mutually exclusive with single-case calibration. Verified credit units, normal
  per-case estimates, the 20 percent reserve, fresh monthly headroom, recipient
  checks, baseline preservation and ambiguity stops remain required. Persist the
  authorization in the run manifest and ledger; another paid run cannot reuse it.
  Ordinary tier limits and isolated execution are unchanged without this opt-in.

The user approved the recommended **8,160-credit ceiling for one six-case pass**,
superseding the earlier 2,200-credit ceiling for this operation and authorizing
the scoped tier exception. The six-case estimate is 6,528, leaving 20 percent
reserved. This is not approval for a second full campaign, saved-agent edits,
deployment or cleanup. Retain failures and report live acceptance honestly.

## Returning-caller identity preservation (2026-10-18)

### Authorized deployed completion (2026-10-18)

- **FR-026**: An explicit existing-customer ID/name binding may resolve multiple
  baseline name groups only after a fresh native `verify_caller_identity` call
  with `read_only: true` returns that exact existing ID/name. This mode never
  renames unknown profiles. Preserve every original baseline row and comparison.
  Without a verified explicit binding FR-025's ambiguity block remains.
- **FR-027**: A newly user-approved follow-up campaign may declare
  `campaign_authorization.continuation_of` referencing the retained failed run.
  Keep the old run and authorization consumed. Under the shared lock validate
  settled ledger charges and matching target/ceiling, include all ancestor spend
  in the 8,160-credit aggregate ceiling and its 20 percent reserve, and reject
  missing/ambiguous/in-progress history. Never overwrite or replay the old run.
  New per-case estimates must retain their evidence and rationale; estimates
  are admission bounds, not provider-side hard cutoffs.
- **FR-028**: Deployment, saved-agent greeting correction, guarded caller-profile
  restoration, owned test-booking lifecycle changes, targeted paid retests and
  native notification/browser checks are now authorized. Prove receiver outcomes
  and native state with fresh read-back; maintain the aggregate ceiling including
  634 credits already settled. Failure history remains evidence, not a pass.

- **FR-029**: Browser settings readiness must wait for the selected pane's fresh
  data and visible controls. An unrelated pending request must not prevent staff
  create/edit/reload acceptance when native staff/config reads have completed.
  Keep the persisted API and reloaded-selector assertions; do not increase
  timeouts or retry away a failure.

- **FR-030**: Offline browser tests must capture the external QR image boundary
  before a local redirect can reach the provider. Keep ordinary loopback traffic
  native and block other external requests. The captured image is offline test
  data and must not be presented as live QR-provider or handset evidence.

- **FR-025**: With `preserve_existing_bookings: true`, use the existing caller's
  single consistent nonblank customer name from the scoped baseline for scenario
  rendering and dynamic context. Do not append a synthetic run suffix to that
  existing identity. Conflicting or missing names in a nonempty baseline block
  before provider resource creation or paid work. New callers retain the
  synthetic name and run suffix. Keep the complete original-record comparison;
  a profile or booking mutation must still fail and stop the campaign.

### Settled targeted recovery and conversation allowance (2026-10-18)

- **FR-031**: Deployed minimal scenarios need up to twelve caller turns to finish ordinary returning-caller clarification, price/duration quotation, explicit consent and native mutation. Preserve success conditions and native evidence; do not change isolated recipes or grant success for truncation. Retain the observed eight-turn C01 failure.
- **FR-032**: The targeted paid retests already authorized in FR-028 may use a fresh explicitly recorded recovery authorization with `continuation_of` and an explicit case subset. Admission must verify that each selected case (including dependencies) was failed or blocked in the immediate settled ancestor, reject replay of passed/incomplete-success cases, retain the complete ancestry and all charges, and forbid forked/reused recovery. A subset is never a complete tier. No ambiguous or unsettled attempt can be retested. Keep reserve and current-quota guards; no automatic retry.

- **FR-033**: An explicitly selected failed/blocked continuation may resume a booking already created by its immediate ancestor, using a recorded owned request ID and fresh exact native read-back. Exclude only that proven owned request from preservation baseline, preserve all other rows, and seed the existing lifecycle group with it. Satisfied passed dependencies may be omitted only with this verified ownership/state; never rerun them. Use a different target time when retrying an already-applied reschedule so the requested change and state assertion remain meaningful. All prior charges, failed evaluations, ancestry, reserve and no-fork gates still apply.

### Differential medium and full stages (2026-10-18)

The user requests medium coverage now, executing only C07–C16 because C01–C06
already have passing functional outcomes. A subsequent full stage executes only
C17–C50. Production messaging registration/setup and system Gmail reconnection
are explicitly deferred. The user confirms receipt of the earlier test WhatsApp
messages and emails. Do not reinterpret that confirmation as receipt of new
notifications, physical audio acceptance, or all 50 live cases passing.

- **FR-034**: Use the existing explicit case selector for differential stages:
  medium C07–C16 and full C17–C50, once each. Keep cumulative default selection
  and dependency expansion unchanged. Report these as subsets, retain earlier
  results with their original target and acceptance scope, and never submit a
  previously passed case just to construct starting state. These ranges have no
  catalog dependencies; each uses its declared isolated fixture. An opt-in
  `stage_authorization` may declare a unique authorization ID, tier, exact
  selected case IDs, and positive stage credit ceiling for isolated execution.
  Validate exact scope/repeat=1 and single use under the existing campaign lock;
  persist it in the manifest and invocation ledger before paid execution. Keep
  verified billing units, fresh quota, per-case estimates, 20 percent reserve,
  unknown-charge stops and attempted-run rejection. This is a distinct budget
  from the historical minimal recovery, whose spend stays visible in provenance.
  No full-stage paid submission is implied by preparing medium.
- **FR-035**: Medium fixtures and checks must prove their stated business
  outcomes before live use. Linked setup creates two linked service requests;
  assert the native setup result rather than expecting one row. C10 must preserve
  the unselected booking, C12 must persist the requested callback type/time,
  C14 must use two distinct qualified specialists, and C15 must move the linked
  visit to the exact requested new start while preserving its full duration and
  contiguity. Keep real native creation and database ownership guards. Regression
  tests must exercise actual owned database setup, not replace `arrange` with a
  no-op and infer live fixture correctness.
- **FR-036**: Reject a selected stage before paid submission when its declared
  setup requires unavailable specialist/calendar bindings or native evidence
  credentials. Check the whole selected range, not just its first case. Do not
  fabricate a second independent account, edit production technicians, weaken
  acceptance assertions, or repair the deferred production systems to pass
  readiness. Preserve all case definitions and disclose any required owner setup.

- **FR-037**: The user's explicit choice of `email_receipt_mode: "operator"`
  for an isolated stage permits new conversation/state/calendar/WhatsApp checks
  without a native receiving-inbox token. Keep email enabled with the designated
  working sender account; do not reconnect the deferred system sender. Preserve
  each case's required email assertion as false/unverified with its reason and
  collect any later operator receipt separately. Report functional outcomes
  separately; cases with pending inbox evidence and the campaign remain
  `incomplete`, never `passed` from manual mode alone. Other failures, provider
  rejections, unknown charges and native delivery checks remain failures/stops.
  Native inbox verification remains the default; invalid modes are rejected
  before provider resources or paid work. No prior receipt is evidence of a new
  test message, and no scenario requirement is removed.

The user approves an **11,250-credit ceiling for C07–C16 only**, with a
9,000-credit conservative admission estimate and 20 percent reserve. The user
designates `davidson.carcare.tech1@gmail.com` as the second technician account and
retains the configured Edvenswa admin recipient. Verify those scoped existing
account bindings before using them; all test phone notifications stay on the
designated handset. The full delta still needs its own reviewed stage budget.

### Deployed-only medium direction (2026-10-18)

- **FR-038**: The latest user direction requires C07–C16 to run against the
  deployed application only. Stop the local live servers and tunnel. Extend the
  existing deployed runner with an explicitly validated medium stage; retain
  isolated behavior and the deployed minimal path. The exact ten cases, once,
  share the existing unused 11,250-credit authorization; do not create a new
  authorization to bypass a prior claim. Deployed full remains unsupported.
  Claim the stage durably before any fixture mutation or provider clone, retain
  fresh quota/reserve/unknown-charge guards, and preserve native tool origins.
- **FR-039**: Create deployed fixtures only through normal native APIs and only
  as explicitly journaled test-owned catalog items, qualifications, calendar
  blocks and bookings. Use the two owner-designated Google accounts and handset.
  The owner-authorized Davidson connection may be bound as a new deployed
  technician; never rewrite an existing technician's identity or credential.
  Existing catalog entries, assignments, settings and customer bookings remain
  unchanged. Use distinct test catalog names so voice selection distinguishes
  test bookings from the existing customer's appointments. Preserve the verified
  existing customer identity. Readiness must validate every selected case before
  paying; failures or ambiguous fixture responses stop further paid work.
  Prepare catalog definitions offline; create those catalog/qualification
  fixtures only inside the single locked execution after the authorization
  claim, before provider clone creation. No separate pre-claimed setup is
  introduced; only the narrowly proven FR-042 continuation may complete an
  existing unpaid execution. Calendar blocks require a future AVAILABLE slot with
  no ACTIVE reservation, exact original-state journal and immediate state
  rechecks before mutation and restoration. Restore only a still-matching block
  without an intervening reservation; otherwise stop for reconciliation.
- **FR-040**: Deployed medium outcomes require case-specific native observations,
  including narrowly scoped read-only database reservation evidence. Preserve
  C07 refusal, C08 blocked-slot alternative, C09 correction, C10 selected/unselected
  identity, C11 corrected intake, C12 exact callback, C13 one qualified technician,
  C14 two qualified technicians, C15 complete linked reschedule and C16 complete
  linked cancellation. Bind service names, prices and durations to the actual
  test-owned deployed catalog; keep full duration and adjacency checks strict.
  Never run isolated global reset/SQL actions against the deployment. Cancel
  only journaled test requests through the native API, release only owned blocks,
  verify preservation, and stop before another paid case if cleanup is unresolved.
- **FR-041**: Operator email mode also applies to this explicit deployed medium
  stage. Native inbox verification stays false/unverified and acceptance stays
  incomplete. Other unavailable acceptance observations remain disclosed; paid
  provider evaluation and every implemented native business check must pass for
  functional success. Production messaging and the expired system Gmail
  connection remain deferred. Add scoped fixture/authorization regression tests
  and run the complete offline gate before the deployed paid stage.
  This initial deployed medium adapter requires explicit operator mode. Reject
  unsupported native inbox mode before claiming or mutating resources, rather
  than paying and inserting an unverified native assertion. Isolated native
  defaults and existing deployed minimal behavior remain unchanged.

FR-038–041 supersede the isolated-only target clauses of FR-034/037 for this
explicit deployed medium request. They do not authorize rewriting production
technicians or recipients merely to evade readiness checks.

### Recovery before the first paid case (2026-10-18)

- **FR-042**: An explicit same-run unpaid continuation may complete the already
  claimed C07–C16 execution within its original authorization and ceiling. It
  must not issue another authorization, claim twice, repeat a paid case, or
  create replacement catalog/provider resources. Under the campaign lock,
  require exactly one matching original claim, exact target/range/ceiling,
  no charge entry whatsoever, no provider test or invocation, no test-creation
  intent even if cleared, no pending/unknown write, no owned booking or calendar
  block, and no fixture case already arranged. Revalidate native baseline,
  designated identity/recipients, whole-stage readiness, exact owned catalog
  definitions/qualifications and existing clone fingerprint. Refresh quota and
  reserve admission. Preserve the original blocked manifest/report immutably
  and append the numbered continuation admission before any test submission.
  Any failed or ambiguous proof keeps the stage blocked. The claim remains
  consumed; this is continuation of its unused execution, not a new allowance.

The first deployed medium attempt stopped before any provider test was created:
the booking-list read took 55.8 seconds, exceeding the harness's 30-second read
timeout. No medium charge or invocation exists. Three catalog definitions and
the verified clone remain owned and retained. Preserve that failure as evidence.

- **FR-043**: Native concurrent catalog updates and FAQ embedding operations
  must not race a shared model download or publish stale/empty catalog knowledge.
  Serialize collection initialization and embedding-producing operations in the
  current single-process deployment, with the catalog snapshot taken inside
  that serialization boundary. Add replacement chunks before deleting the exact
  prior chunk IDs; publish the catalog text atomically after successful indexing.
  An embedding failure must preserve the previous file and searchable chunks.
  Keep provider credentials, unrelated documents and messaging settings intact.
- **FR-044**: Booking-list reads must not block the app's event loop during
  synchronous database or calendar work. Preserve the async route interface,
  filtering and response fields by offloading its blocking body. Retain past
  requests in the list, but do not query Google availability to assign a
  technician at a definitively past booking start; their candidate list is
  empty. Future and unparseable-time eligibility retains its existing behavior.
  Compare timestamps in the configured business timezone. Verify health
  responsiveness during a deliberately held future-candidate lookup and the
  portal's persisted data after that lookup finishes. Within each response,
  evaluate WhatsApp connectivity once per distinct technician phone and reuse
  that result for repeated rows; do not cache it across requests or change the
  underlying onboarding/settings semantics.
- **FR-045**: Knowledge-base indexing must bound each collection embedding add
  to one chunk so the current small-memory deployment never submits a complete
  catalog as one large inference batch. Keep the shared operation lock across
  the full logical replacement. If a later batch fails, remove only that
  attempt's exact new chunk IDs and preserve all previous and unrelated chunks.
  Include the current add's IDs even if it persisted before throwing; surface
  rollback failure as an explicit error rather than reporting a safe recovery.
  Delete prior chunks only after every replacement batch succeeds. Verify the
  chunk bound and partial-batch failure with captured and real Chroma contracts;
  actual 512 MiB runtime behavior remains a separate deployed gate.
- **FR-046**: Native UTF-8 KB uploads must offload synchronous indexing/file work
  from the event loop, retaining their current public async interface and success
  response. Reuse safe replacement semantics and atomically publish document
  bytes only after indexing succeeds. An embedding failure preserves the prior
  file and searchable chunks. Prove health responsiveness while upload indexing
  is held, and preserve upload/download browser behavior and unrelated files.
  Hold the same shared lock across replacement and final file publication so
  concurrent uploads cannot leave file and index from different versions.

Native evidence on 2026-10-18: two serial existing-document uploads returned
200, then the larger catalog upload returned 502. Render event
`evt-dbagtv942hec739a9j60` records an OOM kill with a 512 MiB limit at 18:25:01Z.
Do not repeat that native write against the unrepaired runtime or spend paid
simulation credits until the repair and prerequisite gates are safe.

- **FR-047**: Reuse one lazily initialized default ONNX embedding model per
  process across collection owners, add batches and queries. Preserve the
  existing Chroma `default` embedding identity/configuration, algorithm and
  dimensions so persisted collections remain compatible. Retain one-chunk adds,
  the shared operation lock and replacement rollback. Prove constructor reuse
  and reopening of an existing default collection without model downloads in
  offline tests; verify settled upload latency and memory on the deployment.

After approved deployment, the catalog upload completed with HTTP 200 in
126.3 seconds, but its client disconnected. Download hash reconciliation proved
the intended bytes were atomically published; do not retry that ambiguous write.
No new OOM event occurred and sampled memory peaked at 390,778,880 bytes. Installed
Chroma's default wrapper constructs a new ONNX embedder on every call, discarding
its instance-cached inference session between the bounded chunks.

- **FR-048**: Bound the shared encoder's ONNX session to one intra-operation
  thread and one inter-operation thread for the current constrained CPU runtime.
  Apply session options only to that encoder instance, preserving upstream
  model loading, provider selection, tokenizer, normalization and optimization.
  Never patch the global runtime or other sessions. Prove exact options and
  isolation without downloading a model, retain FR-047 compatibility/reuse, and
  validate actual native latency/memory before paid tests.

FR-047's native warm three-chunk upload still took 11.7 seconds; the large
upload again disconnected its client after exceeding one minute. Its write is
being reconciled without retry. No OOM event or paid test occurred. Installed
ONNX sessions default to intra/inter thread counts zero; official ONNX threading
documentation states the intra default creates threads for host physical cores.
Single-thread session configuration is a bounded repair hypothesis; improvement
must be demonstrated on the deployed CPU quota.

- **FR-049**: Native deployed medium simulator instructions must identify the
  exact owned service at the start of the scenario, including C08 whose
  generic recipe omits a service, and C11 intake corrections. Preserve each case's intended lifecycle,
  selected/unselected visit identity and quote requirements. Do not weaken
  service ownership checks or reinterpret an off-scenario booking as a pass.
- **FR-050**: An explicit same-run continuation may submit only the never-created,
  never-invoked remainder C09–C16 after the settled C07/C08 prefix. Keep the
  original single authorization, total11250ceiling, global unknown-charge stop
  and reserve; include1114settled credits in admission. Require exact original
  claim/selection/target/clone/catalog and immutable prior attempt artifacts,
  terminal verified provider results for the prefix, no test-creation intent or
  ledger/invocation history for any remaining case, and every prior business
  effect settled. C08 remains failed and paid prefix cases are ineligible for
  automatic replay. Archive reconciliation evidence and append a numbered
  remainder admission before any further test creation. Native baseline,
  identity/recipients, readiness and current quota must revalidate under lock.

C07 passed for331credits. C08 cost783credits and genuinely failed: its simulator
asked generic oil change instead of owned catalog47, bypassed the occupied-slot
fixture, created request51 as Repair, then rescheduled it. Guarded ownership
stopped C09–C16 before test creation. Native read-only proof identifies request51
as customer5/the designated phone and independently confirms provenance from the
provider's create result. Reconciliation may cancel only that causally proven
new request and restore exact journaled blocks, retaining all failure evidence.

- **FR-051**: Repair only the owned simulation clone's service-selection policy:
  preserve full canonical catalog names in every service lookup/availability/
  booking call, quote the returned price/duration before mutation and obtain
  consent. Respect the actual legacy tool schemas; use the booking tool's
  service_type for multiple canonical services. Keep the protected production
  agent unchanged. Prepare and verify a minimal prompt-only revision, preserving
  all other fields and tool URLs. Journal old/new fingerprints and prompt hashes
  before the owned-agent update; reconcile any ambiguous update by GET, without
  automatic write retry. A failed paid case remains failed; policy repair does
  not authorize its replay.
- **FR-052**: Extend safe recovery to the never-submitted contiguous C10–C16
  suffix after C07/C08/C09 terminal results (2019settled credits), preserving
  prior admissions and failures. Require all provider/test/invocation/credit
  receipts and immutable attempt/reconciliation history, no suffix creation
  history, exact original claim/cap, settled prior native effects, preserved
  baseline and the explicitly journaled owned prompt revision. No new claim,
  budget, replacement clone/catalog or paid prefix replay. Count aggregate
  spending and reserve; reject repeated suffix admission. Retain sanitized
  fixture failure diagnostics so ambiguous writes can be reconciled safely.

C09 cost905credits. Its native booking/correction succeeded for the exact owned
45minute service, but the voice agent looked up generic60minute facts and quoted
the correct price/duration only after booking; provider evaluation failed. The
cleanup response was ambiguous, but native request52 is cancelled with calendar
DELETED. Reconcile that completed outcome without another cancellation. C10–C16
were stopped before any test creation, keeping total settled spend2019.

- **FR-053**: Apply catalog price/duration-before-booking evaluation only to conversations that create a new appointment. Existing-booking disambiguation, rescheduling and cancellation must retain their native identity/consent/preservation assertions without an unrelated new-booking quote criterion. Preserve C10's original failed provider receipt and 481-credit charge; do not replay it.
- **FR-054**: Give native fixture mutations an explicit bounded read timeout appropriate to the deployed server, while retaining intent-first journaling, diagnostics and unknown-write stops. Never retry an ambiguous write. Record the effective timeout and elapsed duration without response bodies or credentials; keep provider requests separately bounded.
- **FR-055**: Extend the same original stage to the exact never-submitted suffix C11–C16 after C07–C10 settled 2500 credits. Verify every prior admission/archive, the owned prompt revision and native cleanup including C10 requests53/54. Preserve all paid failures, original claim/cap and strict never-submitted guards. Support monotonic suffix progress through immutable admission history rather than replacing resources or replaying paid cases. Fresh quota covers only future estimates; aggregate spending retains all prefix charges. No paid work precedes complete offline gates and native settlement.
