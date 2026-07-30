# SMS Notification System Specification

## 1. Overview & Objectives

The SMS Notification System provides automated, event-driven SMS communications via Twilio for appointment lifecycle events (bookings, reschedules, reassignments, cancellations, and pre-appointment reminders).

The system ensures all relevant parties (customers, current service agents, and former service agents) are informed promptly while minimizing unnecessary noise (e.g., suppressing admin SMS by default and suppressing customer notifications for agent reassignments).

---

## 2. Notification Rules & Matrix

### 2.1 General Rules
1. **Customer Re-assignment Isolation**: Customers are **NOT** notified when an appointment is reassigned to a different service agent unless the date/time also changes.
2. **Admin SMS Control**: Admins do not receive SMS notifications by default; admin alerts can be enabled selectively per event in the system settings.
3. **Previous Agent Unassignment**: When an appointment is reassigned from Agent A to Agent B, Agent A receives an explicit unassignment notice to clear their schedule.
4. **Opt-In Guard**: Every outbound SMS dispatch must check `customer.sms_opt_in` (or `agent.phone_number` presence) before calling the Twilio API. Opted-out customers receive zero SMS.

### 2.2 Event Notification Matrix

| Event | Customer SMS | Service Agent SMS | Previous Agent SMS | Admin SMS (Default) |
| :--- | :---: | :---: | :---: | :---: |
| **Initial Booking** | ✅ Enabled | ✅ Enabled | N/A | ❌ Disabled |
| **Rescheduled (Date/Time)** | ✅ Enabled | ✅ Enabled | N/A | ❌ Disabled |
| **Reassigned Agent Only** | ❌ Disabled | ✅ Enabled | ✅ Enabled | ❌ Disabled |
| **Rescheduled + Reassigned** | ✅ Enabled | ✅ Enabled | ✅ Enabled | ❌ Disabled |
| **Cancelled by Customer** | ✅ Enabled | ✅ Enabled | N/A | ❌ Disabled |
| **Cancelled by System/Admin** | ✅ Enabled | ✅ Enabled | N/A | ❌ Disabled |
| **24-Hour Pre-Appointment Reminder** | ✅ Enabled | ❌ Disabled | N/A | ❌ Disabled |
| **2-Hour Pre-Appointment Reminder** | ✅ Enabled | ✅ Enabled | N/A | ❌ Disabled |

> **Compound Event — Rescheduled + Reassigned**: When an appointment's date/time AND assigned agent both change in a single operation, the system treats this as a compound event. The customer is notified (because time changed), the new agent receives the assignment, and the previous agent receives the unassignment notice.

### 2.3 Schema Prerequisites
The following schema changes are required for SMS notifications to function:
* **`staff_agents` table**: Add `phone_number VARCHAR(50) DEFAULT NULL` column (E.164 format, e.g., `+15550192831`). Without this column, no "Service Agent SMS" notifications can be dispatched.
* **`customers` table**: Add `sms_opt_in BOOLEAN DEFAULT TRUE` column. Required for TCPA compliance opt-out enforcement.
* **`service_requests` table**: Expand status CHECK constraint to include `confirmed` and `cancelled_by_customer`.

---

## 3. Pre-Appointment Reminder Engine

### 3.1 Timing & Rules
* **Customer Reminders**: Scheduled for **24 hours** and **2 hours** prior to appointment start time.
* **Service Agent Reminders**: Scheduled for **2 hours** prior to appointment start time.
* Reminders are automatically cancelled if the appointment is cancelled prior to the scheduled trigger time.
* Reminders are automatically cancelled and rescheduled if the appointment is rescheduled to a new time.

### 3.2 Reminder Storage & Execution
Reminders are stored in the `sms_reminders` table (not in-memory) to survive server restarts:

| Column | Type | Description |
| :--- | :--- | :--- |
| `id` | SERIAL PK | Auto-increment ID |
| `appointment_id` | INTEGER FK | References `service_requests(id)` |
| `recipient_type` | VARCHAR(20) | `customer` or `agent` |
| `recipient_phone` | VARCHAR(50) | Target phone number |
| `reminder_type` | VARCHAR(10) | `24h` or `2h` |
| `scheduled_at` | TIMESTAMP | When the reminder should fire |
| `status` | VARCHAR(20) | `PENDING`, `SENT`, `CANCELLED` |
| `created_at` | TIMESTAMP | Record creation time |

