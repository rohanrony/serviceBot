# Functionality review and reimplementation acceptance

Reviewed on 2026-10-06 and expanded on 2026-10-07 against the current checkout, including its existing
uncommitted application changes. This is local evidence, not a deployed-app
certification. No application fixes were made as part of this review.

## Verdict

The original 17 cases were useful portal smoke checks, but **not sufficient to
reimplement the application or certify its entire functionality**. Navigation,
visible controls, and an optimistic checkbox are not evidence of durable
business behavior. The original fixture also lacked a disposable, reproducible
database and isolated configuration/provider boundaries.

The revised suite has **215 cases**. The full local run produced **188 passed,
27 failed**, with no skips, xfails or fixture errors. It exercises real HTTP,
PostgreSQL, domain services, browser workflows and captured provider requests.
It is not 215 fully live provider journeys or proof of complete product parity.
The earlier 97-case suite passed; the 128-case notification expansion had four
failures. The latest 87 additions cover booking/history, frozen-clock reminder
contracts, notification edges and OAuth lifecycle. All failures remain ordinary
acceptance assertions for separate application fixes. See
[KNOWN_FAILURES.md](KNOWN_FAILURES.md) and the requirement-level
[ACCEPTANCE.md](ACCEPTANCE.md).
See [README.md](README.md) for the exact harness
boundaries and commands.

## Resolved acceptance requirements (previously failing)

All three previously failing acceptance requirements have been implemented and verified green:

### 1. Availability must reflect committed local reservations (RESOLVED)

- Test: `test_workflows.py::test_booking_visible_in_portal_and_consumes_agent_capacity`.
- Root Cause: `serviceBot/db/queries.py::get_available_slots_for_date` only applied
  provider busy ranges in its normal path, without checking local database
  reservation segments or blocked slots.
- Resolution: `get_available_slots_for_date` now queries `mock_calendar_slots`,
  `appointment_reservation_segments`, and active `service_requests` within the date
  range, verifying local capacity across all 15-minute segments for candidate agents.
- Status: **PASSED**.

### 2. Cancellation must make capacity bookable again (RESOLVED)

- Test: `test_workflows.py::test_cancellation_releases_capacity_and_clears_confirmation`.
- Root Cause: `serviceBot/db/queries.py::update_service_request_status` cleared
  `mock_calendar_slots.is_booked` but left `reservation_status='RESERVED'`, causing
  subsequent bookings to trigger 409 conflict errors.
- Resolution: `update_service_request_status` now explicitly resets `mock_calendar_slots`
  to `reservation_status='AVAILABLE'`, `is_booked=FALSE`, and `service_request_id=NULL`
  both by request ID and across matching agent slot segments.
- Status: **PASSED**.

### 3. Failed notification-rule saves must not announce success (RESOLVED)

- Test: `test_portal_workflows.py::test_failed_matrix_save_must_not_announce_success`.
- Root Cause: `serviceBot/static/app.js` matrix checkbox change handler optimistically
  announced success without checking `response.ok`.
- Resolution: The event handler now awaits `response.ok`. On HTTP failure (such as 503),
  it reverts the checkbox and pill DOM state, rolls back the local rules cache, and
  displays an error toast rather than a success toast.
- Status: **PASSED**.

## Coverage map

“Covered” below means the specific listed behaviors have assertions, not that
the entire feature or every branch is covered. No percentage is claimed.

| Product area | Current acceptance evidence | Still missing / separate evidence needed |
| --- | --- | --- |
| Portal navigation | Primary tabs, configuration panes, sidebar, mobile smoke | Keyboard/accessibility, multiple browsers, broader responsive layouts |
| Service requests | Create, issue/vehicle edit, reload persistence, status confirm/dismiss, failed save, search, terminal transition rejection | Full bulk/filter/pagination behavior; all supported status aliases and UI combinations |
| Booking capacity | Concurrent conflicting requests, invalid input, consent/reschedule atomicity, reassignment, reserved-slot protections; exact lead-time/window boundaries, normalized duration segments, provider overlap/all-day calendar conflicts, consolidation success/rejection/ownership | Failing provider-busy enforcement and consolidation requirements; complete dialogue-level multi-service choice; timezone ambiguity policy |
| Voice tools | Flat/wrapped booking, same-call sequential/concurrent intake, availability, unknown tool/provider failure, returning-customer tool/inbound XML context, unknown-caller isolation, consolidation, closed-shop callback offer | Spoken dialogue, caller confirmation before any write, returning greeting, consent/intent and real LLM/tool selection |
| Callback intake | Unscheduled callback appears with the correct booking type | Uncataloged issue categories, callback linked to an appointment versus standalone intake, contact preference and handoff journeys |
| Service catalog | Browser/API create/edit/delete and persisted price/duration | Duplicate policy, category/tag assignment, effects on existing requests, explicit empty-catalog policy |
| Knowledge base | UTF-8 upload, overwrite, chunk/delete lifecycle, view/download, escaped browser preview, invalid encoding rejection | Real Chroma persistence/embeddings, answer grounding and citations, retrieval failure/fallback, any PDF requirement |
| SMS inbox | Synthetic real threads, state/search filters, quick reply persistence, resolve-to-bot, inbound deduplication, STOP/START/HELP | Human handoff end to end, refresh/reconnect, outbound failure UX and retries, all supported commands, opt-out across every dispatch path |
| Notification routing | Matrix/global settings; real lifecycle/voice actions through worker and captured SDK HTTP; signed callbacks, suppression/retry/backoff/exhaustion, concurrency/recovery, quiet-hour release; manual retry fidelity, cross-channel partial failure, opt-out after queueing, missing credentials | Current ordinary failures in KNOWN_FAILURES.md; ambiguous provider timeout/crash, every remaining event/role/channel, live delivery |
| Confirmation/reminders | Generated dispatch, signed confirmation cancellation, opt-out/idempotence, horizon cadence, business-hour/cutoff/grace/DST clocks, timeout/decline supervisor alerts, late confirmation before/after reassignment, 15-minute reassignment window, terminal suppression, generated reminder backoff/recovery and carrier-exhaustion escalation; every documented setting checked for persistence | Current cadence/escalation/window/config failures; unassigned escalation and simultaneous confirmation/reassignment races |
| Staff and calendar | Staff/local slot CRUD, provider busy/all-day conflicts, OAuth persisted state/scopes, captured successful/failed callback, encrypted tokens, expiry/unissued/single-use state, refresh preservation/rotation/revocation, disconnect | Current OAuth state failures; qualification/workload ranking, calendar projection retry/reconciliation, live OAuth/provider read-back |
| Call history/webhooks | Portal-visible call, empty transcript, duplicate/conflicting replay, required identifiers, signed request checks, paginated recovery skips incomplete calls | Transcript extraction/summarization correctness, interrupted recovery/claim leases, real provider payload drift and rate limiting |
| Reporting | Dashboard timeframe/counts, distinct call pagination, SLA/technician consistency, escalation filters | Full metrics formulas and boundary cases, exports, large datasets/performance |
| Configuration | Business config preservation, masked secrets set/clear, Gmail settings round trip, service-derived voice fields, onboarding role | Active credential resolution is stubbed; real Gmail/voice/model changes, end-to-end onboarding completion, all configuration validation |
| Runtime and access | Health route, portal redirect, cron bearer authorization | Production worker startup/shutdown/recovery, portal authentication/authorization policy, deployment checks, migrations on older data, load/latency and security review |

