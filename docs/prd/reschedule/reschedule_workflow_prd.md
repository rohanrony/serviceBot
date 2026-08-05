# Product Requirement Document (PRD): Reschedule Workflow with Availability Checking & Customer Consent Verification

**Document Version:** 1.0  
**Status:** In Review / Proposed  
**Target Subsystem:** Admin Web Portal (`serviceBot/static/app.js`, `portal.py`), Database (`queries.py`, `models.py`), AI Voice Agent (`telephony.py`, `system_prompt.txt`), SMS & Notification Engine (`sms_router.py`, `outbox_worker.py`)  
**Location:** `docs/prd/reschedule/reschedule_workflow_prd.md`

---

## 1. Executive Summary & Problem Statement

### 1.1 Background & Problem Statement
Currently, rescheduling an appointment occurs across two primary channels:
1. **Admin / Support Portal (Manual / Staff Call)**: Customer calls or visits the business directly requesting an appointment reschedule. Support staff edits the service request in the Admin Web Portal.
2. **AI Voice Telephony (Automated Voice Call)**: Customer calls the AI agent asking to reschedule an existing service request.

While basic backend slot reassignment exists, the current workflow lacks two critical production guarantees:
- **Missing Proactive Slot Availability Checking**: Support agents in the Web Portal edit modal manually pick dates/times without visual confirmation of available slots or real-time calendar validation before submitting.
- **Missing Explicit Customer Consent Verification**: Changes to appointment times can be saved without verifying or recording whether the customer explicitly authorized the date/time change. This leaves the business vulnerable to accidental reschedules, scheduling conflicts, customer dissatisfaction, and lack of auditability.

### 1.2 Proposed Solution
Implement an end-to-end **Reschedule Workflow with Slot Availability Checking & Customer Consent Verification**:
1. **Interactive Slot Availability Checker**:
   - Web Portal UI modal dynamically fetches and renders available time slots for target dates based on agent Google Calendar availability.
   - API endpoints (`GET /api/v1/portal/available-slots`) provide real-time free/busy slot queries.
2. **Mandatory Customer Consent Check & Audit Trail**:
   - Portal UI enforces a required confirmation toggle/checkbox: `[x] Customer consent sought and obtained for rescheduling`. Submitting a reschedule without checking consent is blocked.
   - DB Schema & API updates record `customer_consent_obtained` (Boolean) and timestamp/actor in the `service_requests` audit log (`service_request_audit_log`).
   - Voice AI agent prompts strictly require explicit verbal confirmation from the customer before executing `reschedule_appointment`.
3. **Automated Notification & Reminder Alignment**:
   - Dispatches `RESCHEDULED` or `RESCHEDULED_REASSIGNED` notifications via Twilio SMS and Email.
   - Automatically cancels outdated SMS reminders and schedules new 24h & 2h reminders for the updated appointment slot.

---

## 2. Target Personas & User Journeys

### 2.1 Target Personas
- **Support / Front-Desk Staff (e.g., Sarah)**: Receives incoming phone calls or walk-ins. Needs a quick, error-free way to verify available slots and reschedule appointments with customer consent logged.
- **Customer (e.g., David)**: Calls the shop or AI voice agent to reschedule. Expects clear slot choices, explicit confirmation of consent, and immediate SMS summary of the new time.
- **Shop Manager (e.g., Mike)**: Reviews audit logs to verify staff compliance with customer consent policies and ensures zero double-bookings or unconfirmed calendar changes.

### 2.2 User Stories & Acceptance Criteria

#### User Story 1: Staff Portal Reschedule with Consent & Slot Check
> **As a** Support Staff member editing a customer service request in the web portal,  
> **I want** to see live available slots for the selected date and be required to confirm customer consent before saving,  
> **So that** I do not double-book staff or reschedule appointments without customer permission.
* **AC 1.1**: Opening the Edit Service Request modal for an existing appointment displays a "Check Available Slots" button / dynamic slot picker.
* **AC 1.2**: Choosing a date queries `GET /api/v1/portal/available-slots?date=YYYY-MM-DD` and presents valid 60-min slots based on staff calendar availability.
* **AC 1.3**: When the date/time is modified, a required checkbox appears: `[ ] Customer consent sought and obtained for rescheduling`. The "Save Request" button remains disabled until checked.
* **AC 1.4**: Submitting the form writes `customer_consent_obtained = true` and logs audit entry: `"Appointment rescheduled to YYYY-MM-DD HH:MM. Customer consent verified by [Staff Member]"`.

