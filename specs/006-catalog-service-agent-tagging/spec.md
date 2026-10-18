# Feature Specification: Catalog Service Agent Tagging & Multi-Service Back-to-Back Scheduling

**Feature Branch**: `006-catalog-service-agent-tagging`  
**Created**: 2026-10-14  
**Last Updated**: 2026-10-14  
**Status**: Approved Plan  
**Target Version**: `v0.9.0`  
**Author / PM**: AI Product Management Co-Pilot & Engineering  
**Input**: User description: "I want to tag some specific services in catalog to specific agents. 1. So, in the portal, in catalog page, I can tag multiple agents to each. 2. During checking for appointment/callback: if the customer needs multiple services (and cannot be served by one agent, assign different agents as back-to-back appointments. If both are callbacks, they can be two different callback appointments (not necessarily back-to-back). 3. If there is an agent that can handle both the work, it is better to assign that agent. 4. Untagged events open to any agent. 5. Business hours and closing boundaries strictly dynamic from config.json everywhere. 6. Customer earliest availability preferred over waiting for a single agent. 7. 0-minute handoff buffer. 8. Unified customer calendar invite with fallback."

---

## 1. Executive Summary & Value Proposition

### 1.1 Problem Statement
Currently in VoiceService:
1. **Catalog Services are Unassigned**: The `services` table defines offerings (name, duration, pricing, required fields), but cannot associate offerings with specific technicians or service advisors. The scheduling engine assumes all staff agents can perform all services interchangeably.
2. **Multi-Service Single-Agent Bottleneck**: When a customer requests multiple services (e.g., "Oil Change and Transmission Flush"), the system sums durations into a single monolithic block and attempts to find a single agent free for the entire duration, failing if no single agent is free even if two qualified specialists could perform the services consecutively.
3. **No Back-to-Back Multi-Agent Coordination**: If no single agent is qualified or free for all services at the customer's desired time, the system cannot orchestrate contiguous, back-to-back appointments across different technicians.
4. **No Distinct Handling for Dual Callbacks**: If multiple consultation/advisory services are requested, the system has no policy to schedule separate callback windows for different specialized advisors without colliding on the customer's phone line.
5. **Hardcoded Operating Hours / Closing Cutoff**: In various places, 6:00 PM is assumed rather than dynamically calculating closing time from `config.json` (`business_hours`, `business_hours_start`, `business_hours_end`, `business_days`).

### 1.2 Proposed Solution
1. **Catalog Service-to-Agent Tagging**:
   - Establish a many-to-many relationship between `services` and `staff_agents` via `service_staff_agents`.
   - Update Portal Catalog UI (table, Add Service drawer, Edit Service drawer) to allow tagging multiple qualified agents per service.
   - **Untagged Fallback**: Services with zero tagged agents are automatically open to all active staff agents.
2. **Intelligent Multi-Service Scheduling Engine**:
   - **Customer Availability Primary**: The customer's desired time slot is the driving constraint.
   - **Optimization Rule (Single-Agent Preference at Target Time)**: If at least one agent is qualified to perform all requested services and has consecutive availability at the target time, prioritize booking that single agent for the entire duration.
   - **Back-to-Back Multi-Agent Split (Appointments)**: If no single qualified agent is free at the target time, find valid contiguous slots where qualified Agent 1 performs Service 1 from $T$ to $T + D_1$, and qualified Agent 2 performs Service 2 consecutively from $T + D_1$ to $T + D_1 + D_2$ (0-minute buffer).
   - **Non-Overlapping Callback Scheduling (Callbacks)**: If multiple callback services are requested, book distinct callback appointments with appropriate specialized advisors at non-conflicting times (separated by at least 30 minutes).
   - **Dynamic Business Hours & Closing Boundary**: All closing boundary checks, lead time restrictions, and operating schedules must strictly derive from `get_configured_business_hours()` and `get_configured_business_days()`. No hardcoded 6:00 PM.
3. **Atomic Booking & Linked Lifecycle Management**:
   - Create linked `service_requests` rows tied via `linked_appointment_id` and a shared `visit_group_id`.
   - Atomic multi-agent calendar reservations ensuring either all slots reserve or none do (zero orphaned partial bookings).
   - Coordinated customer calendar invite spanning the full visit window, falling back to two separate back-to-back calendar events if provider errors occur.

---

## Clarifications

### Live intake follow-up (2026-10-18)

Browser follow-up: portal navigation and settings icons must have valid SVG path
data and render without browser parse errors. Retain a real-browser regression
for the malformed repeated gear path observed on the deployed portal.

Catalog reads must preserve catalog rows and service-to-staff assignments.
`GET /services` must not delete duplicate names, insert defaults into an empty
catalog or invoke knowledge indexing. An empty catalog returns an empty list;
catalog mutations remain explicit administrative actions.

When voice `create_service_request` omits `service_type` but its stripped
`issue_description` exactly matches one catalog service name (case insensitive),
use that canonical service name for intake metadata and persistence. Quoted
catalog duration, price and qualification must reach the created booking and
reservation. Explicit service types and explicit uncataloged requests retain
precedence. Free text must not be guessed or fuzzily mapped to a service.

