# Master Task List & Implementation Roadmap: SMS & Handoff Feature

This document serves as the master implementation checklist for the SMS Notification System and Two-Way Human Handoff Feature. Tasks are organized sequentially into stories, designed for execution by AI agentic coding sessions.

---

## 📌 Implementation & Verification Guidelines for Agents

For each task in this master list:
1. **Implement Code**: Create/update logic following project conventions in `serviceBot/`.
2. **Create Tests**: Add comprehensive unit, integration, or API test cases in `tests/`.
3. **Validate Execution**: Execute tests (e.g., `pytest tests/`) and confirm 100% pass rate.
4. **Update Status**: Change task checkbox from `- [ ]` to `- [x]`.
5. **Local Web Verification**: At the end of the full epic implementation, launch the local app (`python -m serviceBot.main` or `uvicorn`) and verify the UI pages in browser.

### ⚠️ Critical Schema Dependencies
Before any story begins, the implementing agent must verify the following prerequisites exist (all created in Story 1 Task 1.1):
- `staff_agents.phone_number` column (required for agent SMS)
- `customers.sms_opt_in` column (required for TCPA compliance)
- `service_requests` status CHECK includes `confirmed` and `cancelled_by_customer`
- All 7 new SMS tables: `sms_config`, `sms_matrix_rules`, `sms_whitelist`, `sms_log`, `sms_reminders`, `sms_conversations`, `sms_messages`

---

## 🚀 Epic 1: Configuration & Settings System
**Goal**: Build database schema and API endpoints for SMS settings, matrix toggles, quiet hours, test whitelist, and support numbers.

- [x] **Task 1.1**: Define DB models and schema migrations — add 7 new SMS tables (`sms_config`, `sms_matrix_rules`, `sms_whitelist`, `sms_log`, `sms_reminders`, `sms_conversations`, `sms_messages`) and migrate existing tables (`staff_agents.phone_number`, `customers.sms_opt_in`, expanded `service_requests` status constraint). Seed default config and matrix rules.
- [x] **Task 1.2**: Implement REST API endpoints in `serviceBot/api/portal.py` for reading/updating SMS configuration settings, and whitelist CRUD.
- [x] **Task 1.3**: Add unit tests in `tests/test_sms_config.py` verifying config GET/PUT API behavior, default seeds, schema migrations, and whitelist CRUD.
- [x] **Task 1.4**: Build the SMS Configuration Settings tab/section in the Admin Portal web UI (`serviceBot/static/`) including matrix checkbox table, quiet hours pickers, support number, whitelist management.
- [x] **Task 1.5**: Add Agent Onboarding phone number field & Twilio Verified Caller ID API integration (`POST /api/portal/twilio/verify-caller-id`) for test mode whitelisting.

---

## 🔔 Epic 2: Core Event Notification Router & Quiet Hours
**Goal**: Intercept appointment lifecycle events, apply recipient matrix logic, and calculate quiet hours scheduling.

- [x] **Task 2.1**: Implement `SMSNotificationRouter` service to process appointment events (`CREATED`, `RESCHEDULED`, `REASSIGNED`, `CANCELLED`) with opt-in guard and agent phone check.
- [x] **Task 2.2**: Enforce matrix rules: suppress customer SMS on agent-only reassignment; suppress admin SMS unless explicitly enabled; handle compound `RESCHEDULED_REASSIGNED` event (customer + new agent + previous agent all notified).
- [x] **Task 2.3**: Implement Quiet Hours evaluator with 12-hour urgent event override logic, business timezone (`America/New_York`), and boundary rule (21:00 = inside, 08:00 = outside).
- [x] **Task 2.4**: Build Pre-Appointment Reminder scheduler engine (24h/2h customer, 2h agent) using `sms_reminders` table with automatic cleanup on cancellation and rescheduling.
- [x] **Task 2.5**: Implement Quiet Hours queue release worker (30-second polling interval) to dispatch queued SMS when quiet hours end.
- [x] **Task 2.6**: Add unit & integration tests in `tests/test_sms_router.py` verifying routing rules, quiet hours, boundary cases, compound events, opt-in guard, and reminder scheduling.

