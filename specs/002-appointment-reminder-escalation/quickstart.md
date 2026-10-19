# Quickstart Validation Guide: Appointment Reminders, Confirmation & Escalation

**Feature**: [002-appointment-reminder-escalation](file:///Users/rohanroy/Coding/voiceService/specs/002-appointment-reminder-escalation/spec.md)  
**Date**: 2026-09-30  
**Status**: Ready for Verification  

---

## Prerequisites

1. Active Python virtual environment:
   ```bash
   source .venv/bin/activate
   ```
2. Database initialized with migrations and seed data:
   ```bash
   python -m serviceBot.db.seed
   ```

---

## Validation Scenarios

### Scenario 1: 4-Hour Minimum Advance Notice Guard

**Objective**: Verify bookings $< 4\text{ hours}$ in advance are rejected, while $\ge 4\text{ hours}$ are accepted.

```bash
# 1. Attempt booking for 2 hours from now (MUST FAIL)
curl -X POST http://localhost:8000/api/v1/portal/service-requests \
  -H "Content-Type: application/json" \
  -d '{
    "customer_id": 1,
    "booking_time": "'$(date -v+2H "+%Y-%m-%d %H:00:00")'",
    "service_type": "Oil Change",
    "issue_description": "Test lead time rejection"
  }'
# Expected Output: HTTP 422 with LEAD_TIME_VIOLATION error code.

# 2. Attempt booking for 5 hours from now within business hours (MUST SUCCEED)
curl -X POST http://localhost:8000/api/v1/portal/service-requests \
  -H "Content-Type: application/json" \
  -d '{
    "customer_id": 1,
    "booking_time": "'$(date -v+5H "+%Y-%m-%d %H:00:00")'",
    "service_type": "Oil Change",
    "issue_description": "Valid 5-hour lead time booking"
  }'
# Expected Output: HTTP 201 Created with status 'pending' and confirmation_status 'pending_agent_confirmation'.
```

---

### Scenario 2: Immediate Attempt 1 Dispatch on Booking

**Objective**: Verify both customer and assigned technician receive Attempt 1 notifications immediately upon booking.

```bash
# Verify outgoing reminder queue
python -c "
from serviceBot.db.connection import get_db_connection, dict_cursor
with get_db_connection() as conn:
    with dict_cursor(conn) as cur:
        cur.execute('SELECT id, recipient_type, attempt_number, attempt_kind, status FROM sms_reminders ORDER BY id DESC LIMIT 2;')
        print(cur.fetchall())
"
# Expected Output: 2 rows with attempt_number=1, attempt_kind='immediate_booking', one for 'customer' and one for 'agent'.
```

---

### Scenario 3: Agent SMS Confirmation Keyword ("CONFIRM")

**Objective**: Verify that an inbound SMS reply "CONFIRM" from the technician's phone transitions the appointment to `confirmed`.

```bash
# Simulate inbound Twilio SMS from technician phone (+19195550001)
curl -X POST http://localhost:8000/api/v1/telephony/sms/inbound \
  -d "From=+19195550001&To=+19195550199&Body=CONFIRM&MessageSid=SM_TEST_CONFIRM_01"

# Verify appointment status
python -c "
from serviceBot.db.connection import get_db_connection, dict_cursor
with get_db_connection() as conn:
    with dict_cursor(conn) as cur:
        cur.execute('SELECT id, confirmation_status, confirmed_at, escalation_status FROM service_requests WHERE staff_agent_id = 1 ORDER BY id DESC LIMIT 1;')
        print(cur.fetchone())
"
# Expected Output: confirmation_status='confirmed', confirmed_at is set, escalation_status='none'.
```

---

### Scenario 4: Agent Explicit Decline ("DECLINE") $\rightarrow$ Instant Escalation

**Objective**: Verify that replying "DECLINE" bypasses wait times and immediately flags the appointment as escalated for supervisor reassignment.

```bash
# Simulate inbound Twilio SMS with "DECLINE"
curl -X POST http://localhost:8000/api/v1/telephony/sms/inbound \
  -d "From=+19195550001&To=+19195550199&Body=DECLINE&MessageSid=SM_TEST_DECLINE_01"

# Query escalation queue
curl http://localhost:8000/api/v1/portal/service-requests?escalated=true
# Expected Output: JSON list containing the appointment with escalation_status='escalated', escalation_reason='AGENT_DECLINED'.
```

---

### Scenario 5: Horizon-Adaptive Cutoff & Business Hours Pausing

**Objective**: Verify that an appointment booked at 5:00 PM for tomorrow at 1:00 PM pauses overnight and calculates a morning cutoff.

```bash
python -c "
from datetime import datetime
from serviceBot.services.sms_reminders import calculate_effective_confirmation_cutoff

booked_at = datetime.strptime('2026-10-05 17:00:00', '%Y-%m-%d %H:%M:%S') # Mon 5 PM
appt_time = datetime.strptime('2026-10-06 13:00:00', '%Y-%m-%d %H:%M:%S') # Tue 1 PM

cutoff = calculate_effective_confirmation_cutoff(booked_at, appt_time)
print('Calculated Cutoff:', cutoff)
# Expected Output: 2026-10-06 09:00:00 (Mon 5-6 PM = 1h, Tue 8-9 AM = 1h; 3 business hours total, or Tue 10:00 AM)
"
```

---

### Scenario 6: Supervisor One-Click Reassignment

**Objective**: Reassign an escalated appointment to another technician from the portal.

```bash
curl -X POST http://localhost:8000/api/v1/portal/service-requests/1042/reassign \
  -H "Content-Type: application/json" \
  -d '{
    "new_staff_agent_id": 2,
    "reason": "Technician declined"
  }'
# Expected Output: HTTP 200 with escalation_status='reassigned', notification_sent_to_new_agent=True.
```

---

## Automated Test Suite

To run all unit, contract, and integration tests:

```bash
./run_tests.sh
```


## US4 Normal Dropdown Recovery Verification (2026-10-19)

This follow-up was investigated and implemented locally. Render read-only logs confirm
request 44 failed normal reassignment because agent 12 had no connected Google account;
the 409 toast used a generic time-unavailable message. Calendar validation is retained.

Requirement mapping and review:

| Contract | Observable evidence |
| --- | --- |
| FR-016 | Service/database test with a custom 23-minute setting; assigned/unassigned HTTP and Chromium cases assert pending confirmation, reassigned state, cleared reason/confirmed_at, immediate banner removal and reload; cutoff boundary checked. |
| FR-017 | Unknown calendar, inactive and unqualified agents; grouped-service intersection; final submission revalidation after capacity changes. |
| FR-018 | Full persisted request/reservation/segment/outbox/audit/reminder/slot snapshots on rejection; same-agent no-op preserves escalation and deadline; browser error restores original assignee; confirmed linked companions remain unchanged. |
| FR-019 | Real outbox worker with captured Twilio transport verifies replacement/former-agent recipients and previously unassigned dispatch; exact persisted cutoff checked after processing. |

Validation commands and results after the final runtime change:

- `./run_tests.sh --all --tb=short`: **2137 passed**, 15 existing deprecation warnings.
- `./run_tests.sh --file e2e/test_escalated_assignment.py e2e/test_workflows.py e2e/test_booking_contracts.py e2e/test_staff_lifecycle_contracts.py e2e/test_portal_availability_loading.py e2e/test_portal_read_responsiveness.py e2e/test_notification_workflows.py e2e/test_reminder_contracts.py e2e/test_multiservice_contracts.py e2e/test_portal_recent_features.py e2e/test_appointments.py --tb=short -q`:
  **205 passed**, including all **15** new HTTP/worker/Chromium cases.
- Cached offline Ruff: new tests pass the configured lint rules; changed Python runtime
  files pass E9/F63/F7/F82 checks. JavaScript syntax (`node --check`) and `git diff --check` pass.

Analysis found no blocking inconsistencies in the four scoped follow-up requirements and
eight implementation/verification tasks. Convergence found T041: unassigned recovery
reused BOOKING's deduplication key and suppressed the new prompt. Its new regression failed,
and the classification was repaired. Review then found T042: same-time staff changes reset
confirmed companion segments. A new persisted-state regression failed, and companion updates
were restricted to actual time changes. The third scoped convergence found no actionable
gaps. Historical feature acceptance outside this follow-up was not re-audited.

Local PostgreSQL/Chromium access required execution outside the restricted sandbox. All
test databases were disposable and external providers were mocked/captured. These results
do not establish live SMS delivery. Production was read-only; no assignment, Google account,
notification, deployment, commit, or push was performed. A final read-only database check
confirmed agent 12 is active and has no Google account row. That agent needs their Google
Calendar reconnected before the normal scheduled-assignment path can use them.
