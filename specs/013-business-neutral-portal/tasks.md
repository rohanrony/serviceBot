# Tasks: Generalize Business Configuration and Simplify Portal

**Input**: Design documents from `specs/013-business-neutral-portal/`
**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/`

---

## Phase 1: Setup & Traceability

- [x] T001 Initialize feature workspace and verify `.specify/feature.json` points to `specs/013-business-neutral-portal`.
- [x] T002 Establish `test-coverage.yaml` with all acceptance contract mappings and offline/live obligations.

---

## Phase 2: Tests First (Red Phase)

- [x] T003 [P] [US1] Author failing unit tests for canonical business settings persistence and separate voice provider status reporting in `tests/test_portal_config.py`.
- [x] T004 [P] [US2] Author failing tests for generic intake field classification (detail types, stable keys, repeated types, agent prompt instructions for required vs. optional fields, vehicle fabrication prevention) in `tests/test_business_profile.py`.
- [x] T005 [P] [US3] Author failing tests for date-first availability check and customer consent validation in `tests/test_portal_booking_slots.py`.
- [x] T006 [P] [US6] Author failing tests for staff agent email and phone validation (create rejection on blank/invalid, reject clearing on update, allow unrelated updates on incomplete legacy rows) in `tests/test_staff_agent_validation.py`.
- [x] T007 [P] [US7] Author failing tests for inbound message acknowledgment using configured support helpline in `tests/test_sms_acknowledgment.py`.
- [x] T008 [P] [E2E] Author comprehensive Playwright browser tests in `e2e/test_business_neutral_portal.py` covering all 12 changes (save confirmation modal, removed controls, catalogue redesign, SMS inbox expansion, date-first booking, hidden API keys fallback).

---

## Phase 3: Core Implementation (Green Phase)

### User Story 1 - Canonical Business Settings & Prompt Regeneration
- [x] T009 Update `serviceBot/services/business_profile.py` and `serviceBot/api/portal.py` to make Business Settings the canonical owner of support helpline (`support_phone_number`), synchronizing with `sms_config` in database.
- [x] T010 Update `serviceBot/api/portal.py` `update_config` to report saved settings separately from voice provider synchronization status (`provider_sync`).
- [x] T011 Update `serviceBot/static/index.html` and `serviceBot/static/app.js` to move address, maps link, timezone, and support helpline into Business Settings; remove them from Notifications; remove automotive and prompt-regen checkboxes.
- [x] T012 Implement Save confirmation dialog in `serviceBot/static/app.js`: explain prompt replacement, Cancel makes zero writes/calls, Confirm saves and regenerates prompt. Display separate provider sync status on completion.

### User Story 2 - Generic Intake Classification & Prompt Updates
- [x] T013 Update `IntakeField` model in `serviceBot/services/business_profile.py` with `detail_type` (general, asset_type, brand, model, serial_number), text/number types, and identifier validation.
- [x] T014 Update `build_business_prompt` in `serviceBot/services/business_profile.py` to instruct agent to solicit missing required fields by label, but prohibited from asking for optional fields (allowing volunteered details).
- [x] T015 Update `serviceBot/services/booking.py` `create_service_request` to store generic intake in `intake_data` JSONB and prevent fabricating dummy vehicle records when vehicle data is absent.
- [x] T016 Update `serviceBot/static/app.js` `addBusinessIntakeRow` and `loadBusinessProfile` to support detail type dropdowns, repeated detail types, stable keys, and expose legacy automotive fields as editable generic equivalents.

### User Story 3 - Date-First Booking & Slot Availability Flow
- [x] T017 Update `serviceBot/static/index.html` Service Request modal (`sr-form`): replace manual `datetime-local` input with visible date picker, Check Availability button, and returned slots dropdown.
- [x] T018 Update `serviceBot/static/app.js` slot selection logic: display times in business timezone, clear stale slot choices on input change, handle loading/retry/empty-day/unavailable states, preserve unscheduled requests and unchanged schedules.
- [x] T019 Update service request saving logic in `app.js` and `serviceBot/api/portal.py` to require customer consent checkbox when changing appointment time and revalidate availability atomically.

### User Story 4 - Service Catalogue Redesign & Business-Wide Asset Details
- [x] T020 Remove "Load Automotive Example Catalog" button and its client click handler from `serviceBot/static/index.html` and `serviceBot/static/app.js`.
- [x] T021 Redesign Add Service form and Edit Service drawer in `serviceBot/static/index.html` and `serviceBot/static/style.css` using the visual system (sections, spacing, accessible labels).
- [x] T022 Replace Automotive Details checkbox with Asset Details summary badge list and link to Business Settings in both catalogue forms.

### User Story 5 - Portal Simplification
- [x] T023 Remove Appointment Context sidebar from `#sms-view` in `serviceBot/static/index.html` and clean up unused sidebar rendering in `serviceBot/static/app.js`; expand conversation viewport to full width.
- [x] T024 Hide Connection Help card in Admin configuration (`#gmail-view`) in `serviceBot/static/index.html`.
- [x] T025 Hide API Keys & Voice settings tab and pane in `serviceBot/static/index.html`; update `serviceBot/static/app.js` navigation routing so `#config/voice-settings` falls back to Business Settings.
- [x] T026 Remove duplicate test phone whitelist section from Notifications subtab in `serviceBot/static/index.html` and update references in `serviceBot/static/app.js`.

