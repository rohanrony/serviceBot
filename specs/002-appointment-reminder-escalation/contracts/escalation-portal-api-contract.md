# Contract: Escalation Queue & Portal Management Endpoints

**Feature**: [002-appointment-reminder-escalation](file:///Users/rohanroy/Coding/voiceService/specs/002-appointment-reminder-escalation/spec.md)  
**Contract Type**: REST API Contract  

---

## 1. Get Escalated Appointments (`GET /api/v1/portal/service-requests?escalated=true`)

### Response (200 OK)
```json
{
  "success": true,
  "data": [
    {
      "id": 1042,
      "customer_name": "John Doe",
      "customer_phone": "+19195551234",
      "vehicle": "2021 Toyota Camry",
      "booking_time": "2026-10-01 14:00:00",
      "duration_minutes": 60,
      "service_type": "Brake Inspection",
      "staff_agent_id": 4,
      "staff_agent_name": "Mike Ross",
      "confirmation_status": "pending_agent_confirmation",
      "escalation_status": "escalated",
      "escalation_reason": "TIMEOUT_NO_RESPONSE",
      "confirmation_cutoff_at": "2026-09-30T14:00:00",
      "attempts_dispatched": 3,
      "candidate_agents": [
        {
          "agent_id": 7,
          "agent_name": "Sarah Connor",
          "available": true,
          "current_job_count_today": 1,
          "skills_match": true
        },
        {
          "agent_id": 12,
          "agent_name": "Dave Miller",
          "available": true,
          "current_job_count_today": 3,
          "skills_match": true
        }
      ]
    }
  ]
}
```

---

## 2. Reassign Escalated Appointment (`POST /api/v1/portal/service-requests/{request_id}/reassign`)

### Request Payload
```json
{
  "new_staff_agent_id": 7,
  "reason": "Supervisor reassignment due to timeout of Mike Ross",
  "send_sms_notification": true
}
```

### Response (200 OK)
```json
{
  "success": true,
  "data": {
    "id": 1042,
    "previous_agent_id": 4,
    "previous_agent_name": "Mike Ross",
    "assigned_agent_id": 7,
    "assigned_agent_name": "Sarah Connor",
    "escalation_status": "reassigned",
    "confirmation_status": "pending_agent_confirmation",
    "new_confirmation_window_minutes": 15,
    "notification_sent_to_new_agent": true,
    "notification_sent_to_former_agent": true,
    "google_calendar_updated": true
  }
}
```

---

## 3. Configuration Endpoints (`GET /api/v1/portal/config` & `POST /api/v1/portal/config`)

### Schema Fields
```json
{
  "min_booking_buffer_hours": 4.0,
  "sla_advance_booking_hours": 4.0,
  "sla_medium_booking_hours": 3.0,
  "sla_short_booking_hours": 1.5,
  "final_reminder_hours": 2.0,
  "overnight_grace_minutes": 30,
  "max_dispatch_retries": 3,
  "business_hours_start": 8,
  "business_hours_end": 18,
  "supervisor_alert_phone": "+19195550199",
  "auto_reassign_on_escalation": false
}
```
