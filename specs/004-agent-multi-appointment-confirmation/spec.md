# Feature Specification: Staff Agent Multi-Appointment Confirmation Disambiguation & Batch Processing

**Feature Branch**: `004-agent-multi-appointment-confirmation`  
**Created**: 2026-10-08  
**Status**: Specified  
**Target Version**: `v0.9.0`  
**Author / PM**: AI Product Management Co-Pilot & Engineering  

---

## 1. Executive Summary & Value Proposition

### 1.1 Problem Statement
When dispatchers assign multiple service requests to the same technician (staff agent) within a short window, the technician receives multiple automated assignment alerts via SMS or WhatsApp (e.g. Appointment #101 for a brake inspection and Appointment #102 for an oil change).

Under the current system (`serviceBot/services/sms_classifier.py`):
1. **Blind LIFO Selection**: Replying with a bare `CONFIRM` or `C` executes `ORDER BY created_at DESC LIMIT 1`, silently confirming the most recently created appointment while ignoring earlier assignments.
2. **Ignored Explicit IDs**: If the technician types `CONFIRM 101` or `C #101`, the system tokenizes the string, extracts `"CONFIRM"`, but ignores the number `101`, still applying the action to whichever appointment was created last.
3. **Mishandled Declines**: Replying `DECLINE` unintentionally declines and escalates the wrong service request.
4. **No Batch Workflow**: Technicians during morning dispatches have no mechanism to accept all pending jobs in a single text message.

### 1.2 Proposed Solution
Implement a **Technician-Specific Disambiguation & Batch Confirmation Engine**:
1. **Single-Job Fast Path**: If an agent has exactly **1** pending appointment, replying `CONFIRM`, `C`, or `DECLINE` acts immediately with zero extra friction.
2. **Zero-Guessing Disambiguation Menu**: If an agent has **> 1** pending appointments and sends a bare action (`CONFIRM` or `DECLINE`), the system **never guesses**. It replies with an ordered numbered menu:
   ```text
   ⚠️ You have 2 assignments awaiting confirmation:
   1️⃣ #101 - 2021 Toyota Camry (Oct 12, 10:00 AM)
   2️⃣ #102 - 2018 Ford F-150 (Oct 12, 1:00 PM)

   Reply CONFIRM 1 (or C 1), CONFIRM 2, or CONFIRM ALL.
   (Or reply DECLINE 1 / DECLINE 2).
   ```
3. **Index-Based & ID-Based Replies**: Technicians can reply with either index notation (`CONFIRM 1`, `C 1`, `DECLINE 1`, `1`) or explicit ticket IDs (`CONFIRM 101`, `C 101`).
4. **Batch Acceptance (`CONFIRM ALL`)**: Technicians can reply `CONFIRM ALL` (case-insensitive: `Confirm all`, `C ALL`, `ACCEPT ALL`) to confirm all pending assignments in a single atomic database transaction.
5. **Customer Scope Excluded**: As customer multi-appointment scenarios are rare, customer flows remain unchanged, keeping the customer SMS experience simple.

---

## 2. User Scenarios & Acceptance Criteria

### User Story 1 - Fast-Path Confirmation for Single Pending Assignment (Priority: P1)

As a technician with only one new job assignment awaiting confirmation, I want replying `CONFIRM` or `C` to immediately accept the assignment without any disambiguation questions, so that my workflow remains instantaneous for typical single bookings.

* **Given** Technician Alex has exactly 1 service request (`#101`) in `pending_agent_confirmation` status,
* **When** Alex texts `CONFIRM`, `C`, `YES`, or `ACCEPT`,
* **Then** Appointment `#101` is marked as `confirmed`, reminders for Alex are cancelled, and Alex receives:  
  `"Appointment #101 confirmed. Thank you!"`

---

### User Story 2 - Disambiguation Menu on Bare Response for Multiple Jobs (Priority: P1)

As a technician with 2 or more pending job assignments, when I reply with a bare `CONFIRM` or `DECLINE` without specifying which job, I want the system to present a clear, numbered list of pending jobs rather than guessing, so that the wrong job is never confirmed or escalated.

* **Given** Technician Alex has 2 service requests pending confirmation (`#101` and `#102`),
* **When** Alex texts `CONFIRM` or `C`,
* **Then** the system does not alter the confirmation status of either appointment,
* **And** the system records the ordered list `[101, 102]` into Alex's conversation context,
* **And** dispatches the numbered menu:
  ```text
  ⚠️ You have 2 assignments awaiting confirmation:
  1️⃣ #101 - 2021 Toyota Camry (Oct 12, 10:00 AM)
  2️⃣ #102 - 2018 Ford F-150 (Oct 12, 1:00 PM)

  Reply CONFIRM 1 (or C 1), CONFIRM 2, or CONFIRM ALL.
  (Or reply DECLINE 1 / DECLINE 2).
  ```

---

### User Story 3 - Index & Explicit ID Confirmation (`CONFIRM 1`, `C 1`, `CONFIRM 101`) (Priority: P1)

As a technician reviewing a disambiguation prompt or assignment alerts, I want to reply with the short index (`CONFIRM 1`, `C 1`, `1`) or the appointment number (`CONFIRM 101`), so that I can quickly confirm individual appointments.

* **Scenario 3A (Index Match)**:
  * **Given** the active pending list for Alex is `1️⃣ #101, 2️⃣ #102`,
  * **When** Alex texts `CONFIRM 1` or `C 1`,
  * **Then** Appointment `#101` is confirmed, and Alex receives:  
    `"Appointment #101 confirmed. Thank you! (1 assignment remaining: #102)"`
  * **And** Appointment `#102` remains in `pending_agent_confirmation`.
* **Scenario 3B (Index Decline)**:
  * **Given** the active pending list for Alex is `1️⃣ #101, 2️⃣ #102`,
  * **When** Alex texts `DECLINE 2`,
  * **Then** Appointment `#102` is marked `declined`, escalated to the supervisor alert queue, and Alex receives:  
    `"Appointment #102 marked declined. Supervisor notified. (1 assignment remaining: #101)"`
* **Scenario 3C (Direct Appointment ID Match)**:
  * **Given** Alex receives an alert for Appt `#101`,
  * **When** Alex texts `CONFIRM 101` or `C 101`,
  * **Then** Appointment `#101` is confirmed directly, even before a disambiguation menu was triggered.

---

### User Story 4 - Batch Confirmation (`CONFIRM ALL`) (Priority: P1)

As a technician receiving morning assignments, I want to reply `CONFIRM ALL` to accept all pending jobs in one text, so that I don't have to send separate confirmation messages for each ticket.

* **Given** Technician Alex has 3 pending assignments (`#101`, `#102`, `#103`),
* **When** Alex texts `CONFIRM ALL`, `Confirm all`, `C ALL`, or `ACCEPT ALL`,
* **Then** all 3 appointments are updated to `confirmed` in an atomic database transaction,
* **And** pending SMS reminders for all 3 are cancelled,
* **And** audit log entries are generated for all 3 records,
* **And** Alex receives a consolidated confirmation receipt:  
  `"✅ Confirmed all 3 assignments (#101, #102, #103). Your schedule is up to date!"`

---

## 3. Technical Design & Component Changes

### 3.1 Parser Specification (`serviceBot/services/sms_classifier.py`)

A new parsing function `parse_agent_confirmation_intent(body: str)` will extract:
1. **Action**: `CONFIRM`, `DECLINE`, `CONFIRM_ALL`, `DECLINE_ALL`, or `UNKNOWN`.
2. **Selector Type**: `index`, `id`, `bare`, or `batch`.
3. **Value**: Integer index or ticket ID (if present).

```python
import re

def parse_agent_confirmation_intent(body: str) -> dict:
    clean = (body or "").strip()
    upper = clean.upper()
    tokens = upper.split()
    
    # 1. Batch Confirmation Check
    if any(phrase in upper for phrase in ["CONFIRM ALL", "ACCEPT ALL", "C ALL", "YES ALL"]):
        return {"action": "CONFIRM_ALL", "selector_type": "batch", "value": None}
    if any(phrase in upper for phrase in ["DECLINE ALL", "REJECT ALL", "NO ALL"]):
        return {"action": "DECLINE_ALL", "selector_type": "batch", "value": None}
        
    # 2. Action + Target (e.g. "CONFIRM 1", "C 1", "CONFIRM #101", "DECLINE 2")
    m = re.search(r'\b(CONFIRM|C|ACCEPT|YES|DECLINE|NO)\s*#?\s*(\d+)\b', upper)
    if m:
        act = "CONFIRM" if m.group(1) in ("CONFIRM", "C", "ACCEPT", "YES") else "DECLINE"
        num = int(m.group(2))
        return {"action": act, "selector_type": "numeric", "value": num}
        
    # 3. Pure index reply (e.g. "1" or "2" answering the prompt)
    if upper.isdigit():
        return {"action": "CONFIRM", "selector_type": "index", "value": int(upper)}
        
    # 4. Bare Action
    if any(t in tokens for t in ["CONFIRM", "C", "ACCEPT", "YES"]):
        return {"action": "CONFIRM", "selector_type": "bare", "value": None}
    if any(t in tokens for t in ["DECLINE", "UNAVAILABLE", "NO", "CANNOT"]):
        return {"action": "DECLINE", "selector_type": "bare", "value": None}
        
    return {"action": "UNKNOWN", "selector_type": "none", "value": None}
```

### 3.2 State Tracking & Deterministic Ordering
* Order candidate appointments deterministically by `sr.booking_time ASC, sr.created_at ASC` so index positions (`1`, `2`, `3`) always correspond to the sequential schedule in the disambiguation prompt.
* If `value <= len(pending_list)`, interpret as index (e.g., `1` -> `pending_list[0]`). If `value` matches an explicit `sr.id`, resolve directly to that appointment ID.

---

## 4. Edge Cases & Failure Mode Matrix

| Scenario / Edge Case | Risk | Mitigation |
| :--- | :--- | :--- |
| **Agent texts `CONFIRM 3` when only 2 jobs are pending** | Out-of-bounds selection | Reply: *"Invalid choice. You have 2 pending assignments (#101, #102). Reply CONFIRM 1, CONFIRM 2, or CONFIRM ALL."* |
| **Agent texts `CONFIRM 1` after one appointment was already reassigned by admin** | Race condition / stale assignment | Validate appointment state during transaction. If superseded, notify: *"Appointment #101 was already reassigned to [New Agent]. No action required."* |
| **Agent texts `CONFIRM ALL` when 1 ticket was already escalated** | Incomplete batch | Accept timely tickets, accept late confirmation on the escalated ticket, and report exact details in the receipt. |
| **Technician replies `C 1` on WhatsApp vs SMS** | Format inconsistency | Disambiguation prompt and receipts use `dispatch_agent_receipt` preserving WhatsApp / SMS channel mode. |

---

## 5. Success Metrics
* **Resolution Accuracy**: 100% of multi-assignment replies map to the intended appointment without guessing.
* **Batch Efficiency**: Technicians with 2+ assignments resolve confirmation with 1 text message (`CONFIRM ALL`) in > 70% of multi-assignment occurrences.