A background polling worker checks `WHERE status = 'PENDING' AND scheduled_at <= NOW()` every **30 seconds** and dispatches eligible reminders through the Twilio client.

---

## 4. Quiet Hours & Timezone Management

### 4.1 Behavior
* Non-urgent notification messages generated during Quiet Hours (e.g., an appointment rescheduled for next week generated at 11:30 PM) are delayed and queued until Quiet Hours end (e.g., 8:00 AM).
* **Urgent Override Rule**: If an appointment change occurs within **12 hours** of the appointment start time, the SMS is dispatched immediately regardless of Quiet Hours.

### 4.2 Timezone Policy
* **MVP**: Quiet hours are evaluated against the **business timezone** (`America/New_York`), consistent with the existing `is_within_business_hours()` logic in the codebase. All recipients share the same quiet hours window.
* **Future**: Per-recipient timezone support can be added by introducing a `timezone` column on `customers` and `staff_agents`.

### 4.3 Configuration Parameters
* **Quiet Hours Enabled**: Boolean (Default: `true`)
* **Quiet Start Time**: Time (Default: `21:00` / 9:00 PM)
* **Quiet End Time**: Time (Default: `08:00` / 8:00 AM)
* **Urgent Threshold**: Hours (Default: `12` hours)

### 4.4 Boundary Rule
Quiet hours boundaries are **inclusive-exclusive**: a message generated at exactly `21:00:00` is considered **inside** quiet hours (queued). A message generated at exactly `08:00:00` is considered **outside** quiet hours (dispatched immediately).

### 4.5 Queue Release Worker
A background worker polls for queued SMS records where `scheduled_send_at <= NOW()` and `status = 'QUEUED'`, then pushes them to the Twilio dispatch pipeline. This worker runs alongside the reminder polling worker with the same **30-second** polling interval.

---

## 5. Delivery Status & Failure Management

### 5.1 Integration with Existing Outbox Pattern
The SMS dispatch system reuses the existing `outbox_notifications` transactional outbox pattern (see `serviceBot/services/outbox_worker.py`). New SMS event types are added to the outbox:
* `sms_booking_notification`
* `sms_reschedule_notification`
* `sms_reassignment_notification`
* `sms_cancellation_notification`
* `sms_reminder`

The existing outbox worker's `_dispatch_outbox_event()` handler is extended to route these event types to the `TwilioSMSClient`.

### 5.2 Retry Strategy (SMS-Specific Backoff)
SMS dispatches use a **custom backoff schedule** distinct from the general outbox retry:
* Attempt 1: Immediate
* Attempt 2: +30 seconds
* Attempt 3: +2 minutes
* Attempt 4: +10 minutes

**Hard failure detection**: Twilio error codes `30003` (Unreachable), `30005` (Unknown destination), `30006` (Landline), and `21610` (Blacklisted) terminate the retry loop immediately and mark the record as `FAILED`.

Retry attempts are strictly internal and hidden from the standard dashboard view.

### 5.3 SMS Delivery Log Table
Per-message delivery tracking is stored in the `sms_log` table:

| Column | Type | Description |
| :--- | :--- | :--- |
| `id` | SERIAL PK | Auto-increment ID |
| `appointment_id` | INTEGER FK | References `service_requests(id)` |
| `recipient_type` | VARCHAR(20) | `customer`, `agent`, `previous_agent`, `admin` |
| `recipient_phone` | VARCHAR(50) | Target phone number |
| `template_type` | VARCHAR(50) | `booking_confirmation`, `reschedule`, `cancellation`, `reminder_24h`, `reminder_2h`, `reassignment`, `unassignment` |
| `twilio_message_sid` | VARCHAR(50) | Twilio message SID (nullable until dispatched) |
| `status` | VARCHAR(30) | `PENDING`, `QUEUED`, `SENT`, `DELIVERED`, `FAILED`, `SKIPPED_OPT_OUT`, `SKIPPED_NOT_WHITELISTED` |
| `error_code` | VARCHAR(20) | Twilio error code on failure (nullable) |
| `error_message` | TEXT | Human-readable error description (nullable) |
| `retry_count` | INTEGER | Number of retry attempts (default: 0) |
| `scheduled_send_at` | TIMESTAMP | For quiet hours queuing (nullable) |
| `sent_at` | TIMESTAMP | Actual send time (nullable) |
| `created_at` | TIMESTAMP | Record creation time |

