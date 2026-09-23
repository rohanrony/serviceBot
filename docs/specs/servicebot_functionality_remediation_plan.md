# ServiceBot functionality remediation plan and validation specification

**Status:** Implemented and locally validated on 2026-08-28 for the agreed POC scope. Portal authentication and live-provider acceptance remain release gates.
**Scope:** Calendar availability, appointment booking and rescheduling, SMS handoff, webhook trust and idempotency, notification delivery, and the test bootstrap.
**Non-goal:** This document does not authorize a production deployment, live-provider calls, or an authentication-provider selection.

## 0. Validation record

- Full local suite: 313 passed against `voice_service_test`, with provider integrations mocked.
- Live-safe UI check: the local Playwright service-request save flow passed.
- Static validation: changed Python modules parse successfully and `git diff --check` is clean.
- No real Google, Twilio, Gmail, or ElevenLabs request was sent.

## 1. Root-cause record

The current failures are connected by split ownership of business rules. FastAPI route handlers, `db/queries.py`, and provider-specific services each make booking or delivery decisions independently. A repair must move each decision to one service boundary; changing only a route or a database constraint would preserve the inconsistency.

| Observed behavior | Confirmed cause | Required invariant |
| --- | --- | --- |
| Staff calendar actions return 404 | The portal UI and API specification name calendar endpoints that are not registered by `api/portal.py`. | Every visible calendar action has a versioned, tested route and a stable response schema. |
| After-hours handoff can fail while saving | The handoff service writes `OUT_OF_BUSINESS_HOURS`, but `sms_conversations.state` rejects that value. | Every state emitted by a service is declared once and accepted by the database and UI. |
| Voice bookings can succeed when unavailable | The voice route calls `create_service_request()` directly; validation and agent selection live in a separate `book_appointment()` path. Calendar failures are swallowed after the database commit. | All appointment entry points use one booking service and cannot return “booked” without a durable reservation state. |
| Failed reschedules retain unrelated portal edits | The edit route commits request and vehicle updates before consent and availability checks. | A rejected edit changes no request, vehicle, audit, reservation, or notification state. |
| Forged or retried webhooks can mutate state | Validation is optional/fail-open, and CRM notes use a unique identifier as an exception rather than an idempotency mechanism. | Unauthenticated callbacks are rejected; a valid duplicate is acknowledged once with no duplicate side effects. |
| Channel settings do not control delivery | Rules store `channel`, while the router dispatches through `send_whatsapp()` in every path. Outbox success is based on an absence of exceptions. | The selected rule determines transport; `DELIVERED` means the transport reported success. |
| Test runs are environment-dependent | Import-time logging opens a configured local file, and test discovery/configuration is not isolated. | Tests run with a temporary log path, a test-only database, and no live provider access. |

## 2. Architecture and risk gates

Apply the backend-guideline layering to this FastAPI codebase as:

```text
FastAPI route + Pydantic input -> application service -> repository/transaction -> PostgreSQL
                                               -> outbox -> provider adapter
```

Routes parse input, enforce authorization dependencies, and translate typed domain errors to HTTP responses. They must not choose agents, mutate several aggregates, or call Twilio/Google directly. Use a typed settings object and structured application logging; do not add a new observability vendor as part of this work.

| Workstream | Fit | Complexity | Data risk | Operational risk | Testability | BFRI | Treatment |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Calendar and booking convergence | 2 | 5 | 5 | 5 | 4 | -9 | Redesign service boundary before implementation. |
| Handoff state and webhook trust | 3 | 3 | 4 | 5 | 4 | -5 | Isolate shared validation/state code before changing routes. |
| Notification routing and outbox | 2 | 4 | 4 | 5 | 4 | -7 | Define explicit delivery results and retry semantics first. |
| Test bootstrap | 4 | 2 | 1 | 2 | 5 | 4 | Implement first, with focused tests and monitoring. |

### Decision gates

1. **Booking source of truth:** the recommended contract is PostgreSQL reservations as the atomic record of an accepted booking, with Google Calendar an asynchronously reconciled provider integration. `mock_calendar_slots` may remain a portal availability projection, but must not be a second, competing reservation mechanism. If Google must be authoritative instead, the provider must offer a hold/create operation that is executed before confirmation.
2. **Portal identity provider:** select the existing deployment identity mechanism before adding access control. The application must expose a `require_portal_admin` dependency; it may delegate to a reverse-proxy identity header only after that header is cryptographically trusted and documented. A temporary shared bearer secret is acceptable only for development/test environments.
3. **ElevenLabs verification:** confirm the provider’s current signed-webhook contract before enabling production verification. Do not invent a header or accept unsigned production callbacks.

