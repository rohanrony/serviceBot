# Feature Specification: Appointment Reminders, Dual Confirmation, Business-Hours Escalation & 4-Hour Booking Buffer

**Feature Branch**: `002-appointment-reminder-escalation`

**Created**: 2026-09-30

**Status**: Draft

**Input**: User description: "I want to discuss and plan a reminder logic. When an appointment is made, a reminder could be sent before the appointment time to both the customer and the agent at the same time. The appointment needs to be confirmed before time, and if the appointment is not confirmed, then there needs to be some way to confirm the appointment. It could be through SMS, or it could be through the portal. If the confirmation doesn't happen, there needs to be some sort of an escalation, maybe to change the agent or something. Two things here. Notification logic: We also need a total of three attempt retry logic. 1. Initial notification to be sent immediately, and the reminder could be T-2. 2. Let us restrict booking for 4 hours to give some planning. If the customer is calling at 8:00, do not allow the customer to book before 4 hours after the current time. That is 12:00 in this example. Escalation logic: The escalation logic also depends on the time at which the appointment was made. Let's say it was made at 5 pm. It's likely that the person is going to respond the next morning, so maybe business hours could be considered along with the booking horizon."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 4-Hour Minimum Planning Horizon Restriction (Priority: P1)

As a shop dispatcher and technician, I want all incoming appointment bookings to enforce a minimum 4-hour advance planning buffer from the time of booking (e.g., a caller at 8:00 AM cannot book earlier than 12:00 PM), so that the shop has predictable lead time to prepare parts, organize work bays, and coordinate technician assignments without sudden unmanageable arrivals.

**Why this priority**: Prevents immediate same-hour walk-in collisions, protects technician workflow predictability, and establishes a stable operational baseline for automated reminder and confirmation cycles.

**Independent Test**: Can be tested independently by attempting to book an appointment within 3 hours 59 minutes of current system time (via API or voice intake), verifying the system rejects the booking slot with an informative message, and confirming that slots at or beyond `current_time + 4 hours` are accepted.

**Acceptance Scenarios**:

1. **Given** current time is 8:00 AM, **When** a customer requests an appointment slot before 12:00 PM on the same day, **Then** the booking engine rejects the slot and presents available options starting at or after 12:00 PM.
2. **Given** current time is 4:30 PM and the shop closes at 6:00 PM, **When** a customer requests a same-day slot, **Then** the system recognizes that `4:30 PM + 4 hours` exceeds today's business hours and offers the earliest available slot on the next open business day.
3. **Given** an appointment booking request with a requested time $\ge$ 4 hours in advance, **When** the slot is checked against calendar availability, **Then** the reservation proceeds normally.

---

### User Story 2 - Immediate Initial Notification & 3-Attempt Confirmation Cadence (Priority: P1)

As a customer with a scheduled appointment and as an assigned staff agent, we both want an initial notification sent immediately upon booking, followed by structured confirmation prompts (up to 3 attempts total: Immediate upon booking, Intermediate follow-up, and T-2 Final Reminder) with automatic delivery retries, so that the customer has instant confirmation and the agent has clear prompts to confirm attendance before cutoff.

**Why this priority**: Guarantees immediate intake acknowledgment for the customer while ensuring the assigned technician receives persistent, non-intrusive opportunities to confirm readiness before escalation occurs.

**Independent Test**: Can be tested independently by booking an appointment for tomorrow afternoon, verifying that Attempt 1 is dispatched immediately to both parties, Attempt 2 is scheduled/sent as an intermediate follow-up if still unconfirmed, and Attempt 3 (final prompt) triggers at T-2 hours before appointment time.

**Acceptance Scenarios**:

1. **Given** a new appointment is booked, **When** the booking transaction commits, **Then** Attempt 1 notification is dispatched immediately to the customer (booking details) and the assigned agent (confirmation prompt).
2. **Given** the assigned agent has not confirmed after Attempt 1, **When** the intermediate prompt interval elapses during business hours, **Then** Attempt 2 is dispatched to the agent reminding them to confirm.
3. **Given** the assigned agent remains unconfirmed as the appointment approaches, **When** the time reaches T - 2 hours prior to the appointment start, **Then** Attempt 3 (final urgent reminder) is dispatched to the agent.
4. **Given** an SMS dispatch experiences a transient network or carrier failure, **When** delivery fails, **Then** the system automatically retries dispatch up to 3 times with exponential backoff before logging a failure.