### 5.4 Eventual Failure & UI Tracking
* If max retries are exhausted or Twilio reports a hard failure (e.g., invalid landline, blacklisted number), the SMS log status transitions to `FAILED`.
* An error status indicator (⚠️) is flagged on the Appointments Dashboard row.

#### Appointment Details Popup UI Specification
Clicking the **"Details"** button on any appointment opens a popup containing the SMS log:

```text
+-------------------------------------------------------------------------+
| Appointment Details (#APT-1082)                                     [X] |
+-------------------------------------------------------------------------+
| Customer: John Doe (+1 555-019-2831)                                    |
| Service Agent: Sarah Jenkins                                            |
| Date & Time: Oct 24, 2026 at 2:00 PM                                    |
| Status: Confirmed                                                       |
+-------------------------------------------------------------------------+
| SMS Delivery Logs                                                       |
|                                                                         |
|  [Customer SMS]                                                         |
|  - Booking Confirmation: Delivered (Oct 20, 10:15 AM)                   |
|  - 24h Reminder: Delivered (Oct 23, 2:00 PM)                            |
|  - 2h Reminder: FAILED ❌ (Oct 24, 12:00 PM)                             |
|    Reason: Unreachable Destination (Carrier blocked or number offline)   |
|    [ Retry SMS ]                                                        |
|                                                                         |
|  [Agent SMS]                                                            |
|  - New Job Alert: Delivered                                             |
|  - 2h Reminder: Delivered                                               |
+-------------------------------------------------------------------------+
```

---

## 6. Admin Configuration & Settings Page

The application includes an **SMS Configuration Settings Page** allowing administrators to customize notification behaviors dynamically:

1. **Notification Matrix Toggles**: Interactive checkbox matrix for each Event x Recipient role.
2. **Reminder Schedules**: Configurable timing inputs for Customer (24h/2h) and Agent (2h) reminders.
3. **Quiet Hours Panel**: Time pickers for Start/End times and urgent bypass threshold toggle.
4. **Environment Test Whitelist**: Text input array for whitelisted numbers during staging/testing without full A2P 10DLC registration.
5. **Support & Fallback Contact**: Field to set the corporate Support Phone Number used in automated responses.

### 6.1 Agent Onboarding & Twilio Verified Caller ID Flow (Test Environment)
* **Agent Onboarding Phone Field**: The Service Agent onboarding form in the admin portal includes a required `phone_number` input field (E.164 format, e.g., `+15550192831`).
* **Automated Twilio Verified Caller ID Integration**:
  * In `TEST` / `STAGING` environment mode, saving a new agent/customer phone number presents an **"Add to Twilio Verified Numbers"** button or automated trigger.
  * System calls Twilio REST API (`client.validation_requests.create(phone_number=..., friendly_name=...)`) to register the number as a Verified Caller ID for safe SMS testing.

### 6.2 Twilio Client Configuration
The `TwilioSMSClient` wrapper supports two dispatch modes:
* **Preferred**: Use `TWILIO_MESSAGING_SERVICE_SID` if configured (enables A2P 10DLC compliance, automatic number pool management).
* **Fallback**: Use `TWILIO_FROM_NUMBER` (individual sender number) if Messaging Service SID is not set.

The client reads from environment variables with the following priority:
```
TWILIO_MESSAGING_SERVICE_SID → messaging_service_sid param
TWILIO_FROM_NUMBER           → from_ param (fallback)
```

---

## 7. New Database Tables (DDL)

