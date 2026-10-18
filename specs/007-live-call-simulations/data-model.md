# Data model

Scenario: id, minimum tier, dependencies, fixture recipe, caller behavior,
expected/forbidden tools, required evidence, setup/cleanup rules and requirement refs.
Campaign: UUID, selected cases, source/config fingerprints, start/end, results,
provider invocation/test IDs and owned runtime/database resources.
Budget: verified monthly credits, reset timestamp, tier fraction, 20% reserve,
per-case upper estimate, settled actual spend, unsettled invocation IDs.
Check: name, evidence kind, expected comparison, observed value and status.
Resource manifest: database name, runtime root, created provider test IDs, campaign agent ID, pending creation flags and calendar
IDs with owner account and native-operation observation; cleanup is retryable and never infers ownership from a phone number or title.
Evidence: redacted JSON/Markdown retained 30 days; failed/blocked are never passed.

Persistent allocation registry: next reservation ID block, protected by a root lock.
Native effect log: operation ID, started/finished stage, owner, event/calendar ID,
case, request fingerprint and ambiguous/rejected status; never provider tokens.


## FR-019/020 follow-up
Calibration config: credit_ceiling, case_upper_estimate (positive finite numbers), source_run_id (nonempty provenance). Baseline manifest: original caller request list; calibration manifest: explicit scope, ceiling, estimate and sample provenance. No application database schema change.