### User Story 6 - Staff Contact Validation
- [x] T027 Update `StaffAgentCreate` in `serviceBot/api/portal.py` to require nonblank, valid email and phone number; update frontend "Add Staff Member" form validation.
- [x] T028 Update `StaffAgentUpdate` in `serviceBot/api/portal.py` to reject explicit clearing of email or phone with 400 Bad Request, while allowing unrelated updates on older incomplete profiles.

### User Story 7 - Support Helpline Message Acknowledgment
- [x] T029 Update `serviceBot/services/sms_classifier.py` `handle_agent_confirmation_action` and related receipt dispatchers to reply with "Message received. For urgent scheduling assistance, please call {support helpline}." when helpline is configured, or "Message received." when unconfigured.

---

## Phase 4: Refactor, Verification & Live Readiness

- [x] T030 Execute focused unit tests and verify all Red tests turn Green.
- [x] T031 Execute browser E2E test suite in `e2e/test_business_neutral_portal.py` and verify all browser assertions pass.
- [x] T032 Update `live_simulations/scenarios.json` and `test-coverage.yaml` with accurate scenario assertions, prerequisites, read-back mechanisms, and spending ceilings.
- [x] T033 Run complete offline test suite via `./run_tests.sh --verify` and resolve any regressions.
- [x] T034 Complete `speckit-converge` review and generate consistency report.

---

## Phase 5: Review Findings Resolution (Correctness Defects)

- [x] T035 [Finding 1] Refresh application timezone dynamically after Business Settings saves (`loadBusinessProfile`, `applyBusinessProfile`, `setAppBusinessTimezone`).
- [x] T036 [Finding 2] Keep support helpline consistent across configuration (`config.json`) and database (`sms_config`), treating legacy empty/null/whitespace updates as omitted while updating both stores on explicit changes and avoiding resurrected values or placeholder fallbacks in handoff/acknowledgment.
- [x] T037 [Finding 3] Detect legacy intake using configuration state (`collect_vehicle_details=true`, generic profile state, or absent persisted profile) rather than industry/name substring heuristics.
- [x] T038 [Finding 4] Attempt ElevenLabs prompt synchronization for every configured target agent (development and production) with per-agent outcome reporting and overall synced/failed status without automatic retries.
- [x] T039 [Finding 5] Reject malformed intake shapes (arrays, strings, numbers, booleans) before normalization in `normalize_legacy_intake_args` and `parse_voice_intake`, preventing mutations.
- [x] T040 [Finding 6] Display voice provider synchronization unavailable status with persistent warning styling and notice text without claiming the live voice agent was updated.
- [x] T041 Author and verify failing regressions (Red phase) for all 6 findings before implementation, then verify all tests turn Green.
- [x] T042 [Finding 7] Fix handoff templates when helpline is cleared: replace fragile sentence removal with neutral fallback "Message received." when template needs missing support number, preserve custom templates without placeholders, and render configured helpline normally.
- [x] T043 [Finding 8] Make handoff honor canonical helpline resolver consistently: blank canonical value means cleared, fall back to database only when canonical setting is absent, and prevent in-hours/out-of-hours resurrection.
- [x] T044 Author and verify failing regressions (Red phase) in `tests/test_handoff_regressions.py` covering all template wordings, custom templates, canonical clearing sync failures, and legacy fallbacks; then verify all tests turn Green.
- [x] T045 [Finding 9] Fix handoff template rendering defect for customer_name: resolve customer_name from existing customer/conversation data, render all supported variables consistently, fallback to neutral "Message received." on missing required variables/unsupported placeholders/malformed templates without partial rendering, and maintain comprehensive regressions in `tests/test_handoff_regressions.py`.
- [x] T046 [Finding 10] Clear cached booking time when the slot dropdown is cleared (`serviceBot/static/app.js`), resetting consent and compatibility time input, ensuring new request remains unscheduled with null booking_time and preserving existing appointment schedule when no replacement slot is selected.
- [x] T047 [Finding 11] Validate staff email addresses consistently (`serviceBot/api/portal.py`) with shared `validate_staff_email` regex, trimming whitespace, requiring valid email on create, rejecting malformed emails and explicit blank updates while allowing unrelated edits on legacy incomplete profiles.
- [x] T048 Update obsolete suite tests for date-first scheduling, business timezone ownership, hidden panes, and required staff phone numbers; update `test-coverage.yaml` with real collected test IDs.
