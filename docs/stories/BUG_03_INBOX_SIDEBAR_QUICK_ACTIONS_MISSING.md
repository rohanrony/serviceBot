# Bug 03: Live SMS Inbox Appointment Sidebar Missing Quick Action Buttons

## Bug Description
As a Support Agent viewing a customer handoff thread in the Live SMS Inbox, I cannot perform quick appointment actions (Reschedule, Cancel, Reassign Agent) directly from the Appointment Context sidebar.

## Specification Reference
- **Specification**: `docs/specs/human_handoff_specification.md` §5.1 (Console Features & UI Mockup)
- **Requirement**: "Appointment Sidebar: Displays customer contact info, active appointment details, status, and quick action buttons (*Reschedule*, *Cancel*, *Reassign Agent*)."

## Root Cause Analysis
In `serviceBot/static/index.html` (lines 990-996) and `serviceBot/static/app.js` (lines 2263-2272), `loadSMSMessages()` populates `sms-context-details` with text details (Customer, Phone, Appointment ID, Service, Time, Agent), but renders zero action buttons.

## Steps to Reproduce
1. Navigate to `http://127.0.0.1:8000/portal/#sms-inbox`.
2. Select any active conversation thread.
3. Observe the right-hand **Appointment Context** sidebar.
4. Note that quick action buttons (*Reschedule*, *Cancel*, *Reassign Agent*) are missing.

## Expected Behavior
- Render functional action buttons (*Reschedule*, *Cancel Appointment*, *Reassign Agent*) in `sms-context-details`.
- Clicking *Reschedule* or *Cancel* updates the appointment status and triggers relevant SMS notifications.
- Clicking *Reassign Agent* opens a dropdown to switch assigned staff agents.

## Proposed Remediation Checklist
- [ ] Add quick action buttons (*Reschedule*, *Cancel*, *Reassign Agent*) to `sms-context-details` in `app.js`.
- [ ] Connect button handlers to corresponding portal API endpoints (`POST /api/v1/portal/service-requests/{id}/status`, etc.).
- [ ] Add verification test for sidebar action execution.