---

## 📲 Epic 3: Twilio Delivery Engine & Retry Tracking
**Goal**: Manage outbound Twilio dispatches, exponential backoff retries, delivery failure logging, and dashboard UI popup.

- [x] **Task 3.1**: Create `TwilioSMSClient` service wrapper with dual-mode dispatch (prefer `TWILIO_MESSAGING_SERVICE_SID`, fallback to `TWILIO_FROM_NUMBER`) and environment test whitelist validation.
- [x] **Task 3.2**: Extend existing `outbox_worker.py` with SMS event types and SMS-specific backoff (+30s, +2m, +10m). Implement hard failure detection for Twilio error codes 30003/30005/30006/21610.
- [x] **Task 3.3**: Create Twilio Delivery Status Webhook handler in `serviceBot/api/telephony.py` to record `DELIVERED` or `FAILED` statuses in `sms_log`.
- [x] **Task 3.4**: Add "Details" popup modal to Appointments Table in `serviceBot/static/` showing SMS log history from `sms_log` table and "Retry SMS" button.
- [x] **Task 3.5**: Add unit and mock tests in `tests/test_twilio_delivery.py` for Twilio dispatch (both modes), backoff retries, hard failure codes, status callbacks, whitelist blocking, and Messaging Service fallback.

---

## 💬 Epic 4: Two-Way SMS & Inbound Keyword Classifier
**Goal**: Receive incoming customer SMS via Twilio webhook, classify responses into action keywords vs. free-text, and enforce TCPA compliance.

- [x] **Task 4.1**: Implement Inbound Twilio SMS webhook endpoint (`POST /api/telephony/sms/inbound`) with `X-Twilio-Signature` verification.
- [x] **Task 4.2**: Implement TCPA compliance keyword handler (`STOP`, `UNSUBSCRIBE`, `QUIT`, `END` — note: `CANCEL` excluded to avoid conflict with appointment cancellation) with text normalization (`.strip().upper()`) and single-token matching.
- [x] **Task 4.3**: Implement Action keyword handler (`C`/`CONFIRM`/`YES`, `X`/`CANCEL`/`NO`) with multiple appointment disambiguation (most recent SMS context → next upcoming → error + handoff fallback).
- [x] **Task 4.4**: Add tests in `tests/test_inbound_sms.py` verifying signature validation, text normalization, single-token vs. multi-word, TCPA opt-outs (including `CANCEL` NOT being opt-out), keyword action updates, multiple appointment handling, and keyword-during-handoff behavior.

---

## 🧑‍💻 Epic 5: Human Handoff Lifecycle & Live Inbox UI
**Goal**: Manage conversation state transitions (`HANDOFF_REQUIRED`, `IN_PROGRESS`, `RESOLVED`), auto-responder fallback, and Live Inbox UI.

- [x] **Task 5.1**: Implement Handoff State Machine in `serviceBot/services/handoff_service.py` with per-phone thread scoping (one thread per customer phone, not per appointment).
- [x] **Task 5.2**: Send immediate auto-responder SMS with support phone number when a customer sends a free-text message, with opt-in guard (skip SMS if opted out) and debounce guard (suppress duplicate within 60-second window).
- [x] **Task 5.3**: Build Live SMS Inbox dashboard component in `serviceBot/static/` with "Needs Attention" queue, thread history (from `sms_messages` table), appointment sidebar, and outbound reply input.
- [x] **Task 5.4**: Implement REST API endpoints for human operators to send custom SMS replies (`POST /api/portal/sms/reply`), mark threads as `RESOLVED` (`POST /api/portal/sms/resolve`), and handle agent proactive replies (AUTOMATED → IN_PROGRESS transition).
- [x] **Task 5.5**: Add integration tests in `tests/test_human_handoff.py` covering free-text handoff triggering, auto-responder with opt-in guard, debounce suppression, agent replies, thread resolution, agent proactive reply, and per-phone thread scoping.

