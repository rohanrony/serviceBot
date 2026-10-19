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

## Deployed full preparation (FR-062/063)

Full case contract: exact case ID/setup, native mechanism, owned resources,
positive/negative durable assertions, independent observations, cleanup and
prerequisites. Implementation status is source-owned; it never establishes native
readiness. A full stage is the ordered C17–C50 delta once, under the existing ledger.

The full adapter reuses the `deployed_medium` operation journal and read-only
database binding. Its `full_adapter` marker prevents adopting a medium catalog.
Owned catalog, blocked intervals, temporary qualifications and inactive synthetic
staff have exact identity/read-back and restoration records. Inactive staff remain
inactive after cleanup; no real staff account is deactivated.

`full_google_busy`: deterministic event ID, designated account/calendar/technician,
expected event body, observed ETag, operation intents/results and terminal state.
The separately configured access-token environment variable is resolved in memory;
tokens and raw provider exceptions are never journaled. An uncertain write or
externally edited event blocks automatic retry/deletion. Native availability must
first include the target, then successfully exclude it after the event is visible.

Voice mutation admission resolves a strict positive target and every supplied
source alias against exact complete-phone-owned active appointments. Omitted IDs
are accepted only for one owned candidate. The normalized arguments are temporary;
there is no schema or authentication-model change.

## Grouped appointment components (FR-065/066)

`service_requests.service_components` is nullable JSONB. A supported appointment
snapshot is a nonempty ordered array of exact objects `{name, duration_minutes}`,
with unique nonblank canonical names, positive integer15-minute-grid durations,
sum equal to the stored appointment duration and comma-joined names equal to its
stored service label. Historical rows remain NULL; do not reconstruct composite
snapshots by splitting labels or current catalog durations. Callback snapshots
remain NULL. The additive array-type constraint and migration are repeatable;
rollback discards new metadata and requires reverting dependent app code first.

New appointment blocks group the selected plan by technician's first appearance,
retaining component order within each block. Each block owns one request,
reservation, complete segment grid and calendar projection, with consistent
booking_start_at/booking_time and booking_end_at. The visit retains its shared
linked identity. Old rows and historical paid artifacts are never merged in place.

Selective removal locks the exact owned row/reservation and validates every
segment's staff/time. It uses the snapshotted duration, retains start and staff,
compacts remaining components, shortens the same reservation's end, frees trailing
owned slots and journals the projection/notification/audit in one transaction.
Last-service removal cancels only the selected row using the same cancellation
owner/transaction; historical snapshot fields remain on its cancelled record.
The response explicitly reports remaining components and cancellation, while the
portal reload displays the native persisted status and queued projection/delivery.
Companion request/reservation identities and times stay unchanged.