---

### User Story 3 - Business-Hours Aware Escalation Logic (Priority: P2)

As a shop manager, when an appointment is booked late in the day (e.g., at 5:00 PM) for the next day, I want the escalation evaluation to pause during closed hours and resume at the start of the next business day, so that technicians are not expected to respond overnight and escalation alerts are only dispatched when supervisors and staff are on duty.

**Why this priority**: Eliminates false-positive nighttime escalation alarms, protects off-duty staff work-life boundaries, and aligns automated supervisor escalations with actual shop opening hours.

**Independent Test**: Can be tested independently by simulating a booking created at 5:00 PM for the following day at 12:00 PM, advancing simulated time through the night, verifying that no escalation alarms fire at 2:00 AM, and verifying that the morning response countdown commences at shop opening time (e.g., 7:00 AM / 8:00 AM).

**Acceptance Scenarios**:

1. **Given** an appointment is created at 5:00 PM for the following day at 12:00 PM, **When** the shop closes at 6:00 PM, **Then** the confirmation response clock pauses overnight.
2. **Given** the shop opens at 8:00 AM the next morning, **When** business hours begin, **Then** the response clock resumes, granting the agent their morning business-hours window to confirm.
3. **Given** an unconfirmed booking reaches its effective cutoff (T - 2 hours, or morning opening grace expiration), **When** the confirmation status is still unconfirmed, **Then** the appointment is escalated and an alert is delivered to the supervisor during business hours.
4. **Given** an appointment is booked on a Friday evening or weekend for Monday, **When** calculating escalation deadlines, **Then** weekend hours outside configured business days are excluded from elapsed response time.

---

### User Story 4 - Supervisor Escalation Queue & Single-Click Reassignment (Priority: P2)

As a shop dispatcher, when an assigned agent fails to confirm an appointment after the 3 notification attempts and past their horizon-adaptive business-hours cutoff (e.g., 4 business hours after booking for advance bookings, or T-2 hours for near-term bookings), I want the appointment flagged on the escalation dashboard with an urgent SMS alert, so that I can immediately reassign the appointment to an available technician or contact the customer.

**Why this priority**: Gives dispatchers immediate actionable control over at-risk bookings well in advance of customer arrival.

**Independent Test**: Can be tested independently by allowing an appointment to breach its horizon-adaptive cutoff (e.g. 4 business hours post-booking for an advance appointment), verifying the supervisor receives an urgent SMS with appointment details and unconfirmed agent name, and verifying the dispatcher can reassign to an available agent via the portal API/UI.

**Acceptance Scenarios**:

1. **Given** an assigned agent has not confirmed within their horizon-adaptive cutoff ($T_{\text{cutoff}}$) after 3 notification attempts, **When** the escalation monitor evaluates the queue, **Then** the appointment status updates to `escalated` and an urgent SMS alert is dispatched to the supervisor's phone.
2. **Given** an escalated appointment appears on the dispatcher portal, **When** the supervisor selects a replacement agent from the available agents list, **Then** the appointment is reassigned, the new agent receives an immediate high-priority confirmation SMS, and the previous agent is notified of the transfer.
3. **Given** an assigned agent explicitly replies with "DECLINE" or "UNAVAILABLE", **When** the message is processed, **Then** the system immediately bypasses remaining retry attempts and triggers instant supervisor escalation.

---

### User Story 5 - Portal Admin Configuration for Horizon & Timers (Priority: P3)

As a shop administrator, I want to configure the minimum booking lead time buffer (default: 4 hours), business hours boundaries, notification cadence timings, and supervisor alert contacts from the portal settings, so that shop management can customize rules without code modifications.

**Why this priority**: Enables shop managers to adjust lead times for holiday schedules, peak seasons, or different shop locations.

**Independent Test**: Can be tested independently by updating `min_booking_buffer_hours` from 4 to 3 via the portal config endpoint, and verifying that the booking validator enforces the new 3-hour minimum threshold.

**Acceptance Scenarios**:

1. **Given** an admin opens portal settings, **When** the admin modifies `min_booking_buffer_hours` (default: 4), `final_reminder_hours` (default: 2), or `supervisor_alert_phone`, **Then** the new values are saved and applied to all subsequent booking and reminder calculations.
2. **Given** shop business hours change in settings (e.g., opening at 7:30 AM instead of 8:00 AM), **When** the escalation scheduler runs, **Then** all overnight and morning cutoff calculations adapt to the new opening time.

