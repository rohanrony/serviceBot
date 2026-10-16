# Quickstart Validation Guide: Catalog Service Agent Tagging & Multi-Service Scheduling

**Feature**: `006-catalog-service-agent-tagging`  
**Date**: 2026-10-15  

---

## Prerequisites & Environment
Ensure virtual environment is active and local test suite runs:
```bash
source .venv/bin/activate
pytest tests/test_db_queries.py -q
```

---

## Scenario 1: Admin Tags Agents to Catalog Services via Portal API
1. Create/Update a service with assigned agent IDs `[1, 2]`:
   ```bash
   curl -X PUT http://localhost:8000/api/v1/portal/services/1 \
     -H "Content-Type: application/json" \
     -d '{"name": "Oil Change", "price_range": "$40-70", "duration_minutes": 30, "agent_ids": [1, 2]}'
   ```
2. Verify returned service contains:
   `"assigned_agent_ids": [1, 2]`.
3. Clear tags to test untagged fallback:
   ```bash
   curl -X PUT http://localhost:8000/api/v1/portal/services/1 \
     -H "Content-Type: application/json" \
     -d '{"name": "Oil Change", "price_range": "$40-70", "duration_minutes": 30, "agent_ids": []}'
   ```
   **Expected**: `"is_open_to_all_agents": true`.
4. Automated Test Command:
   ```bash
   pytest tests/test_catalog_agent_tagging.py -k "test_service_agent_tagging_crud" -v
   ```

---

## Scenario 2: Single-Agent Preference at Target Time
1. Setup: Technician John is qualified for both "Oil Change" (30 min) and "Tire Rotation" (30 min).
2. Customer checks availability for "2026-10-16 10:00:00".
3. John is free from 10:00 to 11:00.
4. **Expected Outcome**:
   - System returns John as the sole assigned technician for 60 minutes.
   - Only 1 appointment request is generated for John from 10:00 to 11:00.
5. Automated Test Command:
   ```bash
   pytest tests/test_multi_service_scheduling.py -k "test_single_agent_preferred_when_available" -v
   ```

---

## Scenario 3: Back-to-Back Multi-Agent Allocation (0-Minute Buffer)
1. Setup: Technician John is qualified ONLY for "Oil Change" (30 min). Technician Sarah is qualified ONLY for "Brake Inspection" (60 min).
2. Customer requests both services at 10:00 AM.
3. John is free 10:00–10:30; Sarah is free 10:30–11:30.
4. **Expected Outcome**:
   - Booking assigns John for Oil Change (10:00–10:30 AM).
   - Booking assigns Sarah for Brake Inspection (10:30–11:30 AM).
   - Both appointments share the same `visit_group_id` and cross-link via `linked_appointment_id`.
   - 0-minute gap between segments.
5. Automated Test Command:
   ```bash
   pytest tests/test_multi_service_scheduling.py -k "test_back_to_back_split_allocation" -v
   ```

---

## Scenario 4: Dynamic Closing Boundary Enforcement
1. Set `business_hours_end: 17` (5:00 PM) in `serviceBot/config.json`.
2. Customer requests a 90-minute multi-service appointment at 4:00 PM (16:00).
3. **Expected Outcome**:
   - Appointment is rejected because 16:00 + 90 mins = 17:30 (past closing).
   - An appointment at 3:00 PM (15:00 to 16:30) is accepted.
4. Automated Test Command:
   ```bash
   pytest tests/test_multi_service_scheduling.py -k "test_dynamic_closing_boundary" -v
   ```

---

## Scenario 5: Atomic Rollback on Concurrent Conflict
1. Simulate concurrent booking: Lock Sarah's slot at 10:30 AM.
2. Attempt multi-service booking requiring John at 10:00 AM and Sarah at 10:30 AM.
3. **Expected Outcome**:
   - Booking fails with `BookingConflictError`.
   - John's temporary reservation at 10:00 AM is rolled back cleanly.
   - Zero orphaned records in `service_requests` and `mock_calendar_slots`.
4. Automated Test Command:
   ```bash
   pytest tests/test_multi_service_scheduling.py -k "test_atomic_multi_segment_rollback" -v
   ```
