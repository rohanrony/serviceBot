# Implementation Plan: Appointment Reminders, Dual Confirmation, Business-Hours Escalation & 4-Hour Booking Buffer

**Branch**: `002-appointment-reminder-escalation` | **Date**: 2026-09-30 | **Spec**: [specs/002-appointment-reminder-escalation/spec.md](file:///Users/rohanroy/Coding/voiceService/specs/002-appointment-reminder-escalation/spec.md)

**Input**: Feature specification from `/specs/002-appointment-reminder-escalation/spec.md`

---

## Summary

This feature implements a reliable, business-hours aware reminder, confirmation, and escalation system for customer appointments:
1. **4-Hour Advance Booking Planning Buffer**: Prevents immediate chaotic walk-ins by programmatically enforcing that appointments cannot be booked earlier than `current_time + 4 hours` across both AI voice telephony and the portal.
2. **Immediate Dual Notification & 3-Attempt Cadence**: Dispatches Attempt 1 immediately upon booking to both customer (informational) and assigned technician (confirmation prompt), followed by up to 3 structured notification attempts adapted to the booking horizon, with automatic delivery retries.
3. **Horizon-Adaptive Assignment Acceptance SLA**: Evaluates technician confirmation deadlines in elapsed **business hours from booking**, rather than a static naive $T-2\text{ hours}$. Advance bookings (>24h) enforce a 4-business-hour acceptance SLA so that non-responsive technicians trigger early escalation days in advance.
4. **Business-Hours Escalation & Morning Grace**: Escalation countdowns pause overnight and over weekends, and early-morning appointments apply a morning grace rule, ensuring zero false alarms during off-hours.
5. **Supervisor Escalation Queue & Single-Click Reassignment**: Provides immediate SMS alerts to the supervisor upon cutoff timeout or explicit agent decline, accompanied by an escalation dashboard on the portal with candidate technician ranking and one-click reassignment.

---

## Technical Context

**Language/Version**: Python 3.11+  
**Primary Dependencies**: FastAPI, Pydantic, Twilio SDK (SMS & Voice), ElevenLabs Conversational AI, Google Calendar API (`serviceBot/services/google_calendar.py`), psycopg / PostgreSQL connection pool.  
**Storage**: PostgreSQL (`service_requests`, `sms_reminders`, `staff_agents`, `customers`, `service_request_audit_log`).  
**Testing**: `pytest` via `./run_tests.sh` (unit tests, integration tests, mock webhook tests).  
**Target Platform**: Linux Container (Render Web Service) executing FastAPI with background reminder worker threads.  
**Project Type**: Voice AI & Telephony Web Service with Shop Dispatcher Portal.  
**Performance Goals**:
- 4-hour lead time validation check latency < 10ms.
- Inbound confirmation SMS processing latency < 100ms.
- Escalation dispatch to supervisor phone within 15 seconds of cutoff expiration.  
**Constraints**: Zero false-positive escalation alerts dispatched outside of configured shop operating business hours; backward compatible with existing appointment records and calendar events.  
**Scale/Scope**: Real-time service intake for Davidson Car Care.  

---

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Compliance Assessment | Gate Status |
|---|---|---|
| **I. Library-First** | Lead time validation, business hours math, and cutoff algorithms implemented as modular library functions in `serviceBot/services/booking.py` and `serviceBot/services/sms_reminders.py`. | **PASS** |
| **II. Test-First (TDD)** | Unit and contract tests defined in `quickstart.md` and implemented in `tests/` before modifying live application logic. Verified via `./run_tests.sh`. | **PASS** |
| **III. Observability** | Structured logging via `serviceBot.logger` for all dispatch attempts, agent confirmations, declines, and supervisor escalations. | **PASS** |
| **IV. Integration Testing** | Endpoints in `serviceBot/api/telephony.py` and `serviceBot/api/portal.py` validated with simulated Twilio webhooks and status callbacks. | **PASS** |
| **V. Simplicity & YAGNI** | Extends existing tables (`service_requests`, `sms_reminders`) with targeted columns and indexes; reuses existing background worker without introducing external queuing infrastructure like Celery/Redis. | **PASS** |

---

## Project Structure

### Documentation (this feature)

```text
specs/002-appointment-reminder-escalation/
├── spec.md              # Feature specification
├── plan.md              # Implementation plan (this file)
├── research.md          # Phase 0 architectural research & decisions
├── data-model.md        # Phase 1 schema, state machines & validation rules
├── quickstart.md        # Phase 1 verification & test execution guide
├── contracts/           # Phase 1 interface specifications
│   ├── booking-lead-time-contract.md
│   ├── sms-confirmation-webhook-contract.md
│   └── escalation-portal-api-contract.md
└── checklists/
    └── requirements.md  # Quality checklist
```

### Source Code Modifications (repository root)

```text
serviceBot/
├── db/
│   ├── migrations/
│   │   └── 0002_reminders_escalation.sql       # New columns & indexes
│   ├── connection.py                            # Table schemas & init
│   └── queries.py                               # DB queries for confirmation, cutoff & reassignment
├── services/
│   ├── booking.py                               # 4-hour lead time validation
│   ├── sms_reminders.py                         # Cutoff algorithm, 3-attempt scheduler, polling worker
│   ├── sms_classifier.py                        # Inbound agent CONFIRM/DECLINE keyword parser
│   └── twilio_sms.py                            # Multi-attempt SMS dispatch with retry backoff
├── api/
│   ├── telephony.py                             # Tool validation & SMS webhook routing
│   └── portal.py                                # Escalation queue & reassignment endpoints
├── config.json                                  # Default timing thresholds & business hours
└── static/
    ├── app.js                                   # Portal escalation banner, badge & reassignment modal
    └── index.html                               # Escalated appointment UI tab / badge
tests/
├── test_booking_lead_time.py                    # 4-hour buffer validation tests
├── test_sms_reminders_cadence.py                # 3-attempt cadence & delivery retry tests
├── test_horizon_escalation_cutoff.py            # Business hours & morning grace math tests
├── test_agent_sms_confirmation.py               # Inbound CONFIRM, DECLINE, race condition tests
└── test_portal_escalation_api.py                # Escalation queue & reassignment API tests
```

---

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|---|---|---|
| Horizon-Adaptive Cutoff Formula | Differentiates advance bookings (>24h) from same-day bookings (<6h). | A fixed T-2 cutoff leaves multi-day advance bookings unconfirmed until the day of service, causing dispatcher crisis. |
| Inbound SMS Routing Disambiguation | Allows technicians to confirm via simple SMS reply without web portal login. | Requiring mobile web portal login introduces high friction for technicians working in garage bays. |
