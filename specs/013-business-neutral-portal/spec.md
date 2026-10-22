# Feature Specification: Generalize Business Configuration and Simplify Portal

**Feature Branch**: `feat/business-neutral-portal-20261021`

**Created**: 2026-10-21

**Status**: Ready for Implementation

**Input**: User description: "Generalize business configuration and simplify the portal under specs/013-business-neutral-portal"

---

## User Scenarios & Testing

### User Story 1 - Canonical Business Settings & Prompt Regeneration (Priority: P1)

As a business owner or administrator,
I want to manage my business address, map link, business timezone, and support helpline directly in Business Settings,
So that business configuration is centralized, canonical, and accurately reflected in voice agent greetings and customer notifications.

**Why this priority**: Centralizes business identity and removes duplicate or conflicting configuration across tabs, making Business settings the single canonical source of truth for business contact details.

**Independent Test**: Can be tested by loading Business Settings, saving address, maps URL, timezone, and support phone, confirming the prompt regeneration modal, and verifying that SMS config and agent prompts reflect the updated values.

**Acceptance Scenarios**:
1. **Given** existing business settings and SMS configuration, **When** Business Settings is loaded, **Then** Business Address, Google Maps Link, Business Time Zone, and Support Helpline are pre-populated with existing values, and these inputs are absent from the Notifications tab.
2. **Given** a change to Business Settings, **When** the user clicks "Save Business Settings", **Then** a confirmation dialog opens explaining that current AI greeting and instructions will be replaced.
3. **Given** the confirmation dialog is open, **When** the user clicks Cancel, **Then** no API writes or voice provider synchronization calls occur.
4. **Given** the confirmation dialog is open, **When** the user clicks Confirm, **Then** settings are persisted to configuration, prompt and greeting are regenerated, and voice provider synchronization status is reported separately (a failed/unavailable sync remains visible without claiming the live agent was updated).
5. **Given** a stored support helpline, **When** the support number is viewed or updated via legacy SMS configuration interfaces, **Then** both interfaces resolve and update the same effective canonical value.

---

### User Story 2 - Generic Intake Field Classification & Asset Details (Priority: P1)

As an administrator of any service business (automotive, salon, consulting, clinic, field service, etc.),
I want to define repeatable, generic intake fields with stable keys, detail types, business labels, value types, and requirements,
So that customer intake, agent speech, portal booking, summaries, and notifications handle arbitrary assets without fabricating vehicle records.

**Why this priority**: Eliminates hardcoded automotive assumptions, enabling full business neutrality while maintaining backwards compatibility with historical data.

**Independent Test**: Configure custom fields with repeated detail types (e.g. two serial numbers), verify prompt phrasing for required vs. optional fields, submit service requests with intake data, and verify no dummy vehicle row is created.

**Acceptance Scenarios**:
1. **Given** business intake configuration, **When** fields are defined, **Then** each field has a stable key, detail type (General detail, Asset type, Brand, Model, or Serial number), business label, value type (text or number; identifiers strictly text), and required flag.
2. **Given** multiple fields with the same detail type (e.g., two Serial number fields), **When** configured, **Then** they have distinct stable keys, distinct labels, and independent required/optional settings.
3. **Given** existing system configurations with legacy vehicle fields, **When** loaded in the form, **Then** existing text/number fields are preserved and legacy automotive fields (Make as Brand, Model as Model, Year as General detail [numeric]) are exposed as editable generic equivalents.
4. **Given** configured required and optional intake fields, **When** the voice agent instructions are built, **Then** the prompt explicitly instructs the agent to ask for missing required fields using their configured labels, but prohibited from soliciting optional fields (while recording volunteered values).
5. **Given** a service request created with generic intake data, **When** saved, **Then** intake values are stored in `intake_data` JSONB and no vehicle record is fabricated in the `vehicles` table.

---

### User Story 3 - Date-First Booking & Availability Slot Selection (Priority: P1)

As a portal operator scheduling service requests,
I want to pick a date, check calendar availability, and choose from returned time slots in the business timezone,
So that manual date/time input errors are prevented and appointment scheduling remains synchronized with staff availability.

**Why this priority**: Eliminates double-bookings and race conditions by enforcing a date-first, availability-verified workflow with explicit customer consent for reschedules.

**Independent Test**: Open create/edit service request modal, select a date, click Check Availability, select an available slot, verify display in business timezone, and verify customer consent is required on time modification.

