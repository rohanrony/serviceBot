# Technical Specification: Service Request Status Workflow, Agent Confirmation & Decision Engine

**Document Version:** 1.1  
**Status:** Ready for Engineering Implementation  
**Target Subsystem:** `serviceBot` Backend API, Database, Worker, Portal Frontend  
**Location:** `docs/prd/serviceRequest_status/service_request_status_technical_spec.md`  

---

## 1. System Architecture Overview

This technical specification details the implementation for the Service Request Status Workflow, Finite State Machine (FSM), Post-Call Agent Confirmation loop, and the Unconfirmed Agent Decision Engine.

```
[ AI Voice Agent / Web Intake ]
             │
             ▼
[ Check Google Calendar Availability ] ──► (Primary Truth)
             │
             ▼
[ Create Service Request (status = 'pending') ]
             │
             ├──────────────────────────────────────────┐
             ▼                                          ▼
[ Send Customer SMS Summary + CANCEL Link ]    [ Trigger Post-Call Agent Notification ]
                                                        │
                                                        ▼
                                           [ agent_escalation.py Worker ]
                                                        │
                                       ┌────────────────┴────────────────┐
                                       ▼                                 ▼
                         [ Agent Accepts (SMS/Email/Portal) ]   [ Agent Declines / SLA Overdue ]
                                       │                                 │
                                       ▼                                 ▼
                         [ Status -> 'confirmed' ]            [ Candidate #2 Auto-Reassign or ]
                                                              [ Manager Dashboard Alert ]
```

---

## 2. Database Schema Specifications

### 2.1 Table `service_requests` Constraints & Columns
The `service_requests` table status CHECK constraint is expanded, and tracking columns are added:

```sql
-- Migration Script: Expand status CHECK constraint and add audit tracking columns
ALTER TABLE service_requests DROP CONSTRAINT IF EXISTS service_requests_status_check;

ALTER TABLE service_requests ADD CONSTRAINT service_requests_status_check 
  CHECK (status IN ('pending', 'confirmed', 'in_progress', 'completed', 'cancelled', 'rescheduled', 'cancelled_by_customer'));

-- Add agent triage lock and SLA tracking columns if not existing
ALTER TABLE service_requests ADD COLUMN IF NOT EXISTS triage_lock_owner INTEGER REFERENCES staff_agents(id) ON DELETE SET NULL;
ALTER TABLE service_requests ADD COLUMN IF NOT EXISTS agent_confirmed_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NULL;
ALTER TABLE service_requests ADD COLUMN IF NOT EXISTS sla_expires_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NULL;
```

### 2.2 Table `service_request_audit_log` DDL
To track all workflow changes and ensure audit compliance:

```sql
CREATE TABLE IF NOT EXISTS service_request_audit_log (
    id SERIAL PRIMARY KEY,
    request_id INTEGER NOT NULL REFERENCES service_requests(id) ON DELETE CASCADE,
    from_status VARCHAR(50) DEFAULT NULL,
    to_status VARCHAR(50) NOT NULL,
    triggered_by VARCHAR(100) NOT NULL, -- 'customer_sms', 'agent_sms', 'agent_email', 'manager_override', 'system_sla'
    notes TEXT DEFAULT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sr_audit_log_request_id ON service_request_audit_log(request_id);
```

### 2.3 Status Normalization Mapping
| DB Stored Status | Portal Display Status | Badges & Styling Class |
| :--- | :--- | :--- |
| `pending` | `pending` | `.status-select-badge.warning` (`#f59e0b`, transparent bg) |
| `confirmed` | `confirmed` | `.status-select-badge.teal` (`#06b6d4`, transparent bg) |
| `in_progress` | `in_progress` | `.status-select-badge.info` (`#3b82f6`, transparent bg) |
| `completed` / `done` | `done` | `.status-select-badge.success` (`#10b981`, transparent bg) |
| `cancelled` / `cancelled_by_customer` | `cancelled` | `.status-select-badge.danger` (`#ef4444`, transparent bg) |

---

## 3. Finite State Machine (FSM) Transition Rules

### 3.1 Transition Validation Matrix (Python Implementation)

```python
# Allowed status transition map in serviceBot/db/queries.py
ALLOWED_TRANSITIONS = {
    "pending": {"confirmed", "in_progress", "completed", "cancelled"},
    "confirmed": {"in_progress", "completed", "cancelled"},
    "in_progress": {"completed", "cancelled"},
    "completed": set(),  # Terminal state (locked)
    "cancelled": set(),  # Terminal state (locked)
}

def validate_status_transition(current_status: str, new_status: str) -> bool:
    curr = "completed" if current_status == "done" else current_status
    curr = "cancelled" if curr == "cancelled_by_customer" else curr
    nxt = "completed" if new_status == "done" else new_status
    nxt = "cancelled" if nxt == "cancelled_by_customer" else nxt
    
    if curr == nxt:
        return True  # No change
        
    allowed = ALLOWED_TRANSITIONS.get(curr, set())
    if nxt not in allowed:
        raise ValueError(f"Illegal status transition from '{curr}' to '{nxt}'. Allowed: {list(allowed)}")
    return True
```