---

### Edge Cases & Timing Matrices

- **Booking Horizon Collision (< 4 Hours)**:
  - Caller requests an appointment 2 hours from now. System rejects with clear explanation: *"We require at least 4 hours advance notice to prepare for your vehicle. The earliest time we can schedule you today is [Current Time + 4h]."*
- **Late Afternoon / Evening Bookings (e.g., Booked at 5:00 PM for Next Day)**:
  - Creation Time: 5:00 PM.
  - Appointment Time: Next day at 12:00 PM.
  - Attempt 1: Dispatched immediately at 5:00 PM (both customer and agent).
  - Overnight: Response clock pauses when business hours end (e.g. 6:00 PM).
  - Next Morning: Response clock resumes at shop opening (e.g. 8:00 AM).
  - Attempt 2: Dispatched at shop opening (8:00 AM) if agent hasn't confirmed yet.
  - Attempt 3 / Cutoff: Dispatched at 10:00 AM (T - 2 hours).
  - Escalation: Triggers at 10:00 AM if still unconfirmed.
- **Early Morning Appointments Booked Previous Evening (e.g., Booked at 5:00 PM for Next Day 8:30 AM or 9:00 AM)**:
  - Naive $T - 2\text{ hours}$ would fall at 6:30 AM or 7:00 AM (before the shop opens at 8:00 AM).
  - System applies the **Morning Opening Grace Rule**: $T_{\text{cutoff}} = \min(T_{\text{appt}} - 30\text{ min}, \text{Open} + 30\text{ min})$.
  - For a 9:00 AM appointment with an 8:00 AM shop opening: $T_{\text{cutoff}} = 8:30\text{ AM}$. The agent has 30 minutes from shop opening to confirm before escalation triggers.
- **Same-Day Minimum Horizon Bookings (e.g., Booked at 8:00 AM for 12:00 PM)**:
  - Creation Time: 8:00 AM.
  - Appointment Time: 12:00 PM (exactly 4 hours lead time).
  - Attempt 1: Dispatched immediately at 8:00 AM.
  - Attempt 2: Dispatched at 9:00 AM (1 hour post-booking) if unconfirmed.
  - Attempt 3 / Cutoff: Dispatched at 10:00 AM (T - 2 hours).
  - Escalation: Triggers at 10:00 AM if still unconfirmed.
- **Weekend & Non-Business Days**:
  - Bookings made on Friday afternoon for Monday: Clock runs until Friday close, freezes across Saturday and Sunday, and resumes Monday morning at shop opening.
- **SMS Delivery Failures & Carrier Retries**:
  - If Twilio returns an error (rate limit, temporary carrier failure, unreachable network) on any attempt, system executes up to 3 delivery retries spaced by exponential backoff (+1 min, +5 min, +15 min).
  - If all 3 delivery retries fail, an alert is flagged as `DELIVERY_FAILED` and the appointment immediately escalates to the supervisor without waiting for remaining reminder attempts.
- **Explicit Agent Decline**:
  - If the agent replies "DECLINE" or "NO" at any time, the system does not wait for Attempts 2/3 or the T-2 cutoff; it immediately marks the appointment `escalated_declined` and alerts the supervisor queue for immediate reassignment.
- **Customer Cancellation**:
  - If the customer replies "CANCEL" or "NO", the booking is marked `cancelled_by_customer`, calendar reservations are released, and the assigned agent is informed that the slot is open.

---

## Detailed Escalation Logic & State Machine

```
[Appointment Created (with 4h+ buffer)]
             │
             ▼
     [Attempt 1 Dispatched] ───(Agent replies "CONFIRM")───► [CONFIRMED]
             │
     (Unconfirmed)
             │
             ▼
 [Business Hours Clock Ticking]
 (Pauses during closed hours/weekends)
             │
             ├────────(Agent replies "DECLINE")─────────────► [ESCALATED: AGENT_DECLINED]
             ├────────(3 Carrier Delivery Failures)────────► [ESCALATED: DELIVERY_FAILED]
             │
             ▼
     [Attempt 2 Dispatched] ───(Agent replies "CONFIRM")───► [CONFIRMED]
             │
     (Unconfirmed)
             │
             ▼
  [Cutoff Reached: T - 2h]
  (or Morning Grace Window)
             │
             ▼
     [Attempt 3 Dispatched]
             │
     (Still Unconfirmed at Cutoff)
             │
             ▼
[ESCALATED: TIMEOUT_NO_RESPONSE]
             │
             ├──► 1. Urgent SMS Alert to Supervisor Mobile
             ├──► 2. Highlight on Dispatcher Portal Escalation Queue
             ├──► 3. Automated Candidate Ranking (Available Staff Agents)
             │
             ▼
   [Supervisor Reassignment / Auto-Fallback]
             │
             ├──► New Agent Assigned ──► Immediate High-Priority SMS to New Agent (15m window)
             ├──► Former Agent Notified of Reassignment
             └──► If No Agents Available ──► Flagged `CAPACITY_OVERFLOW` for Manual Customer Reschedule
```

