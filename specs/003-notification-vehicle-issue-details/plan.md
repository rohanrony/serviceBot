# Implementation Plan: Vehicle Details and Issue Description in Customer and Agent Notifications

**Branch**: `003-notification-vehicle-issue-details` | **Date**: 2026-10-08 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/003-notification-vehicle-issue-details/spec.md`

## Summary

Enhance customer and staff agent appointment notifications across all lifecycle stages (initial booking, rescheduling, cancellations, status updates, and reminder cycles) to consistently and cleanly display both the vehicle/asset details (e.g., "2021 Toyota Camry") and reported issue description (e.g., "Squeaking front brakes"). Implement structured labeled lines for customer notifications and full multi-line alert blocks for all agent follow-up and reminder attempts, backed by robust fallback logic for partial or missing inputs.

## Technical Context

**Language/Version**: Python 3.13 / FastAPI  
**Primary Dependencies**: Twilio Python SDK, PostgreSQL (psycopg2)  
**Storage**: PostgreSQL (`service_requests`, `customers`, `vehicles`, `staff_agents`, `sms_reminders`, `sms_log`)  
**Testing**: `pytest`, `./run_tests.sh`  
**Target Platform**: Linux / macOS  
**Project Type**: Voice AI Backend & Telephony Service  
**Performance Goals**: String template rendering < 1ms; zero added database roundtrips during normal message dispatch  
**Constraints**: SMS 160 GSM-7 / UCS-2 character concatenation compatibility; 100% offline mock execution; adherence to VoiceAI Constitution v1.2.0  

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- [x] **Principle I (Simple Architecture & Clear Ownership)**: SMS template formatting remains strictly inside `sms_router.py` and `sms_reminders.py`. No competing formatter abstractions.
- [x] **Principle II (Reliable State & Provider Operations)**: Formatting is idempotent and pure. Does not alter database state or retry counts.
- [x] **Principle III (Privacy & Trusted Integrations)**: No sensitive credentials or customer PII leaked into unredacted logs.
- [x] **Principle IV (Strict Test-First Development & Contract Coverage)**: Full TDD Red-Green-Refactor. All new behavioral contracts covered in `tests/test_notification_vehicle_issue_details.py`. Offline mocks only.
- [x] **Principle V (Observable Calls & Human Recovery)**: Messages cleanly present actionable information (appointment id, vehicle, issue, slot, response commands `CONFIRM` / `DECLINE`).

## Project Structure

### Documentation (this feature)

```text
specs/003-notification-vehicle-issue-details/
├── spec.md              # Feature specification & user clarifications
├── plan.md              # This file
├── checklists/
│   └── requirements.md  # Spec quality checklist
└── tasks.md             # Implementation tasks
```

### Source Code

```text
serviceBot/
├── services/
│   ├── sms_router.py     # Core notification router (customer & agent dispatch templates)
│   └── sms_reminders.py  # Pre-appointment reminder worker & agent follow-up templates
tests/
├── test_notification_vehicle_issue_details.py  # New behavioral test suite
├── test_sms_router.py                          # Existing router regression suite
└── test_no_duplicate_booking_messages.py       # Existing duplicate prevention suite
```

## Implementation Phases

### Phase 1: Clarified Formats & Template Design
1. **Customer Messages**:
   - Add `Vehicle: {veh}` and `Issue: {iss}` to all customer templates (`BOOKING`, `RESCHEDULED`, `CANCELLED`, `STATUS_IN_PROGRESS`, `STATUS_COMPLETED`).
   - Graceful helper `_format_issue_line(issue)`: returns `f"Issue: {clean_issue}\n"` if valid, empty string if "N/A" or missing.
   - Graceful helper `_format_vehicle_line(veh)`: returns `f"Vehicle: {clean_veh}\n"` if valid, empty string if "N/A" or missing.
2. **Customer Reminders (`sms_reminders.py`)**:
   - Ensure `fetch_appointment_customer_details` populates `"issue": row.get("issue_description") or ""`.
   - Include `Vehicle: ...` and `Issue: ...` in immediate booking, intermediate follow-up, and upcoming customer reminders.
3. **Agent Messages (`sms_router.py` & `sms_reminders.py`)**:
   - `sms_router.py`: Ensure initial alert, reassignment alert, and cancellation notices include both vehicle and issue.
   - `sms_reminders.py`: Upgrade agent reminder templates (Attempts 1, 2, 3, upcoming, supervisor) from brief one-liners to full multi-line alert blocks containing Customer, Vehicle, Service, Issue, Slot, and response instructions.

### Phase 2: Test-Driven Development (TDD)
- Author `tests/test_notification_vehicle_issue_details.py` verifying all customer and agent formats (Red phase).
- Update implementation in `sms_router.py` and `sms_reminders.py` (Green phase).
- Verify all existing suites pass without regression (`./run_tests.sh`).
