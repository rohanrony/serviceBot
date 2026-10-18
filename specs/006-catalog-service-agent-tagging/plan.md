# Implementation Plan: Catalog Service Agent Tagging & Multi-Service Back-to-Back Scheduling

**Branch**: `006-catalog-service-agent-tagging` | **Date**: 2026-10-14 | **Spec**: [spec.md](file:///Users/rohanroy/Coding/voiceService/specs/006-catalog-service-agent-tagging/spec.md)

## Summary

### Live intake follow-up (2026-10-18)

Correct the two malformed existing gear-icon paths in the portal HTML after a
browser regression captures their parse errors. Preserve controls and semantics;
no visual redesign. Validate navigation/settings rendering in the browser.

Remove duplicate deletion and empty-catalog seeding/indexing from the GET route.
Use a read transaction only; preserve every existing catalog row/tag. Add actual
database/API contracts for duplicate rows with assignments and an empty catalog,
including no knowledge-index side effects. Existing add/update/delete operations
retain ownership of explicit changes. No schema migration is needed.

Resolve an omitted voice service type only through a unique case-insensitive
exact catalog name matching the stripped issue description. Feed that canonical
name to the existing metadata and booking paths; preserve explicit type and
uncataloged precedence and generic free-text fallback. No fuzzy inference or
schema change. Regress durable duration, segments, service identity and returned
price using an isolated catalog entry before implementation, then run both
offline suites. This local repair is not deployed by the test campaign.

Provide many-to-many tagging between catalog services and staff agents in the portal, and augment the scheduling engine in `booking.py`, `queries.py`, and `telephony.py` to:
1. Allow tagging multiple agents per service; untagged services remain open to any available staff agent.
2. Prioritize customer availability: at the requested time, book a single qualified agent if available; if not, coordinate contiguous back-to-back appointments (0-minute buffer) across qualified technicians.
3. Schedule non-conflicting, separated callback consultations (minimum 30 minutes apart) when multiple callback services are requested.
4. Strictly derive all business hours, operating days, and closing boundaries dynamically from `config.json` via `get_configured_business_hours()` and `get_configured_business_days()`.
5. Atomically reserve calendar slots with row locks, preventing partial reservations.
6. Provide unified customer Google Calendar invite with fallback to two clean back-to-back events if provider sync encounters errors.

---

## Technical Context
- **Language/Version**: Python 3.13, Vanilla JavaScript / HTML5 / CSS (Portal UI)
- **Primary Dependencies**: FastAPI, psycopg2, Pydantic, Google Calendar API
- **Storage**: PostgreSQL (`connection.py`)
- **Testing**: pytest (`./run_tests.sh`), isolated offline mocks for Google Calendar & Twilio
- **Constraints**: 
  - Dynamic closing cutoff derived from `max(get_configured_business_hours()) + 1`.
  - Zero external network dependencies in automated tests (Principle IV).
  - Atomic database transactions with row-level locks for multi-agent slot reservations (Principle II).

---

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Requirement | Verification / Status |
|---|---|---|
| **I. Simple Architecture & Ownership** | Single service owner shared across voice, portal, and background workflows | **PASS**: `BookingService` in `booking.py` and `queries.py` remain the single authority for multi-service scheduling across portal and telephony. |
| **II. Reliable State & Provider Operations** | Atomic reservations, zero partial updates, rollback on conflict | **PASS**: Back-to-back reservations use PostgreSQL row-level locks on `mock_calendar_slots` with savepoint rollback; zero orphaned bookings. |
| **III. Privacy & Trusted Integrations** | Admin operations authorized, credentials outside VCS/logs | **PASS**: No secrets in repo/logs. Calendar OAuth tokens stored encrypted. |
| **IV. Strict Test-First & Contract Coverage** | TDD Red-Green-Refactor, automated offline tests, zero external network calls | **PASS**: Tests in `tests/test_catalog_agent_tagging.py` and `tests/test_multi_service_scheduling.py` run 100% offline with mocks. |
| **V. Observable Calls & Recovery** | Clear actionable outcomes for conflicts, supervisor escalation on decline | **PASS**: Voice prompt clearly announces both technicians; decline auto-reassigns or escalates to manager with full visit context. |

---

## Project Structure

### Documentation (this feature)

```text
specs/006-catalog-service-agent-tagging/
├── plan.md              # Implementation Plan
├── research.md          # Phase 0 decisions & alternatives
├── data-model.md        # Phase 1 entities, schemas & state machine
├── quickstart.md        # Phase 1 runnable validation scenarios
├── contracts/           # Phase 1 external & telephony contracts
│   ├── portal-service-tagging-contract.md
│   └── multi-service-scheduling-contract.md
├── checklists/          # Requirements & quality checklists
│   └── requirements.md
└── tasks.md             # Phase 2 implementation task breakdown
```

### Source Code Impact

```text
serviceBot/
├── db/
│   ├── connection.py     # [MODIFY] service_staff_agents table schema & visit_group_id migration
│   └── queries.py        # [MODIFY] service agent tagging helpers & multi-service check_availability
├── services/
│   ├── booking.py        # [MODIFY] reserve_multi_service_appointment with atomic lock & rollback
│   ├── calendar_sync.py  # [MODIFY] dynamic business hours & closing boundary helpers
│   ├── google_calendar.py# [MODIFY] unified customer visit event & per-tech calendar sync
│   └── sms_reminders.py  # [MODIFY] technician decline auto-reassignment logic
├── api/
│   ├── portal.py         # [MODIFY] GET/POST/PUT /services with agent_ids
│   └── telephony.py      # [MODIFY] dynamic is_within_business_hours & multi-service voice tool output
└── static/
    ├── index.html        # [MODIFY] assigned agent column & drawer multi-select checkboxes
    └── app.js            # [MODIFY] portal agent tagging load & save logic

tests/
├── test_catalog_agent_tagging.py    # [NEW] CRUD tests for service-to-agent tagging
└── test_multi_service_scheduling.py # [NEW] Single agent vs back-to-back & atomic rollback tests
```

---

## Complexity Tracking

> **Constitution Compliance**: No violations detected. Relational join table and atomic savepoints strictly align with Principle I and Principle II.

---

## Architecture & Data Flow

```mermaid
flowchart TD
    Customer([Customer Intake - Voice/SMS/Portal]) --> TargetSlot[Parse Target Date & Time]
    TargetSlot --> SvcParse[Parse Requested Catalog Services]
    
    SvcParse --> QualifiedLookup[Lookup Tagged Agents per Service\nEmpty = All Agents]
    
    QualifiedLookup --> CheckCandidate[Check Customer's Preferred Time]
    
    CheckCandidate --> SingleAvail{Is Any Single Qualified Agent\nFree for Full Combined Duration?}
    
    SingleAvail -->|Yes| AssignSingle[Assign Single Agent for Full Duration]
    
    SingleAvail -->|No| CheckType{Booking Type}
    
    CheckType -->|Appointments| PermuteB2B[Permute Contiguous Back-to-Back Slots\nAgent 1 @ T1 -> Agent 2 @ T2 (0-min buffer)\nMust conclude before Configured Closing Hour]
    CheckType -->|Callbacks| StaggerCalls[Schedule Non-Overlapping Callback Windows\nAdvisor 1 @ T1, Advisor 2 @ T2 (>=30 min apart)]
    
    AssignSingle --> AtomicTx[Atomic DB Reservation & Lock]
    PermuteB2B --> AtomicTx
    StaggerCalls --> AtomicTx
    
    AtomicTx --> SyncCal[Create Calendar Invites & Send Confirmation SMS]
```

---

## Database Migrations & Model Changes

### 1. `service_staff_agents` Join Table
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

### 2. `service_requests` Visit Linking
```sql
ALTER TABLE service_requests ADD COLUMN IF NOT EXISTS visit_group_id VARCHAR(64) DEFAULT NULL;
CREATE INDEX IF NOT EXISTS idx_sr_visit_group ON service_requests(visit_group_id);
```

---

## Component Changes Breakdown

### 1. Database & Queries (`serviceBot/db/queries.py` & `connection.py`)
- Register `service_staff_agents` table in `connection.py` `DDL_SCHEMA` and `init_db()`.
- Add queries:
  - `get_service_agent_ids(service_id: int) -> list[int]`
  - `set_service_agents(service_id: int, agent_ids: list[int])`
  - `get_qualified_agents_for_services(service_names: list[str]) -> dict[str, list[int]]` (empty list = all agents).
- Update `check_availability()`:
  - Dynamically get closing hour: `closing_hour = max(get_configured_business_hours()) + 1`.
  - Validate candidate slots against `closing_hour` and total duration.
  - Evaluate single-agent candidates first; if none free at requested time, evaluate back-to-back candidates with 0-minute handoff buffer.
  - Partition 3+ services greedily: combine as many services as possible with the first qualified technician, then schedule companion technicians back-to-back.

### 2. Booking Service (`serviceBot/services/booking.py`)
- Enhance `BookingService`:
  - `reserve_multi_service_appointment(...)`: Atomically reserve Agent 1 from $T \to T + D_1$ and Agent 2 from $T + D_1 \to T + D_1 + D_2$.
  - Use database savepoints / transactional locks on `mock_calendar_slots`. If Agent 2 fails, roll back Agent 1.
  - Set `visit_group_id` = UUID on both service requests and cross-link `linked_appointment_id`.
  - Dynamic closing boundary enforcement: `normalize_reservation_duration` and `validate_appointment_lead_time` respect `get_configured_business_hours()`.
  - **Visit Revision / Cancellation**: If customer cancels, cancel all linked segments. If customer drops one service, revise visit: cancel unwanted segment, shorten total duration, and update calendar invite.
  - **Technician Decline Auto-Reassignment**: If a technician declines via SMS or times out on their SLA, auto-reassign that specific segment to another qualified technician free at that exact back-to-back slot; if none free, escalate to shop manager.

### 3. Portal API (`serviceBot/api/portal.py`)
- `GET /services`: Include `assigned_agent_ids: list[int]` and `assigned_agent_names: list[str]`.
- `POST /services` & `PUT /services/{service_id}`: Accept `agent_ids: list[int]` in payload and update `service_staff_agents`.
- Dynamically format closing hour across portal config endpoints.

### 4. Portal UI (`serviceBot/static/index.html` & `app.js`)
- **Services Catalog Table**: Add "Assigned Technicians" column displaying badge chips for each assigned agent (or "Any Available Agent").
- **Add / Edit Service Drawers**: Add multi-select checkboxes for staff agents.
- **Service Requests View**: Add visual badge linking multi-service visits together.

### 5. Telephony Voice Assistant (`serviceBot/api/telephony.py`)
- Update `is_within_business_hours()` to dynamically inspect `get_configured_business_hours()` and `get_configured_business_days()`.
- Update prompt messages: replace static "6:00 PM" with dynamic string formatted from configured closing hour.
- Natural language output for ElevenLabs:
  *"I have reserved back-to-back appointments for you: John for your Oil Change from 10:00 to 11:00, and Sarah immediately following at 11:00 for your Transmission Flush."*

### 6. Calendar Sync & Invites (`serviceBot/services/google_calendar.py`)
- Primary: Attempt creating a unified Google Calendar event for the customer spanning $T_{start} \to T_{end}$ with both technicians listed.
- Fallback: If unified event creation encounters provider errors, cleanly create two sequential Google Calendar events.

---

## Verification Plan

### Automated Tests (`tests/test_multi_service_scheduling.py`)
1. **Test Service Tagging CRUD**: Verify assigning, updating, and clearing agents on catalog services.
2. **Test Fallback for Untagged Services**: Untagged services allow any staff agent.
3. **Test Preferred Time Single-Agent Priority**: At target time, if a single agent is free, book them.
4. **Test Preferred Time Back-to-Back Allocation**: If no single agent is free at target time, book two qualified technicians back-to-back (0-min buffer).
5. **Test Dynamic Closing Boundary**: Configure closing hour = 17:00; verify a 2-hour appointment at 16:00 is rejected, but 15:00 is accepted.
6. **Test Atomic Rollback**: Verify that if the second technician's slot is taken, the entire booking rolls back cleanly.
7. **Test Dual Callbacks**: Verify two callback requests receive non-overlapping times (>= 30 mins apart).

### Manual Verification
- In the Portal: Assign John to Oil Change, Sarah to Brake Inspection.
- Book both services at 10:00 AM via conversation simulator.
- Verify John is booked 10:00-11:00, Sarah 11:00-12:00, with 0-min buffer.
