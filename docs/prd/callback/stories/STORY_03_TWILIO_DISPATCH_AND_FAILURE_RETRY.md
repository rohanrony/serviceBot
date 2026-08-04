# Story 3: Twilio Delivery Engine & Retry Tracking

## User Story
As a Developer, I want an SMS dispatch service integrated with Twilio that handles exponential backoff retries, records delivery statuses, and presents SMS delivery history in the UI, so that delivery failures can be diagnosed and retried.

## Sub-tasks & Checklist

- [ ] **Task 3.1: Twilio Client & Whitelist Validator**
  * File: `serviceBot/services/twilio_client.py`
  * Wrap Twilio SDK with dual-mode dispatch:
    * **Preferred**: Use `TWILIO_MESSAGING_SERVICE_SID` (if set) for A2P compliance and number pool management.
    * **Fallback**: Use `TWILIO_FROM_NUMBER` (individual sender number) if Messaging Service SID is not configured.
  * Validate target number against `sms_whitelist` table in non-production environments (`sms_config.environment != 'PRODUCTION'`). Block dispatch and log as `SKIPPED_NOT_WHITELISTED` if number is not whitelisted.
  * Check `customer.sms_opt_in` before every customer-targeted dispatch. Log as `SKIPPED_OPT_OUT` if opted out.

- [ ] **Task 3.2: SMS Retry via Existing Outbox Pattern**
  * File: `serviceBot/services/outbox_worker.py` (extend, not new file)
  * Add new SMS event types to the outbox dispatcher: `sms_booking_notification`, `sms_reschedule_notification`, `sms_reassignment_notification`, `sms_cancellation_notification`, `sms_reminder`.
  * Extend `_dispatch_outbox_event()` to route SMS event types to the `TwilioSMSClient`.
  * Implement SMS-specific backoff schedule (+30s, +2m, +10m) — override the default outbox exponential backoff for SMS events.
  * **Hard failure detection**: Twilio error codes `30003`, `30005`, `30006`, `21610` terminate retry immediately and mark as `FAILED`.

- [ ] **Task 3.3: Twilio Delivery Status Webhook**
  * File: `serviceBot/api/telephony.py`
  * Endpoint `POST /api/telephony/sms/status` to receive status updates (`delivered`, `undelivered`, `failed`).
  * Update `sms_log` record with delivery status, Twilio error code, and error message.

- [ ] **Task 3.4: Appointment Details SMS Log Popup**
  * File: `serviceBot/static/`
  * Add "Details" modal button to Appointments table.
  * Render SMS log history per recipient from `sms_log` table with status indicators (`DELIVERED`, `FAILED`, `SKIPPED_OPT_OUT`, `SKIPPED_NOT_WHITELISTED`).
  * Add "Retry SMS" button to manually re-queue failed dispatches (inserts new outbox event).

- [ ] **Task 3.5: Automated Tests**
  * File: `tests/test_twilio_delivery.py`
  * Test Twilio dispatch with mocked API calls (both Messaging Service SID and FROM_NUMBER modes).
  * Test backoff retry queueing and failure transitions.
  * Test hard failure codes terminate retry immediately.
  * Test status callback webhook updates `sms_log`.
  * Test whitelist blocking in non-production environment.
  * Test Messaging Service SID fallback to FROM_NUMBER.

## Verification Checklist
- Run `pytest tests/test_twilio_delivery.py` to confirm all tests pass.