## 3. Implementation order

### Phase 0 — establish a safe baseline

1. Record the deployed PostgreSQL schema and migration history; do not rely on `CREATE TABLE IF NOT EXISTS` to alter existing constraints.
2. Add an application settings fixture that uses a temporary `LOG_FILE`, a test-only database URL, and fake provider adapters. The fixture must refuse a database URL that is not explicitly marked as test-only.
3. Make logging initialization idempotent and tolerant of an unavailable file handler: retain stdout logging and emit one structured warning instead of failing import.
4. Configure pytest discovery to `tests/` and prevent `scratch/` from being collected.

**Exit criterion:** `./run_tests.sh --all` reaches collection without writing to the checkout or contacting Twilio, Google, or ElevenLabs.

### Phase 1 — restore and define the calendar API contract

Implement a `CalendarAvailabilityService` and repository for the endpoints already documented in `docs/specs/api_spec.md`:

- `GET /api/v1/portal/agents/{agent_id}/calendar`
- `POST /api/v1/portal/agents/{agent_id}/calendar`
- `PATCH /api/v1/portal/calendar/{slot_id}`
- `DELETE /api/v1/portal/calendar/{slot_id}`
- `POST /api/v1/portal/agents/{agent_id}/calendar/populate`
- `POST /api/v1/portal/calendar/sync-all`

Contract requirements:

- Accept and return timezone-aware ISO 8601 timestamps; the API converts business-hour rules in `America/New_York` before persistence.
- Reject an unknown agent, an invalid business-hour slot, duplicate `(agent_id, slot_datetime)`, and an attempt to manually reopen a slot with an active reservation. Return `404`, `422`, or `409` respectively.
- Make populate/sync idempotent for a given agent and range. It may update the projection, but may not overwrite a locally reserved slot.
- Return per-agent success/failure information from sync; a failed provider lookup is not represented as an available slot.
- Update the portal client to show server errors and refresh only after a successful mutation.

### Phase 2 — converge appointment creation and rescheduling

Create a framework-independent `BookingService` with `create_appointment`, `reschedule_appointment`, and `cancel_or_release_reservation` operations. All three entry points—voice tools, portal creation, and portal edit—must call it.

1. Keep `create_service_request()` limited to intake/callback records. An appointment request is delegated to `BookingService`; it may not select the first staff agent on its own.
2. Validate business hours, duration, staff eligibility, and overlap before writing. Claim the local reservation in one transaction (`SELECT ... FOR UPDATE` or a unique exclusion/overlap constraint) so concurrent callers cannot double-book.
3. Persist a calendar-integration state such as `PENDING`, `CREATED`, or `FAILED` with an idempotency key. Commit the reservation and an outbox event together; provider work happens after commit.
4. Do not announce a booking as confirmed while its integration state is `FAILED`. The product response may be “received and pending confirmation” only if that state is explicit in the API and UI.
5. Replace the current portal edit sequence with one `update_service_request` application service. It validates consent and the new reservation before it commits request fields, vehicle fields, audit rows, and outbox events.

### Phase 3 — make SMS states and webhooks trustworthy

1. Introduce one Python enum/value module for SMS conversation states. Add `OUT_OF_BUSINESS_HOURS` through an explicit PostgreSQL migration, use it in the UI/filter contract, and define its allowed next transitions. The preferred transition is: outside-hours handoff -> `OUT_OF_BUSINESS_HOURS`; a new eligible handoff during business hours -> `HANDOFF_REQUIRED`.
2. Add a reusable Twilio request-verification dependency used by inbound SMS, delivery status, and voice inbound callbacks. In production, missing signature, invalid signature, verifier errors, or a missing configured secret return `403` without processing the payload. Testing bypasses verification only through an explicit dependency override.
3. Add a provider-specific verifier for post-call webhooks after the Phase 0 decision gate. Redact request headers and transcript/body logging; log an event ID, provider, verification result, and outcome instead.
4. Create a `webhook_events` ledger keyed by provider and provider event ID (or use a single carefully documented unique event key). Claim the event before side effects. A duplicate returns `200` with `duplicate: true`; it neither inserts another CRM note nor sends another callback notification.