---

## 4. API Endpoints & Request/Response Contracts

### 4.1 Update Status Endpoint
- **URL**: `PATCH /api/v1/portal/service-requests/{request_id}/status`
- **Request Payload**:
  ```json
  {
    "status": "confirmed"
  }
  ```
- **Response (200 OK)**:
  ```json
  {
    "success": true,
    "data": {
      "id": 102,
      "status": "confirmed",
      "updated_at": "2026-08-04T13:50:00Z"
    }
  }
  ```
- **Error Response (400 Bad Request)**:
  ```json
  {
    "detail": "Illegal status transition from 'completed' to 'pending'. Allowed: []"
  }
  ```

### 4.2 Agent Magic Link Confirmation Endpoint
- **URL**: `GET /api/v1/agent-confirm`
- **Query Parameters**: `token` (JWT / HMAC token), `action` (`confirm` | `decline`)
- **Behavior**:
  - `action=confirm`: Sets `status = 'confirmed'`, sets `agent_confirmed_at = NOW()`.
  - `action=decline`: Clears `triage_lock_owner`, queries `get_available_agents_for_request(request_id)` for Candidate #2. If Candidate #2 found, auto-reassigns and notifies Candidate #2.

---

## 5. Background SLA Worker (`serviceBot/services/agent_escalation.py`)

The background worker runs periodically (every 60 seconds):
1. **Query Unconfirmed Requests**: `SELECT * FROM service_requests WHERE status = 'pending' AND sla_expires_at < NOW()`.
2. **Check Agent Google Calendar Busy State**: Invokes `calendar_sync.py` to inspect if agent is in a meeting.
3. **Trigger Escalation Actions**:
   - If SLA expired: Flags booking as `⚠️ SLA Overdue` on the Admin Portal dashboard, and dispatches an immediate notification email and SMS alert to the Shop Manager (admin).

### 5.1 Dynamic Re-assignment Query (Candidate #2)
To fetch Candidate #2 when an agent declines or is unresponsive:
```sql
SELECT sa.id, sa.name, sa.phone_number, sa.email
FROM staff_agents sa
WHERE sa.id != :declined_agent_id
  AND sa.id NOT IN (
      SELECT DISTINCT staff_agent_id 
      FROM service_requests 
      WHERE booking_time = :slot_time 
        AND status IN ('confirmed', 'in_progress', 'completed')
  )
ORDER BY sa.id ASC
LIMIT 1;
```

---

## 6. Portal Frontend Code Specification (`app.js` & `style.css`)

### 6.1 CSS Classes (`serviceBot/static/style.css`)

```css
.status-select-badge {
  background-color: transparent !important;
  font-weight: 600;
  border: 1px solid transparent;
  padding: 4px 10px;
  border-radius: 12px;
}

.status-select-badge[data-status="pending"] {
  color: #f59e0b;
}

.status-select-badge[data-status="confirmed"] {
  color: #06b6d4;
}

.status-select-badge[data-status="in_progress"] {
  color: #3b82f6;
}

.status-select-badge[data-status="completed"],
.status-select-badge[data-status="done"] {
  color: #10b981;
}

.status-select-badge[data-status="cancelled"] {
  color: #ef4444;
}
```

### 6.2 Confirmation Modal DOM Structure (`index.html`)

```html
<div id="status-confirm-modal" class="modal" tabindex="-1">
  <div class="modal-dialog">
    <div class="modal-content">
      <div class="modal-header">
        <h5 class="modal-title">Confirm Status Change</h5>
      </div>
      <div class="modal-body">
        <p id="status-confirm-msg">Are you sure you want to change status?</p>
      </div>
      <div class="modal-footer">
        <button type="button" class="btn btn-secondary" id="btn-cancel-status-change">Cancel</button>
        <button type="button" class="btn btn-primary" id="btn-confirm-status-change">Confirm Change</button>
      </div>
    </div>
  </div>
</div>
```

---

## 7. Automated Test Plan

1. `tests/test_status_fsm.py`: Unit test `validate_status_transition` against all allowed and illegal transitions.
2. `tests/test_agent_confirmation_api.py`: Integration test for `PATCH /service-requests/{id}/status` and `/api/v1/agent-confirm`.
3. `tests/test_agent_escalation_worker.py`: Test Candidate #2 auto-reassignment and SLA timeout queueing.
