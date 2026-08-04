# Bug 01: SMS Delivery Logs & Appointment Details Modal Inaccessible from Dashboard

## Bug Description
As an Admin or Support Agent, I cannot access the SMS Delivery Logs or trigger a manual SMS retry for an appointment from the Service Requests table on the Dashboard because the "Details" button and failure status indicators (⚠️ / ❌) are missing from the table rows.

## Specification Reference
- **Specification**: `docs/specs/sms_system_specification.md` §5.4 (Eventual Failure & UI Tracking)
- **Requirement**: "An error status indicator (⚠️) is flagged on the Appointments Dashboard row. Clicking the **Details** button on any appointment opens a popup containing the SMS log."

## Root Cause Analysis
In `serviceBot/static/app.js`, `window.openSMSLogDrawer` (line 2323) and the drawer markup `sms-log-drawer` in `index.html` (line 1084) are implemented. However, the Service Requests table renderer (`renderServiceRequests` in `app.js`) does not include an "Actions" column or "Details" button, nor does it check for failed SMS logs to render error status badges. Consequently, the SMS delivery log drawer is never invoked from the UI.

## Steps to Reproduce
1. Navigate to `http://127.0.0.1:8000/portal/#dashboard`.
2. Inspect the **Service Requests** table.
3. Observe that there is no "Details" button or "Actions" column to view SMS logs for an appointment.

## Expected Behavior
- Add an **Actions** column to the Service Requests table with a **Details / SMS Log** button for each appointment.
- Display an error badge (⚠️ / ❌) on rows where SMS delivery has failed.
- Clicking **Details / SMS Log** opens the `sms-log-drawer` displaying the log entries and functional "Retry SMS" button.

## Proposed Remediation Checklist
- [ ] Add `Actions` header and column to `service-requests-table` in `index.html` and `app.js`.
- [ ] Render a **Details** button in `renderServiceRequests()` that calls `openSMSLogDrawer(req.id)`.
- [ ] Flag SMS failure indicators on table rows when status is `FAILED`.
- [ ] Add automated UI/API verification test.
