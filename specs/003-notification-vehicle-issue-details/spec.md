# Feature Specification: Vehicle Details and Issue Description in Customer and Agent Notifications

**Feature Branch**: `003-notification-vehicle-issue-details`

**Created**: 2026-10-08

**Status**: Specified

**Input**: User description: "1. In the message to the customer, can we include the issue and the car vehicle/asset details? 2. The message to the agent: Can we see the vehicle details and the issue details?"

## Clarifications

### Session 2026-10-08
- Q: How should the vehicle details and issue description be formatted in customer SMS and WhatsApp messages? → A: Structured labeled lines (`Vehicle: 2021 Toyota Camry`, `Issue: Squeaking front brakes`).
- Q: How should vehicle and issue details be formatted in agent follow-up and reminder messages (Attempts 2 and 3)? → A: Full multi-line alert block repeated on every follow-up attempt (including Customer, Vehicle, Service, Issue, Slot, and response instructions).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Vehicle and Issue Details in Customer Notifications and Reminders (Priority: P1)

As a customer receiving appointment confirmations and pre-appointment reminders, I want the messages to clearly state my vehicle/asset details (e.g., "2021 Toyota Camry") and the specific service issue or symptoms (e.g., "Squeaking front brakes"), so that I have complete confidence in what service is booked, know exactly which vehicle to bring in, and can spot any misunderstandings before arrival.

**Why this priority**: Directly addresses customer clarity and intake confidence. When customers book multiple vehicles or specific repairs, seeing both their vehicle and reported issue in the confirmation and reminder messages eliminates ambiguity and reduces unnecessary follow-up calls to the shop.

**Independent Test**: Can be tested independently by booking an appointment with vehicle and issue description provided, verifying that the customer confirmation SMS/WhatsApp and customer pre-appointment reminder messages contain both the vehicle string and the issue description.

**Acceptance Scenarios**:

1. **Given** a customer books an appointment for a "2021 Toyota Camry" with issue "Squeaking front brakes", **When** the booking confirmation message is dispatched, **Then** the message body includes `Vehicle: 2021 Toyota Camry` (or `🚘 Vehicle: 2021 Toyota Camry`) and `Issue: Squeaking front brakes` (or `🔧 Issue: Squeaking front brakes`).
2. **Given** an appointment has scheduled reminders, **When** the pre-appointment reminder (immediate, follow-up, or T-2 final reminder) is sent to the customer, **Then** the reminder message includes the vehicle details and the reported issue description.
3. **Given** an appointment is rescheduled, **When** the reschedule confirmation is dispatched to the customer, **Then** the message includes the updated slot, the vehicle details, and the issue description.
4. **Given** a customer appointment has no specific issue description provided (or "N/A"), **When** the customer message is composed, **Then** the issue line defaults cleanly to the primary service type or is gracefully omitted without leaving placeholder text like "Issue: N/A".

---

### User Story 2 - Vehicle and Issue Details in Agent Alerts and Confirmation Reminders (Priority: P1)

As an assigned service advisor or technician, I want all initial job assignment alerts, follow-up prompts, and pre-appointment reminders to include both the customer's vehicle/asset details and the reported issue description, so that I immediately understand what vehicle is arriving, what technical problem requires diagnosis, and can assess bay/part readiness before confirming or attending the appointment.

**Why this priority**: Technicians need operational context directly in the alert message without being forced to log into the web portal just to find out what car and problem they are confirming.

**Independent Test**: Can be tested independently by triggering an agent booking alert, intermediate confirmation reminder, or final urgent reminder, verifying that all agent SMS/WhatsApp messages include the vehicle details and issue description alongside the appointment ID and slot.

**Acceptance Scenarios**:

1. **Given** a new appointment is assigned to a technician, **When** the initial booking alert message is dispatched to the agent, **Then** the message displays the customer name, phone number, vehicle details, service type, time slot, and issue description with confirmation instructions (`Reply CONFIRM or DECLINE`).
2. **Given** an agent has not yet confirmed an appointment and an intermediate follow-up reminder triggers, **When** the follow-up reminder is dispatched, **Then** the reminder includes the vehicle details and issue description (e.g., `Follow-up: Service request #42 (2021 Toyota Camry - Squeaking front brakes) is awaiting your confirmation...`).
3. **Given** an agent remains unconfirmed at T-2 hours, **When** the urgent reminder triggers, **Then** the urgent alert includes the vehicle and issue details so the technician has immediate context on the critical job.
4. **Given** an appointment is reassigned from Agent A to Agent B, **When** the assignment alert is sent to Agent B, **Then** Agent B sees the vehicle details, issue description, and previous agent name.

