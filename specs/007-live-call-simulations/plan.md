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

Derive the persona name from the read-only scoped baseline before creating any
owned provider resource. For an opted-in nonempty baseline require exactly one
consistent nonblank customer name; ambiguous or absent names fail closed. Supply
that name to both rendered scenarios and dynamic variables without a run suffix.
Keep all original fields in the baseline equality check. Add a captured intake
provider that mirrors native profile updates and proves original rows survive,
plus missing/conflicting-name admission tests and explicit mutation detection.
This is a local harness repair. No saved-agent patch, deployment, profile
restoration, cleanup or automatic paid replay is included.
