# Contract: Booking Lead Time & Horizon Validation

**Feature**: [002-appointment-reminder-escalation](file:///Users/rohanroy/Coding/voiceService/specs/002-appointment-reminder-escalation/spec.md)  
**Contract Type**: API & Telephony Tool Validation Contract  

---

## 1. Overview

This contract governs lead-time validation for appointment reservations across both the AI Voice Telephony assistant (`serviceBot/api/telephony.py`) and the Web Portal booking endpoints (`serviceBot/api/portal.py`).

---

## 2. Validation Specification

### Input
- `requested_datetime`: ISO-8601 string or datetime object representing the requested appointment start time.
- `current_time`: Timestamp of the request (default: `datetime.now()`).
- `min_buffer_hours`: Configured planning buffer (default: `4.0` hours).

### Business Rule
$$\text{Delta} = \text{requested\_datetime} - \text{current\_time}$$
$$\text{If } \text{Delta} < \text{min\_buffer\_hours} \times 3600 \implies \mathbf{REJECT}$$

---

## 3. Telephony Tool Contract (`book_appointment` & `get_available_slots`)

### 3.1 Rejected Slot Response (Payload to Voice Agent)

```json
{
  "success": false,
  "error": "INSUFFICIENT_LEAD_TIME",
  "min_buffer_hours": 4,
  "earliest_allowed_time": "2026-09-30T12:00:00",
  "suggested_slots": [
    "2026-09-30T12:00:00",
    "2026-09-30T13:30:00",
    "2026-09-30T15:00:00"
  ],
  "agent_instruction": "Politely inform the caller that our shop requires at least 4 hours advance notice to prepare bays and parts. Offer the suggested slots at or after 12:00 PM."
}
```

### 3.2 Spoken Response Contract (What Rachel says to caller)

> *"I'd love to help you with that! Because our technicians need a little time to prepare your work bay and parts, our shop requires at least 4 hours advance notice. The earliest time I can book you today is 12:00 PM. Would 12:00 PM or 1:30 PM work for you?"*

---

## 4. Portal REST API Contract (`POST /api/v1/portal/service-requests`)

### 4.1 Error Response (HTTP 422 Unprocessable Entity)

```json
{
  "detail": {
    "error_code": "LEAD_TIME_VIOLATION",
    "message": "Appointment slot 2026-09-30T09:30:00 violates the minimum advance notice policy of 4 hours.",
    "current_time": "2026-09-30T08:00:00",
    "min_buffer_hours": 4,
    "earliest_valid_time": "2026-09-30T12:00:00"
  }
}
```
