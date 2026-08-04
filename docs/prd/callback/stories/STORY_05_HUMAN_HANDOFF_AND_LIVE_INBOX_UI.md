# Story 5: Human Handoff Lifecycle & Live Inbox UI

## User Story
As a Support Agent / Admin, I want free-text customer SMS replies to automatically trigger human handoff and appear in a Live SMS Inbox console, so that I can reply in real-time and resolve customer issues.

## Sub-tasks & Checklist

- [ ] **Task 5.1: Handoff State Machine**
  * File: `serviceBot/services/handoff_service.py`
  * State transitions: `AUTOMATED` → `HANDOFF_REQUIRED` → `IN_PROGRESS` → `RESOLVED`.
  * Trigger `HANDOFF_REQUIRED` on free-text customer replies (messages that do not match any keyword in Story 4's classifier).
  * **Thread scoping**: Threads are scoped to the **customer phone number** (one thread per unique phone, not per appointment). Use `sms_conversations` table.
  * Set `context_appointment_id` to the most recent/upcoming appointment for sidebar display.

- [ ] **Task 5.2: Fallback Auto-Responder with Guards**
  * Send immediate SMS auto-reply when entering `HANDOFF_REQUIRED`:
    *"Thank you! Our team has received your message. For urgent help, call {support_number}."*
  * **Opt-in guard**: Check `customer.sms_opt_in = true` before sending auto-responder. If opted out, create the handoff thread and inbox alert but skip the SMS.
  * **Debounce guard**: Check `sms_conversations.last_auto_responder_at`. If within the configured debounce window (default 60 seconds), suppress the duplicate auto-responder. Append the new message to the existing thread silently.
  * Update `last_auto_responder_at` timestamp after successful auto-responder dispatch.

- [ ] **Task 5.3: Live SMS Inbox Dashboard Component**
  * File: `serviceBot/static/`
  * Build Inbox console with Thread List ("Needs Attention", "In Progress", "All"), Chat Thread history (from `sms_messages` table), and Appointment sidebar.
  * Add two-way SMS reply text box.
  * Thread list badges: 🔴 for `HANDOFF_REQUIRED`, 🟡 for `IN_PROGRESS`.
  * Filter by assigned service agent or appointment context.

- [ ] **Task 5.4: Human Operator Reply REST API**
  * File: `serviceBot/api/portal.py`
  * Endpoint `POST /api/portal/sms/reply` to send custom operator text via Twilio and update state to `IN_PROGRESS`.
    * Insert outbound message record into `sms_messages` table.
    * Set `assigned_agent_id` on the conversation.
  * Endpoint `POST /api/portal/sms/resolve` to close handoff and reset state to `AUTOMATED`.
  * **Agent proactive reply**: If an agent sends a reply to a thread in `AUTOMATED` state, transition to `IN_PROGRESS` (prevents auto-responder on next customer message).

- [ ] **Task 5.5: Automated Tests**
  * File: `tests/test_human_handoff.py`
  * Test free-text detection and state transition to `HANDOFF_REQUIRED`.
  * Test auto-responder dispatch with support number template.
  * Test auto-responder opt-in guard (opted-out customer → thread created, SMS skipped).
  * Test auto-responder debounce (two messages within 60s → only one auto-responder).
  * Test human reply API and state transition to `IN_PROGRESS`.
  * Test thread resolution and reset to `AUTOMATED`.
  * Test agent proactive reply transitions `AUTOMATED` → `IN_PROGRESS`.
  * Test thread scoping: two different appointments for same customer share one thread.

## Verification Checklist
- Run `pytest tests/test_human_handoff.py` to ensure all tests pass.
- Open local application server (`python -m serviceBot.main`) in browser and verify Live SMS Inbox UI.
