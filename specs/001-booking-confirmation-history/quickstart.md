# Quickstart Validation Guide: Booking Confirmation Guard & History Context

**Feature**: `001-booking-confirmation-history`
**Date**: 2026-09-29

## Prerequisites & Environment
Ensure the local test environment is configured:
```bash
# Verify Python venv is active and tests pass
source .venv/bin/activate
pytest tests/test_db_queries.py -q
```

---

## Scenario 1: Preventing Duplicate Booking on Time Change (Deferred Execution & Deduplication)

### Purpose
Validates that if a caller discusses 10:00 AM, then shifts to 10:30 AM before confirming, exactly ONE appointment is persisted.

### Validation Steps
1. Simulate incoming voice tool calls:
   ```python
   # 1. Check availability for 10:00 AM
   # 2. Caller modifies preference to 10:30 AM
   # 3. Booking executed once for 10:30 AM with explicit confirmation
   ```
2. Verify Database State:
   ```sql
   SELECT id, booking_time, duration_minutes, status
   FROM service_requests
   WHERE customer_id = [TEST_CUST_ID] AND booking_type = 'appointment';
   ```
   **Expected**: Exactly 1 record with `booking_time` = 10:30:00. Zero records for 10:00:00.
3. Test Automation Command:
   ```bash
   pytest tests/test_booking_confirmation_guard.py -k "test_single_booking_on_time_change" -v
   ```

---

## Scenario 2: Returning Customer Inbound Context & Issue Description in Appointments

### Purpose
Validates that when an existing customer calls, their upcoming appointment (including vehicle and issue description) is fetched and passed into session context.

### Validation Steps
1. Seed a test customer with an upcoming appointment for "Brake squeak inspection" on Friday at 10:00 AM.
2. Invoke `POST /api/v1/telephony/inbound` with `From="+15551234567"`.
3. Inspect returned TwiML XML:
   **Expected**:
   - `<Parameter name="customer_name" value="[Customer Name]" />`
   - `<Parameter name="upcoming_appointments_summary" value="...Brake squeak inspection..." />`
4. Invoke `get_customer_appointments` tool for `5551234567`:
   **Expected**:
   - Response contains `issue_description`: `"Brake squeak inspection"` and `duration_minutes`: `60`.
5. Test Automation Command:
   ```bash
   pytest tests/test_customer_history_context.py -k "test_inbound_upcoming_appointment_context" -v
   ```

---

## Scenario 3: Consolidating Multiple Issues into an Existing Appointment

### Purpose
Validates that when a customer with an existing appointment adds an issue for the same car, the appointment duration expands and the new issue is appended.

### Validation Steps
1. Existing appointment: Friday 10:00 AM, 45 minutes ("Oil change").
2. Customer adds "Check check engine light" (estimated 45 min).
3. System verifies contiguous availability from 10:00 AM to 11:30 AM.
4. Execute consolidation tool call.
5. Verify Database State:
   ```sql
   SELECT duration_minutes, issue_description 
   FROM service_requests 
   WHERE id = [APPT_ID];
   ```
   **Expected**:
   - `duration_minutes` updated from 45 to 90.
   - `issue_description` contains both "Oil change" and "Check check engine light".
   - Start time remains 10:00 AM; expected end time is 11:30 AM.
6. Test Automation Command:
   ```bash
   pytest tests/test_consolidate_appointment_issues.py -v
   ```

---

## Scenario 4: Start & End Time Disclosure with Extension Notice

### Purpose
Validates that when Rachel quotes an appointment or confirms a booking, she states both start and expected end times, plus the standard extension notice.

### Validation Steps
1. Run conversation simulation:
   ```bash
   python scripts/run_conversation_tests.py
   ```
2. Verify agent response contains:
   - Start time and expected end time (e.g. *"from 10:00 AM to approximately 11:30 AM"*).
   - The required disclosure: *"likely to extend depending on service findings"*.
