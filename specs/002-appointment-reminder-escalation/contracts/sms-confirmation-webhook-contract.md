# Contract: SMS Confirmation & Telephony Webhook Payloads

**Feature**: [002-appointment-reminder-escalation](file:///Users/rohanroy/Coding/voiceService/specs/002-appointment-reminder-escalation/spec.md)  
**Contract Type**: Twilio SMS Webhook & Notification Contract  

---

## 1. Inbound SMS Webhook (`POST /api/v1/telephony/sms/inbound`)

### 1.1 Inbound Request Form (Standard Twilio Payload)
```text
From: +19195551234
To: +19195550199
Body: CONFIRM
MessageSid: SM1234567890abcdef
```

### 1.2 Agent Sender Identification Logic
1. Lookup sender phone number against `staff_agents.phone_number`.
2. If match found: Route to **Agent Action Classifier**.
3. If no match found: Route to standard customer SMS classifier (`tcpa_opt_out`, `action_confirm`, `help`).

### 1.3 Agent Reply Classification & Outcomes

| Inbound Body Tokens | Classification | Action Executed | Automated Outbound Reply |
|:---|:---|:---|:---|
| `CONFIRM`, `C`, `YES`, `ACCEPT` | `agent_confirm` | Transition `service_requests.confirmation_status = 'confirmed'`, update `confirmed_at = NOW()`, cancel pending escalation timers. | *"Appointment #[ID] confirmed. Thank you!"* |
| `DECLINE`, `UNAVAILABLE`, `NO`, `CANNOT` | `agent_decline` | Transition `service_requests.escalation_status = 'escalated'`, set `escalation_reason = 'AGENT_DECLINED'`, dispatch immediate supervisor alert. | *"Appointment #[ID] has been marked declined. Supervisor notified."* |
| Late `CONFIRM` (Pre-Reassignment) | `agent_confirm_late` | Accept confirmation, transition `escalation_status = 'resolved'`, auto-dismiss supervisor alert. | *"Late confirmation accepted for Appointment #[ID]. Thank you!"* |
| Late `CONFIRM` (Post-Reassignment) | `agent_confirm_superseded` | Reject confirmation. Retain newly assigned agent. | *"Appointment #[ID] was already reassigned to [New Agent Name]. No action required."* |

---

## 2. Outbound Prompt Dispatches (Twilio SMS)

### 2.1 Attempt 1: Immediate Booking Confirmation
- **To Agent**:  
  `"Davidson Car Care: You are assigned Appointment #1042 on Thu Oct 1 at 2:00 PM for John Doe (2021 Toyota Camry - Oil Change). Reply CONFIRM or C to accept."`
- **To Customer**:  
  `"Davidson Car Care: Your appointment #1042 is scheduled for Thu Oct 1 at 2:00 PM. View details or manage: https://davidson.carcare/portal/a/1042"`

### 2.2 Attempt 2: Intermediate Follow-Up
- **To Agent**:  
  `"Davidson Car Care REMINDER: Appointment #1042 for John Doe on Thu Oct 1 at 2:00 PM is pending your confirmation. Reply CONFIRM to accept."`

### 2.3 Attempt 3: Final Urgent Prompt
- **To Agent**:  
  `"FINAL NOTICE: Appointment #1042 will escalate to dispatch in 15 minutes unless confirmed. Reply CONFIRM to accept."`

### 2.4 Urgent Supervisor Escalation Alert
- **To Supervisor (`supervisor_alert_phone`)**:  
  `"URGENT ESCALATION: Appointment #1042 (John Doe at 2:00 PM) is UNCONFIRMED by technician Mike Ross (Reason: TIMEOUT). Review & reassign: https://davidson.carcare/portal/reassign/1042"`
