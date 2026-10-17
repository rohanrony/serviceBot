# Comprehensive end-to-end testing plan

This plan covers the product's main workflows and recent features. It identifies
executable checks, manual checks, and what the evidence proves. A test count does
not establish complete product coverage. Application fixes are a separate change;
unmet requirements must remain normal failures. Run instructions are in
[Testing VoiceService](../docs/TESTING.md).

## Run order and completion criteria

1. Run `./run_tests.sh --all` for the unit/integration baseline.
2. Run `./run_tests.sh --features` while fixing recent-feature regressions.
3. Run `./run_tests.sh --e2e` for all HTTP/worker and browser acceptance contracts.
4. Run `./run_tests.sh --browser --e2e-headed` to watch real browser journeys.
   This is a subset of step 3, not an additional test count.
5. Rerun affected cases after each fix, then the relevant full suite. Acceptance
   requires no failures or collection/setup errors and no skipped/expected-failure
   requirements. Keep JUnit reports and failed-browser traces as evidence.
6. For a release, also execute the separately scoped manual gates below. Record
   commit, environment, browser/version, result and evidence. Mark unexecuted
   gates **not run**, not passed.

`./run_tests.sh --verify` runs steps 1 and 3 in separate processes, continues to
E2E if unit tests fail, and returns failure if either suite fails.

## Automated workflow matrix

Paths are under `e2e/` unless prefixed with `tests/`. Browser means real
Playwright actions; HTTP/worker means real routes/services/PostgreSQL with
external provider boundaries. Each row describes specific asserted behaviors,
not every possible branch of that feature.

| Area / requirement | Journey and observable outcome | Executable coverage |
| --- | --- | --- |
| Navigation/layout | Primary/config tabs, sidebar, mobile navigation and the correct visible pane | `test_portal_nav.py`, `test_config.py`, `test_portal_workflows.py` (browser) |
| Request intake | Enter customer/vehicle/service/date, confirm, fresh read and reload; dismissal preserves previous state | `test_portal_workflows.py` (browser), `test_workflows.py` |
| Edit/status/search | Persist issue/vehicle/time; filter; confirm/dismiss status change; failed saves show errors and preserve backend | `test_appointments.py`, `test_portal_workflows.py` (browser), `test_workflows.py` |
| Reservation rules | Configured lead-time boundaries, opening/closing/weekends, normalized duration and all contiguous segments, busy/all-day provider calendars | `test_booking_contracts.py`, `test_workflows.py` |
| Atomicity/races | Competing customers have one winner; rejected consolidation or second visit segment leaves no partial reservation/queue work | `test_booking_contracts.py`, `test_workflows.py`, `test_multiservice_contracts.py` |
| Consent/history (001) | Consent before reschedule; same-call updates/concurrency; caller vehicle/issue/duration and customer ownership | `test_booking_contracts.py`, `test_voice_and_reporting.py`, `test_workflows.py` |
| Catalog CRUD | Add/edit/delete, persisted price/duration, failed saves and knowledge sync boundary | `test_services.py`, `test_portal_workflows.py` (browser) |
| Technician tags (006) | Add one/multiple tags, edit/clear, row-specific badges, reload, failed edit, inactive staff absent | `test_portal_catalog_agent_tagging.py` (browser), `tests/test_catalog_agent_tagging.py` |
| Multi-service assignment (006) | Prefer one qualified technician, otherwise contiguous split; three-service grouping; linked IDs and every capacity segment persist | `test_multiservice_contracts.py`, `tests/test_multi_service_scheduling.py` |
| Multi-service availability | A free first specialist cannot make an unavailable whole visit bookable | `test_multiservice_contracts.py::test_multiservice_availability_requires_both_specialists` |
| Linked lifecycle | Customer cancellation/reschedule affects all linked services; revision releases only removed capacity and retains companion start | `test_multiservice_contracts.py`; revision currently uses the real domain entry point, not a public UI |
| Multi-service side effects | Voice booking appears in browser after reload; captured customer notification lists both services/technicians | `test_multiservice_contracts.py` (HTTP plus browser); calendar helper tests in `tests/test_multi_service_scheduling.py` |
| Dual callbacks | Shared visit, distinct callback windows at least 30 minutes apart, voice dispatcher retains callback type | `test_multiservice_contracts.py`; domain and public entry points tested separately |
| Staff/deactivation | Browser create/edit/dismiss-delete/deactivate; historical rows/reservations preserved, future work escalated, inactive choices excluded | `test_portal_recent_features.py` (browser), `test_staff_lifecycle_contracts.py`, `test_workflows.py` |
| Reassignment | Assignment/reservation/segments agree; no unqualified/inactive substitute; no replacement escalates | `test_staff_lifecycle_contracts.py`, `test_reminder_contracts.py`, `test_workflows.py` |
| Multiple SMS assignments (004) | Bare confirmation presents a menu; index selects one; CONFIRM ALL updates all and stops pending reminders | `test_staff_lifecycle_contracts.py`; decline/invalid selectors in `tests/test_agent_multi_appointment_confirmation.py` |
| Timezone (005) | Save Chicago/Phoenix/Los Angeles in browser; reload and runtime agree; DST/UTC conversions | `test_portal_recent_features.py` (browser), `test_reminder_contracts.py`, `tests/test_configurable_business_timezone.py` |
| Hours/buffers | Browser changes closing boundary; real booking enforces it; dynamic prompt and callback buffers | `test_portal_recent_features.py`, `test_booking_contracts.py`, `tests/test_callback_lead_time.py`, `tests/test_prompt_business_hours_sync.py` |
| Recording disclosure | Default greeting mentions recording; edited greeting persists/reloads and reaches captured ElevenLabs config; failed save preserves stored greeting | `test_portal_recent_features.py` (browser plus captured HTTP) |
| Notification matrix | Rules persist; failed saves roll back visibly; both enabled channels select one preferred channel | `test_config.py`, `test_portal_workflows.py` (browser), `test_notification_edges.py` |
| Booking to delivery (003) | Browser creates booking, commit precedes dispatch, captured SDK body has vehicle/issue, signed callback updates visible log | `test_portal_recent_features.py` (browser), `test_notification_workflows.py`, `tests/test_notification_vehicle_issue_details.py` |
| Notification lifecycle | Correct recipients for booking/reschedule/reassign/cancel/progress/completion; retry only failed recipients, preserve content and stop at exhaustion | `test_notification_workflows.py`, `test_notification_edges.py` |
| Reminder/escalation (002) | Horizon tiers, operating-hours clock, cutoff/grace, retries, terminal suppression, timeout/decline alerts and late audit | `test_reminder_contracts.py` |
| Quiet hours/consent | Queue/release once, DST boundaries, opt-out after queueing, no false production sent status without credentials | `test_notification_edges.py`, `test_notification_workflows.py`, `test_reminder_contracts.py` |
| Inbox/human recovery | Real thread filters/search, reply, persisted messages/state and resolution back to bot | `test_sms_inbox.py`, `test_portal_workflows.py` (browser), `test_workflows.py` |
| Knowledge files | Upload/overwrite/list/preview/download/delete; reject non-UTF8 without writing | `test_portal_workflows.py` (browser), `test_workflows.py` |
| Webhooks/recovery | Signatures/tampering/stale/missing IDs, replay once, recover paginated calls, authenticate cron | `test_integrations.py`, `test_workflows.py` |
| Google accounts | Issued/single-use/expired/omitted state, encrypted storage, failed exchange, refresh/rotation/revocation/disconnect | `test_google_contracts.py`, `test_regression_contracts.py` |
| Reporting/history | Dashboard/timeframes/counts, call pagination, technician/SLA and unresolved escalations match data | `test_voice_and_reporting.py`, reporting panes in `test_portal_workflows.py` |
| Permanent regressions | Unknown calendar blocks booking; distinct reschedules each notify; disabled initial switch controls dispatch | `test_regression_contracts.py`, existing unknown-calendar/late-audit cases |

