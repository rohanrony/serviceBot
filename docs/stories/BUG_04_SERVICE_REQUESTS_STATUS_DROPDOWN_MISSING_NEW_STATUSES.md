# Bug 04: Service Requests Status Dropdown Missing Confirmed & Cancelled By Customer Options

## Bug Description
As an Admin or Support Agent updating a service request status on the Dashboard, I cannot set the status to `confirmed` or `cancelled_by_customer` because those options are missing from the frontend status dropdown menu.

## Specification Reference
- **Specification**: `docs/specs/human_handoff_specification.md` §3.5 & `docs/specs/sms_system_specification.md` §2.3
- **Requirement**: "Expand `service_requests` table status CHECK constraint to include `confirmed` and `cancelled_by_customer` in addition to existing values (`pending`, `in_progress`, `completed`, `cancelled`, `rescheduled`)."

## Root Cause Analysis
In `serviceBot/static/app.js` (lines 427-434), the status select dropdown options generated in `renderServiceRequests()` are hardcoded:
```javascript
const statusSelectHtml = `
  <select class="status-select-badge ${statusBadgeClass}" data-id="${req.id}">
    <option value="pending" ${currentStatus === 'pending' ? 'selected' : ''}>pending</option>
    <option value="in_progress" ${currentStatus === 'in_progress' ? 'selected' : ''}>in progress</option>
    <option value="completed" ${currentStatus === 'completed' || currentStatus === 'done' ? 'selected' : ''}>done</option>
    <option value="rescheduled" ${currentStatus === 'rescheduled' ? 'selected' : ''}>rescheduled</option>
    <option value="cancelled" ${currentStatus === 'cancelled' ? 'selected' : ''}>cancelled</option>
  </select>
`;
```
`confirmed` and `cancelled_by_customer` options are absent from the `<select>` element.

## Steps to Reproduce
1. Navigate to `http://127.0.0.1:8000/portal/#dashboard`.
2. Click the status dropdown on any Service Request row.
3. Observe that `confirmed` and `cancelled_by_customer` are not listed.

## Expected Behavior
- Include `confirmed` and `cancelled_by_customer` as selectable options in the status dropdown.
- Apply appropriate badge styles (e.g. green for `confirmed`, red/purple for `cancelled_by_customer`).

## Proposed Remediation Checklist
- [ ] Add `confirmed` and `cancelled_by_customer` `<option>` tags to `statusSelectHtml` in `app.js`.
- [ ] Update badge style mapping for `confirmed` and `cancelled_by_customer`.
- [ ] Add filter option in Service Requests status filter dropdown for `confirmed` and `cancelled_by_customer`.