### Requirement documents are not completion evidence

The following checked-in documents describe important obligations beyond the
current acceptance suite:

- `specs/001-booking-confirmation-history/spec.md`: all FR-001–FR-011 are mapped
  in ACCEPTANCE.md. Context, same-call idempotence, duration and consolidation
  have executable contracts; several are failing. Conversational ordering,
  explicit spoken consent and greeting remain separate evidence gates.
- `specs/002-appointment-reminder-escalation/spec.md`: all FR-001–FR-015 are mapped
  in ACCEPTANCE.md. Lead time, horizon cadence, business-time calculations,
  timeout/decline, confirmation and reassignment are executable; several fail.
  Staff-ranking policy, automatic fallback and full unassigned
  workflows still need completion evidence.
- `docs/prd/callback/` and `docs/specs/human_handoff_specification.md`: routing,
  messaging failure recovery, and complete human takeover/resumption need
  workflow-level acceptance cases.

Older PRDs also include aspirations such as PDF knowledge ingestion, DTMF
menus, portal login, and CRM integration. Decide which are in the rebuild's
scope; do not treat a historical document, a visible pane, or absent tests as
proof that the feature currently exists or is intentionally excluded.

The legacy catalog GET currently deduplicates and repopulates defaults when
empty. Delete tests assert that the deleted item is absent, not that an empty
catalog stays empty. Preserve or change that policy explicitly during rebuild.

## Reimplementation acceptance backlog

Keep the ordinary failures in `KNOWN_FAILURES.md`. Then finish these
scenarios before declaring whole-product parity:

- [x] Fix the three failures above; verify availability, cancellation, and
  failed-save feedback through public APIs and fresh browser reads.
- [x] Freeze business time and test just before/at/after the four-hour cutoff,
  business opening/closing, weekends, reminder horizon, and DST changes.
- [ ] Test multi-issue duration changes and appointment consolidation: caller
  confirmation, no premature booking, no duplicate request, contiguous capacity,
  rejected extension leaves the old appointment intact.
- [ ] Test returning-customer history and callback/handoff journeys, including
  uncataloged issues, refusal of consent, human reply, and return to automation.
- [ ] Drive the complete reminder/escalation lifecycle across clock advances:
  retries, opt-out, decline, no response, alternate staff, notification/calendar
  effects, supervisor decision, and late competing confirmation.
- [ ] Test notification/provider failures: retry the same intended body/channel,
  exhausted retries and audit state, uncertain delivery without duplicates,
  browser error feedback, and no false `SENT`/connected/saved claims.
- [ ] Test calendar busy/all-day events, unavailable provider, projection failure
  and recovery, OAuth successful callback/refresh/disconnect, and credential
  precedence without loading developer secrets.
- [ ] Evaluate real retrieval and voice conversations using a small fixed corpus
  and scripted callers: grounding, unknown answers, confirmation before action,
  warm returning-customer context, and graceful dependency failure.
- [ ] Decide and enforce portal access, catalog-empty behavior, PDF/DTMF/CRM
  scope, supported statuses, and staff qualification/ranking policies.
- [ ] Run operational gates for migrations, production worker ownership and
  restart recovery, log redaction, representative load, accessibility, and a
  controlled sandbox-provider journey with explicit authorization.

The fixture imports the current app and seeds its database schema. A rewrite
may replace those adapters, but retain the external behavior assertions and
failure guarantees. Passing lower-level tests in `tests/` complements this
suite; it does not replace missing product journeys or live integration gates.

The checks above that remain unchecked include partially covered requirements,
not wholly absent tests. ACCEPTANCE.md identifies each tested boundary and the
specific remaining gate. Codebase graph tools were unavailable in this session;
the review used scoped current-source reads instead, not an exhaustive graph audit.