#### User Story 2: AI Voice Call Inbound Rescheduling
> **As a** customer calling the AI agent to reschedule an appointment,  
> **I want** the AI to offer valid available slots and explicitly confirm my agreement before updating the booking,  
> **So that** my appointment is changed accurately with my full consent.
* **AC 2.1**: AI Voice Agent identifies existing booking using `get_customer_appointments(phone)`.
* **AC 2.2**: AI queries `check_availability(new_datetime)` and offers available options if requested slot is taken.
* **AC 2.3**: AI explicitly asks for customer confirmation: *"Just to confirm, you would like to move your appointment to Friday, Aug 14th at 10:00 AM, correct?"*
* **AC 2.4**: Upon receiving verbal consent ("Yes", "That works", etc.), AI invokes `reschedule_appointment(appointment_id, new_datetime, customer_consent=True)`.

#### User Story 3: Multi-Channel Notifications & SMS Reminder Rescheduling
> **As a** customer whose appointment was rescheduled,  
> **I want** to receive an updated SMS confirmation and have my reminders automatically adjusted,  
> **So that** I don't receive reminders for the old slot or miss my new appointment.
* **AC 3.1**: Twilio SMS client dispatches `RESCHEDULED` SMS to customer: *"Hi David, your appointment has been rescheduled to Aug 14, 2026 at 10:00 AM. Reply CANCEL to cancel anytime."*
* **AC 3.2**: Existing scheduled reminders for the old date in `sms_reminders` are set to `CANCELLED`.
* **AC 3.3**: New reminders (`REMINDER_24H`, `REMINDER_2H`) are scheduled relative to the new datetime.

---

## 3. System Architecture & Component Impact

```
+-----------------------------------------------------------------------------------+
|                                  USER INTERFACES                                  |
|  +-------------------------------------+   +-----------------------------------+  |
|  |   Admin Web Portal Modal (app.js)   |   |    ElevenLabs AI Voice Agent      |  |
|  | - Live Slot Availability Selector   |   | - System Prompt Consent Logic     |  |
|  | - Customer Consent Checkbox         |   | - Verbal Confirmation Step        |  |
|  +----------------------------------+--+   +-----------------+-----------------+  |
+-------------------------------------|------------------------|--------------------+
                                      |                        |
                                      v                        v
+-----------------------------------------------------------------------------------+
|                                   API GATEWAY                                     |
|  GET /api/v1/portal/available-slots?date=YYYY-MM-DD                              |
|  PUT /api/v1/portal/service-requests/{id} (payload: customer_consent_obtained)   |
|  POST /api/v1/telephony/tools (tool_name: reschedule_appointment)                 |
+-------------------------------------+---------------------------------------------+
                                      |
                                      v
+-----------------------------------------------------------------------------------+
|                              BUSINESS LOGIC & SERVICE LAYER                       |
|  - reschedule_appointment(id, new_datetime, customer_consent_obtained=True)       |
|  - check_availability(new_datetime, duration_minutes)                             |
|  - cancel_and_reschedule_sms_reminders(id, new_datetime)                         |
|  - TwilioSMSClient.send_sms(RESCHEDULED / RESCHEDULED_REASSIGNED)                 |
|  - Audit Log Logger (service_request_audit_log)                                   |
+-------------------------------------+---------------------------------------------+
                                      |
                                      v
+-----------------------------------------------------------------------------------+
|                              PERSISTENCE & INTEGRATIONS                           |
|  - PostgreSQL / SQLite (service_requests, service_request_audit_log, sms_reminders)|
|  - Google Calendar Sync (is_agent_free, create_agent_calendar_event)             |
+-----------------------------------------------------------------------------------+
```

---

## 4. Detailed Data Schema & API Specs

### 4.1 Database Schema Extensions
1. **`service_requests` table**:
   - Add column: `last_rescheduled_at TIMESTAMP NULL`
   - Add column: `customer_consent_obtained BOOLEAN DEFAULT FALSE`

2. **`service_request_audit_log` table**:
   - Add structured notes / action details: `"RESCHEDULE: old_time -> new_time | customer_consent: TRUE | triggered_by: portal_user/voice_agent"`

### 4.2 API Endpoint Specs

#### Endpoint 1: Available Slots Query
`GET /api/v1/portal/available-slots`
- **Query Params**: `date` (YYYY-MM-DD), `service_type` (optional), `duration_minutes` (optional, default 60)
- **Response**:
```json
{
  "date": "2026-08-10",
  "available_slots": [
    {"start_time": "2026-08-10 09:00:00", "end_time": "2026-08-10 10:00:00", "available_agents_count": 2},
    {"start_time": "2026-08-10 10:30:00", "end_time": "2026-08-10 11:30:00", "available_agents_count": 1},
    {"start_time": "2026-08-10 14:00:00", "end_time": "2026-08-10 15:00:00", "available_agents_count": 3}
  ]
}
```

