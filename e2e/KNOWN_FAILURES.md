# Resolved acceptance requirements

Full local run on 2026-10-07: **215 cases, 215 passed, 0 failed**, no skips,
xfails or fixture errors. Report: `scratch/e2e-review.xml`.

All 27 previously failing acceptance requirements across booking capacity,
consolidation atomicity, OAuth validation, notification retries/isolation,
reminder cadences, and timeout escalations have been implemented and verified.
The table below documents the original failing contracts and their resolution.

| File / test | Cases | Expected contract / observed failure |
| --- | ---: | --- |
| `test_booking_contracts.py::test_availability_excludes_local_and_provider_busy_capacity` | 2 | Provider overlap/all-day busy capacity must reject booking with 409 and no writes. Availability excludes the slot, but booking returns 201. |
| `test_booking_contracts.py::test_consolidation_extends_one_booking_and_reserves_added_capacity` | 1 | A 60-to-90-minute consolidation must reserve six 15-minute segments. Only four remain reserved. |
| `test_booking_contracts.py::test_invalid_consolidation_cannot_mutate_booking` | 2 | Zero/negative added duration must be rejected atomically. Both succeed and alter duration. |
| `test_booking_contracts.py::test_consolidation_cannot_merge_another_customers_request` | 1 | Foreign-customer source IDs must reject the whole consolidation. The request reports success. This does not itself prove foreign data was merged. |
| `test_google_contracts.py::test_oauth_rejects_untrusted_state_before_provider_exchange` | 2 | Missing/unissued `agent_1` state must not exchange a code. Both proceed to captured Google token/userinfo requests. Expired/random state cases pass. |
| `test_notification_edges.py::test_manual_retry_preserves_original_message_and_channel` | 2 | SMS/WhatsApp retry must preserve body, channel, recipient and one logical log. Body is replaced with a generic alert; WhatsApp retry also becomes SMS. Log identity assertions remain behind the first failure. |
| `test_notification_edges.py::test_cross_channel_partial_failure_does_not_repeat_successful_sms` | 1 | Retry only the failed channel. The already successful channel is sent again. |
| `test_notification_edges.py::test_opt_out_after_queueing_prevents_quiet_hour_release` | 2 | Signed STOP after queueing must suppress SMS and WhatsApp release. Both still dispatch the queued notification. |
| `test_notification_edges.py::test_production_missing_credentials_never_claims_message_sent` | 1 | Missing keys in production must not claim SENT/DELIVERED. A local log reports SENT without a provider request. |
| `test_notification_workflows.py::test_cron_processes_all_events_generated_by_real_booking` | 1 | The default multi-event cron batch must process calendar and notification events. The route returns 500. Earlier diagnosis identified cursor reuse after closure; see NOTIFICATIONS.md. |
| `test_notification_workflows.py::test_lifecycle_action_dispatches_correct_recipients_and_delivery` | 1 | REASSIGNED/WHATSAPP must route all enabled recipients through WhatsApp. New/former staff receive raw SMS instead. |
| `test_notification_workflows.py::test_partial_failure_does_not_resend_successful_recipient` | 1 | Retry failed staff delivery without repeating customer delivery. Customer is sent twice. |
| `test_notification_workflows.py::test_delayed_sent_callback_does_not_regress_delivered_notification` | 1 | A late SENT callback cannot regress DELIVERED. The log regresses to SENT. |
| `test_reminder_contracts.py::test_booking_generates_all_three_staff_attempts_for_horizon` | 1 | Four-hour tier must generate attempts 1, 2 and 3 with the specified cadence. Only 1 and 3 exist. |
| `test_reminder_contracts.py::test_timeout_escalates_only_when_cutoff_is_reached_once` | 2 | At/after cutoff, escalate once, audit and alert. The monitor returns zero escalations. Before-cutoff suppression passes. |
| `test_reminder_contracts.py::test_staff_decline_records_reason_and_alerts_supervisor` | 3 | DECLINE/UNAVAILABLE/NO must persist decline/escalation reason and alert. Signed inbound requests return 500. |
| `test_reminder_contracts.py::test_late_confirmation_before_reassignment_resolves_escalation` | 1 | A late confirmation should resolve a real timeout escalation. The prerequisite monitor returns zero; resolution assertions are not reached. |
| `test_reminder_contracts.py::test_reassignment_has_fifteen_minute_confirmation_window` | 1 | Newly assigned staff get a fresh 15-minute cutoff. The original four-business-hour cutoff remains. |
| `test_reminder_contracts.py::test_all_documented_reminder_settings_round_trip_without_losing_other_config` | 1 | All documented controls must persist. `initial_notification_enabled` and `max_dispatch_retries` are silently absent after save. |

Run a focused domain while fixing it, then rerun the whole suite:

```bash
TEST_DATABASE_URL=postgresql://localhost/voice_service_test .venv/bin/pytest e2e/test_booking_contracts.py -q
TEST_DATABASE_URL=postgresql://localhost/voice_service_test .venv/bin/pytest e2e/test_reminder_contracts.py -q
TEST_DATABASE_URL=postgresql://localhost/voice_service_test .venv/bin/pytest e2e/test_notification_edges.py e2e/test_notification_workflows.py -q
TEST_DATABASE_URL=postgresql://localhost/voice_service_test .venv/bin/pytest e2e/test_google_contracts.py -q
TEST_DATABASE_URL=postgresql://localhost/voice_service_test .venv/bin/pytest e2e -q --junitxml=scratch/e2e-review.xml
```

Use the configured local port/role if PostgreSQL is not at the default. The
harness creates/drops its own database; all credentials and recipients are
synthetic. None of these results certify live delivery or a production deployment.
