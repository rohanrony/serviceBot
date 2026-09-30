# Phase 0 Research: Technical Decisions & Architectural Foundations

**Feature**: [002-appointment-reminder-escalation](file:///Users/rohanroy/Coding/voiceService/specs/002-appointment-reminder-escalation/spec.md)  
**Date**: 2026-09-30  
**Status**: Completed  

---

## 1. 4-Hour Minimum Planning Horizon Restriction

### Decision
Enforce the 4-hour lead time buffer at the core booking validation layer (`serviceBot/services/booking.py`), exposed consistently to both the AI Telephony Voice Agent (`serviceBot/api/telephony.py`) and the Web Staff Portal (`serviceBot/api/portal.py`).

### Rationale
- **Centralized Enforcement**: Placing the rule in `serviceBot/services/booking.py` (`validate_appointment_lead_time`) prevents code duplication and ensures neither callers speaking to Rachel nor staff booking via the portal can bypass the planning restriction.
- **Configurable Default**: Store `min_booking_buffer_hours = 4` in `config.json` with dynamic fallback in code.
- **Friendly Voice Guidance**: When a caller requests an invalid slot (e.g., asking for 10:00 AM at 8:00 AM), the AI assistant politely informs the caller: *"We require at least 4 hours advance notice to prepare technician bays and parts. The earliest available slot today is [Earliest Slot $\ge$ Current Time + 4h]."*

### Alternatives Considered
- *Enforcing only in prompt text*: Vulnerable to LLM hallucination and prompt drift. Rejected in favor of programmatic validation.
- *Hardcoding 4 hours in database queries*: Too rigid; would prevent admin adjustment for shop holidays or emergency diagnostic bays.

---

## 2. Two-Factor Horizon-Adaptive Confirmation Cutoff Algorithm

### Decision
Calculate the agent confirmation cutoff deadline at booking time using a two-factor formula:
$$T_{\text{cutoff}} = \min\Big( T_{\text{booked}} \oplus_{\text{BH}} \text{AcceptanceSLA}(H_{\text{lead}}), \quad T_{\text{appt}} - \text{final\_reminder\_hours} \Big)$$
where $\oplus_{\text{BH}}$ accumulates time strictly during shop operating business hours (`business_hours_start` to `business_hours_end` and `business_days`).

### Rationale
- **Operational Reality**: Naive $T - 2\text{ hours}$ works only for same-day bookings. For bookings made days or weeks in advance, finding out at $T - 2\text{h}$ that a technician is unavailable causes chaotic last-minute scrambles.
- **Assignment Acceptance vs. Pre-Visit Reminder**: Separates the **Technician Acceptance Window** (must accept within 4 business hours of booking) from the **Pre-Appointment Attendance Check** (courtesy reminder 24h and 2h prior).
- **Business Hours Calendar Math**: If an appointment is booked at 5:00 PM for tomorrow at 1:00 PM:
  - From 5:00 PM to 6:00 PM = 1 business hour on Day 1.
  - Overnight (6:00 PM to 8:00 AM) = 0 business hours (clock pauses).
  - From 8:00 AM to 10:00 AM = 2 business hours on Day 2.
  - Total 3 business hours elapsed = 10:00 AM deadline. Escalation alerts only fire when dispatchers and technicians are on site.
- **Morning Grace Protection**: For early morning slots (e.g. 8:30 AM appointment when shop opens at 8:00 AM), $T_{\text{cutoff}} = \min(8:00\text{ AM} + 30\text{m}, 8:30\text{ AM} - 30\text{m}) = \mathbf{8:00\text{ AM} - 8:30\text{ AM}}$, preventing false alarms before doors open.

### Alternatives Considered
- *Wall-clock countdown without business hours*: Would trigger SMS alerts to technicians and supervisors at 2:00 AM, causing burnout and waking staff. Rejected.
- *Single static deadline for all appointments*: Ignored differences between same-day bookings and advance bookings. Rejected.

---

## 3. Multi-Attempt Notification & Delivery Retry Architecture

### Decision
Implement a structured 3-attempt notification state machine recorded in a dedicated table `sms_reminders` with retry counters and backoff intervals:
1. **Attempt 1**: Dispatched immediately upon booking creation (Customer booking confirmation + Agent assignment request).
2. **Attempt 2**: Intermediate reminder during active business hours (scheduled midway through the active horizon SLA).
3. **Attempt 3**: Final confirmation prompt at $T_{\text{cutoff}}$. If unconfirmed after Attempt 3 $\rightarrow$ escalate to supervisor.
4. **Transport Retry Logic**: If Twilio returns a delivery error, retry up to 3 times with exponential backoff (+1m, +5m, +15m) before marking `DELIVERY_FAILED` and escalating.

### Rationale
- Reuses the existing `sms_reminders` table and background worker thread (`start_reminder_polling_worker`), extending the schema with `attempt_number`, `attempt_kind`, and `retry_count`.
- Background worker uses `SELECT ... FOR UPDATE SKIP LOCKED` to prevent concurrent worker race conditions on Render.

### Alternatives Considered
- *Celery / Redis Queue*: Adds heavy infrastructure dependencies (Redis container, worker processes). Not justified when Postgres row locking (`SKIP LOCKED`) and Python background threads already operate reliably in Render.

---

## 4. Inbound Agent SMS Confirmation & Decline Routing

### Decision
Extend `serviceBot/services/sms_classifier.py` and `serviceBot/api/telephony.py` to identify inbound messages from registered `staff_agents` phone numbers and route them to an **Agent Action Handler**:
- Keywords `CONFIRM`, `C`, `ACCEPT`, `YES` $\rightarrow$ Transition the agent's pending service request to `confirmed`, clear pending escalation timers, and return a receipt SMS.
- Keywords `DECLINE`, `UNAVAILABLE`, `NO`, `CANNOT` $\rightarrow$ Transition appointment to `escalated` with reason `AGENT_DECLINED`, bypass remaining wait times, and alert the supervisor immediately.
- Free text from agents $\rightarrow$ Forwarded to the internal notes / portal dashboard.

### Rationale
- Technicians on the shop floor need ultra-low friction confirmation. Replying "C" or "CONFIRM" via SMS takes 2 seconds and does not require opening a web browser or logging into an app.
- Phone number lookup against `staff_agents.phone_number` disambiguates customer replies from technician replies cleanly.

### Alternatives Considered
- *Portal-only confirmation*: Technicians under cars or in transit do not have laptops open; requiring portal login leads to frequent missed deadlines.
- *Voice call verification*: Too disruptive and costly compared to SMS.

---

## 5. Supervisor Escalation Queue & Single-Click Reassignment

### Decision
1. **Escalation Notification**: When an escalation condition occurs (`TIMEOUT_NO_RESPONSE`, `AGENT_DECLINED`, `DELIVERY_FAILED`, `UNASSIGNED_ON_CREATION`), dispatch an urgent SMS to `supervisor_alert_phone` containing the customer name, scheduled time, service issue, unconfirmed agent name, and direct portal link.
2. **Dashboard Visibility**: Add an `escalated` status filter and prominent red alert badge on the Dispatcher Portal (`serviceBot/static/app.js` and `serviceBot/api/portal.py`).
3. **Candidate Ranking**: Re-use `get_available_agents_for_request(request_id)` to rank replacement technicians who have no conflicting appointments during that slot, matching service skills, and sorted by daily workload.
4. **One-Click Reassignment**: Supervisor clicks "Reassign to [Agent]" $\rightarrow$ Rebinds booking, immediately sends high-priority SMS to the new technician (with a 15-minute response window), informs previous technician, and updates Google Calendar.

### Rationale
- Keeps the human dispatcher in control by default while automating the tedious work of checking schedules and sending notifications.
- Supports an optional config flag `auto_reassign_on_escalation = true` if the shop prefers fully autonomous reassignment.

---

## 6. Race Conditions & Late Confirmation Resolution

### Decision
- **Late Confirmation Before Reassignment**: If the assigned technician confirms after the cutoff has passed, but *before* the supervisor reassigns the ticket, the confirmation is **accepted**. The appointment status transitions to `confirmed`, and the supervisor alert is automatically resolved.
- **Late Confirmation After Reassignment**: If the technician confirms *after* the supervisor has already reassigned the ticket to another agent, the late confirmation is **rejected**. The system sends an SMS to the former technician: *"Appointment #[ID] has already been reassigned to [New Agent Name]. No action required."*

### Rationale
- Deterministic state transitions protected by row-level locking (`SELECT FOR UPDATE`) prevent split-brain technician assignments.