### 7.1 SMS Configuration Table
```sql
CREATE TABLE IF NOT EXISTS sms_config (
    id SERIAL PRIMARY KEY,
    quiet_hours_enabled BOOLEAN DEFAULT TRUE,
    quiet_start_time TIME DEFAULT '21:00',
    quiet_end_time TIME DEFAULT '08:00',
    urgent_threshold_hours INTEGER DEFAULT 12,
    support_phone_number VARCHAR(50) DEFAULT NULL,
    auto_responder_template TEXT DEFAULT 'Thank you! Our team has received your message. For urgent help, call {support_number}.',
    auto_responder_debounce_seconds INTEGER DEFAULT 60,
    environment VARCHAR(20) DEFAULT 'PRODUCTION',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 7.2 SMS Matrix Rules Table
```sql
CREATE TABLE IF NOT EXISTS sms_matrix_rules (
    id SERIAL PRIMARY KEY,
    event_type VARCHAR(50) NOT NULL,
    recipient_role VARCHAR(30) NOT NULL,
    enabled BOOLEAN DEFAULT TRUE,
    UNIQUE(event_type, recipient_role)
);

-- Default seed: matches the notification matrix in §2.2
-- event_type values: BOOKING, RESCHEDULED, REASSIGNED, RESCHEDULED_REASSIGNED,
--                    CANCELLED_BY_CUSTOMER, CANCELLED_BY_ADMIN, REMINDER_24H, REMINDER_2H
-- recipient_role values: customer, agent, previous_agent, admin
```

### 7.3 SMS Whitelist Table
```sql
CREATE TABLE IF NOT EXISTS sms_whitelist (
    id SERIAL PRIMARY KEY,
    phone_number VARCHAR(50) NOT NULL UNIQUE,
    friendly_name VARCHAR(255) DEFAULT NULL,
    twilio_verified BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 7.4 SMS Log Table
See §5.3 for column definitions.

### 7.5 SMS Reminders Table
See §3.2 for column definitions.

### 7.6 SMS Conversations Table (Two-Way / Handoff)
```sql
CREATE TABLE IF NOT EXISTS sms_conversations (
    id SERIAL PRIMARY KEY,
    customer_phone VARCHAR(50) NOT NULL UNIQUE,
    state VARCHAR(30) DEFAULT 'AUTOMATED' CHECK (state IN ('AUTOMATED', 'HANDOFF_REQUIRED', 'IN_PROGRESS', 'RESOLVED')),
    last_auto_responder_at TIMESTAMP DEFAULT NULL,
    context_appointment_id INTEGER DEFAULT NULL REFERENCES service_requests(id) ON DELETE SET NULL,
    assigned_agent_id INTEGER DEFAULT NULL REFERENCES staff_agents(id) ON DELETE SET NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_sms_conversations_state ON sms_conversations(state);
```

### 7.7 SMS Messages Table (Inbound/Outbound Log for Live Inbox)
```sql
CREATE TABLE IF NOT EXISTS sms_messages (
    id SERIAL PRIMARY KEY,
    conversation_id INTEGER NOT NULL REFERENCES sms_conversations(id) ON DELETE CASCADE,
    direction VARCHAR(10) NOT NULL CHECK (direction IN ('inbound', 'outbound')),
    sender_type VARCHAR(20) NOT NULL CHECK (sender_type IN ('customer', 'system', 'agent')),
    sender_name VARCHAR(255) DEFAULT NULL,
    body TEXT NOT NULL,
    twilio_message_sid VARCHAR(50) DEFAULT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_sms_messages_conversation ON sms_messages(conversation_id);
```

---

## 8. Comprehensive Test Plan

### 8.1 Unit & Integration Test Suites

| Test ID | Test Category | Scenario / Inputs | Expected Output / Behavior |
| :--- | :--- | :--- | :--- |
| **UT-SMS-01** | Routing Matrix | Trigger `APPOINTMENT_REASSIGNED` (Agent A -> Agent B) | SMS generated for Agent B (New Job) and Agent A (Removal). Zero SMS generated for Customer. |
| **UT-SMS-02** | Routing Matrix | Trigger `APPOINTMENT_RESCHEDULED` | SMS generated for Customer and Assigned Agent. |
| **UT-SMS-03** | Admin Suppression | Trigger `APPOINTMENT_CREATED` with default settings | Customer & Agent receive SMS. Admin receives 0 SMS. |
| **UT-SMS-04** | Admin Override | Enable `Admin SMS` for `APPOINTMENT_CANCELLED` in config | Admin receives SMS notification when cancellation occurs. |
| **UT-SMS-05** | Reminder Timing | Create appointment 48 hours in advance | System schedules Customer 24h & 2h jobs and Agent 2h job in `sms_reminders` table. |
| **UT-SMS-06** | Reminder Cleanup | Cancel appointment 30 hours in advance | System updates scheduled 24h and 2h reminder records to `CANCELLED` status. |
| **UT-SMS-07** | Quiet Hours (Non-Urgent)| Reschedule appointment (7 days away) at 11:30 PM | SMS is queued in DB with `scheduled_send_at` set to 8:00 AM next day. |
| **UT-SMS-08** | Quiet Hours (Urgent) | Reschedule appointment starting in 3 hours at 11:30 PM | Urgent override triggers; SMS dispatches immediately despite quiet hours. |
| **UT-SMS-09** | Test Whitelist | Dispatch SMS in `STAGING` to non-whitelisted number | Dispatch blocked by whitelist validator; log created with status `SKIPPED_NOT_WHITELISTED`. |
| **UT-SMS-10** | Compound Event | Reschedule + reassign appointment in single operation | Customer receives reschedule SMS. New Agent receives assignment SMS. Previous Agent receives unassignment SMS. |
| **UT-SMS-11** | Quiet Hours Boundary | Generate SMS at exactly `21:00:00` | SMS is queued (21:00 is inside quiet hours). |
| **UT-SMS-12** | Opt-In Guard | Trigger booking notification for opted-out customer | SMS dispatch skipped. Log status set to `SKIPPED_OPT_OUT`. |
| **UT-SMS-13** | Agent No Phone | Trigger agent SMS when agent has NULL phone_number | SMS dispatch skipped gracefully. Log entry created with appropriate skip status. |
| **UT-SMS-14** | Reminder Reschedule | Reschedule appointment after reminders are already scheduled | Old reminder records set to `CANCELLED`. New reminders created for updated time. |

### 8.2 Twilio Mock & Delivery Failure Tests

| Test ID | Test Category | Scenario / Inputs | Expected Output / Behavior |
| :--- | :--- | :--- | :--- |
| **FT-SMS-01** | Retry Engine | Twilio API returns transient HTTP 500 error | System retries with backoff (+30s, +2m, +10m). Retries hidden from standard UI. |
| **FT-SMS-02** | Hard Failure | Twilio returns Error 30003 (Unreachable destination) | Retry loop terminates immediately. Record marked `FAILED`. Error icon displayed on dashboard. |
| **FT-SMS-03** | Manual Retry | Click "Retry SMS" button in Appointment Details Popup | System queues immediate re-dispatch attempt and updates log status. |
| **FT-SMS-04** | Messaging Service Fallback | `TWILIO_MESSAGING_SERVICE_SID` not set | Client falls back to `TWILIO_FROM_NUMBER`. SMS dispatches normally. |

### 8.3 End-to-End (E2E) Acceptance Testing

1. **Full Appointment Lifecycle E2E**:
   * Create Appointment → Verify Customer & Agent receive initial SMS.
   * Reassign to Agent B → Verify Agent A receives unassignment notice, Agent B receives assignment SMS, Customer receives no SMS.
   * Reschedule Appointment → Verify Customer & Agent B receive updated time SMS.
   * Trigger 2h Reminder → Verify Customer & Agent B receive 2h reminder.
   * Cancel Appointment → Verify Customer & Agent B receive cancellation confirmation.

2. **Server Restart Resilience**:
   * Schedule reminders for an appointment → restart server → verify reminders still fire at correct time (they are DB-persisted, not in-memory).
