# Tasks: Catalog Service Agent Tagging & Multi-Service Back-to-Back Scheduling

**Feature Branch**: `006-catalog-service-agent-tagging`  
**Input**: Feature specification (`spec.md`) and implementation plan (`plan.md`)

---

## Phase 1: Database Schema & Core Data Model

- [x] T001 Add `service_staff_agents` join table schema and `visit_group_id` column on `service_requests` to `DDL_SCHEMA` and `init_db()` in `serviceBot/db/connection.py`
- [x] T002 Write unit tests for `service_staff_agents` CRUD queries in `tests/test_catalog_agent_tagging.py`
- [x] T003 Implement `get_service_agent_ids`, `set_service_agents`, and `get_qualified_agent_ids` in `serviceBot/db/queries.py`

---

## Phase 2: User Story 1 - Admin Tags Staff Agents to Catalog Services in Portal (Priority: P1)

- [x] T004 [US1] Add integration tests for `GET /services`, `POST /services`, and `PUT /services/{id}` agent tagging in `tests/test_catalog_agent_tagging.py`
- [x] T005 [US1] Update `portal.py` service endpoints to ingest, validate, and return `assigned_agent_ids` and `assigned_agent_names`
- [x] T006 [US1] Add Assigned Technicians column to Services Catalog table in `serviceBot/static/index.html`
- [x] T007 [US1] Add multi-select technician checkboxes to Add and Edit Service Drawers in `serviceBot/static/index.html`
- [x] T008 [US1] Wire technician tagging data loading and drawer form submissions in `serviceBot/static/app.js`

---

## Phase 3: User Story 2 & 3 - Multi-Service Scheduling Engine: Single Agent vs Back-to-Back (Priority: P1)

- [x] T009 [US2/US3] Add unit/integration tests in `tests/test_multi_service_scheduling.py` testing:
  - Single-agent assignment when qualified technician is free at target time
  - Back-to-back split (0-minute buffer) across qualified technicians when single is unavailable at target time
  - Dynamic closing cutoff rejection (using configured business hours)
  - Atomic transaction rollback if one leg fails
- [x] T010 [US2/US3] Update `check_availability()` in `serviceBot/db/queries.py` to support multi-service queries, dynamic closing boundaries, single-agent evaluation, and back-to-back permutations
- [x] T011 [US2/US3] Implement `reserve_multi_service_appointment()` in `serviceBot/services/booking.py` with row-level locks, atomic savepoint rollback, and linked service request creation

---

## Phase 4: User Story 4 - Multi-Service Dual Callbacks (Priority: P2)

- [x] T012 [US4] Add tests for dual callback requests with distinct non-overlapping windows (>= 30 mins apart) in `tests/test_multi_service_scheduling.py`
- [x] T013 [US4] Update callback booking flow in `serviceBot/services/booking.py` and `serviceBot/db/queries.py` to schedule separated callback windows

---

## Phase 5: User Story 5 - Dynamic Business Hours System-Wide (Priority: P1)

- [x] T014 [US5] Audit and refactor `telephony.py` (`is_within_business_hours`), `booking.py`, and `calendar_availability.py` to strictly use `get_configured_business_hours()` and `get_configured_business_days()`
- [x] T015 [US5] Replace hardcoded "6:00 PM" strings in voice prompt messages with dynamically formatted closing times

---

## Phase 6: Telephony Voice Assistant & Calendar Sync

- [x] T016 Update `tool_name in ["check_availability", "book_appointment"]` in `serviceBot/api/telephony.py` to support multi-service arguments and return natural back-to-back descriptions
- [x] T017 Implement unified customer Google Calendar event with fallback to sequential events in `serviceBot/services/google_calendar.py`

---

## Phase 7: Polish & Verification

- [x] T018 Execute full test suite via `./run_tests.sh` to confirm zero regressions
- [x] T019 Execute Spec-Kit converge analysis against `spec.md`, `plan.md`, and `tasks.md`