---

### User Story 3 - Graceful Fallbacks for Incomplete Asset or Issue Data (Priority: P2)

As a shop dispatcher, when a caller provides partial vehicle info (e.g. make and model only without year, or general service without a detailed issue description), I want the notification system to format the message cleanly without ugly "None", "null", or "N/A" artifacts, so that communications maintain professional formatting.

**Why this priority**: Prevents embarrassing message defects when callers do not know their vehicle year or report a generic maintenance request.

**Independent Test**: Can be tested by creating appointments with partial vehicle fields (e.g. year is null) and empty issue descriptions, verifying the resulting SMS messages omit empty tokens cleanly.

**Acceptance Scenarios**:

1. **Given** an appointment where vehicle year is null but make is "Honda" and model is "Civic", **When** messages are generated, **Then** the vehicle string formats as "Honda Civic" rather than "None Honda Civic".
2. **Given** an appointment where no vehicle was provided, **When** messages are generated, **Then** the vehicle line either says "Vehicle on file" or is gracefully omitted.
3. **Given** an appointment where issue description is empty or identical to the service type, **When** messages are generated, **Then** redundant duplicate lines are prevented.

---

## Edge Cases

- **Long Issue Descriptions**: What happens when a customer dictates a paragraph-long symptom list? The SMS should either keep the full text or truncate cleanly at 160 characters with ellipsis if SMS segment constraints apply, preserving readability.
- **Multiple Consolidated Issues**: When multiple issues are combined (e.g. from consolidation), all issues should be formatted cleanly (e.g., `Combined Issues: ...` or comma-separated).
- **Vehicle Asset Mapping**: When an asset is linked via `vehicle_id` vs passed directly in intake `details["vehicle"]`, the router must resolve the vehicle string consistently.
- **Opt-Out & Quiet Hours**: Adding vehicle and issue fields must not bypass TCPA opt-out checks or quiet hours queuing logic.

---

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST include vehicle details (Year Make Model) in all customer appointment SMS and WhatsApp messages (booking, reschedule, and pre-appointment reminders).
- **FR-002**: System MUST include the issue description in all customer appointment SMS and WhatsApp messages (booking, reschedule, and pre-appointment reminders).
- **FR-003**: System MUST include vehicle details and issue description in all staff agent SMS and WhatsApp messages, including initial assignment alerts, follow-up confirmation reminders, and urgent pre-appointment reminders.
- **FR-004**: System MUST ensure `fetch_appointment_customer_details` in `sms_reminders.py` queries and returns `issue_description` alongside vehicle and customer details.
- **FR-005**: System MUST format vehicle details cleanly when partial information exists, omitting `None` or `N/A` placeholders.
- **FR-006**: System MUST format issue descriptions cleanly, omitting the line or providing a sensible default when the caller provided no additional symptoms beyond the service name.
- **FR-007**: System MUST preserve parity across all notification channels (SMS, WhatsApp, and email).

### Key Entities

- **Customer Notification**: Outbound message dispatched to the customer containing appointment date/time, advisor, vehicle, service type, and issue description.
- **Agent Notification / Reminder**: Outbound dispatch to the assigned technician containing customer contact info, vehicle details, service type, issue description, slot, and confirmation response instructions.
- **Vehicle / Asset**: Customer asset defined by Year, Make, Model, License Plate, and VIN.
- **Service Request**: Core record containing `service_type`, `issue_description`, `booking_time`, `vehicle_id`, and `staff_agent_id`.

---

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of customer booking, rescheduling, and reminder messages display the vehicle details and reported issue description when available.
- **SC-002**: 100% of agent assignment alerts, follow-up reminders, and urgent confirmation SMS messages display the vehicle details and reported issue description.
- **SC-003**: Zero customer or agent messages contain raw "None", "null", or "N/A" strings in vehicle or issue fields.
- **SC-004**: Automated test suite achieves 100% contract coverage across customer and agent notification templates with zero regressions in existing tests.

---

## Assumptions

- Standard SMS segments (160 GSM-7 or 70 UCS-2 characters per segment) allow multi-part delivery via Twilio, so adding 1-2 lines for vehicle and issue details remains well within standard carrier limits.
- Technicians and customers find structured emoji tags (e.g. `🚘 Vehicle: ...`, `🔧 Issue: ...`) clear and legible on modern smartphones.
- `service_requests.issue_description` is the canonical source of truth for the customer's reported symptoms.
