# Research: Catalog Service Agent Tagging & Multi-Service Back-to-Back Scheduling

**Feature**: `006-catalog-service-agent-tagging`  
**Date**: 2026-10-15  
**Status**: Completed  

---

## Decision 1: Relational Join Table vs In-Row Array for Agent Tagging

### Context
Each service in the catalog can be associated with multiple staff agents (technicians or service advisors). We must decide how to store this association in PostgreSQL.

### Decision
Implement a standard relational join table `service_staff_agents (service_id, staff_agent_id, created_at, PRIMARY KEY (service_id, staff_agent_id))` with foreign key `ON DELETE CASCADE`.

### Rationale
- Strict referential integrity: if an agent is removed, the link is cleaned up automatically without leaving stale IDs.
- Direct indexed lookups: allows efficient bidirectional queries (`SELECT staff_agent_id FROM service_staff_agents WHERE service_id = %s` and `SELECT service_id FROM service_staff_agents WHERE staff_agent_id = %s`).
- Backward compatibility: existing `services` table schema remains intact; untagged services simply have 0 rows in `service_staff_agents`.

### Alternatives Considered
- **PostgreSQL JSONB / Array Column on `services` (Rejected)**: Storing `assigned_agent_ids INTEGER[]` or `JSONB` directly on `services` complicates foreign key cascading, requires complex unnesting for joins, and breaks relational guarantees when an agent is deleted.
- **Single Foreign Key `services.staff_agent_id` (Rejected)**: Cannot support multiple qualified technicians per service (many-to-many relationship).

---

## Decision 2: Multi-Service Candidate Matching Algorithm & Optimization Heuristic

### Context
When a customer requests $N$ services (e.g. Oil Change, Transmission Flush, Tire Rotation), how should the engine search for slots and technicians?

### Decision
1. **Customer Preferred Slot First**: Search candidate slots centered around the customer's requested date and time.
2. **Single-Agent Priority Check**:
   - Query all technicians qualified for **all** requested services: $\text{Candidates} = \bigcap_{i=1}^N \text{QualifiedAgents}(S_i)$ (treating untagged services as open to all technicians).
   - If any candidate in $\text{Candidates}$ is free for the entire combined duration $\sum D_i$ at the requested time, select them as a single appointment.
3. **Multi-Agent Back-to-Back Split (Greedy Partitioning)**:
   - If no single technician can perform all services at that slot, greedily assign as many services as possible to the first qualified technician $A_1$, then assign companion technician $A_2$ for the remaining services.
   - Verify contiguous availability: $A_1$ free from $T \to T + D(A_1)$, and $A_2$ free from $T + D(A_1) \to T + D(A_1) + D(A_2)$ (0-minute handoff buffer).
4. **Dynamic Closing Boundary Enforcement**:
   - Total visit end time $T_{end}$ must not exceed `closing_hour = max(get_configured_business_hours()) + 1` (dynamically loaded from `config.json`).
5. **Dual Callbacks Separation**:
   - For multiple callback consultations, generate distinct non-overlapping windows separated by at least 30 minutes.

### Alternatives Considered
- **Strict Single-Technician Requirement (Rejected)**: Forcing the customer to wait days or weeks until a single technician is free violates the core user principle that customer availability is primary.
- **Combinatorial Optimization / ILP (Rejected)**: Overkill for auto repair shops with 2–10 technicians and 2–4 services per customer; greedy partitioning delivers sub-5ms latency and intuitive technician handoffs.

---

## Decision 3: Atomic Multi-Segment Database Reservation & Concurrency Defense

### Context
Reserving a back-to-back appointment across two technicians (e.g., John from 10:00–11:00 and Sarah from 11:00–12:00) involves multiple rows in `mock_calendar_slots` and `service_requests`. A race condition could allow another concurrent booking to take Sarah's slot after John's slot was already locked.

### Decision
1. **Single Transaction with Savepoint Rollback**:
   - Open a PostgreSQL transaction.
   - Acquire row-level locks (`SELECT ... FOR UPDATE`) across both technician slots in `mock_calendar_slots`.
   - If any segment encounters a lock conflict or is already booked, roll back the transaction immediately with a `BookingConflictError`.
2. **Visit Group Linking**:
   - Generate a shared `visit_group_id = str(uuid.uuid4())` stored on both `service_requests` rows.
   - Cross-link them bidirectionally via `linked_appointment_id`.
3. **Single Visit Mental Model for Customer**:
   - For the customer, the visit is a single unified appointment.
   - A full cancellation cancels all linked segments.
   - A request to drop one service triggers a **visit revision** (the unwanted segment is cancelled, visit duration is shortened, and the remaining technician is preserved).

### Alternatives Considered
- **Two Separate Independent Transactions (Rejected)**: High risk of orphaned bookings where Customer gets Technician 1 reserved, but Technician 2 fails, leaving the visit half-booked.
- **Single Huge Service Request with Multiple Agent IDs (Rejected)**: Breaks relational reporting, per-technician calendar syncing, and individual technician confirmation tracking. Linked rows under a `visit_group_id` maintain clean 1:1 agent-to-slot mapping.

---

## Decision 4: System-Wide Dynamic Business Hours & Closing Boundaries

### Context
Operating hours and closing times were previously hardcoded as "6:00 PM" in various files (`telephony.py`, prompt strings, and availability checks). The user mandated that business hours must be dynamically configured everywhere.

### Decision
1. Eliminate all static "18:00" and "6:00 PM" constants.
2. Route all closing boundary logic through `get_configured_business_hours()` and `get_configured_business_days()` in `calendar_sync.py` and `timezone_service.py`.
3. Closing time string is calculated dynamically: `f"{closing_hour % 12 or 12}:00 {'PM' if closing_hour >= 12 else 'AM'}"`.
4. Update `is_within_business_hours()` in `telephony.py` to check `now.hour in get_configured_business_hours()` and `now.weekday() in get_configured_business_days()`.

### Alternatives Considered
- **Hardcoding 6:00 PM as Fallback Only (Rejected)**: Hardcoded values risk leaking into edge cases. Always use dynamic configuration with defaults in `config.json`.

---

## Decision 5: Calendar Sync & Invitation Delivery

### Context
When a back-to-back appointment is booked with Technician A (10:00–11:00) and Technician B (11:00–12:00), how should Google Calendar events and customer notifications be structured?

### Decision
1. **Technicians' Google Calendars**:
   - Technician A receives a calendar event for 10:00–11:00 referencing the customer and Service A (with note: *"Part 1 of 2: Followed by Service B with Technician B"*).
   - Technician B receives a calendar event for 11:00–12:00 referencing the customer and Service B (with note: *"Part 2 of 2: Preceded by Service A with Technician A"*).
2. **Customer Calendar Invite**:
   - Primary: Customer receives **one combined calendar invite** for the entire visit (10:00–12:00) naming both technicians in the description.
   - Fallback: If Google Calendar multi-attendee sync fails or encounters API errors, fall back safely to two clean back-to-back calendar events.
3. **SMS Confirmation**:
   - Customer receives a single clear SMS:
     *"Your visit to CBA Auto is confirmed for Oct 16: 10:00 AM Oil Change with John, followed at 11:00 AM by Transmission Flush with Sarah."*