### 1. Escalation Trigger Conditions

An appointment enters the `escalated` state upon any of the following 4 discrete events:
1. **`TIMEOUT_NO_RESPONSE`**: The assigned agent has not confirmed, 3 notification attempts have completed, and the calculated business-hour confirmation cutoff ($T_{\text{cutoff}}$) has passed.
2. **`AGENT_DECLINED`**: The assigned agent actively responds with a decline keyword ("DECLINE", "UNAVAILABLE", "NO", "CANNOT") via SMS or clicks "Decline" in the staff portal. Bypasses all remaining reminder attempts and escalates immediately.
3. **`DELIVERY_FAILED`**: All 3 automatic delivery retries to the assigned agent's phone number failed (e.g. invalid phone number, carrier block, unreachable network), indicating the agent cannot receive notifications.
4. **`UNASSIGNED_ON_CREATION`**: An appointment was successfully booked by the caller/bot, but no qualified staff agent was available for assignment at creation time.

### 2. Horizon-Adaptive Business-Hours Cutoff Algorithm ($T_{\text{cutoff}}$)

The confirmation deadline is **not** a one-size-fits-all $T - 2\text{ hours}$. In service operations, an appointment booked days in advance should not wait until the day of service to discover the assigned technician is unresponsive. 

The system implements a **Two-Factor Horizon-Adaptive Deadline Model**:
1. **Assignment Acceptance SLA ($T_{\text{booked}} \oplus_{\text{BH}} \text{AcceptanceSLA}$)**: Technicians are held to an operational response window that runs during active business hours from the moment of assignment.
2. **Pre-Appointment Safety Net Ceiling ($T_{\text{appt}} - \text{final\_reminder\_hours}$)**: Ensures the deadline never occurs closer than 2 hours before customer arrival (or morning grace for early morning bookings).

The effective cutoff timestamp ($T_{\text{cutoff}}$) is calculated as:

$$T_{\text{cutoff}} = \min\Big( T_{\text{booked}} \oplus_{\text{BH}} \text{AcceptanceSLA}(H_{\text{lead}}), \quad T_{\text{appt}} - \text{final\_reminder\_hours} \Big)$$

where $\oplus_{\text{BH}}$ accumulates duration **strictly during active shop business hours** (pausing at shop closing, freezing over weekends and holidays, and resuming at morning opening).

#### Horizon Tiers & Acceptance SLAs

| Tier | Booking Horizon ($H_{\text{lead}}$) | Example | Acceptance SLA ($\text{AcceptanceSLA}$) | Effective Confirmation Cutoff ($T_{\text{cutoff}}$) | Escalation Moment & Dispatcher Benefit |
|:---|:---|:---|:---|:---|:---|
| **Tier 1: Advance Bookings** | $> 24\text{ hours}$ in advance | Booked Mon 10:00 AM for Thu 2:00 PM (76h lead time) | **4 Business Hours** (`sla_advance_booking_hours`, default: 4h) | **Mon 2:00 PM** ($T_{\text{booked}} + 4\text{ BH}$) | Escalates on **Monday at 2:00 PM**. Dispatcher has **3 full days** to calmly reassign a replacement technician without last-minute panic. |
| **Tier 2: Mid-Horizon Bookings** | $6\text{ to } 24\text{ hours}$ in advance | Booked Mon 4:00 PM for Tue 1:00 PM (21h lead time) | **3 Business Hours** (`sla_medium_booking_hours`, default: 3h) | **Tue 9:00 AM** (2h on Mon: 4–6 PM + 1h on Tue: 8–9 AM) | Escalates at **9:00 AM on Tuesday** (4 hours before appointment), giving the dispatcher adequate time to adjust morning bay assignments. |
| **Tier 3: Short-Horizon Bookings** | $4\text{ to } 6\text{ hours}$ in advance | Booked 8:00 AM for 12:00 PM today (4h lead time) | **1.5 Business Hours** (`sla_short_booking_hours`, default: 1.5h) or $T - 2\text{h}$ | **9:30 AM** or **10:00 AM** ($\min(9:30\text{ AM}, 10:00\text{ AM}) = \mathbf{9:30\text{ AM}}$) | Escalates at **9:30 AM**, giving the dispatcher 2.5 hours prior to the 12:00 PM arrival to swap technicians. |