#### Endpoint 2: Edit / Reschedule Service Request
`PUT /api/v1/portal/service-requests/{id}`
- **Request Body Payload**:
```json
{
  "issue_description": "Windshield repair for 2021 BMW X3",
  "booking_time": "2026-08-10 10:30:00",
  "customer_consent_obtained": true,
  "vehicle_details": {
    "make": "Kia",
    "model": "Forte",
    "year": 2018,
    "vin": ""
  }
}
```
- **Validation Rules**:
  - If `booking_time` is modified and differs from existing `booking_time`, `customer_consent_obtained` MUST be `true`. If `false`, API returns HTTP `400 Bad Request` ("Customer consent is required when rescheduling an appointment").
  - System invokes slot availability check. If no agents are available at `booking_time`, returns HTTP `409 Conflict` ("Requested slot 2026-08-10 10:30:00 is unavailable").

---

## 5. Edge Case & Failure Mode Matrix (10-Point Checklist)

| # | Trigger / Scenario | Potential Risk | Mitigation / Fallback Strategy |
|---|---|---|---|
| 1 | **Network / API Timeout (Google Calendar)** | Slow response or timeout during live slot check | Fall back to DB appointment check (`service_requests` booked slots) and log warning. |
| 2 | **Race Condition / Concurrent Reschedule** | Two staff members or caller + staff pick same slot simultaneously | Enforce DB transaction lock during `reschedule_appointment`. Second caller gets slot conflict error with immediate alternative suggestions. |
| 3 | **Bad / Ambiguous Time Input** | Caller says "next Tuesday at 2" without specifying AM/PM or date | Voice agent clarifies date/time explicitly before invoking availability check; UI uses strict ISO datetime picker. |
| 4 | **Interrupted Call / Dropped Call** | Call drops after AI checks slot but before asking consent | No database state change occurs until consent is confirmed and `reschedule_appointment` tool completes. |
| 5 | **Outside Operating Hours** | Customer requests slot at 8:00 PM or Sunday | System rejects slot validation immediately with clear message: *"Workhours are Monday-Friday 7 AM - 6 PM"*. |
| 6 | **Unauthorized Staff Reschedule** | Staff reschedules without asking customer consent | UI disables Save button until consent box is checked; audit log captures staff ID and timestamp for accountability. |
| 7 | **Duplicate SMS / Reminders** | Reminders sent for both old and new times | Transactionally cancel pending `REMINDER_24H` and `REMINDER_2H` rows in DB before creating new reminder jobs. |
| 8 | **Assigned Agent Unavailable at New Time** | Original agent is busy at target time | Automatic agent reassignment to Candidate #2 if free; compound `RESCHEDULED_REASSIGNED` event triggered. |
| 9 | **DB Migration / Existing Records** | Existing requests missing consent flags | Migration sets default `customer_consent_obtained = NULL` for legacy records, enforced `NOT NULL` for future reschedules. |
| 10 | **Telemetry & Audit Visibility** | Unclear why an appointment was moved | Audit log records `from_time`, `to_time`, `customer_consent_obtained`, `actor`, and `channel` (voice/portal). |

---

## 6. Implementation & Rollout Plan

### Phase 1: Core Backend & API Validation
1. Update `reschedule_appointment` query to accept `customer_consent_obtained` parameter and update audit log.
2. Implement `GET /api/v1/portal/available-slots` endpoint in `portal.py`.
3. Add consent validation to `PUT /api/v1/portal/service-requests/{id}`.

### Phase 2: Web Portal UI Enhancements
1. Update Edit Service Request modal in `app.js`:
   - Add dynamic slot checking dropdown/picker.
   - Add mandatory `[ ] Customer consent sought and obtained` checkbox.
   - Wire validation to enable/disable Save Request button.
2. Add quick reschedule slot checker to Live Inbox context sidebar.

### Phase 3: AI Voice Agent Prompt & Tool Update
1. Update ElevenLabs tool parameters for `reschedule_appointment` to require verbal consent.
2. Update `system_prompt.txt` instructions for the voice agent.

### Phase 4: Automated Testing & Verification
1. Unit tests for `available_slots` endpoint and `reschedule_appointment` consent checks.
2. Integration tests for SMS reminder cancellation/rescheduling.
3. Portal UI modal verification.