## Visible-browser walkthrough

Use `--browser --e2e-headed` and select a journey with `-k` when useful. Every
write should agree across the browser, fresh backend read and reloaded document.

- Create a service with two tags, edit to one, then clear. Check its own row,
  not another service's badges. Fail a save and check error plus unchanged tags.
- Create/edit/reload a staff profile, dismiss deletion, then deactivate a staff
  member with future work. Check the retained booking and reassignment escalation.
- Save timezone and hours, reload, and check real accepted/rejected booking
  boundaries. Persistence alone is not proof that a setting affects behavior.
- Verify recording disclosure, save a greeting and inspect captured sync. Fail
  storage and check that the stored greeting survives a document reload.
- Create a portal booking through confirmation, process its actual outbox,
  capture the SDK request, submit a signed callback and inspect the delivery log.
- Book linked services through the voice HTTP tool and verify every segment in
  the browser after reload. This does not evaluate spoken dialogue or imply the
  portal has a multi-service input control.
- Run existing inbox reply/resolution, knowledge-file lifecycle, failed
  status/matrix saves, mobile navigation and configuration-subtab journeys.

## Manual and release gates (separate from default runs)

Use isolated/staging environments and synthetic data. Live checks need separately
authorized sandbox accounts/recipient numbers. Record each outcome; captured HTTP
does not prove real delivery. No live checks are performed by adding these tests.

