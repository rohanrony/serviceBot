# Bug 05: Live SMS Inbox Chat View Does Not Auto-Refresh Sent Messages & Lacks Automated Filter

## Bug Description
As a Support Agent replying to a customer in the Live SMS Inbox, when I click "Send SMS", the sent message bubble does not automatically appear in the chat view. Additionally, there is no option to filter threads by the `AUTOMATED` state.

## Specification Reference
- **Specification**: `docs/specs/human_handoff_specification.md` §5.1 (Console Features & UI Mockup) & §4.2 (State Machine)
- **Requirement**: "Main Chat View: Displays full chronological conversation history (both automated templates sent by Twilio and inbound/outbound text messages)... Thread List Column: Split into Needs Attention (Handoff Required), In Progress, and All Messages."

## Root Cause Analysis
1. In `serviceBot/static/app.js` (lines 2298-2313), the `sendReplyBtn` event listener invokes `POST /api/portal/sms/reply` and then calls `loadSMSConversations()`. However, `loadSMSConversations()` only re-renders the left thread list column, failing to call `loadSMSMessages(activeConversationId, convDetails)` to refresh the active message history container.
2. In `index.html` (lines 960-965), the `sms-thread-filter` dropdown options are `all`, `HANDOFF_REQUIRED`, `IN_PROGRESS`, `RESOLVED`. It lacks an option to filter specifically by `AUTOMATED`.

## Steps to Reproduce
1. Navigate to `http://127.0.0.1:8000/portal/#sms-inbox`.
2. Select a thread in `HANDOFF_REQUIRED` state.
3. Type a message in the reply input and click **Send SMS**.
4. Observe that the toast says "SMS reply sent.", but the new message does not appear in the chat window until you re-click the thread or refresh the page.

## Expected Behavior
- Immediately refresh chat messages via `loadSMSMessages()` after `send_agent_reply` succeeds.
- Add an `AUTOMATED` filter option to `sms-thread-filter` in `index.html`.

## Proposed Remediation Checklist
- [ ] Update `sendReplyBtn` click listener in `app.js` to call `loadSMSMessages()` after sending a reply.
- [ ] Add `<option value="AUTOMATED">🟢 Automated</option>` to `sms-thread-filter` in `index.html`.
- [ ] Verify message thread auto-scrolling and live updates.
