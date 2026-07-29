# Story 2: Core Notification Router & Quiet Hours Engine

## User Story
As a System Engine, I want to route appointment lifecycle events (`CREATED`, `RESCHEDULED`, `REASSIGNED`, `CANCELLED`) to the appropriate recipient roles based on settings matrix and quiet hours rules, so that stakeholders receive timely SMS without off-hours disruption.

## Sub-tasks & Checklist

- [ ] **Task 2.1: Notification Router Service**
  * File: `serviceBot/services/sms_router.py`
  * Create `SMSNotificationRouter` class to intercept appointment lifecycle events.
  * Look up `sms_matrix_rules` dynamically to check if SMS is enabled for target role.
  * Check `customer.sms_opt_in` before generating any customer SMS record. If opted out, create `sms_log` entry with status `SKIPPED_OPT_OUT`.
  * Check `staff_agents.phone_number` is not NULL before generating agent SMS. If missing, skip gracefully.

- [ ] **Task 2.2: Isolation, Suppression & Compound Event Rules**
  * Enforce rule: Customer is **NOT** notified when an appointment is reassigned to a new agent unless date/time changed.
  * Enforce rule: Previous Agent receives unassignment notice on reassignment.
  * Enforce rule: Admin SMS suppressed by default unless enabled in matrix settings.
  * **Compound event handling**: When both date/time AND agent change in a single operation, treat as `RESCHEDULED_REASSIGNED`. Customer gets reschedule SMS, new agent gets assignment, previous agent gets unassignment (see SMS Spec §2.2 compound row).

- [ ] **Task 2.3: Quiet Hours Evaluator**
  * File: `serviceBot/services/quiet_hours.py`
  * Implement quiet hours evaluation logic using **business timezone** (`America/New_York`) for MVP.
  * If event occurs in Quiet Hours AND appointment starts in >12 hours, queue SMS with `scheduled_send_at` for Quiet Hours end (e.g. 8:00 AM).
  * If appointment starts in <12 hours, trigger **Urgent Override** and dispatch immediately.
  * **Boundary rule**: `21:00:00` is inside quiet hours (queued), `08:00:00` is outside (dispatched).

- [ ] **Task 2.4: Reminder Scheduler Engine**
  * File: `serviceBot/services/reminder_service.py`
  * Schedule Customer 24h and 2h pre-appointment reminders by inserting records into `sms_reminders` table.
  * Schedule Service Agent 2h pre-appointment reminder.
  * Clean up / cancel pending reminders when an appointment is cancelled (set `status = 'CANCELLED'`).
  * **On reschedule**: Cancel existing reminders and create new ones for the updated time.
  * **Polling worker**: Add a background polling loop (30-second interval) that queries `sms_reminders WHERE status = 'PENDING' AND scheduled_at <= NOW()` and dispatches eligible reminders through the Twilio client.

- [ ] **Task 2.5: Quiet Hours Queue Release Worker**
  * Add a background polling loop (30-second interval) for quiet-hours-queued SMS: query `sms_log WHERE status = 'QUEUED' AND scheduled_send_at <= NOW()` and push to dispatch pipeline.
  * This can share the same polling thread as the reminder worker.

- [ ] **Task 2.6: Automated Tests**
  * File: `tests/test_sms_router.py`
  * Test routing matrix output for all event types including compound `RESCHEDULED_REASSIGNED`.
  * Test quiet hours queuing vs. urgent override dispatch.
  * Test quiet hours boundary (exactly 21:00 → queued, exactly 08:00 → dispatched).
  * Test reminder job scheduling and cancellation cleanup.
  * Test reminder rescheduling (old cancelled, new created).
  * Test opt-in guard (opted-out customer → SKIPPED_OPT_OUT).
  * Test agent with no phone number → graceful skip.

## Verification Checklist
- Run `pytest tests/test_sms_router.py` to confirm 100% pass rate.
