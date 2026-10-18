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
