# Inbound Call Telephony Contract: Twilio & ElevenLabs Integration

**Feature**: `001-booking-confirmation-history`
**Endpoint**: `POST /api/v1/telephony/inbound`

## Description
When an incoming call is received by Twilio, this webhook looks up the caller's phone number against existing customer and service records. It renders a TwiML response containing the ElevenLabs `<ConversationAgent>` element enriched with dynamic context parameters.

## Inbound Request from Twilio
Standard `application/x-www-form-urlencoded` webhook payload from Twilio:
- `From`: Caller's phone number (e.g., `+15551234567`)
- `CallSid`: Unique Twilio call identifier (e.g., `CA1234567890abcdef`)
- `To`: Davidson Service Center phone number

## Outbound TwiML Response
```xml
<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Connect>
        <ConversationAgent url="https://api.elevenlabs.io/v1/convai/conversation/stream" agentId="[AGENT_ID]">
            <Parameter name="caller_phone" value="5551234567" />
            <Parameter name="customer_name" value="John Doe" />
            <Parameter name="upcoming_appointments_summary" value="Scheduled for Friday Oct 2 at 10:00 AM for 2021 Toyota Camry regarding Oil Change (Engine oil change and multipoint inspection). Duration: 45 min." />
            <Parameter name="recent_history_summary" value="Previous visit on Aug 14, 2026 for Tire Rotation (completed)." />
        </ConversationAgent>
    </Connect>
</Response>
```

## System Prompt Context Consumption
In `serviceBot/system_prompt.txt` and `serviceBot/config.json`:
- `{{customer_name}}`: Used to greet returning callers warmly: *"Hello {{customer_name}}, thanks for calling Davidson Car Care. How can I help you today?"*
- `{{upcoming_appointments_summary}}`: Retained in agent memory. When the caller mentions their vehicle or reports an issue, Rachel acknowledges: *"I see you already have an appointment scheduled for {{upcoming_appointments_summary}}..."*
- `{{recent_history_summary}}`: Informs Rachel of past work to provide continuous automotive service advice without repeating prior questions.