#### Early-Morning Appointment Protection (Morning Grace Rule)
If an early-morning appointment (e.g. 8:30 AM or 9:00 AM when shop opens at 8:00 AM) results in a pre-appointment ceiling that falls prior to shop opening:
$$T_{\text{cutoff}} = \min(T_{\text{cutoff}}, \; \text{Shop Opening} + \text{overnight\_grace\_minutes})$$
*(Default: Shop Opening + 30 minutes, e.g. 8:30 AM).*

#### Three-Attempt Distribution Across the Tiers
The 3 notification attempts adapt to the active horizon tier:
- **Tier 1 (> 24h Horizon, 4h SLA)**:
  - **Attempt 1**: Immediate upon booking ($T_{\text{booked}}$).
  - **Attempt 2**: Intermediate follow-up at $T_{\text{booked}} + 2\text{ BH}$.
  - **Attempt 3 / Escalation**: Final acceptance prompt at $T_{\text{booked}} + 4\text{ BH}$. If unconfirmed $\rightarrow$ **Escalates immediately to supervisor!**
  - *Pre-Visit Reminders*: Closer to the visit (at $T - 24\text{h}$ and $T - 2\text{h}$), automated courtesy reminders still go to customer and confirmed agent.
- **Tier 2 (6h to 24h Horizon, 3h SLA)**:
  - **Attempt 1**: Immediate upon booking.
  - **Attempt 2**: At $T_{\text{booked}} + 1.5\text{ BH}$ (or at morning opening if booked overnight).
  - **Attempt 3 / Escalation**: At $T_{\text{booked}} + 3\text{ BH}$ (or $T - 2\text{h}$).
- **Tier 3 (4h to 6h Horizon, 1.5h SLA)**:
  - **Attempt 1**: Immediate upon booking.
  - **Attempt 2**: At $T_{\text{booked}} + 45\text{ min}$.
  - **Attempt 3 / Escalation**: At $T_{\text{booked}} + 1.5\text{ h}$ (or $T - 2\text{h}$).

### 3. Escalation Action Sequence

When an appointment transitions to `escalated`:
1. **Audit Logging & Status Transition**:
   - `service_requests.status` remains `pending` or transitions to `in_progress`.
   - `service_requests.escalation_status` is updated to `escalated`.
   - `service_requests.escalation_reason` is set (`TIMEOUT_NO_RESPONSE`, `AGENT_DECLINED`, `DELIVERY_FAILED`, or `UNASSIGNED`).
   - Audit trail row created in `service_request_audit_log` with timestamp, elapsed business hours, and trigger details.
2. **Supervisor Multi-Channel Alert**:
   - Dispatch immediate SMS to `supervisor_alert_phone`:
     *"URGENT: Appointment #[ID] for [Customer Name] at [Time] is ESCALATED (Reason: [Reason], Agent: [Agent Name]). Open portal to reassign: [Portal Link]"*
   - Real-time portal escalation banner with audible chime and visual red badge on the dashboard.
3. **Automated Replacement Candidate Ranking**:
   - System evaluates all active `staff_agents` excluding the current unconfirmed agent.
   - Filters out agents with conflicting calendar reservations during the appointment window.
   - Ranks available candidates by:
     - Availability (strictly no overlapping calendar slots).
     - Skill/Service qualification match (e.g. Transmission vs. Oil Change vs. Brake specialist).
     - Lowest current daily job load (load balancing across technicians).
4. **Reassignment Execution**:
   - **Dispatcher-Guided (Default)**: Supervisor reviews ranked candidates on the portal and clicks "Assign to [Agent Name]" or replies to the SMS alert with the agent's ID.
   - **Automated Fallback (if `auto_reassign_on_escalation=true` in portal config)**: If supervisor does not intervene within a configured grace window (e.g. 15 minutes), system automatically assigns the top-ranked candidate.
   - **Capacity Exhaustion**: If zero alternate agents are available, status updates to `CAPACITY_OVERFLOW`, prompting the supervisor to either overbook a lead technician or call the customer to reschedule.