---

## 🧪 Epic 6: End-to-End Verification & Local Web Testing
**Goal**: Full system integration testing and manual validation via local web server.

- [x] **Task 6.1**: Run full test suite (`pytest`) and ensure 100% pass rate across all new SMS and handoff test files.
- [x] **Task 6.2**: Launch local web application server (`python -m serviceBot.main`).
- [x] **Task 6.3**: Open local web portal in browser and test:
  * SMS Matrix & Settings Configuration Page (including whitelist management).
  * Appointment Details SMS Log Popup (verify delivery statuses and Retry button).
  * Live SMS Inbox Dashboard & Human Handoff Console (verify thread states, debounce, reply flow).
- [x] **Task 6.4**: Verify server restart resilience — confirm scheduled reminders persist and fire correctly after restart (DB-backed, not in-memory).

---

## 🐛 Discovered UI Bugs & Specification Gaps

The following bugs were identified during browser testing against `human_handoff_specification.md` and `sms_system_specification.md`:

- [x] **Bug 01**: [BUG_01_SMS_LOGS_AND_DETAILS_MODAL_NOT_ACCESSIBLE.md](file:///Users/rohanroy/Coding/voiceService/docs/stories/BUG_01_SMS_LOGS_AND_DETAILS_MODAL_NOT_ACCESSIBLE.md) — Service Requests table missing "Details" button and SMS failure indicators (⚠️/❌), making SMS logs and manual retry drawer inaccessible.
- [x] **Bug 02**: [BUG_02_SERVICE_AGENT_PHONE_AND_TWILIO_VERIFICATION_MISSING.md](file:///Users/rohanroy/Coding/voiceService/docs/stories/BUG_02_SERVICE_AGENT_PHONE_AND_TWILIO_VERIFICATION_MISSING.md) — Staff Member form missing `phone_number` field and Twilio Verified Caller ID trigger.
- [x] **Bug 03**: [BUG_03_INBOX_SIDEBAR_QUICK_ACTIONS_MISSING.md](file:///Users/rohanroy/Coding/voiceService/docs/stories/BUG_03_INBOX_SIDEBAR_QUICK_ACTIONS_MISSING.md) — Live SMS Inbox Appointment Context sidebar missing quick action buttons (*Reschedule*, *Cancel*, *Reassign Agent*).
- [x] **Bug 04**: [BUG_04_SERVICE_REQUESTS_STATUS_DROPDOWN_MISSING_NEW_STATUSES.md](file:///Users/rohanroy/Coding/voiceService/docs/stories/BUG_04_SERVICE_REQUESTS_STATUS_DROPDOWN_MISSING_NEW_STATUSES.md) — Dashboard Service Requests status dropdown missing `confirmed` and `cancelled_by_customer` options.
- [x] **Bug 05**: [BUG_05_LIVE_INBOX_CHAT_AUTO_REFRESH_AND_FILTER_LIMITATION.md](file:///Users/rohanroy/Coding/voiceService/docs/stories/BUG_05_LIVE_INBOX_CHAT_AUTO_REFRESH_AND_FILTER_LIMITATION.md) — Live Inbox chat view fails to auto-refresh message bubbles upon reply, and thread filter lacks `AUTOMATED` state option.
- [x] **Bug 06**: [BUG_06_SMS_CONFIG_ENVIRONMENT_DROPDOWN_MISMATCH.md](file:///Users/rohanroy/Coding/voiceService/docs/stories/BUG_06_SMS_CONFIG_ENVIRONMENT_DROPDOWN_MISMATCH.md) — Environment dropdown shows `PRODUCTION` on initial load due to `TESTING` vs `TEST` default value mismatch.