| Gate | Instructions | Evidence to retain |
| --- | --- | --- |
| Voice conversations | Script new/returning callers, refusal of consent, reschedule/cancel, multiple services, unavailable slots, interruptions and dependency failure. Listen for disclosure and rate/duration/date/time confirmation before writes. | Transcript/audio, tool-call and consent ordering, before/after booking IDs; direct tools do not establish model behavior |
| Retrieval quality | Use a fixed small corpus; ask known/ambiguous/unknown questions and simulate provider failure. | Expected facts, retrieved text, grounded response and explicit unknown/failure |
| Live Twilio | In an authorized sandbox, book once, deliver to a designated test recipient, retry a controlled failure and withdraw consent. | Provider SID, receiver-side delivery, signed callback, no duplicates after retry/STOP |
| Live Google | Connect sandbox account, check busy/all-day conflicts, book split visit, inspect customer/staff events and fallback, reschedule/cancel, revoke/reconnect. | Local reservation and provider event IDs/times/scopes; no orphan effects |
| Calendar recovery | Stop after local commit before projection, restart and process pending work; repeat after controlled provider failure. | Durable queue before/after restart and exactly one final intended provider effect |
| Worker lifecycle | Start real app on isolated DB, enqueue due reminder/outbox work, restart, then terminate gracefully. | Startup/worker/shutdown logs, completed work and bounded retries; manual pytest cycles do not prove lifespan |
| Migration/recovery | Back up a disposable previous-schema database, migrate, verify existing bookings/new tags and exercise documented recovery. | Schema version, row integrity and observed recovery; no untested rollback claim |
| Browser/accessibility | Run every intended supported engine; manually check keyboard tab order, focus/escape, labels, zoom and narrow/mobile layout. | Per-engine JUnit and manual checklist; Chromium alone is not cross-browser proof |
| Load/concurrent orderings | Agree on traffic and latency/error budgets; test competing multi-service bookings and confirm/reassign/decline orderings. | Workload, measurements and reservation/notification invariants; no invented performance threshold |

## Live WhatsApp checklist

Run this separately from pytest, with an explicitly authorized test recipient and
environment. The automated suites intentionally capture provider traffic and do
not send WhatsApp messages.

1. Record the URL and deployed commit. Verify that it includes the fixes being
   accepted; a local green run does not update the deployed application.
2. Confirm the intended customer/staff phone numbers and enabled notification
   rules. Use only designated test recipients. Check initial-notification,
   consent, quiet-hours and reminder settings before booking.
3. If using the Twilio Sandbox, each recipient must send the **current** join
   code from the portal/Console to the correct Sandbox and receive its enrollment
   confirmation. A stored `whatsapp_onboarded=true` flag is not provider proof.
   Enrollment expires after three days; error `63015` means the recipient is not
   currently enrolled in that Sandbox. See [Twilio's error reference](https://www.twilio.com/docs/api/errors/63015).
4. Send an inbound WhatsApp message from the designated recipient immediately
   before the test. Free-form outbound messages require an open 24-hour customer
   service window; outside it, use a supported approved template. See
   [Twilio's Sandbox requirements](https://www.twilio.com/docs/whatsapp/sandbox).
5. Create one valid future booking through the deployed browser UI. Record its
   request/visit ID and booking time. Verify the committed booking after reload,
   its outbox event, and a non-mock provider SID in the notification log.
6. Wait for the signed delivery callback. Verify `DELIVERED` in the persisted
   log **and** receipt on the recipient's phone. `SENT`, an HTTP 200 from a test
   ping, an outbox event labelled `DELIVERED`, or a connected badge alone do not
   prove handset delivery. Record any error code and its timestamp.
7. Reschedule once, confirm the new time after reload, then cancel. Verify exactly
   one intended notification per enabled recipient/channel for each change,
   no stale reminders, and released capacity. These are real data changes and
   may send more messages; agree on their scope before running them.
8. Test a scheduled reminder and quiet-hours release in an isolated deployment
   with controlled times. Include a period without browser traffic and a process
   restart. Verify durable pending work and eventual delivery, not only a manual
   worker call. Free Render instances sleep after idle periods, so in-process
   workers alone do not guarantee scheduled execution while asleep. See
   [Render's free-instance limits](https://render.com/docs/free).
9. In a sandbox only, exercise an unjoined recipient and expired messaging
   window. Require an honest failure status and useful provider error; do not
   mark onboarding/delivery successful from request acceptance. Rejoin/reopen
   the window, use the scoped retry control once, and verify no duplicate logical
   message. Never flush or replay the entire production queue for this check.

Retain environment/commit, request ID, masked recipient, provider SID, callback
status/time and receiver confirmation. Mark any step not executed as **not run**.

## Maintain the coverage

Add a requirement row and executable references before calling a new feature
covered. Cover success, boundaries, rejection, dependency failure and relevant
races. Use deterministic clocks, not sleeps or mocked validators. Keep changed
contracts reviewable rather than silently dropping old guarantees. Refresh
[KNOWN_FAILURES.md](KNOWN_FAILURES.md) from a current run after fixes; historical
notes are context, not a release result.