5. **Reassignment Communication Protocol**:
   - **Newly Assigned Agent**: Receives urgent SMS: *"URGENT ASSIGNMENT: You have been assigned Appointment #[ID] for [Customer Name] at [Time] ([Service]). Reply CONFIRM within 15 minutes."* (A fast 15-minute confirmation clock applies).
   - **Previous Agent**: Receives notice: *"Appointment #[ID] at [Time] has been reassigned due to lack of confirmation."*
   - **Google Calendar**: System rebinds the reservation to the new agent's calendar.

### 4. Late Confirmation & Race Condition Resolution

- **Scenario A: Agent confirms AFTER cutoff, but BEFORE supervisor reassigns**:
  - System accepts the agent's late confirmation!
  - `escalation_status` transitions from `escalated` to `manually_resolved` / `confirmed`.
  - Supervisor alert is automatically dismissed/marked resolved.
  - Audit note logged: *"Late confirmation accepted from assigned agent prior to reassignment."*
- **Scenario B: Agent confirms AFTER supervisor already reassigned to a new technician**:
  - System rejects the late confirmation from the previous agent.
  - Agent receives SMS: *"Appointment #[ID] was already reassigned to [New Agent Name]. No further action required."*
  - The new technician remains assigned.

---

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System and AI booking assistant MUST enforce a minimum booking buffer of at least 4 hours (`min_booking_buffer_hours`, default: 4) from the current timestamp for any new appointment reservation.
- **FR-002**: System MUST reject any appointment booking attempt scheduled earlier than `current_time + min_booking_buffer_hours`, and suggest the nearest valid slot at or after the 4-hour buffer within operating business hours.
- **FR-003**: System MUST dispatch an immediate initial notification (Attempt 1) upon appointment creation to both the customer (informational booking confirmation) and the assigned staff agent (assignment notification with confirmation prompt).
- **FR-004**: System MUST execute a 3-attempt notification sequence adapted to the appointment booking horizon:
  - **Tier 1 (> 24h Horizon)**: Attempt 1 immediate on booking; Attempt 2 at $T_{\text{booked}} + 2$ business hours; Attempt 3 at $T_{\text{booked}} + 4$ business hours (triggering escalation if unconfirmed).
  - **Tier 2 (6h to 24h Horizon)**: Attempt 1 immediate on booking; Attempt 2 at $T_{\text{booked}} + 1.5$ business hours; Attempt 3 at $T_{\text{booked}} + 3$ business hours (or $T - 2$h).
  - **Tier 3 (4h to 6h Horizon)**: Attempt 1 immediate on booking; Attempt 2 at $T_{\text{booked}} + 45$ minutes; Attempt 3 at $T - 2$ hours (triggering escalation if unconfirmed).
- **FR-005**: System MUST provide automatic delivery retry logic for failed SMS transmissions, retrying up to 3 times with exponential backoff before recording a delivery failure.
- **FR-006**: System MUST enable assigned staff agents to confirm readiness via SMS keyword reply (e.g., "CONFIRM", "C") or via a secure portal link/button.
- **FR-007**: Upon receipt of valid agent confirmation, System MUST transition the appointment state to `confirmed`, cancel remaining scheduled attempts/escalation monitors, and record an audit entry.
- **FR-008**: System MUST evaluate escalation deadlines in the context of shop business hours:
  - Escalation timers MUST pause when current time is outside configured business hours (`business_hours_start` to `business_hours_end` and `business_days`).
  - Escalation timers MUST resume at the start of the next business day (`business_hours_start`).
- **FR-009**: System MUST calculate the effective confirmation cutoff ($T_{\text{cutoff}}$) using the Two-Factor Horizon-Adaptive formula:
  $$T_{\text{cutoff}} = \min\Big( T_{\text{booked}} \oplus_{\text{BH}} \text{AcceptanceSLA}(H_{\text{lead}}), \quad T_{\text{appt}} - \text{final\_reminder\_hours} \Big)$$
  and apply the Morning Opening Grace formula ($\min(T_{\text{cutoff}}, \text{Opening} + \text{overnight\_grace\_minutes})$) for early-morning appointments.
