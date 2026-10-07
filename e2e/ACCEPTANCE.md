# Reimplementation acceptance contract

This maps the documented requirements to observable tests, rather than equating
test counts with completeness. Keep the behavioral assertions when replacing
the app; adapt transport/database fixtures to the new implementation. A failing
test is an unmet acceptance requirement, not a reason to skip or weaken it.

## Booking confirmation and history specification

Source: `specs/001-booking-confirmation-history/spec.md`.
Paths below are relative to `e2e/`. “Partial” describes the evidence boundary,
not an assertion that the implementation is correct.

| Requirement | Executable evidence | Boundary / next gate |
| --- | --- | --- |
| FR-001 deferred booking and explicit caller confirmation | `test_portal_workflows.py::test_new_request_form_creates_booking_after_confirmation` | Partial: browser confirmation is covered; spoken confirmation before tool selection needs a conversation evaluator. |
| FR-002 one active booking per call | `test_voice_and_reporting.py::test_voice_time_change_in_same_call_updates_one_booking`; `test_booking_contracts.py::test_same_call_concurrent_intake_cannot_create_two_requests` | Sequential and concurrent intake; conversational intent remains separate. |
| FR-003 caller context | `test_booking_contracts.py::test_customer_lookup_and_inbound_context_include_issue_duration_and_vehicle`; `test_unknown_caller_cannot_receive_existing_customer_context` | Actual tool result and inbound XML; no generated spoken response asserted. |
| FR-004 detailed appointment lookup | Same caller lookup test | Issue, vehicle, time and duration read-back. |
| FR-005 check existing appointments | Caller lookup test | Partial: tool capability, not proof that the LLM calls it every time. |
| FR-006 offer consolidation | Consolidation tests in `test_booking_contracts.py` | Partial: write/validation contract; natural-language offer needs conversation evaluation. |
| FR-007 update issue and total duration | `test_consolidation_extends_one_booking_and_reserves_added_capacity`; `test_invalid_consolidation_cannot_mutate_booking`; `test_consolidation_cannot_merge_another_customers_request` | Capacity extension, invalid input and ownership are ordinary failing requirements where broken. |
| FR-008 contiguous capacity before extension | `test_blocked_consolidation_leaves_original_booking_and_notifications_unchanged`; successful consolidation test; `test_duration_consumes_every_normalized_segment` | No premature writes, no stolen capacity; caller choice between moving/separate visits needs dialogue evaluation. |
| FR-009 start/end/duration and extension caveat | `test_voice_and_reporting.py::test_voice_intake_creates_real_booking_visible_in_portal` | Persisted start/end/duration and tool caveat; speaking the full quote needs conversation evaluation. |
| FR-010 warm greeting without pre-empting intent | Inbound context and unknown-caller tests | Partial: identity/context only. Scripted returning/new-caller dialogues still required. |
| FR-011 deferred execution plus confirmed in-place changes | Same-call and browser confirmation tests above; `test_workflows.py::test_reschedule_requires_consent_and_preserves_booking_on_rejection` | Partial: tool/database defense covered, LLM ordering/explicit acknowledgement is not. |

## Reminder and escalation specification

Source: `specs/002-appointment-reminder-escalation/spec.md`.

