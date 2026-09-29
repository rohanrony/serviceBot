# Feature Specification: Booking Confirmation Guard & Customer Appointment History Context

**Feature Branch**: `001-booking-confirmation-history`

**Created**: 2026-09-29

**Status**: Draft

**Input**: User description: "1. In the last call, there were two appointments made even though the user asked only for one. The user was initially asking for 10 am, then he changed the time to 10:30 or something. The agent booked two slots. That should not be done because the user can change his mind later. Let's wait until everything is confirmed, and then send the appointment. 2. even though the same customer, with the same mobile number and on the same card, had a different issue on a new call, the agent did not notice that (there was an issue noted like before). It's good to check if there are any upcoming appointments, or maybe it's good to pick from the history. Just to make the conversation a little better and contextual, it is good to get the history a bit, or at least upcoming appointments or very relevant ones. That helps the conversation, especially if the customer is wanting to book another appointment for the same car. Then both the appointments could be combined to become a bigger slot or something. What do we do about this?"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Single Confirmed Appointment Booking with Deferred Execution (Priority: P1)

As a customer calling to schedule service, I want the assistant to confirm my chosen date, time, vehicle, issue, and estimated price before actually creating a booking, so that if I change my mind during the call (e.g., shifting from 10:00 AM to 10:30 AM), only one final appointment slot is reserved on the calendar.

**Why this priority**: Prevents ghost bookings, calendar clutter, double-booked technician slots, and customer confusion caused by premature tool execution mid-conversation.

**Independent Test**: Can be tested independently by simulating a caller who requests 10:00 AM, then shifts to 10:30 AM before finishing the call. Verifies that exactly one appointment record is created in the database and only one calendar event is scheduled.

**Acceptance Scenarios**:

1. **Given** a caller is discussing appointment options and expresses interest in 10:00 AM, **When** the caller has not yet heard the complete intake summary and verbally confirmed, **Then** the system does not reserve a calendar slot or persist an appointment.
2. **Given** a caller initially chooses 10:00 AM and later changes their preferred time to 10:30 AM during the same call, **When** the caller finalizes and confirms the 10:30 AM time, **Then** only the 10:30 AM appointment is booked, with zero duplicate bookings created for 10:00 AM.
3. **Given** an appointment was already submitted during an active call session, **When** the caller requests a revised time before hanging up, **Then** the system reschedules or updates the existing appointment rather than creating a second overlapping appointment.
4. **Given** an appointment time is being communicated or confirmed with the caller, **When** the assistant presents the booking schedule, **Then** the assistant states both the start time and expected end time/duration, noting clearly that the visit is booked for this period but is likely to extend depending on diagnostic and service findings.

---

### User Story 2 - Contextual Recognition of Upcoming Appointments & History (Priority: P2)

As a returning customer calling from a known phone number, I want the assistant to be aware of my vehicle, past reported issues, and any upcoming scheduled appointments, so that I don't have to repeat information and the conversation feels personal, informed, and coherent.

**Why this priority**: Drastically improves caller experience, eliminates repetitive questioning, and enables the assistant to address the caller's actual context immediately.

**Independent Test**: Can be tested independently by initiating an inbound call or simulating a conversation for a phone number with an existing upcoming appointment and past service record, verifying that the assistant acknowledges the scheduled visit and previously noted issue.

**Acceptance Scenarios**:

1. **Given** a customer with an active upcoming appointment calls from their registered phone number, **When** the call begins, **Then** the assistant has access to the customer's name, vehicle details, upcoming appointment time, and the specific issue previously recorded.
2. **Given** a returning customer calls about an issue, **When** the customer asks about or references their vehicle, **Then** the assistant references their scheduled appointment or recent visit context without forcing the caller to re-state all vehicle and contact information.
3. **Given** a caller provides a phone number matching an account with an existing appointment, **When** the assistant retrieves customer appointment data, **Then** the returned details include the specific issue description, scheduled service, and booked datetime.

---

### User Story 3 - Consolidating New Issues into Existing Appointments (Priority: P3)

As a returning customer who already has an upcoming appointment for my vehicle, when I call with an additional or different issue for that same car, I want the assistant to offer to add the new issue to my existing appointment and adjust the appointment duration, so that I can have both issues handled in a single, coordinated service visit.

**Why this priority**: Increases shop efficiency, prevents fragmented disjointed bookings for the same vehicle, and provides a seamless customer experience.

**Independent Test**: Can be tested independently by having a customer with an upcoming 45-minute oil change appointment report a brake squeak for the same vehicle, verifying the system offers to combine the issues and updates the appointment scope and duration accordingly.

**Acceptance Scenarios**:

1. **Given** a customer has an upcoming appointment for an Oil Change on Friday at 10:00 AM for their 2021 Toyota Camry, **When** the customer calls reporting a battery or brake issue for the same vehicle, **Then** the assistant recognizes the upcoming appointment and asks if they would like to combine the new issue into the Friday 10:00 AM visit.
2. **Given** the customer agrees to combine the new issue into their existing appointment, **When** the update is finalized, **Then** the existing appointment record is updated with the combined issue description and increased service duration without creating a separate conflicting appointment slot.
3. **Given** the combined service duration requires more time than the remaining calendar availability permits at the current slot, **When** the assistant evaluates the schedule, **Then** the assistant informs the customer and offers either to reschedule to a slot with sufficient contiguous time or book a separate visit.

