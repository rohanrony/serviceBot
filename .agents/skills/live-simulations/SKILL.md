---
name: live-simulations
description: Preview or run VoiceService live conversation campaigns with a minimal, medium or full tier. Use when asked to run the live simulation workflow.
---

# Live simulation workflow

Accept a tier parameter: `$live-simulations minimal`, `medium`, or `full`.
Default to minimal if omitted. Use `--config PATH` when supplied; otherwise use
`scratch/live-simulations.local.json`. Read `docs/LIVE_SIMULATIONS.md` for missing
account configuration or readiness details. Never read or source workspace `.env`.

1. Run `./run_live_simulations.sh --tier TIER [--config PATH]` to preview offline.
   Report selected count and budget readiness. An invocation requesting only a
   preview does not authorize live execution. Do not invent quota or estimates.
2. When live execution is requested, use the same entrypoint with `--live` and
   the user's prepared `--run-id` if available. In an interactive user terminal,
   a new run guides account setup before launching the selected campaign.
   Agent tool sessions usually lack interactive input: use existing prepare/serve
   commands for setup, retain the printed run ID, stop serve before execution,
   then invoke the workflow with that prepared `--run-id`. Do not auto-submit a
   setup prompt or claim accounts are ready without evidence.
3. Forward explicit `--cases`/`--repeat` parameters. The existing runner remains
   the authority for budgets, dependencies, evidence and resource ownership.
4. Report campaign status, report path and unfinished acceptance/cleanup. Do not
   rerun ambiguous paid submissions; use the documented reconciliation operation.
   Retain failure evidence. Cleanup is a separate explicit operation.

Minimal has 6 cases and a 1% monthly credit ceiling; medium 16 and 2%; full 50 and
5%. Full also requires handset attestation. Real-phone/audio acceptance remains
separate. Missing advanced fixture bindings block execution; never silently skip
cases or treat captured offline providers as proof of live delivery.

## Combined verification

When asked to include the other app tests, use `./run_tests.sh --verify` for the
full offline unit/integration and E2E layers. When live execution is also requested,
use `./run_tests.sh --verify --live-tier TIER`, with optional `--live-config PATH`
and `--live-run-id UUID`. These options belong to the shell runner, not pytest.
Both offline suites run; either failing skips paid work. A noninteractive agent
session needs a prepared live run ID. Preserve the offline-success gate.

## Existing deployed application

When the user chooses the deployed app, use `--target deployed` and
`scratch/live-simulations.deployed.json` (or the supplied config). Start with
`./run_live_simulations.sh --target deployed --tier TIER --check` for read-only
readiness, then `--live` only when requested. No tunnel or local Runtime is used.
Do not edit deployed staff or recipients to bypass readiness. Retain the same
budget and ledger. Fixture-dependent tier selections block before paid work.
This mode is conversation/API smoke: report functional_status separately and
missing native acceptance evidence as incomplete, even when the conversation and
API lifecycle succeed. Use report/reconcile/cleanup with the deployed config;
cleanup removes only owned ElevenLabs resources and retains deployment data.

An explicitly user-authorized `campaign_authorization` may set a separate ceiling
for one complete deployed minimal C01–C06 pass. Use its existing authorization ID;
never generate another ID to evade prior usage. The runner rejects subsets,
repetition, simultaneous calibration and paid reuse. Verified quota, reserve,
recipient/readiness and unknown-charge gates still apply. Do not infer approval
for this exception from a normal tier request.