| Requirement | Executable evidence | Boundary / next gate |
| --- | --- | --- |
| FR-001 minimum four-hour buffer | `test_booking_contracts.py::test_four_hour_lead_time_boundary_is_atomic` | Portal and voice, one second before/at/after threshold. |
| FR-002 reject and suggest valid time | Same boundary test; `test_configured_business_window_boundary` | Reject/no side effects and voice earliest-time field; complete nearest-slot suggestion/dialogue remains partial. |
| FR-003 initial customer/staff notifications | `test_notification_workflows.py::test_cron_processes_all_events_generated_by_real_booking`; lifecycle recipient/channel parametrizations | Real booking -> queue -> worker -> SDK HTTP. Normal multi-event cron is required, even when currently failing. |
| FR-004 three horizon-adaptive attempts | `test_reminder_contracts.py::test_booking_generates_all_three_staff_attempts_for_horizon`; generated reminder dispatch tests | Each horizon tier and scheduled times; short-horizon missing attempt is retained as a failure. |
| FR-005 failed-delivery retry/backoff | `test_generated_staff_reminder_retry_honors_backoff_and_recovers`; `test_generated_staff_delivery_exhaustion_alerts_supervisor_and_stops_retrying`; notification transient/exhaustion tests | Automatic retry timing, message preservation, three carrier retries and terminal supervisor escalation. Ambiguous transport acceptance/crash remains separate. |
| FR-006 staff confirmation | `test_integrations.py::test_agent_confirmation_via_sms_visible_in_portal`; generated confirmation tests; browser status-confirmation tests | Signed SMS and portal transitions; portal identity/access policy is not established by these tests. |
| FR-007 stop attempts and audit | `test_notification_workflows.py::test_agent_confirmation_stops_booking_generated_prompts`; late-confirmation and terminal tests | Cancellation and read-back; exhaustive concurrent confirm/reassign ordering remains a separate stress gate. |
| FR-008 operating-hours clock | `test_business_hour_deadlines_pause_outside_operating_window`; `test_business_deadline_preserves_wall_clock_across_dst_weekend` | Overnight, weekends and both DST changes, with deterministic clocks. |
| FR-009 cutoff formula/morning grace | `test_confirmation_cutoff_uses_horizon_tier_and_safety_ceiling`; `test_early_morning_cutoff_is_after_opening_but_before_appointment` | Boundary horizons and configured formula. The spec's exactly-24-hour tier wording is inconsistent; current contract uses advance tier at >=24h. |
| FR-010 timeout/decline/delivery/unassigned escalation | `test_timeout_escalates_only_when_cutoff_is_reached_once`; `test_staff_decline_records_reason_and_alerts_supervisor`; generated delivery-exhaustion test | Timeout, DECLINE/UNAVAILABLE/NO and carrier-exhaustion end-to-end. No-staff workflow remains partial. |
| FR-011 supervisor alert with reason | Same timeout/decline tests | Durable state, audit, actual captured supervisor send and idempotence. No live delivery claim. |
| FR-012 alternate staff ranking | Staff CRUD, availability and reassignment tests in `test_workflows.py` | Partial: qualification/workload ranking requires an agreed policy and dedicated ranking scenarios. |
| FR-013 reassignment effects and 15-minute window | Reassignment/capacity and notification lifecycle tests; `test_reassignment_has_fifteen_minute_confirmation_window` | Routing and local capacity real; calendar projection is captured in notification tests. Automated fallback remains separate. |
| FR-014 late-response races | `test_late_confirmation_before_reassignment_resolves_escalation`; `test_old_staff_confirmation_after_reassignment_cannot_confirm_new_staff` | Both sequential orderings; exhaustive simultaneous races not claimed. |
| FR-015 editable settings | `test_all_documented_reminder_settings_round_trip_without_losing_other_config`; API/browser config round trips; configured lead-time and cutoff calculations | All documented settings checked for persistence; initial-notification/retry-count save currently fails. Every UI field, invalid range and subsequent worker consumer remains partial. |

## Other application areas

The file-by-file map in [README.md](README.md) covers catalog, knowledge-file
lifecycle, inbox/human reply/resolution, staff/calendar editing, call history,
provider signatures/replays, recovery pagination, configuration and reporting.
New Google contracts cover successful OAuth, encrypted token storage, single-use
state, expired/unissued state, failed exchange, refresh preservation/rotation,
revocation and disconnect. Notification edge tests cover channel/body-preserving
manual retry, cross-channel partial success, consent withdrawal after queueing,
and no false production `SENT` when credentials are absent.

## Explicit remaining completion gates

No finite suite proves every possible behavior. These specific gaps prevent a
claim of complete whole-product parity today:

1. Evaluate scripted new/returning caller conversations with real model tool
   selection: refusal of consent, quote/date/time confirmation before writes,
   warm greeting, consolidation offers and interruption recovery. Direct tool
   calls cannot prove those conversational requirements.
2. Evaluate real retrieval/grounded answers using a fixed small corpus, unknown
   questions and dependency failure. In-memory Chroma tests cover file lifecycle,
   not embeddings or answer quality.
3. Finish notification crash/ambiguous-timeout, unassigned booking,
   calendar projection reconciliation and simultaneous
   confirmation/reassignment races. Do not treat SDK capture as live delivery.
4. Confirm product policies for portal access, alternate-staff ranking,
   auto-reassignment, catalog-empty behavior and legacy PDF/DTMF/CRM aspirations.
   Unknown policy must not be invented just to make an assertion pass.
5. Run production lifecycle/migration/restart, representative load, accessibility
   and supported-browser gates. Use explicitly authorized sandbox accounts for
   live Twilio/Google/ElevenLabs checks; this default suite never contacts them.

Use [KNOWN_FAILURES.md](KNOWN_FAILURES.md) to fix current behavioral failures
separately. Tests and documents were changed for this extension; application
implementation was deliberately left untouched.
