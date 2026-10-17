# Tasks: Catalog Service Agent Tagging & Multi-Service Back-to-Back Scheduling

**Feature**: `006-catalog-service-agent-tagging`  
**Spec**: [spec.md](file:///Users/rohanroy/Coding/voiceService/specs/006-catalog-service-agent-tagging/spec.md) | **Plan**: [plan.md](file:///Users/rohanroy/Coding/voiceService/specs/006-catalog-service-agent-tagging/plan.md)  

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Database schema creation, join table migrations, and test harness setup

- [x] T001 Add `service_staff_agents` join table schema and `visit_group_id` column to `DDL_SCHEMA` in `serviceBot/db/connection.py`
- [x] T002 Add safe auto-migration execution for `service_staff_agents` and `visit_group_id` in `init_db()` in `serviceBot/db/connection.py`
- [x] T003 [P] Initialize unit test harness for catalog agent tagging in `tests/test_catalog_agent_tagging.py`
- [x] T004 [P] Initialize integration test harness for multi-service scheduling in `tests/test_multi_service_scheduling.py`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core database query helpers that ALL subsequent user stories depend on

**⚠️ CRITICAL**: No user story implementation can begin until these foundational database queries are in place.

- [x] T005 [P] Implement `get_service_agent_ids(service_id: int) -> list[int]` query helper in `serviceBot/db/queries.py`
- [x] T006 [P] Implement `set_service_agents(service_id: int, agent_ids: list[int])` transactional query helper in `serviceBot/db/queries.py`
- [x] T007 Implement `get_qualified_agent_ids(service_name: str) -> list[int]` helper supporting untagged fallback in `serviceBot/db/queries.py`
- [x] T008 [P] Implement `get_services_with_agents() -> list[dict]` batch query helper in `serviceBot/db/queries.py`

**Checkpoint**: Foundation ready — database schema, migrations, and query helpers are verified and ready for user story implementation.

---

## Phase 3: User Story 1 - Admin Tags Staff Agents to Catalog Services in Portal (Priority: P1) 🎯 MVP

**Goal**: Enable shop managers to view, assign, update, and clear staff agent tags for catalog services via Portal API and Catalog UI.

**Independent Test**: Load the Portal Catalog page, assign Technician A and Technician B to "Oil Change", save the service, verify the table displays both technician badges, and verify `GET /api/v1/portal/services` returns `assigned_agent_ids: [1, 2]`.

### Tests for User Story 1
> **NOTE: Write these tests FIRST and ensure they FAIL before implementing portal changes**

- [x] T009 [P] [US1] Unit test `service_staff_agents` CRUD operations and foreign key cascade on agent deletion in `tests/test_catalog_agent_tagging.py`
- [x] T010 [P] [US1] Integration test `GET /services`, `POST /services`, and `PUT /services/{id}` agent tagging payloads in `tests/test_catalog_agent_tagging.py`
- [ ] T010b [US1] Author Playwright browser end-to-end test in `e2e/test_portal_catalog_agent_tagging.py` verifying catalog table technician badge chips, drawer multi-select checkboxes, and save persistence

### Implementation for User Story 1

- [x] T011 [US1] Update `ServiceCreate` Pydantic model in `serviceBot/api/portal.py` to accept optional `agent_ids: list[int]`
- [x] T012 [US1] Update `create_service` and `update_service` endpoints in `serviceBot/api/portal.py` to persist agent tags via `set_service_agents`
- [x] T013 [US1] Update `GET /services` endpoint in `serviceBot/api/portal.py` to return `assigned_agent_ids` and `assigned_agent_names` for each service
- [x] T014 [P] [US1] Add "Assigned Technicians" column to Services Catalog table in `serviceBot/static/index.html`
- [x] T015 [P] [US1] Add staff agent multi-select checkbox controls to Add and Edit Service Drawers in `serviceBot/static/index.html`
- [x] T016 [US1] Wire technician tagging data loading, badge rendering, and form submission in `serviceBot/static/app.js`

**Checkpoint**: User Story 1 complete — Portal catalog tagging is fully functional and testable independently (MVP milestone).

---

## Phase 4: User Story 5 - Dynamic Closing Boundary & Operating Hours Enforced Everywhere (Priority: P1)

**Goal**: Guarantee that operating days, hours, and closing cutoffs are dynamically derived from `config.json` system-wide, eliminating hardcoded 6:00 PM assumptions.

**Independent Test**: Configure `business_hours_end: 17` (5:00 PM) in `config.json`. Verify that an appointment ending past 5:00 PM is rejected, while an appointment ending at 4:30 PM is accepted.

### Tests for User Story 5
> **NOTE: Write these tests FIRST and ensure they FAIL before implementing business hours refactoring**

- [x] T017 [P] [US5] Test dynamic closing boundary rejection for appointments exceeding configured `business_hours_end` in `tests/test_multi_service_scheduling.py`
- [x] T018 [P] [US5] Test weekend / non-operating day rejection dynamically driven by `business_days` in `tests/test_multi_service_scheduling.py`

### Implementation for User Story 5

- [x] T019 [US5] Refactor `is_within_business_hours()` in `serviceBot/api/telephony.py` to use `get_configured_business_hours()` and `get_configured_business_days()`
- [x] T020 [US5] Refactor `normalize_reservation_duration` and `validate_appointment_lead_time` in `serviceBot/services/booking.py` to dynamically inspect configured closing hours
- [x] T021 [US5] Replace hardcoded "6:00 PM" string literals with dynamically formatted closing times in prompt templates in `serviceBot/api/telephony.py`

**Checkpoint**: User Story 5 complete — dynamic operating hours and closing boundary logic enforced system-wide.

---

## Phase 5: User Story 2 & 3 - Multi-Service Scheduling Engine: Single Agent vs Back-to-Back (Priority: P1)

**Goal**: Prioritize customer availability: at requested time, assign a single qualified technician if free; otherwise, allocate split qualified technicians as contiguous back-to-back appointments (0-min buffer) with atomic database locks and rollback.

**Independent Test**:
1. Check availability when John is qualified for both services and free: verify John is assigned for the full combined duration.
2. Check availability when John can only do Service A and Sarah can only do Service B: verify John is booked at $T$ and Sarah is booked at $T + D_A$ with 0-minute buffer.
3. Simulate concurrent lock on Sarah's slot: verify John's reservation rolls back cleanly.

### Tests for User Story 2 & 3
> **NOTE: Write these tests FIRST and ensure they FAIL before implementing scheduling engine changes**

- [x] T022 [P] [US2] Test single-agent priority assignment when a single technician is qualified and free at target time in `tests/test_multi_service_scheduling.py`
- [x] T023 [P] [US3] Test back-to-back multi-agent split (0-min buffer) when no single technician can perform both at target time in `tests/test_multi_service_scheduling.py`
- [ ] T024 [P] [US3] Test greedy partitioning for 3+ services across technicians in `tests/test_multi_service_scheduling.py`
- [x] T025 [P] [US3] Test atomic rollback on concurrent slot conflict (zero orphaned bookings) in `tests/test_multi_service_scheduling.py`

### Implementation for User Story 2 & 3

- [x] T026 [US2/US3] Refactor `check_availability()` in `serviceBot/db/queries.py` to parse multiple services, compute qualified candidate intersections, evaluate single-agent slots, and permute back-to-back candidate slots
- [x] T027 [US3] Implement greedy partitioning helper for 3+ services in `serviceBot/services/booking.py` to group maximum services with first qualified technician
- [x] T028 [US3] Implement `reserve_multi_service_appointment()` in `serviceBot/services/booking.py` with multi-slot row locks on `mock_calendar_slots`, atomic savepoints, and full rollback on conflict
- [x] T029 [US3] Implement linked appointment creation: set shared `visit_group_id` UUID and cross-reference `linked_appointment_id` on `service_requests` rows in `serviceBot/services/booking.py`

**Checkpoint**: User Stories 2 & 3 complete — multi-service scheduling engine handles single-agent preference, back-to-back splits, greedy 3+ partitioning, and atomic rollbacks.

---

## Phase 6: User Story 4 - Multi-Service Dual Callbacks (Priority: P2)

**Goal**: Schedule distinct, non-overlapping callback windows (separated by at least 30 minutes) when multiple callback services are requested.

**Independent Test**: Request two callback services with different specialized advisors. Verify two distinct callback requests are logged with times separated by $\ge$ 30 minutes.

### Tests for User Story 4
> **NOTE: Write these tests FIRST and ensure they FAIL before implementing callback separation**

- [x] T030 [P] [US4] Test dual callback availability returns non-overlapping slots separated by $\ge$ 30 minutes in `tests/test_multi_service_scheduling.py`
- [x] T031 [P] [US4] Test booking dual callbacks logs linked service requests with distinct times in `tests/test_multi_service_scheduling.py`

### Implementation for User Story 4

- [x] T032 [US4] Update callback slot generation in `serviceBot/db/queries.py` to enforce $\ge$ 30-minute separation between distinct callback requests
- [x] T033 [US4] Update callback booking flow in `serviceBot/services/booking.py` to link companion callbacks under a shared `visit_group_id`

**Checkpoint**: User Story 4 complete — dual callbacks are scheduled in distinct, non-conflicting windows.

---

## Phase 7: Lifecycle Management: Cancellation, Revision & Decline Auto-Reassignment

**Goal**: Support single-visit customer mental model: full visit cancellation, partial service revision, and technician SMS decline auto-reassignment.

**Independent Test**:
1. Cancel one segment of a visit: verify all linked segments cancel.
2. Request dropping one service: verify the unwanted service is unreserved, remaining service is preserved, and total visit duration shortens.
3. Simulate technician decline (`D` via SMS): verify the system auto-reassigns to another qualified technician free at that slot, or escalates to manager.

### Tests for Lifecycle Management
> **NOTE: Write these tests FIRST and ensure they FAIL before implementing lifecycle changes**

- [ ] T034 [P] Test full visit cancellation cancels all linked segments in `tests/test_multi_service_scheduling.py`
- [ ] T035 [P] Test single-service revision preserves companion appointment and resizes visit in `tests/test_multi_service_scheduling.py`
- [ ] T036 [P] Test technician SMS decline auto-reassigns to next available qualified technician in `tests/test_multi_service_scheduling.py`

### Implementation for Lifecycle Management

- [ ] T037 Implement `cancel_multi_service_visit(visit_group_id: str)` in `serviceBot/services/booking.py`
- [ ] T038 Implement `revise_multi_service_visit(request_id_to_cancel: int)` in `serviceBot/services/booking.py`
- [ ] T039 Implement technician decline auto-reassignment hook in `serviceBot/services/sms_reminders.py` / `outbox_worker.py`

---

## Phase 8: Telephony Voice Assistant & Calendar Sync

**Goal**: Update telephony tool handlers to speak natural back-to-back confirmations and synchronize Google Calendar invites.

- [x] T040 Update `tool_name == "check_availability"` in `serviceBot/api/telephony.py` to parse multi-service queries and output natural schedule descriptions
- [x] T041 Update `tool_name == "book_appointment"` in `serviceBot/api/telephony.py` to dispatch `reserve_multi_service_appointment` and return back-to-back voice confirmation
- [ ] T042 [P] Implement unified customer Google Calendar event creation spanning full visit duration with fallback to separate events in `serviceBot/services/google_calendar.py`
- [ ] T043 [P] Synchronize individual technician calendar events for their respective segments in `serviceBot/services/google_calendar.py`

---

## Phase 9: Polish & Cross-Cutting Concerns

**Purpose**: Final verification, end-to-end regression testing, and documentation alignment

- [ ] T044 Execute complete automated test suite via `./run_tests.sh` to confirm zero regressions
- [ ] T045 [P] Update API documentation and endpoint comments in `serviceBot/api/portal.py`
- [ ] T046 Run Spec-Kit converge analysis against `spec.md`, `plan.md`, and `tasks.md`

---

## Dependencies & Execution Order

### Phase Dependencies
- **Phase 1 (Setup)**: No dependencies — start immediately.
- **Phase 2 (Foundational)**: Depends on Phase 1 completion — BLOCKS all user stories.
- **Phase 3 (User Story 1 - MVP)**: Depends on Phase 2 — can be deployed/tested as a standalone MVP.
- **Phase 4 (User Story 5 - Dynamic Hours)**: Depends on Phase 2 — can run in parallel with US1.
- **Phase 5 (User Stories 2 & 3 - Scheduling Engine)**: Depends on Phase 2 and Phase 4.
- **Phase 6 (User Story 4 - Dual Callbacks)**: Depends on Phase 2 and Phase 5.
- **Phase 7 (Lifecycle Management)**: Depends on Phase 5.
- **Phase 8 (Telephony & Calendar Sync)**: Depends on Phase 5 and Phase 7.
- **Phase 9 (Polish & Verification)**: Depends on all prior phases being complete.

### Parallel Execution Opportunities
- `T003` and `T004` (test harness setups) can execute in parallel.
- `T005`, `T006`, and `T008` (query helpers) can execute in parallel.
- `T009` and `T010` (US1 tests) can execute in parallel.
- `T014` and `T015` (UI portal HTML modifications) can execute in parallel.
- `T022`, `T023`, `T024`, and `T025` (scheduling engine tests) can execute in parallel.
- `T042` and `T043` (calendar sync implementations) can execute in parallel.

---

## Implementation Strategy: MVP First

1. **Step 1: Setup & Foundation (Phases 1 & 2)**: Database migrations and query helpers.
2. **Step 2: User Story 1 (Phase 3 - MVP)**: Catalog service-to-agent tagging in Portal API and UI. Deploy/test as MVP milestone!
3. **Step 3: Dynamic Operating Hours (Phase 4)**: Ensure system-wide dynamic hours before scheduling engine changes.
4. **Step 4: Multi-Service Scheduling Engine (Phase 5)**: Single agent preference, back-to-back splits, greedy 3+ partitioning, and atomic rollbacks.
5. **Step 5: Callbacks & Lifecycle (Phases 6 & 7)**: Dual callbacks, visit cancellation, single-service revision, and decline auto-reassignment.
6. **Step 6: Telephony & Calendar Sync (Phase 8)**: ElevenLabs voice announcements and Google Calendar invites.
7. **Step 7: Full Verification (Phase 9)**: `./run_tests.sh` full regression suite pass.
