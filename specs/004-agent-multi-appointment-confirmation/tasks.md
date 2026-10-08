# Tasks: Staff Agent Multi-Appointment Confirmation Disambiguation & Batch Processing

**Input**: Design documents from `/specs/004-agent-multi-appointment-confirmation/`

**Prerequisites**: [spec.md](spec.md), [plan.md](plan.md)

**Organization**: Tasks are grouped by user story following strict TDD (Red-Green-Refactor) per VoiceAI Constitution v1.2.0.

## Phase 1: Setup & Foundational Test Harness

- [x] T001 Setup test module `tests/test_agent_multi_appointment_confirmation.py` with mock Twilio client and helper fixtures.

---

## Phase 2: Intent Parsing Engine (`parse_agent_confirmation_intent`)

**Goal**: Accurately parse inbound technician responses into structured action intents (`CONFIRM`, `DECLINE`, `CONFIRM_ALL`, `DECLINE_ALL`) and selector targets (`index`, `id`, `bare`, `batch`).

### Tests
- [x] T002 [P] [Parser] Author tests in `tests/test_agent_multi_appointment_confirmation.py` asserting `parse_agent_confirmation_intent` correctly parses bare tokens (`CONFIRM`, `C`, `DECLINE`), batch phrases (`CONFIRM ALL`, `ACCEPT ALL`, `C ALL`, `DECLINE ALL`), numeric selections (`CONFIRM 1`, `C 1`, `CONFIRM 101`, `DECLINE 2`), and pure numbers (`1`, `2`).

### Implementation
- [x] T003 [Parser] Implement `parse_agent_confirmation_intent(body: str) -> dict` in `serviceBot/services/sms_classifier.py`.

**Checkpoint**: Parser tests pass cleanly.

---

## Phase 3: User Story 1 - Single Pending Assignment Fast Path (Priority: P1)

**Goal**: When a technician has exactly 1 pending assignment, replying `CONFIRM`, `C`, or `DECLINE` acts immediately with zero extra friction.

### Tests for User Story 1
- [x] T004 [P] [US1] Author test asserting that when an agent has 1 pending appointment, replying `CONFIRM` or `C` confirms it and cancels reminders immediately.
- [x] T005 [P] [US1] Author test asserting that when an agent has 1 pending appointment, replying `DECLINE` marks it declined and escalates to supervisor.

### Implementation for User Story 1
- [x] T006 [US1] Update `handle_agent_confirmation_action` in `serviceBot/services/sms_classifier.py` to use `parse_agent_confirmation_intent` and preserve single-job fast path.

**Checkpoint**: User Story 1 tests pass cleanly.

---

## Phase 4: User Story 2 - Disambiguation Menu on Bare Response (Priority: P1)

**Goal**: When a technician has 2 or more pending assignments, a bare `CONFIRM` or `DECLINE` never guesses; it sends an ordered numbered disambiguation menu.

### Tests for User Story 2
- [x] T007 [P] [US2] Author test asserting that when an agent has 2+ pending appointments, replying `CONFIRM` or `C` does not alter confirmation status and replies with the formatted numbered menu listing pending jobs.

### Implementation for User Story 2
- [x] T008 [US2] Implement numbered disambiguation menu construction and dispatch in `handle_agent_confirmation_action`.

**Checkpoint**: User Story 2 tests pass cleanly.

---

## Phase 5: User Story 3 - Index & Explicit ID Confirmation (Priority: P1)

**Goal**: Allow technicians to reply with index notation (`CONFIRM 1`, `C 1`, `DECLINE 1`, `1`) or explicit ticket IDs (`CONFIRM 101`), reporting remaining pending counts.

### Tests for User Story 3
- [x] T009 [P] [US3] Author test asserting `CONFIRM 1` or `C 1` confirms the 1st appointment in the sorted schedule and notes remaining assignments.
- [x] T010 [P] [US3] Author test asserting `DECLINE 2` declines the 2nd appointment in the sorted schedule, escalates to supervisor, and notes remaining assignments.
- [x] T011 [P] [US3] Author test asserting `CONFIRM 101` confirms appointment `#101` directly matching explicit ticket ID.
- [x] T012 [P] [US3] Author test asserting pure numeric reply `1` confirms index 1.

### Implementation for User Story 3
- [x] T013 [US3] Implement index mapping, explicit ID matching, and remaining assignment receipt summary in `handle_agent_confirmation_action`.

**Checkpoint**: User Story 3 tests pass cleanly.

---

## Phase 6: User Story 4 - Batch Confirmation & Decline (Priority: P1)

**Goal**: Allow technicians to reply `CONFIRM ALL` (or `DECLINE ALL`) to confirm or decline all pending assignments in a single atomic database transaction.

### Tests for User Story 4
- [x] T014 [P] [US4] Author test asserting `CONFIRM ALL`, `Confirm all`, and `C ALL` atomically confirm all pending appointments and dispatch consolidated receipt.
- [x] T015 [P] [US4] Author test asserting `DECLINE ALL` atomically declines all pending appointments and escalates them.

### Implementation for User Story 4
- [x] T016 [US4] Implement atomic batch confirmation and batch decline in `handle_agent_confirmation_action`.

**Checkpoint**: User Story 4 tests pass cleanly.

---

## Phase 7: Edge Cases & Hardening (Priority: P2)

**Goal**: Handle out-of-bounds selections, superseded reassignments, and zero pending edge cases gracefully.

### Tests for Edge Cases
- [x] T017 [P] [Edge] Author test asserting out-of-bounds index (e.g. `CONFIRM 5` when 2 pending) dispatches helpful error listing valid choices.
- [x] T018 [P] [Edge] Author test asserting late confirmation on already reassigned appointment notifies technician cleanly.

### Implementation for Edge Cases
- [x] T019 [Edge] Implement out-of-bounds validation and helpful error guidance in `handle_agent_confirmation_action`.

---

## Phase 8: Full Regression & Verification

- [x] T020 Run `./run_tests.sh` to verify all new tests pass and 0 regressions across the entire suite.