---

### Edge Cases

- **Frequent Time Changes**: Caller changes their preferred time multiple times in a single call (e.g., 10:00 AM -> 10:30 AM -> 2:00 PM). The system must only book once the final choice is verbally confirmed.
- **Call Disconnect Before Confirmation**: Caller disconnects mid-call after discussing times but before giving explicit verbal confirmation. No appointment must be created, and the tentative time must not remain blocked on the calendar.
- **Multiple Vehicles on One Customer Profile**: Caller has two different vehicles registered under the same phone number (e.g., a Honda Civic and a Ford F-150). If the caller calls about an issue on the Ford, the system must not assume it combines with an upcoming appointment that was booked for the Honda without verifying the vehicle.
- **Full Calendar for Combined Duration**: Combining two issues doubles the required technician time, but the technician has another appointment directly after the original slot. The system must verify contiguous slot availability before confirming the extended duration.
- **Concurrent Inbound Calls / Race Conditions**: Two calls or simultaneous webhook events arrive for the same customer phone number; transactional locking must prevent concurrent duplicate bookings.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST enforce deferred appointment booking, executing calendar reservations only after explicit caller confirmation of the date, time, service scope, and estimated pricing/duration.
- **FR-002**: System MUST track active booking operations within a call session to ensure that multiple time modifications during one call update/reschedule the tentative booking rather than creating duplicate appointments.
- **FR-003**: System MUST provide caller context—including customer name, vehicle details, upcoming appointment datetimes, service types, and issue descriptions—to the AI voice assistant at session start and during profile retrieval.
- **FR-004**: System MUST include the detailed issue description and estimated duration in all customer appointment lookup tool responses (`get_customer_appointments`).
- **FR-005**: AI Voice Assistant MUST check for existing upcoming appointments when a returning caller reports a service issue.
- **FR-006**: When a returning caller with an upcoming appointment reports a new issue for the same vehicle, the system MUST offer the option to consolidate the new issue into the existing appointment.
- **FR-007**: When an appointment is consolidated with an additional issue, the system MUST update the existing service request's issue description and adjust the total scheduled duration.
- **FR-008**: System MUST check contiguous slot capacity before extending an existing appointment; if capacity permits, extend the duration on the current appointment slot. If blocked, offer to move the combined visit to an open larger slot or book a separate slot.
- **FR-009**: When booking an appointment or communicating an appointment time to a customer, the assistant MUST state both the start time and the expected end time/duration, informing the customer that the shop is booking for that window but the visit is likely to extend depending on service and diagnostic findings.
- **FR-010**: Assistant MUST greet returning callers warmly by name (e.g., *"Hello John, thanks for calling Davidson Car Care. How can I help you today?"*), and reference their upcoming appointment and vehicle context once the caller describes their issue or vehicle, avoiding pre-empting the caller's intent in the opening greeting.
- **FR-011**: System MUST implement two-layer booking defense: strictly defer executing the booking tool until the end of the call after all details, rate quotes, start/expected end times, and explicit caller confirmation are completed; and if an appointment was already created during the active call session, the assistant MUST explicitly confirm the time change (e.g., *"I'll update that from 10:00 AM to 10:30 AM for you"*) and update/reschedule the existing booking in place rather than creating a duplicate slot.

### Key Entities *(include if feature involves data)*

- **Customer**: Represents the caller, identified by 10-digit phone number and name. Associated with one or more vehicles and service requests.
- **Vehicle**: Represents an asset owned by a customer (Year, Make, Model).
- **Service Request / Appointment**: Represents a scheduled service reservation or callback intake. Contains booking type (`appointment` or `callback`), scheduled datetime, duration in minutes, primary service type, detailed issue description, status (`pending`, `confirmed`, `completed`, `cancelled`), and associated Google Calendar event ID.
- **Call Session Context**: Transient or session-scoped state linking a call to any tentative or created service request ID within that specific call, preventing duplicate creation across turn adjustments.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Zero duplicate appointment bookings created when a caller modifies their desired time slot during a phone call.
- **SC-002**: 100% of returning callers with upcoming appointments have their existing appointment details and prior issue descriptions made available to the assistant at the start of the interaction.
- **SC-003**: Inbound calls where a customer reports an additional issue for an existing appointment can consolidate issues in a single visit without requiring human staff manual intervention.
- **SC-004**: Customer intake and booking accuracy improves, reducing conflicting or ghost calendar entries by at least 95%.
- **SC-005**: Average conversation turn count for returning customers booking a follow-up or additional service is reduced by at least 20% due to retained context.

## Assumptions

- Returning callers typically call from the same mobile phone number previously registered; if calling from a different number, identity verification by phone number lookup remains available via tool call.
- Existing Google Calendar integration supports modifying event duration and descriptions for existing events.
- Single appointments can accommodate multiple service issues when the shop's technician schedule has adequate continuous capacity.
- The voice platform (ElevenLabs / Twilio) allows passing dynamic session variables or retrieving customer context via synchronous tool call at the onset of intake.
