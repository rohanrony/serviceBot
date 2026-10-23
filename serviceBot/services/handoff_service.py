import re
import string
import datetime as dt_mod
from serviceBot.db.queries import (
    get_sms_config,
    get_customer_opt_in,
    update_sms_conversation_state,
    add_sms_message,
    get_sms_conversations,
    lookup_customer_by_phone,
)
from serviceBot.services.twilio_sms import TwilioSMSClient
from serviceBot.api.telephony import is_within_business_hours

SUPPORTED_HELPLINE_FIELDS = {"support_number", "support_phone_number", "helpline"}
SUPPORTED_CUSTOMER_FIELDS = {"customer_name"}
ALL_SUPPORTED_FIELDS = SUPPORTED_HELPLINE_FIELDS | SUPPORTED_CUSTOMER_FIELDS
NEUTRAL_FALLBACK_MESSAGE = "Message received."


def _resolve_customer_name(conversation_id: int, customer_phone: str, conv: dict = None) -> str:
    """
    Resolves customer_name from existing customer/conversation data when available.
    Does not invent customer names or placeholders.
    """
    if conv and conv.get("customer_name"):
        c_name = str(conv["customer_name"]).strip()
        if c_name and c_name.lower() not in ("unknown", "unknown customer", "unknown caller"):
            return c_name

    if customer_phone:
        try:
            cust = lookup_customer_by_phone(customer_phone)
            if cust and cust.get("name"):
                c_name = str(cust["name"]).strip()
                if c_name and c_name.lower() not in ("unknown", "unknown customer", "unknown caller"):
                    return c_name
        except Exception:
            pass

    return ""


def render_auto_responder_template(template_str: str, support_number: str = "", customer_name: str = "") -> str:
    """
    Renders the auto-responder template with supported variables:
      - support_number (aliases: support_phone_number, helpline)
      - customer_name

    Invariants:
      - Plain-text templates (no placeholders) are preserved as-is.
      - If a template requires a variable that is missing or unavailable (e.g. cleared helpline,
        missing customer_name), returns the neutral fallback "Message received."
      - If an unsupported placeholder is used or the template is malformed, returns "Message received."
      - Never dispatches a partially rendered template.
    """
    template = (template_str or "").strip()
    if not template:
        template = "Thank you! Our team has received your message. For urgent help, call {support_number}."

    try:
        parsed = list(string.Formatter().parse(template))
    except Exception:
        return NEUTRAL_FALLBACK_MESSAGE

    field_names = [fn for _, fn, _, _ in parsed if fn is not None]
    if not field_names:
        return template

    clean_support = (support_number or "").strip()
    clean_customer = (customer_name or "").strip()
    if clean_customer.lower() in ("unknown", "unknown customer", "unknown caller"):
        clean_customer = ""

    format_kwargs = {}
    for fn in field_names:
        fn_lower = fn.lower()
        if fn_lower not in ALL_SUPPORTED_FIELDS:
            return NEUTRAL_FALLBACK_MESSAGE
        if fn_lower in SUPPORTED_HELPLINE_FIELDS:
            if not clean_support:
                return NEUTRAL_FALLBACK_MESSAGE
            format_kwargs[fn] = clean_support
        elif fn_lower in SUPPORTED_CUSTOMER_FIELDS:
            if not clean_customer:
                return NEUTRAL_FALLBACK_MESSAGE
            format_kwargs[fn] = clean_customer

    try:
        rendered = template.format(**format_kwargs)
    except Exception:
        return NEUTRAL_FALLBACK_MESSAGE

    if re.search(r"\{[^{}]*\}", rendered):
        return NEUTRAL_FALLBACK_MESSAGE

    return rendered


def trigger_human_handoff(conversation_id: int, customer_phone: str, message_body: str) -> dict:
    """
    Transitions conversation to HANDOFF_REQUIRED, checks auto-responder debounce and opt-in status,
    and dispatches auto-responder SMS if eligible.
    Enforces business hours (Mon-Fri 7am-6pm ET).
    """
    from serviceBot.services.sms_classifier import get_support_helpline
    config = get_sms_config() or {}
    support_number = get_support_helpline()

    # Business Hours Check
    if not is_within_business_hours():
        if support_number:
            out_of_hours_text = f"Live agent support is only available during our business hours (Mon-Fri 7:00 AM - 6:00 PM ET). For urgent help, please call {support_number} or schedule an appointment."
        else:
            out_of_hours_text = "Live agent support is only available during our business hours (Mon-Fri 7:00 AM - 6:00 PM ET). For urgent help, please schedule an appointment."
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

    template_str = config.get("auto_responder_template")

    # Fetch conversation to inspect debounce and resolve customer name
    convs = get_sms_conversations()
    conv = next((c for c in convs if c["id"] == conversation_id), None)

    customer_name = _resolve_customer_name(conversation_id, customer_phone, conv)
    auto_responder_text = render_auto_responder_template(
        template_str,
        support_number=support_number,
        customer_name=customer_name
    )

    debounce_sec = config.get("auto_responder_debounce_seconds", 60)

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
