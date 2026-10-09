# Tasks: Configurable Business Time Zone Settings & System-Wide Timezone Linking

**Feature Branch**: `005-configurable-business-timezone`  
**Input**: Feature specification (`spec.md`) and implementation plan (`plan.md`)

---

## Phase 1: Setup & Foundational Infrastructure

- [x] T001 Add default `"business_timezone": "America/New_York"` to `serviceBot/config.json`
- [x] T002 Write initial failing unit tests for centralized timezone service in `tests/test_configurable_business_timezone.py`
- [x] T003 Implement centralized timezone service in `serviceBot/services/timezone_service.py`

---

## Phase 2: User Story 1 - Admin Configures Shop Time Zone in Portal Settings (Priority: P1)

- [x] T004 [US1] Add failing API tests for `GET /config`, `POST /config`, and `PUT /sms/config` timezone updating and IANA validation in `tests/test_configurable_business_timezone.py`
- [x] T005 [US1] Update `ConfigUpdatePayload`, `get_config()`, `update_config()`, and `/sms/config` in `serviceBot/api/portal.py` to validate and persist `business_timezone`
- [x] T006 [US1] Add Business Time Zone select dropdown to Settings UI in `serviceBot/static/index.html`
- [x] T007 [US1] Wire settings load, save, and validation for `business_timezone` in `serviceBot/static/app.js`

---

## Phase 3: User Story 2 - Backend Booking & Availability Linked to Configured Time Zone (Priority: P1)

- [x] T008 [US2] Add failing tests for availability slots and 4-hour lead time restriction in `tests/test_configurable_business_timezone.py`
- [x] T009 [US2] Refactor `serviceBot/services/calendar_availability.py` to use `timezone_service` for business hours and 4-hour lead-time calculations
- [x] T010 [US2] Refactor `serviceBot/services/booking.py` to use dynamic business timezone from `timezone_service`
- [x] T011 [US2] Refactor `serviceBot/services/google_calendar.py`, `serviceBot/services/calendar_sync.py`, and `serviceBot/services/gmail.py` to use configured business timezone and dynamic offset

---

## Phase 4: User Story 3 - Quiet Hours & Reminder Escalation Linked to Configured Time Zone (Priority: P1)

- [x] T012 [US3] Add failing tests for quiet hours and reminder scheduling in `tests/test_configurable_business_timezone.py`
- [x] T013 [US3] Refactor `serviceBot/services/quiet_hours.py` to evaluate quiet hours and morning release times using `timezone_service`
- [x] T014 [US3] Refactor `serviceBot/services/sms_reminders.py` to calculate reminder cadences and cutoff deadlines using `timezone_service`

---

## Phase 5: User Story 4 - Consistent Time Display Across All Portal Views (Priority: P1)

- [x] T015 [US4] Update timestamp formatting functions in `serviceBot/static/app.js` to format dates and times using `Intl.DateTimeFormat` with configured business timezone
- [x] T016 [US4] Add timezone badge and indicator in dashboard header and appointment views in `serviceBot/static/index.html` and `serviceBot/static/app.js`

---

## Phase 6: Polish & Verification

- [x] T017 Execute complete test suite via `./run_tests.sh` to confirm zero regressions
- [x] T018 Execute Spec-Kit converge loop to verify complete requirement fulfillment