**Acceptance Scenarios**:
1. **Given** the service request create or edit form, **When** viewed, **Then** manual datetime-local input is replaced with a visible date picker, Check Availability button, and returned-slot selector.
2. **Given** returned slots, **When** displayed, **Then** all slot start and end times are presented in the configured business timezone.
3. **Given** an unscheduled service request or an edit retaining its original schedule, **When** loaded, **Then** unscheduled requests remain unscheduled and existing schedules are preserved without forced slot reselection.
4. **Given** an active slot selection or lookup, **When** scheduling inputs (date, duration, service, or agent) change, **Then** stale slot choices are cleared, and loading, retry, empty-day, and unavailable-calendar states are cleanly displayed.
5. **Given** an existing appointment being edited, **When** the appointment time is changed, **Then** customer consent is required before saving, and reservations are revalidated against the booking service to reject conflicts atomically.

---

### User Story 4 - Service Catalogue Redesign & Business-Wide Asset Details (Priority: P2)

As a business manager maintaining catalogue offerings,
I want a clean, responsive service catalogue form with an Asset Details summary linked to Business Settings,
So that service definitions match the modern visual system and respect business-wide intake rules.

**Why this priority**: Modernizes catalogue management, removes obsolete automotive example seed buttons, and unifies intake requirements at the business level.

**Independent Test**: Load the catalogue page, verify the example seed button is absent, create and edit services using the redesigned forms, verify the Asset Details summary shows configured badges, and click the link to Business Settings.

**Acceptance Scenarios**:
1. **Given** the Services Catalog page, **When** viewed, **Then** the "Load Automotive Example Catalog" button is removed.
2. **Given** the Add Service form and Edit Service drawer, **When** viewed, **Then** both utilize consistent sectioning, clear spacing, accessible labels, and visible validation states.
3. **Given** the service forms, **When** inspected, **Then** Automotive Details checkbox is replaced with an Asset Details summary displaying configured intake fields with Required/Optional badges and a link to Business Settings.
4. **Given** pricing, duration, and assigned staff agents, **When** services are saved, **Then** their pricing ranges, durations, and agent assignment associations are preserved.

---

### User Story 5 - Portal Simplification: SMS Inbox, Admin Help, API Keys & Whitelist (Priority: P2)

As a portal user navigating the workspace,
I want uncluttered pages with simplified navigation,
So that irrelevant sidebars, obsolete whitelist tables, and internal configuration panes do not distract from operational tasks.

**Why this priority**: Streamlines user workflows across SMS Inbox, Admin Settings, Notifications, and Navigation ribbons.

**Independent Test**: View SMS Inbox (confirm full-width chat and absent context sidebar), Admin Config (confirm Connection Help hidden), Navigation Ribbon (confirm API Keys & Voice hidden and old links redirect to Business), and Notifications (confirm duplicate whitelist removed).

**Acceptance Scenarios**:
1. **Given** the SMS Inbox, **When** viewed, **Then** the Appointment Context sidebar and its actions are removed, and the conversation area expands into the full available width.
2. **Given** Admin Configuration, **When** viewed, **Then** the "Connection Help" card is hidden.
3. **Given** the portal navigation, **When** viewed, **Then** the "API Keys & Voice" pane and ribbon tab are hidden; opening `#config/voice-settings` falls back cleanly to Business settings without loading hidden controls.
4. **Given** the Notifications subtab, **When** viewed, **Then** the duplicate test phone whitelist section is removed, while staff, admin, and customer onboarding remain accessible on their respective pages.

---

### User Story 6 - Staff Validation for Email and Phone (Priority: P2)

As an administrator adding or updating staff members,
I want mandatory, valid email and phone numbers for new staff, while protecting against accidental field clearing on existing profiles,
So that communication channels (calendar invites, SMS, WhatsApp) are guaranteed for active staff.

**Why this priority**: Prevents broken staff notification dispatch caused by missing or empty contact information.

**Independent Test**: Submit "Add Staff Member" with missing or invalid email/phone (verify rejection in browser and API), edit existing staff with empty string (verify rejection), and edit name on an older incomplete profile (verify success).

**Acceptance Scenarios**:
1. **Given** the "Add Staff Member" form or API endpoint, **When** email or phone is missing, blank, or malformed, **Then** validation fails in both browser and API with a clear error.
2. **Given** an existing staff member, **When** an update attempts to explicitly clear email or phone to an empty string, **Then** the update is rejected with a 400 error.
3. **Given** an older incomplete staff profile in the database with NULL email or phone, **When** an unrelated field (e.g., name or role) is updated, **Then** the update succeeds without being blocked by legacy missing fields.

---

### User Story 7 - Message Acknowledgment with Configured Helpline (Priority: P3)

As a customer or staff agent sending an unrecognized or free-text message,
I want an immediate, accurate acknowledgment referencing the business support helpline,
So that urgent scheduling assistance is clearly directed without referring to an obsolete "dispatch" contact.

