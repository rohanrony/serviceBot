# Bug 02: Staff Member Form Missing Phone Field & Twilio Verified Caller ID Trigger

## Bug Description
As an Admin onboarding a new Service Agent, I cannot specify the agent's phone number or verify it with Twilio directly from the Staff Calendars section, preventing automated agent SMS dispatches.

## Specification Reference
- **Specification**: `docs/specs/sms_system_specification.md` §6.1 (Agent Onboarding & Twilio Verified Caller ID Flow)
- **Requirement**: "The Service Agent onboarding form in the admin portal includes a required `phone_number` input field (E.164 format, e.g., `+15550192831`). In `TEST` / `STAGING` environment mode, saving a new agent/customer phone number presents an **Add to Twilio Verified Numbers** button or automated trigger."

## Root Cause Analysis
- In `serviceBot/static/index.html` (lines 580-605), `add-agent-form` only contains input fields for Name, Role, and Email (`new-agent-name`, `new-agent-role`, `new-agent-email`).
- In `serviceBot/static/app.js` (lines 108-111, 1070-1110), the staff agent creation payload does not accept or submit a `phone_number` field.
- No "Add to Twilio Verified Numbers" button or caller ID trigger exists in the agent onboarding / profile card in Staff Calendars.

## Steps to Reproduce
1. Navigate to `http://127.0.0.1:8000/portal/#staff`.
2. Locate the **Add Staff Member** form.
3. Observe that there is no field to enter a phone number or trigger Twilio caller ID verification.

## Expected Behavior
- Include a required **Phone Number** input field (`new-agent-phone`) in `add-agent-form`.
- Save `phone_number` on `staff_agents` DB records via API.
- Provide an **Add to Twilio Verified Numbers** button or auto-trigger when creating/editing an agent profile in TEST/STAGING modes.

## Proposed Remediation Checklist
- [ ] Add `Phone Number` input field to `add-agent-form` in `index.html`.
- [ ] Update `app.js` to collect `phone_number` and post it to `POST /api/v1/portal/agents`.
- [ ] Add "Add to Twilio Verified Numbers" action button calling `POST /api/v1/portal/twilio/verify-caller-id`.
- [ ] Add unit test verifying agent phone creation and whitelisting trigger.
