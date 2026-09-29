# Tasks: Booking Confirmation Guard & Customer Appointment History Context

**Input**: Design documents from `/specs/001-booking-confirmation-history/`

**Prerequisites**: [plan.md](file:///Users/rohanroy/Coding/voiceService/specs/001-booking-confirmation-history/plan.md), [spec.md](file:///Users/rohanroy/Coding/voiceService/specs/001-booking-confirmation-history/spec.md), [research.md](file:///Users/rohanroy/Coding/voiceService/specs/001-booking-confirmation-history/research.md), [data-model.md](file:///Users/rohanroy/Coding/voiceService/specs/001-booking-confirmation-history/data-model.md), [contracts/](file:///Users/rohanroy/Coding/voiceService/specs/001-booking-confirmation-history/contracts/)

**Tests**: Test-driven development (TDD) required per project constitution; test tasks are included and must be executed first.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (`[US1]`, `[US2]`, `[US3]`)
- Include exact file paths in descriptions

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Establish call session tracking and in-flight booking state management.

- [x] T001 Setup in-flight booking session tracking dictionary and helper functions in `serviceBot/services/booking.py`
- [x] T002 [P] Define Pydantic request models for session booking context and consolidation in `serviceBot/api/telephony.py`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core database query enhancements and calendar capacity checking that MUST be complete before user stories can execute.

- [x] T003 Update `get_customer_appointments` query in `serviceBot/db/queries.py` to include `sr.issue_description` and `sr.duration_minutes`
- [x] T004 [P] Implement `get_customer_service_history` query in `serviceBot/db/queries.py` to fetch recent service requests and callbacks with issue notes
- [x] T005 [P] Implement contiguous calendar slot capacity checker `verify_contiguous_slot_capacity` in `serviceBot/services/calendar_availability.py`

**Checkpoint**: Foundation ready - user story implementation can now begin.

---

## Phase 3: User Story 1 - Single Confirmed Appointment Booking (Priority: P1) 🎯 MVP

**Goal**: Prevent duplicate appointment creation when callers change their preferred time (e.g., 10:00 AM to 10:30 AM). Enforce deferred tool execution until explicit confirmation, quote start and expected end duration with extension notice, and deduplicate/update in-flight bookings within the call session.

**Independent Test**: Simulate an incoming tool call sequence where a caller changes preference from 10:00 AM to 10:30 AM. Verify that exactly one appointment row is created in `service_requests` and only one calendar event exists.

### Tests for User Story 1 (TDD) ⚠️

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [x] T006 [P] [US1] Create automated unit/integration tests for single booking on time shift and session deduplication in `tests/test_booking_confirmation_guard.py`
- [x] T007 [P] [US1] Create unit tests verifying start/end time disclosure and extension notice in `tests/test_booking_confirmation_guard.py`

### Implementation for User Story 1

- [x] T008 [US1] Implement session deduplication and in-place update logic for `create_service_request` and `book_appointment` in `serviceBot/api/telephony.py`
- [x] T009 [US1] Update `serviceBot/system_prompt.txt` to strictly defer booking tool calls until explicit end-of-call confirmation and require start/end time window disclosure with the "likely to extend" notice
- [x] T010 [US1] Synchronize ElevenLabs agent prompt in `serviceBot/config.json` with deferred booking rules and start/end time disclosure
- [x] T011 [US1] Run and verify User Story 1 test suite via `pytest tests/test_booking_confirmation_guard.py`

**Checkpoint**: User Story 1 is fully functional and independently testable. Duplicate bookings on time shifts are eliminated.

---

## Phase 4: User Story 2 - Contextual Recognition of Upcoming Appointments & History (Priority: P2)

**Goal**: Recognize returning callers by phone number, inject upcoming appointment and previous issue context into inbound call initialization, greet callers warmly by name first, and reveal appointment/car context when the caller describes their issue or vehicle.

**Independent Test**: Initiate an inbound call with a returning customer's phone number having an upcoming appointment. Verify TwiML contains enriched parameters (`customer_name`, `upcoming_appointments_summary`) and `get_customer_appointments` returns the prior issue description.

### Tests for User Story 2 (TDD) ⚠️

- [x] T012 [P] [US2] Create automated integration tests for inbound TwiML parameter injection and `get_customer_appointments` issue descriptions in `tests/test_customer_history_context.py`

### Implementation for User Story 2

- [x] T013 [US2] Enrich `inbound_call` endpoint in `serviceBot/api/telephony.py` with `customer_name`, `upcoming_appointments_summary`, and `recent_history_summary` parameters in TwiML
- [x] T014 [US2] Update `get_customer_appointments` tool handler in `serviceBot/api/telephony.py` to return `issue_description`, `duration_minutes`, and vehicle specs
- [x] T015 [US2] Update `serviceBot/system_prompt.txt` and `serviceBot/config.json` with returning caller greeting protocol (greet warmly by name first; recall appointment and vehicle context when issue or car is mentioned)
- [x] T016 [US2] Run and verify User Story 2 test suite via `pytest tests/test_customer_history_context.py`

**Checkpoint**: User Stories 1 AND 2 are independently functional and integrated. Returning callers receive high-touch contextual service.

---

## Phase 5: User Story 3 - Consolidating New Issues into Existing Appointments (Priority: P3)

**Goal**: When a returning customer with an upcoming appointment reports a new issue for the same car, offer to consolidate both issues into the existing appointment, verify contiguous calendar capacity, and adjust total duration.

**Independent Test**: Seed a customer with an upcoming 45-min Oil Change. Simulate reporting a 45-min Brake Inspection for the same vehicle. Verify the system checks calendar capacity, updates `duration_minutes` to 90, appends to `issue_description`, and expands the calendar event.

### Tests for User Story 3 (TDD) ⚠️

- [x] T017 [P] [US3] Create automated integration tests for consolidating multiple issues and duration extension in `tests/test_consolidate_appointment_issues.py`

### Implementation for User Story 3

- [x] T018 [US3] Implement `consolidate_appointment_service` query function in `serviceBot/db/queries.py` to append issue descriptions and update duration
- [x] T019 [US3] Implement `consolidate_appointment_service` tool endpoint in `serviceBot/api/telephony.py` with contiguous slot verification
- [x] T020 [US3] Register `consolidate_appointment_service` in `serviceBot/conversation_simulator.py` and tool schemas
- [x] T021 [US3] Update `serviceBot/system_prompt.txt` and `serviceBot/config.json` with conversational rules to offer consolidating additional issues into existing appointments for the same vehicle
- [x] T022 [US3] Run and verify User Story 3 test suite via `pytest tests/test_consolidate_appointment_issues.py`

**Checkpoint**: All three user stories are complete, independently verified, and seamlessly cooperative.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: End-to-end scenario validation and regression testing across the entire codebase.

- [x] T023 [P] Execute quickstart validation scenarios 1 through 4 from `specs/001-booking-confirmation-history/quickstart.md`
- [x] T024 Run full local test suite via `./run_tests.sh` to ensure zero regressions across existing telephony, portal, and calendar suites
- [x] T025 [P] Update API and telephony documentation in `docs/specs/api_spec.md` reflecting new tool responses and consolidation semantics

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: Can start immediately.
- **Foundational (Phase 2)**: Depends on Phase 1; blocks all User Story implementations.
- **User Story 1 (Phase 3)**: Depends on Phase 2. MVP milestone.
- **User Story 2 (Phase 4)**: Depends on Phase 2; can proceed in parallel with or after US1.
- **User Story 3 (Phase 5)**: Depends on Phase 2, US1 (booking updates), and US2 (appointment context).
- **Polish (Phase 6)**: Depends on completion of US1, US2, and US3.

### Parallel Opportunities

- `T001` and `T002` can run in parallel.
- `T003`, `T004`, and `T005` can run in parallel once Setup completes.
- In US1: `T006` and `T007` (tests) can be created in parallel before implementation.
- In US2: `T012` (tests) can run in parallel with US1 implementation.
- In US3: `T017` (tests) can run in parallel with US2 implementation.
- `T023` and `T025` can run in parallel during Polish.

---

## Implementation Strategy

### MVP First (User Story 1 Only)
1. Complete Setup (T001-T002) and Foundational (T003-T005).
2. Execute User Story 1 (T006-T011).
3. **Validate MVP**: Verify time shifts during a call only create a single booking and start/end time disclosures are uttered.
4. Deploy / verify MVP.

### Incremental Delivery
1. Foundation + US1 (MVP): Single confirmed booking guard & duration disclosures.
2. US2: Returning customer context & warm greeting.
3. US3: Issue consolidation into existing appointment & slot expansion.
4. Polish: Full regression test execution and documentation updates.