### Phase 4 — make notification delivery rule-driven and retryable

1. Replace the implicit WhatsApp-only dispatch with a `NotificationDispatcher` that receives a `Notification` object and selects `SMS`, `WHATSAPP`, or `EMAIL` from the enabled matrix rule.
2. Provider adapters return a typed `DispatchResult(success, provider_id, retryable, error_code, error_message)`. `_dispatch_outbox_event()` returns an aggregate result; the worker marks an item `DELIVERED` only when all required dispatches succeed. Retryable failures remain pending with bounded attempts and a next retry time.
3. Store the rendered body (or immutable template plus context) before a message is queued. The quiet-hours worker must send that stored content, not a generic appointment placeholder.
4. Preserve partial-delivery detail per recipient/channel. A customer WhatsApp success must not hide an agent email failure.

## 4. Required test specification

Write the tests below first. On the current baseline, the tests covering the existing defects should fail for the documented reason; remove no assertion merely to accommodate existing behavior. Use a PostgreSQL test database, TestClient with dependency overrides, and fake provider adapters—never real credentials or network calls.

| Test module | Required cases | Acceptance condition |
| --- | --- | --- |
| `tests/test_runtime_bootstrap.py` | Import app with an unwritable `LOG_FILE`; collect tests; assert `scratch/` is not collected. | Import succeeds, stdout logging remains active, and collection is limited to `tests/`. |
| `tests/test_calendar_portal_contract.py` | List/create/update/delete slots; unknown agent; duplicate slot; invalid local business-hour time; idempotent populate and sync; provider failure. | Routes match the documented paths/statuses and failed sync never creates a free slot. |
| `tests/test_booking_service.py` | Voice, portal-create, and portal-edit call the same service; invalid hours; busy agent; two concurrent claims; provider event failure; callback remains separate. | Exactly one reservation wins; invalid/busy requests produce no confirmed booking or success message. |
| `tests/test_service_request_edit_atomicity.py` | Reschedule without consent; unavailable new slot; successful edit/reschedule. | First two leave request, vehicle, audit, reservation, and outbox rows unchanged; the success case changes all expected rows once. |
| `tests/test_handoff_state_transitions.py` | Existing conversation outside hours; opt-out; debounce; next business-hours request; state filtering. | State persists without a check-constraint error and only documented transitions occur. |
| `tests/test_webhook_trust_and_idempotency.py` | Missing/invalid/valid Twilio signatures on all Twilio endpoints; valid post-call payload twice; malformed payload; provider verification failure. | Untrusted callbacks cause no database mutation; a duplicate valid callback is acknowledged once and has one CRM note/notification set. |
| `tests/test_notification_dispatcher.py` | One rule each for SMS, WhatsApp, Email, disabled rule, retryable failure, non-retryable failure, and quiet-hours release. | Selected transport matches rule; delivered status reflects provider success; queued message retains exact rendered body. |
| `tests/test_portal_frontend_contract.py` | Calendar action URLs, non-200 error UI, and the SMS-config navigation/subtab contract. | Every fetched route exists in the API contract and DOM assertions reflect intentional navigation semantics. |

For database tests, assert both the HTTP/service result and persisted rows. For provider tests, assert the fake adapter call count and idempotency key. For concurrency, run two service calls against the same test slot and assert one success plus one typed conflict.

## 5. Release gates and observability

1. Run unit tests for services, route integration tests, and repository/transaction tests against a clean test database.
2. Run the full suite through `./run_tests.sh --all` with temporary log and cache locations.
3. Verify migration forward and rollback on a disposable PostgreSQL database. Backup and inspect affected rows before production migration.
4. Deploy behind the selected portal-auth mechanism. Confirm with a read-only smoke test that unauthenticated portal mutations and unsigned webhooks return `401`/`403` and do not create records.
5. Monitor structured counters for: booking conflicts, calendar integration failures, webhook verification failures, duplicate webhook acknowledgements, outbox retries, and deliveries by channel/result. Alert on sustained calendar failure or retry exhaustion.

## 6. Definition of done

The work is complete only when all contract tests pass, the full suite runs from a clean checkout, every booking path shares `BookingService`, calendar API/UI calls are aligned, state values are migration-backed, provider callbacks are verified and idempotent, and an outbox item is marked delivered only after a successful provider result.
