# Research: Booking Confirmation Guard & Customer Appointment History Context

**Feature**: `001-booking-confirmation-history`
**Date**: 2026-09-29

## Decision 1: Two-Layer Booking Defense (Prompt Deferral + Backend Session Deduplication)

### Context
In previous calls, when a caller said "10:00 AM" and subsequently changed their mind to "10:30 AM", the AI assistant invoked the booking tool twice, generating two separate reservations on Google Calendar and in PostgreSQL.

### Decision
Implement a two-layer defense architecture:
1. **Conversational Prompt Layer**: Rachel is instructed to NEVER invoke `create_service_request` or `book_appointment` mid-conversation until all 4 intake details, rate quote, start and expected end times are communicated and the caller gives explicit verbal confirmation.
2. **Backend Call-Session Deduplication Layer**: In `/api/v1/voice/tools`, track active appointment creation per call session (keyed by `call_sid`, `conversation_id`, or `(customer_id, phone)` within an active 15-minute call window). If a booking request arrives when an appointment was already created in that session:
   - Instead of inserting a new row and creating a second calendar event, the backend automatically updates/reschedules the existing booking's `booking_time` and modifies the calendar event.
   - If the caller was modifying time, the response explicitly acknowledges: *"Updated existing booking from 10:00 AM to 10:30 AM."*

### Alternatives Considered
- **Pure Prompt Deferral (Rejected)**: Relies entirely on LLM adhering to negative constraints ("DO NOT call tool until..."). Conversational models occasionally trigger tools prematurely when users say "Sounds good for 10am". A backend safety net is strictly required to guarantee zero duplicate calendar events.
- **Silent Backend Deduplication (Rejected)**: Overwriting silently without informing the agent leaves the agent uncertain whether the old slot was canceled or if two slots exist.

---

## Decision 2: Returning Customer Context & Greeting Protocol

### Context
When a returning customer calls in from a registered number, Rachel historically lacked immediate context about their upcoming appointments, vehicle, and previous issue descriptions.

### Decision
1. **Inbound Context Enrichment (`/api/v1/telephony/inbound`)**:
   - Query customer by phone number, retrieving customer name, primary vehicle, and all upcoming appointments (including `appointment_datetime`, `service_type`, `issue_description`, and `duration_minutes`).
   - Pass rich context parameters via Twilio `<ConversationAgent>` parameters (`customer_name`, `upcoming_appointments_summary`, `recent_history_summary`, `caller_phone`).
2. **Conversational Greeting (User Choice Q2: Option B)**:
   - Rachel greets returning callers warmly by name: *"Hello [Customer Name], thanks for calling Davidson Car Care. How can I help you today?"*
   - Rachel avoids pre-empting the caller's reason for calling in the opening sentence.
   - As soon as the caller mentions their vehicle or reports an issue, Rachel acknowledges their existing appointment and car context: *"I see you already have an appointment scheduled for this Thursday at 10:00 AM for your Civic regarding brake inspection..."*

### Alternatives Considered
- **Proactive Opening Greeting (Q2: Option A - Rejected by User)**: Mentioning the appointment immediately in turn 1 can be jarring if the customer is calling about a different emergency or vehicle.
- **Query Only On-Demand (Rejected)**: Waiting for the agent to call `get_customer_appointments` introduces latency (filler phrase + API roundtrip) on every inbound call. Supplying context at call start ensures instant responsiveness.

---

## Decision 3: Consolidating New Issues into Existing Appointments (Slot Extension & Capacity)

### Context
A customer with an upcoming appointment for one issue (e.g. 45-min Oil Change) calls reporting a second issue for the same vehicle (e.g. Brake noise). Booking a separate appointment creates fragmented shop visits.

### Decision
1. **Opportunity Identification**: When the customer reports a new issue for a vehicle that has an upcoming appointment, Rachel asks if they would like to combine the new service into their existing visit.
2. **Capacity Verification & Duration Extension (User Choice Q1: Option A)**:
   - When combining services, calculate new total duration: `original_duration + new_service_duration`.
   - Call `check_availability` or query calendar around the existing appointment time to verify if the technician/shop has contiguous availability to extend the slot.
   - If contiguous space is available, update the appointment record: append to `issue_description`, update `duration_minutes`, and expand the Google Calendar event end time.
   - If contiguous space is NOT available, explain the schedule limitation to the caller and offer:
     a) Moving the entire consolidated appointment to a different slot that can fit the larger duration.
     b) Booking a separate visit for the second issue.
3. **Start & End Time Disclosure (User Choice Q1 Addition)**:
   - Whenever Rachel quotes or confirms an appointment, she states both the **start time** and the **expected end time/duration window** (e.g., *"We have you scheduled from 10:00 AM to approximately 11:30 AM"*).
   - Rachel explicitly adds the disclosure: *"We are booking for this period, but please note it is likely to extend depending on our diagnostic and service findings."*

### Alternatives Considered
- **Fixed Slot with Overflow Notes (Q1: Option B - Rejected)**: Cramming 2+ hours of work into a 45-minute calendar block causes severe technician schedule delays and cascade overruns.
- **Separate Appointments by Default (Rejected)**: Inconvenient for customers who prefer a single drop-off.

---

## Decision 4: Query Layer & Schema Enhancements

### Context
`get_customer_appointments` in `serviceBot/db/queries.py` currently selects:
`sr.id, sr.booking_time AS appointment_datetime, sr.service_type, sr.status, v.year, v.make, v.model`
It completely excludes `sr.issue_description` and `sr.duration_minutes`!

### Decision
1. **Update `get_customer_appointments`**:
   - Add `sr.issue_description` and `sr.duration_minutes` to the query.
   - Format results cleanly in JSON for tool consumption.
2. **Add `get_customer_service_history`**:
   - Query recent completed or in-progress service requests and callbacks (last 90 days) for the customer, including issue notes and timestamps.
3. **Add `consolidate_appointment_service`**:
   - Updates an existing appointment by appending the new issue description, adding duration minutes, and updating calendar event length.
