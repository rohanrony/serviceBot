# Story 4: Two-Way SMS & Inbound Keyword Classifier

## User Story
As a Customer, I want to reply to SMS messages with simple keywords (`C` to confirm, `X` to cancel, `STOP` to opt out) so that I can manage my appointments easily without calling support.

## Sub-tasks & Checklist

- [ ] **Task 4.1: Inbound Webhook & Security Verification**
  * File: `serviceBot/api/telephony.py`
  * Endpoint `POST /api/telephony/sms/inbound`.
  * Validate Twilio Request Signature (`X-Twilio-Signature`) using the Twilio `RequestValidator`.
  * Reject requests with invalid signatures (return 403).

- [ ] **Task 4.2: TCPA Compliance Opt-Out / Opt-In Handler**
  * File: `serviceBot/services/inbound_classifier.py`
  * **Pre-processing**: Normalize all inbound message text via `.strip().upper()`.
  * **Single-token matching only**: Only exact single-word matches trigger keyword handlers. Multi-word messages route to handoff (Story 5).
  * Handle `STOP`, `UNSUBSCRIBE`, `QUIT`, `END` → set `customers.sms_opt_in = false`.
    * **Note**: `CANCEL` is intentionally **excluded** from the opt-out list to avoid conflict with appointment cancellation.
  * Handle `START`, `UNSTOP` → set `customers.sms_opt_in = true`.
  * Handle `HELP` → auto-reply with support contact details from `sms_config.support_phone_number`.

- [ ] **Task 4.3: Action Keyword Handlers**
  * Handle `C`, `CONFIRM`, `YES` → update appointment status to `confirmed`, send receipt, alert agent.
  * Handle `X`, `CANCEL`, `NO` → update appointment status to `cancelled_by_customer`, free agent slot, alert agent.
  * **Multiple appointment disambiguation**:
    1. Target the appointment referenced by the most recently sent outbound SMS to this customer (store `last_sms_appointment_id` context).
    2. Fallback: target the next upcoming appointment chronologically.
    3. If no active appointments exist, send error reply and route to `HANDOFF_REQUIRED`.
  * **Keyword during active handoff**: Action keywords are processed normally even if thread is in `HANDOFF_REQUIRED` or `IN_PROGRESS` state. The action is logged in the thread for agent context.
  * **Opt-out keywords during handoff**: Always processed immediately regardless of thread state.

- [ ] **Task 4.4: Automated Tests**
  * File: `tests/test_inbound_sms.py`
  * Test signature validation logic (valid and invalid signatures).
  * Test text normalization (whitespace, casing).
  * Test single-token vs. multi-word: `"CONFIRM"` → confirmed; `"Yes, but can we change time?"` → handoff.
  * Test opt-out / opt-in status updates and SMS suppression.
  * Test `CANCEL` triggers appointment cancellation (not opt-out).
  * Test confirmation and cancellation action handlers.
  * Test multiple appointments: targets most recent SMS context, falls back to next upcoming.
  * Test zero appointments: error reply + handoff.
  * Test keyword during active handoff: action still processed, logged in thread.

## Verification Checklist
- Run `pytest tests/test_inbound_sms.py` to ensure all tests pass.
