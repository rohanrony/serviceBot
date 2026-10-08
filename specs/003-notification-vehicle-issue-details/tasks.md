# Tasks: Vehicle Details and Issue Description in Customer and Agent Notifications

**Input**: Design documents from `/specs/003-notification-vehicle-issue-details/`

**Prerequisites**: [spec.md](spec.md), [plan.md](plan.md)

**Organization**: Tasks are grouped by user story following strict TDD (Red-Green-Refactor) per VoiceAI Constitution v1.2.0.

## Phase 1: Setup & Foundational Test Harness

- [x] T001 Setup test module `tests/test_notification_vehicle_issue_details.py` with mock Twilio client and helper fixtures.

---

## Phase 2: User Story 1 - Customer Notifications & Reminders (Priority: P1)

**Goal**: Ensure all customer appointment messages (booking, reschedule, pre-appointment reminders) include structured lines for Vehicle and Issue.

### Tests for User Story 1
- [x] T002 [P] [US1] Author test asserting customer `BOOKING` SMS/WhatsApp body includes `Vehicle: <veh>` and `Issue: <iss>` in `tests/test_notification_vehicle_issue_details.py`.
- [x] T003 [P] [US1] Author test asserting customer `RESCHEDULED` SMS/WhatsApp body includes `Vehicle: <veh>` and `Issue: <iss>` in `tests/test_notification_vehicle_issue_details.py`.
- [x] T004 [P] [US1] Author test asserting customer reminders (immediate, follow-up, upcoming) include `Vehicle: <veh>` and `Issue: <iss>` in `tests/test_notification_vehicle_issue_details.py`.

### Implementation for User Story 1
- [x] T005 [US1] Update `serviceBot/services/sms_router.py` customer notification templates (`BOOKING`, `RESCHEDULED`, `CONSOLIDATED`, `CANCELLED`, `STATUS_*`) to include structured `Vehicle:` and `Issue:` lines.
- [x] T006 [US1] Update `fetch_appointment_customer_details` in `serviceBot/services/sms_reminders.py` to extract and return `issue` from `sr.issue_description`.
- [x] T007 [US1] Update customer reminder message templates in `serviceBot/services/sms_reminders.py` to include `Vehicle:` and `Issue:` lines.

**Checkpoint**: User Story 1 tests pass cleanly.

---

## Phase 3: User Story 2 - Agent Alerts & Reminders (Priority: P1)

**Goal**: Ensure all staff agent messages (booking alert, reassignment, follow-up reminders, urgent reminders, upcoming reminders, supervisor escalations) display the full multi-line alert block containing Customer, Vehicle, Service, Issue, Slot, and response instructions.

### Tests for User Story 2
- [x] T008 [P] [US2] Author test asserting agent `BOOKING` alert includes Customer, Vehicle, Service, Slot, Issue, and reply instructions in `tests/test_notification_vehicle_issue_details.py`.
- [x] T009 [P] [US2] Author test asserting agent Attempt 2 follow-up reminder includes full multi-line alert block with Vehicle and Issue in `tests/test_notification_vehicle_issue_details.py`.
- [x] T010 [P] [US2] Author test asserting agent Attempt 3 urgent reminder includes full multi-line alert block with Vehicle and Issue in `tests/test_notification_vehicle_issue_details.py`.
- [x] T011 [P] [US2] Author test asserting supervisor escalation alert includes Vehicle and Issue in `tests/test_notification_vehicle_issue_details.py`.

### Implementation for User Story 2
- [x] T012 [US2] Ensure `serviceBot/services/sms_router.py` agent templates (`BOOKING`, `REASSIGNED`, `CANCELLED`, previous agent notice) format Vehicle and Issue clearly.
- [x] T013 [US2] Upgrade agent reminder bodies in `serviceBot/services/sms_reminders.py` (Attempts 1, 2, 3, upcoming, supervisor) to render full multi-line alert blocks with Customer, Vehicle, Service, Issue, Slot, and response instructions.

**Checkpoint**: User Story 2 tests pass cleanly.

---

## Phase 4: User Story 3 - Clean Fallback Formats & Edge Case Hardening (Priority: P2)

**Goal**: Ensure partial vehicle fields (missing year/model) and empty/generic issues format cleanly without "None", "null", or "N/A" strings.

### Tests for User Story 3
- [x] T014 [P] [US3] Author test with null vehicle year and empty issue verifying no "None" or "Issue: N/A" appears in customer and agent messages in `tests/test_notification_vehicle_issue_details.py`.

### Implementation for User Story 3
- [x] T015 [US3] Implement clean vehicle and issue line sanitization helpers in `serviceBot/services/sms_router.py` and `serviceBot/services/sms_reminders.py`.

---

## Phase 5: Regression & Full Verification

- [x] T016 Run `./run_tests.sh` across the complete test suite to verify 0 regressions.