**Why this priority**: Eliminates confusing "contact dispatch" wording and provides the actual configured helpline number.

**Independent Test**: Send an unrecognized inbound message when support helpline is configured (assert message includes helpline), and when helpline is blank/empty (assert message is exactly "Message received.").

**Acceptance Scenarios**:
1. **Given** a configured support helpline (e.g. "+18005550199"), **When** an unrecognized message is received, **Then** the system replies: "Message received. For urgent scheduling assistance, please call +18005550199."
2. **Given** no support helpline is configured, **When** an unrecognized message is received, **Then** the system replies: "Message received." (with no placeholder or dummy number).
3. **Given** inbound messages, **When** received, **Then** sender classification, confirmation commands (CONFIRM, CANCEL), and rate debounce are preserved.

---

## Edge Cases

- **Concurrent booking slot reservation**: If two portal users select the same slot on the same staff agent simultaneously, the booking service atomic reservation rejects the second request and informs the user to recheck availability.
- **Legacy requests with historical intake fields**: If an intake field is renamed or deleted from Business Settings, older service requests retaining values under the old key remain readable in historical summaries.
- **Timezone boundary shifts**: When business timezone changes (e.g. from America/New_York to America/Los_Angeles), slot generation and date-first displays immediately convert and display times in the new timezone.
- **Provider synchronization outage**: If ElevenLabs or external telephony API returns 5xx or times out during Business Settings save, configuration and prompt changes remain safely saved locally, and the user receives a warning notice indicating settings saved but voice sync failed.
- **Malformed or blank support helpline**: Empty strings or whitespace in helpline configuration gracefully trigger the concise fallback acknowledgment: "Message received."

---

## Requirements

### Functional Requirements

- **FR-001**: Business Settings MUST be the canonical owner of Business Address, Google Maps URL, Business Time Zone, and Support Helpline.
- **FR-002**: Notifications tab MUST NOT display inputs for Business Address, Google Maps URL, Business Time Zone, or Support Helpline.
- **FR-003**: Saving Business Settings MUST prompt with a confirmation dialog explaining prompt/greeting replacement; Cancel MUST perform zero writes or API calls.
- **FR-004**: System MUST report configuration save status independently from voice provider synchronization status.
- **FR-005**: Intake field definitions MUST support a generic detail classification with stable key, detail type (General detail, Asset type, Brand, Model, Serial number), label, value type (text or number; identifiers text), and required flag. Repeated detail types MUST be permitted.
- **FR-006**: Existing text/number fields MUST be preserved and legacy automotive fields exposed as editable generic equivalents.
- **FR-007**: Generated AI prompt MUST instruct the voice agent to solicit missing required intake fields by label, but NOT solicit optional fields (recording volunteered values).
- **FR-008**: Generic service requests MUST store values in `intake_data` JSONB without creating dummy vehicle records in the database.
- **FR-009**: Service request forms MUST use a date-first workflow: visible date picker, Check Availability action, and returned-slot selector formatted in the business timezone.
- **FR-010**: Changing appointment time on an existing request MUST require customer consent and revalidate calendar availability before committing.
- **FR-011**: Service catalogue MUST remove the automotive example button and replace Automotive Details checkboxes with an Asset Details summary badge list and link to Business Settings.
- **FR-012**: SMS Inbox MUST remove the Appointment Context sidebar and expand the conversation column.
- **FR-013**: Admin Configuration MUST hide Connection Help.
- **FR-014**: API Keys & Voice navigation entry and pane MUST be hidden, falling back to Business Settings.
- **FR-015**: Notifications subtab MUST remove the duplicate phone whitelist section.
- **FR-016**: Staff member creation MUST require valid, nonblank email and phone numbers. Profile edits MUST reject explicit clearing while allowing edits on legacy incomplete records.
- **FR-017**: Unrecognized inbound message acknowledgment MUST reply with "Message received. For urgent scheduling assistance, please call {support helpline}." or "Message received." if unconfigured.

---

## Success Criteria

### Measurable Outcomes

- **SC-001**: 100% of the twelve requested business-neutral portal capabilities and simplifications are implemented and verified offline.
- **SC-002**: Zero schema migrations required; existing customer, vehicle, booking, and intake data remain fully preserved.
- **SC-003**: All automated test suites (`tests/` and `e2e/`) pass cleanly with 0 regressions and full contract coverage recorded in `test-coverage.yaml`.
- **SC-004**: Voice prompt generation reflects configured labels and required/optional distinctions accurately without hardcoded automotive terms when disabled.