### Session 2026-10-15
- Q: When a customer or staff cancels one segment of a multi-service back-to-back visit, how should the system handle the companion appointment? → A: For the customer it is a single appointment. If the customer cancels, the entire visit (all linked services) is cancelled. If the customer calls to have only one thing checked, the visit is revised (the unwanted service is cancelled/removed, duration shortened, and the remaining service kept at its originally confirmed start time without shifting, avoiding technician schedule disruption).
- Q: If a customer requests 3 or more services where no single technician can perform all of them, how should the scheduling engine partition the work? → A: Greedy grouping: combine as many services as possible with the first qualified technician, then schedule the companion technician back-to-back to minimize bay/technician handoffs.
- Q: If Technician 1 confirms via SMS but Technician 2 declines (or times out) for a back-to-back appointment, how should the system handle the declined segment? → A: Automatically reassign the declined segment to another qualified technician free at that exact slot after a 15-minute confirmation SLA timeout; if no other qualified technician is available, escalate to manager with linked visit context.

---

## 2. User Scenarios & Acceptance Criteria

### User Story 1 - Admin Tags Qualified Staff Agents to Services in Portal Catalog (Priority: P1)
As a shop manager or administrator, I want to tag one or more qualified staff agents to each service in the Catalog page, so that our scheduling engine routes appointments only to technicians with the right skills and certifications.

**Acceptance Scenarios**:
1. **Given** an admin opens the Services Catalog tab in the Portal, **When** viewing the services table, **Then** each row displays the list of assigned agent badges (or "Any Available Agent" if untagged).
2. **Given** an admin opens the "Add New Service" or "Edit Service" drawer, **When** configuring the service, **Then** a multi-select control allows selecting multiple staff agents.
3. **Given** an admin saves the service with assigned agents, **When** the update completes, **Then** `service_staff_agents` records are persisted, and the service details return the assigned `staff_agent_ids`.
4. **Given** a service has no agents tagged, **When** availability is checked, **Then** the engine treats the service as open to all active staff agents.

---

### User Story 2 - Customer Desired Time Prioritized: Single Agent Preferred if Available at that Slot (Priority: P1)
As a customer calling CBA Auto for an Oil Change and Tire Rotation at 10:00 AM, I want to be scheduled with a single technician if one is available at 10:00 AM, but if only split technicians can do 10:00 AM, I want the split rather than being pushed to another day.

**Acceptance Scenarios**:
1. **Given** John is tagged for both "Oil Change" and "Tire Rotation", and is free at 10:00 AM, **When** availability is checked, **Then** John is booked as a single appointment for the combined 90 minutes.
2. **Given** John is only free on Friday, but Sarah (Oil Change) and Dave (Tire Rotation) can do 10:00 AM Tomorrow back-to-back, **When** the customer asks for tomorrow morning, **Then** Sarah and Dave are scheduled back-to-back at 10:00 AM.

---

### User Story 3 - Multi-Service Split into Back-to-Back Appointments with 0-Minute Handoff Buffer (Priority: P1)
As a customer requesting "Brake Replacement" (handled by Sarah) and "Transmission Fluid Flush" (handled by Dave), I want both services scheduled back-to-back in a single visit with 0 minutes wasted between services.

**Acceptance Scenarios**:
1. **Given** no single agent is tagged for both services, **When** the caller requests a date/time, **Then** the system searches for contiguous time slots where Sarah is available for Brakes (e.g., 10:00 AM - 11:00 AM) and Dave is available for Transmission immediately following (11:00 AM - 12:00 PM).
2. **Given** a valid back-to-back slot is found, **When** booking is executed, **Then** both appointments are reserved atomically in the database and mock/Google calendars.
3. **Given** the customer receives a confirmation SMS, **When** delivered, **Then** it clearly lists both services, their sequential times, and the respective technician names.

---

### User Story 4 - Multi-Service Dual Callbacks Scheduled at Non-Conflicting Times (Priority: P2)
As a customer requesting phone consultations on two specialized issues (e.g. custom engine tuning and insurance collision estimate), I want two separate callback slots scheduled with the appropriate advisors without overlapping on my phone line.

**Acceptance Scenarios**:
1. **Given** two callback requests for services with different tagged advisors, **When** checking callback availability, **Then** the system schedules two distinct callback slots (e.g. Advisor A at 1:00 PM, Advisor B at 2:00 PM), ensuring at least 30 minutes between calls.
2. **Given** the caller accepts, **When** confirmed, **Then** two linked callback service requests are logged with their respective advisors and times.

---

### User Story 5 - Dynamic Closing Boundary & Operating Hours Enforced Across All Modules (Priority: P1)
As a shop manager who configures operating hours (e.g. 8:00 AM to 5:00 PM) in Portal Settings, I want multi-service back-to-back appointments to strictly respect the configured closing hour, so that no technicians are scheduled past shop closing.