- **FR-010**: System MUST trigger escalation immediately upon:
  - Expiration of $T_{\text{cutoff}}$ without confirmation (`TIMEOUT_NO_RESPONSE`).
  - Receipt of an explicit decline keyword from the assigned agent (`AGENT_DECLINED`).
  - Exhaustion of all 3 carrier delivery retry attempts to the agent (`DELIVERY_FAILED`).
  - Creation of a booking where no agent was available for assignment (`UNASSIGNED_ON_CREATION`).
- **FR-011**: When an appointment is escalated, System MUST transition `escalation_status` to `escalated`, record the specific `escalation_reason`, and dispatch an urgent SMS notification to `supervisor_alert_phone`.
- **FR-012**: System MUST automatically query and rank alternate available staff agents for an escalated appointment by calendar availability, service qualifications, and daily workload.
- **FR-013**: System MUST support one-click supervisor reassignment and optional automated reassignment fallback, notifying both new and former agents, updating Google Calendar events, and enforcing a 15-minute confirmation window on the newly assigned agent.
- **FR-014**: System MUST handle race conditions gracefully: accepting late confirmations if received before reassignment occurs, and rejecting late confirmations with an informative message if reassignment has already completed.
- **FR-015**: System MUST persist and expose administrative configuration settings in the portal for:
  - `min_booking_buffer_hours` (default: 4)
  - `initial_notification_enabled` (default: true)
  - `sla_advance_booking_hours` (default: 4 business hours for bookings > 24h)
  - `sla_medium_booking_hours` (default: 3 business hours for bookings 6h–24h)
  - `sla_short_booking_hours` (default: 1.5 business hours for bookings 4h–6h)
  - `final_reminder_hours` (default: 2)
  - `overnight_grace_minutes` (default: 30)
  - `max_dispatch_retries` (default: 3)
  - `business_hours_start` (default: 7 or 8)
  - `business_hours_end` (default: 18)
  - `supervisor_alert_phone` (supervisor mobile number)
  - `auto_reassign_on_escalation` (default: false)

### Key Entities *(include if feature involves data)*

- **Appointment / Service Request**: Represents the service booking. Attributes include scheduled datetime, estimated duration, vehicle, assigned staff agent ID, confirmation status (`pending_agent_confirmation`, `confirmed`, `declined`), escalation status (`none`, `escalated`, `reassigned`, `resolved`), and creation timestamp.
- **Staff Agent**: Represents the technician assigned to the job. Contains phone number, active calendar availability, and shift schedule.
- **Customer**: Represents the vehicle owner with contact phone number, vehicle association, and opt-in status.
- **Reminder & Prompt Log**: Tracks each dispatch attempt (Attempt 1, Attempt 2, Attempt 3), delivery status (`scheduled`, `sent`, `delivered`, `failed`), retry count (0 to 3), and recipient type (`customer`, `agent`, `supervisor`).
- **Escalation Audit Trail**: Logs escalation breaches, supervisor alert dispatches, reasons (timeout vs. agent decline), and agent reassignment transfers.
- **Shop Operating Configuration**: Persists business hours, business days, minimum booking horizon buffer (4h), cutoff hours (2h), and supervisor phone numbers.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of newly created appointments enforce the $\ge 4$-hour planning buffer, with zero appointments booked under 4 hours from request time.
- **SC-002**: 100% of new appointments dispatch Attempt 1 notifications to both customer and assigned agent within 30 seconds of booking creation.
- **SC-003**: 100% of unconfirmed appointments receive up to 3 structured notification attempts before reaching escalation.
- **SC-004**: Zero false-positive escalation alerts dispatched to supervisors or technicians outside of configured shop business hours.
- **SC-005**: 100% of appointments reaching the T-2 business-hour cutoff without confirmation trigger an escalation alert to the supervisor within 2 minutes of the cutoff threshold.
- **SC-006**: When an agent replies "DECLINE", supervisor escalation is triggered within 15 seconds.

## Assumptions

- Shop business hours and business days are maintained in system configuration (e.g. Monday–Friday 7:00 AM – 6:00 PM, or configured shop hours).
- The AI voice bot and portal calendar lookup endpoints use the shared booking horizon validator to reject slots with lead times under 4 hours.
- The assigned agent has a valid mobile phone number capable of receiving SMS messages and sending short keyword replies.
- Telephony and messaging services support status callbacks or delivery tracking with automatic retries for transient carrier errors.
- Supervisors have portal access to review the escalation queue and perform one-click technician reassignments.
