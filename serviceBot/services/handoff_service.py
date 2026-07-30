import datetime as dt_mod
from serviceBot.db.queries import (
    get_sms_config,
    get_customer_opt_in,
    update_sms_conversation_state,
    add_sms_message,
    get_sms_conversations
)
from serviceBot.services.twilio_sms import TwilioSMSClient
from serviceBot.api.telephony import is_within_business_hours


def trigger_human_handoff(conversation_id: int, customer_phone: str, message_body: str) -> dict:
    """
    Transitions conversation to HANDOFF_REQUIRED, checks auto-responder debounce and opt-in status,
    and dispatches auto-responder SMS if eligible.
    Enforces business hours (Mon-Fri 7am-6pm ET).
    """
    config = get_sms_config()
    support_number = config.get("support_phone_number") or "+18005550199"

    # Business Hours Check
    if not is_within_business_hours():
        out_of_hours_text = f"Live agent support is only available during our business hours (Mon-Fri 7:00 AM - 6:00 PM ET). For urgent help, please call {support_number} or schedule an appointment."
        convs = get_sms_conversations()
        conv = next((c for c in convs if c["id"] == conversation_id), None)
        now = dt_mod.datetime.utcnow()
        should_send = get_customer_opt_in(customer_phone)

        update_sms_conversation_state(conversation_id, "OUT_OF_BUSINESS_HOURS", last_auto_responder_at=now)

        if should_send:
            client = TwilioSMSClient()
            client.send_sms(to=customer_phone, body=out_of_hours_text, template_type="auto_responder")
            add_sms_message(conversation_id, "outbound", "system", "Auto-Responder", out_of_hours_text)

        return {
            "success": False,
            "conversation_id": conversation_id,
            "state": "OUT_OF_BUSINESS_HOURS",
            "auto_responder_sent": should_send,
            "message": "Human handoff is only available during business hours (Monday - Friday, 7:00 AM - 6:00 PM ET)."
        }

    template_str = config.get(
        "auto_responder_template",
        "Thank you! Our team has received your message. For urgent help, call {support_number}."
    )
    auto_responder_text = template_str.format(support_number=support_number)
    debounce_sec = config.get("auto_responder_debounce_seconds", 60)

    # Fetch conversation
    convs = get_sms_conversations()
    conv = next((c for c in convs if c["id"] == conversation_id), None)

    # Check 60-second debounce
    now = dt_mod.datetime.utcnow()
    should_send_auto_responder = True

    if conv and conv.get("last_auto_responder_at"):
        last_at = conv["last_auto_responder_at"]
        if isinstance(last_at, str):
            try:
                last_at = dt_mod.datetime.fromisoformat(last_at)
            except Exception:
                last_at = None
        if last_at:
            delta = (now - last_at).total_seconds()
            if delta < debounce_sec:
                should_send_auto_responder = False

    # Check Opt-In Guard
    if not get_customer_opt_in(customer_phone):
        should_send_auto_responder = False

    # Update state to HANDOFF_REQUIRED
    last_auto_at = now if should_send_auto_responder else (conv.get("last_auto_responder_at") if conv else None)
    update_sms_conversation_state(conversation_id, "HANDOFF_REQUIRED", last_auto_responder_at=last_auto_at)

    if should_send_auto_responder:
        client = TwilioSMSClient()
        client.send_sms(to=customer_phone, body=auto_responder_text, template_type="auto_responder")
        add_sms_message(conversation_id, "outbound", "system", "Auto-Responder", auto_responder_text)

    return {
        "success": True,
        "conversation_id": conversation_id,
        "state": "HANDOFF_REQUIRED",
        "auto_responder_sent": should_send_auto_responder
    }


def send_agent_reply(conversation_id: int, message: str, agent_name: str = "Support Agent") -> dict:
    """
    Dispatches custom SMS from human operator to customer, updating conversation state to IN_PROGRESS.
    Supports proactive agent replies transitioning directly from AUTOMATED to IN_PROGRESS.
    """
    convs = get_sms_conversations()
    conv = next((c for c in convs if c["id"] == conversation_id), None)
    if not conv:
        return {"success": False, "error": "Conversation not found"}

    customer_phone = conv["customer_phone"]

    # Dispatch SMS via Twilio
    client = TwilioSMSClient()
    res = client.send_sms(to=customer_phone, body=message, template_type="agent_reply")

    # Update state to IN_PROGRESS
    update_sms_conversation_state(conversation_id, "IN_PROGRESS")

    # Log in sms_messages
    msg = add_sms_message(
        conversation_id=conversation_id,
        direction="outbound",
        sender_type="agent",
        sender_name=agent_name,
        body=message,
        twilio_message_sid=res.get("sid")
    )

    return {"success": True, "state": "IN_PROGRESS", "message": msg, "dispatch": res}


def resolve_conversation(conversation_id: int) -> dict:
    """Resets conversation state back to AUTOMATED."""
    updated = update_sms_conversation_state(conversation_id, "AUTOMATED")
    return {"success": True, "state": "AUTOMATED", "conversation": updated}