**Acceptance Scenarios**:
1. **Given** `config.json` specifies `business_hours_end: 17` (5:00 PM), **When** a multi-service appointment totaling 2 hours is requested, **Then** the latest start time offered is 3:00 PM (concluding at 5:00 PM).
2. **Given** the shop is closed on weekends per `business_days`, **When** slots are generated, **Then** weekend slots are never returned.
3. **Given** telephony and availability check prompts, **When** formatting instructions to the caller or voice agent, **Then** the closing time message dynamically reflects the configured closing hour rather than hardcoded 6:00 PM.

---

## 3. Comprehensive Edge Cases & System Constraints

| Category | Edge Case Scenario | Expected System Behavior & Mitigation |
|---|---|---|
| **Data & Tagging** | Service has zero tagged agents | Treated as **"Any Available Agent"**. The scheduling engine considers all active technicians eligible. |
| **Data & Tagging** | Tagged technician is deleted or removed | Foreign key `ON DELETE CASCADE` removes them from `service_staff_agents`. Existing booked appointments remain assigned or trigger a manager reassignment alert. |
| **Scheduling** | Shop Closing Boundary (Dynamic from Config) | Back-to-back duration ($D_1 + D_2$) must fully conclude by the dynamically configured closing hour (`max(get_configured_business_hours()) + 1`). |
| **Scheduling** | 4-Hour Minimum Advance Notice Lead Time | The start time of the first appointment must be $\ge \text{now} + 4\text{ hours}$. |
| **Scheduling** | Buffer between Technicians | Exactly 0 minutes (consecutive handoff). Service 2 starts at the exact minute Service 1 ends. |
| **Scheduling** | Single Agent vs Customer Availability Trade-off | Customer availability at target slot takes precedence. If single agent is free at target slot, pick single agent; otherwise, allocate split back-to-back agents. |
| **Scheduling** | Dual Callbacks Collision | Two callbacks are scheduled with separate qualified advisors at **non-overlapping** times (separated by at least 30 minutes) so the customer is not double-called simultaneously. |
| **Scheduling** | 3+ Services Partitioning | When a customer requests 3 or more services and no single technician can perform all of them, the engine applies greedy grouping: it assigns as many services as possible to the first qualified technician, then schedules companion technicians back-to-back to minimize bay/technician handoffs. |
| **Concurrency** | Partial Booking Failure (Race Condition) | When reserving Agent 1 and Agent 2, both slot sets are locked `FOR UPDATE`. If Agent 2 fails, the transaction rolls back cleanly with `BookingConflictError`, leaving zero orphan bookings. |
| **Lifecycle** | Customer Reschedules, Cancels, or Revises | For the customer, the visit is a single appointment. If the customer cancels, all linked back-to-back services are cancelled together. If the customer requests to keep only one service, the visit is revised (the unwanted service is cancelled/unreserved, the remaining service is preserved at its original start time without shifting, and total visit duration/calendar invite is shortened accordingly). Rescheduling evaluates both services together for a new joint slot. |
| **Lifecycle** | Technician SMS Decline or SLA Timeout | If Technician 1 confirms via SMS (`C101`) but Technician 2 declines (`D102`) or times out (15-minute confirmation SLA), the system automatically attempts to reassign Technician 2's segment to another qualified technician free at that exact back-to-back slot. If no other qualified technician is available, the visit is escalated to the shop manager with linked visit context. |
| **Calendar Sync** | Google Calendar Visibility & Fallback | Customer receives a single unified visit invite covering the full duration (both technicians in notes). If calendar sync encounters errors, falls back to two separate back-to-back invites. |

---

## 4. Key Entities & Database Schema

### 4.1 New Table: `service_staff_agents`
```sql
CREATE TABLE IF NOT EXISTS service_staff_agents (
    service_id INTEGER NOT NULL REFERENCES services(id) ON DELETE CASCADE,
    staff_agent_id INTEGER NOT NULL REFERENCES staff_agents(id) ON DELETE CASCADE,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
    PRIMARY KEY (service_id, staff_agent_id)
);
CREATE INDEX IF NOT EXISTS idx_ssa_service_id ON service_staff_agents(service_id);
CREATE INDEX IF NOT EXISTS idx_ssa_agent_id ON service_staff_agents(staff_agent_id);
```

### 4.2 Extensions to `service_requests`
- `linked_appointment_id INTEGER REFERENCES service_requests(id) ON DELETE SET NULL` (cross-references companion service request).
- `visit_group_id VARCHAR(64) DEFAULT NULL` (UUID grouping all segments of a multi-service visit).

---

## 5. Success Criteria

- **SC-001**: 100% of catalog services can have multiple agents tagged (or left untagged for "Any Agent") via the Portal UI and API.
- **SC-002**: Multi-service booking requests at customer's desired time slot automatically assign a single qualified technician if free, or split across qualified technicians back-to-back (0-min buffer) if needed.
- **SC-003**: 100% of multi-service appointments conclude strictly before the dynamically configured business closing hour.
- **SC-004**: Zero orphaned calendar reservations occur under concurrent race conditions.
- **SC-005**: All existing unit and integration tests continue to pass without regression.
