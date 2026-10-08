# Implementation Plan: Staff Agent Multi-Appointment Confirmation Disambiguation & Batch Processing

**Branch**: `004-agent-multi-appointment-confirmation` | **Date**: 2026-10-08 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/004-agent-multi-appointment-confirmation/spec.md`

## Summary

Implement a technician-specific disambiguation and batch confirmation engine within `serviceBot/services/sms_classifier.py` for inbound staff agent SMS/WhatsApp messages. When a technician has a single pending appointment, maintain the instantaneous zero-friction fast path (`CONFIRM`/`C`/`DECLINE`). When a technician has multiple pending appointments, eliminate blind LIFO auto-selection by presenting a clear numbered disambiguation menu upon receiving bare action tokens, supporting index-based selection (`CONFIRM 1`, `C 1`, `1`, `DECLINE 2`), direct ticket ID targeting (`CONFIRM 101`), and atomic batch acceptance (`CONFIRM ALL`).

## Technical Context

**Language/Version**: Python 3.13 / FastAPI  
**Primary Dependencies**: Twilio Python SDK, PostgreSQL (psycopg2)  
**Storage**: PostgreSQL (`service_requests`, `staff_agents`, `sms_reminders`, `sms_log`, `sms_conversations`)  
**Testing**: `pytest`, `./run_tests.sh`  
**Target Platform**: Linux / macOS  
**Project Type**: Voice AI Backend & Telephony Service  
**Performance Goals**: Intent classification & DB resolution < 25ms; atomic multi-record updates in a single transaction  
**Constraints**: Zero regression on existing single-appointment agent and customer confirmation flows; strict adherence to VoiceAI Constitution v1.2.0 (TDD, deterministic ordering, offline test mocks)  

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- [x] **Principle I (Simple Architecture & Clear Ownership)**: Agent confirmation action parsing and state execution remain centralized in `serviceBot/services/sms_classifier.py` (`handle_agent_confirmation_action`). No duplicated routing or competing handlers.
- [x] **Principle II (Reliable State & Provider Operations)**: Status updates (`confirmed`, `declined`, `escalated`) and reminder cancellations execute inside atomic database transactions. In multi-ticket batch processing (`CONFIRM ALL`), all tickets commit together or roll back on error.
- [x] **Principle III (Privacy & Trusted Integrations)**: Phone numbers and technician responses are validated and sanitized. Receipts redact internal database details.
- [x] **Principle IV (Strict Test-First Development & Contract Coverage)**: Comprehensive automated test suite in `tests/test_agent_multi_appointment_confirmation.py` covering fast-path, disambiguation menu generation, index parsing, explicit ID targeting, batch confirmation, and boundary validation before implementation.
- [x] **Principle V (Observable Calls & Human Recovery)**: Out-of-bounds selections and ambiguous requests return actionable prompt guidance rather than silent failures or dropped messages.

## Project Structure

### Documentation (this feature)

```text
specs/004-agent-multi-appointment-confirmation/
├── spec.md              # Feature specification & user stories
├── plan.md              # Implementation plan (this file)
└── tasks.md             # Actionable task list
```

### Source Code & Tests

```text
serviceBot/
├── services/
│   └── sms_classifier.py   # Intent parser and handle_agent_confirmation_action engine
tests/
├── test_agent_multi_appointment_confirmation.py  # New comprehensive test suite
├── test_sms_classifier.py                        # Existing classifier tests
└── test_no_duplicate_booking_messages.py         # Existing duplicate prevention suite
```

## Implementation Phases

### Phase 1: Intent Parser (`serviceBot/services/sms_classifier.py`)
1. Implement `parse_agent_confirmation_intent(body: str) -> dict`:
   - Detect batch keywords: `CONFIRM ALL`, `ACCEPT ALL`, `C ALL`, `YES ALL` -> `action: CONFIRM_ALL`, `selector_type: batch`.
   - Detect batch decline: `DECLINE ALL`, `REJECT ALL`, `NO ALL` -> `action: DECLINE_ALL`, `selector_type: batch`.
   - Regex parse action + target (e.g. `CONFIRM 1`, `C 1`, `CONFIRM #101`, `DECLINE 2`) -> `action: CONFIRM/DECLINE`, `selector_type: numeric`, `value: int`.
   - Parse pure numeric reply (e.g. `1`, `2`) -> `action: CONFIRM`, `selector_type: index`, `value: int`.
   - Parse bare actions (`CONFIRM`, `C`, `ACCEPT`, `DECLINE`) -> `selector_type: bare`.

### Phase 2: Disambiguation & Dispatch Engine (`handle_agent_confirmation_action`)
1. Query all active appointments for candidate agent IDs where `confirmation_status = 'pending_agent_confirmation'` and `status NOT IN ('completed', 'cancelled', 'cancelled_by_customer')`, ordered deterministically by `sr.booking_time ASC, sr.created_at ASC`.
2. **Single Job Case (`len == 1`)**:
   - For `CONFIRM`, `C`, `CONFIRM 1`, `CONFIRM <id>` -> execute standard confirmation fast-path.
   - For `DECLINE`, `DECLINE 1`, `DECLINE <id>` -> execute decline & escalation fast-path.
3. **Multiple Jobs Case (`len > 1`)**:
   - **Bare Action (`CONFIRM` / `DECLINE`)**:
     - Do not guess! Construct formatted numbered menu:
       ```text
       ⚠️ You have {N} assignments awaiting confirmation:
       1️⃣ #{id} - {vehicle} ({time})
       2️⃣ #{id} - {vehicle} ({time})

       Reply CONFIRM 1 (or C 1), CONFIRM 2, or CONFIRM ALL.
       (Or reply DECLINE 1 / DECLINE 2).
       ```
     - Dispatch receipt preserving WhatsApp/SMS transport mode and return status `disambiguation_requested`.
   - **Batch Action (`CONFIRM ALL`)**:
     - In an atomic transaction, update all pending records to `confirmed`, cancel their reminders, and dispatch consolidated confirmation receipt:
       `✅ Confirmed all {N} assignments ({#ids}). Your schedule is up to date!`
   - **Batch Decline (`DECLINE ALL`)**:
     - Mark all declined, escalate to supervisor, and dispatch receipt:
       `❌ Declined all {N} assignments ({#ids}). Supervisor notified.`
   - **Numeric / Index Action (`value`)**:
     - If `1 <= value <= len(pending)`: target `pending[value - 1]`.
     - Else if `value in [p['id'] for p in pending]`: target appointment with matching ID.
     - Else (out-of-bounds): dispatch error message with valid choices.
   - **Post-Action Summary**:
     - When individual appointment is confirmed or declined and other appointments remain pending, include remaining count:
       `Appointment #{id} confirmed. Thank you! ({K} assignment(s) remaining: #{remaining_ids})`

### Phase 3: Test-Driven Verification (TDD)
1. Author `tests/test_agent_multi_appointment_confirmation.py` covering all user stories and edge cases (Red phase).
2. Implement parser and routing logic in `serviceBot/services/sms_classifier.py` (Green phase).
3. Verify test suite and ensure 0 regressions across `./run_tests.sh`.
