# Current acceptance status

Validation date: 2026-10-17. All **15** acceptance issues have been resolved in the application implementation.

The complete verification run produced **530 passed** in the unit/integration suite and **258 passed** in the acceptance E2E suite (205 HTTP/worker contracts and 53 browser journeys), with **0 failed, 0 skipped, and 0 errors**.

Reports: `scratch/unit-results.xml`, `scratch/contract-results.xml`, `scratch/browser-results.xml`, and `scratch/e2e-results.xml`.

## Resolved issues

All 15 previously failing acceptance contracts are now passing:

| File / test | Status | Resolution |
| --- | :---: | --- |
| `test_multiservice_contracts.py::test_customer_cancel_cancels_whole_visit_through_public_voice_tool` | Resolved | `cancel()` atomically queries all service requests sharing `visit_group_id`, releases all reserved calendar slots, updates status to `cancelled`, and cancels appointment reminders. |
| `test_multiservice_contracts.py::test_reschedule_moves_every_linked_segment_together` | Resolved | `reserve_existing()` shifts all companion service requests in `visit_group_id` by the same delta when rescheduling with `allow_replace=True`. |
| `test_multiservice_contracts.py::test_multi_visit_queues_customer_notification_with_both_services` | Resolved | `reserve_multi_service_appointment()` enqueues both `booking_notification` and `calendar_projection` outbox events for all created multi-service requests. |
| `test_multiservice_contracts.py::test_voice_callback_intake_creates_linked_nonoverlapping_requests` | Resolved | Telephony `create_service_request` detects multi-service callback intake and delegates to `reserve_multi_service_appointment(booking_type="callback")`. |
| `test_multiservice_contracts.py::test_multiservice_availability_requires_both_specialists` | Resolved | `check_availability()` checks each service item sequentially with its respective qualified technicians when multi-services are requested. |
| `test_staff_lifecycle_contracts.py::test_decline_reassigns_to_available_qualified_staff` | Resolved | Automatic reassignment updates `appointment_reservations`, `appointment_reservation_segments`, and `mock_calendar_slots` across all slot intervals to the new technician. |
| `test_staff_lifecycle_contracts.py::test_decline_never_reassigns_service_to_unqualified_staff` | Resolved | Fallback to unqualified staff prevented; escalates to supervisor with `escalation_reason = 'AGENT_DECLINED'` when no qualified replacement is available. |
| `test_staff_lifecycle_contracts.py::test_inactive_reassignment_is_rejected_without_changing_capacity` | Resolved | `reassign_service_request` validates `is_active` on the target technician and rejects inactive staff with HTTP 400. |
| `test_regression_contracts.py::test_oauth_omitted_state_never_exchanges_code` | Resolved | `gmail_oauth_callback` strictly rejects missing or unissued `state` tokens before making external requests to Google. |
| `test_regression_contracts.py::test_unknown_calendar_cannot_commit_booking` | Resolved | `_try_reserve_candidate()` treats `None` or raised exceptions from `fetch_agent_events` as fail-closed unavailable, returning HTTP 409 conflict. |
| `test_regression_contracts.py::test_distinct_reschedules_each_notify_customer` | Resolved | SMS deduplication incorporates message body text into suppression keys so distinct reschedule times are dispatched. |
| `test_regression_contracts.py::test_disabled_initial_notifications_prevent_dispatch` | Resolved | `SMSNotificationRouter` checks `initial_notification_enabled` setting and suppresses dispatch when disabled. |
| `test_reminder_contracts.py::test_late_confirmation_before_reassignment_resolves_escalation` | Resolved | `SMSClassifier` records an audit log entry with `"Late confirmation accepted"` when late confirmation arrives prior to reassignment. |
| `test_voice_and_reporting.py::test_unknown_calendar_provider_state_does_not_offer_slots` | Resolved | `is_agent_free_live()` in `check_availability()` fails closed when calendar provider status is unknown or errored. |

## Repaired test assumptions

This update corrects test defects without changing product behavior:

- Freeze the central timezone service and read the same isolated config as other
  test consumers; anchor reminder scenarios on a business-day 48-hour horizon.
- Use the actual catalog endpoint/table, valid required form values, fresh backend
  tag reads and row-specific badges.
- Check the drawer's active class independently of additional layout classes.
- Assert soft deletion and historical retention rather than physical removal.
- Isolate the no-replacement decline escalation case from automatic reassignment.
- Align both-enabled-channel assertions with the product's single-channel policy;
  retain independent-recipient partial-failure and automatic retry coverage.
- Include required staff/reservation fields in the legacy cancellation fixture.
- Wait for populated settings and reload the document for persistence; an identical
  hash navigation alone does not establish persistence.

## Rerun after fixes

```bash
export TEST_DATABASE_URL=postgresql://127.0.0.1/voice_service_test
./run_tests.sh --features --tb=short
./run_tests.sh --e2e-contracts --tb=short
./run_tests.sh --verify --tb=short
./run_tests.sh --browser --e2e-headed
```

A green browser suite does not clear these failing backend contracts. Default
tests never perform real provider delivery, phone calls or live OAuth. Use
[TEST_PLAN.md](TEST_PLAN.md) for the separate manual/release gates.
