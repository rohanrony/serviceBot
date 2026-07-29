import datetime as dt_mod
from serviceBot.db.queries import (
    update_customer_opt_in,
    get_customer_opt_in,
    get_sms_config,
    get_or_create_sms_conversation,
    add_sms_message
)
from serviceBot.services.twilio_sms import TwilioSMSClient

OPT_OUT_KEYWORDS = {"STOP", "UNSUBSCRIBE", "QUIT", "END"}
OPT_IN_KEYWORDS = {"START", "UNSTOP"}
HELP_KEYWORDS = {"HELP"}

CONFIRM_KEYWORDS = {"C", "CONFIRM", "YES"}
CANCEL_KEYWORDS = {"X", "CANCEL", "NO"}


def classify_inbound_message(body: str) -> dict:
    """
    Classifies an inbound SMS body into:
    - 'tcpa_opt_out'
    - 'tcpa_opt_in'
    - 'help'
    - 'action_confirm'
    - 'action_cancel'
    - 'free_text' (human handoff)
    """
    if not body:
        return {"category": "free_text", "normalized": ""}

    normalized = body.strip().upper()
    tokens = normalized.split()

    # Single-token regulatory checks
    if len(tokens) == 1:
        token = tokens[0]
        if token in OPT_OUT_KEYWORDS:
            return {"category": "tcpa_opt_out", "token": token}
        if token in OPT_IN_KEYWORDS:
            return {"category": "tcpa_opt_in", "token": token}
        if token in HELP_KEYWORDS:
            return {"category": "help", "token": token}

        # Single-token action checks
        if token in CONFIRM_KEYWORDS:
            return {"category": "action_confirm", "token": token}
        if token in CANCEL_KEYWORDS:
            return {"category": "action_cancel", "token": token}

    return {"category": "free_text", "raw": body, "normalized": normalized}


def process_inbound_sms(from_phone: str, body: str, twilio_message_sid: str = None) -> dict:
    """Processes an inbound SMS message through the classification pipeline."""
    client = TwilioSMSClient()
    config = get_sms_config()
    support_number = config.get("support_phone_number") or "+18005550199"

    # Get or create conversation record
    conv = get_or_create_sms_conversation(from_phone)
    conv_id = conv["id"]

    # Log incoming message
    add_sms_message(
        conversation_id=conv_id,
        direction="inbound",
        sender_type="customer",
        sender_name=from_phone,
        body=body,
        twilio_message_sid=twilio_message_sid
    )

    # Classify message
    result = classify_inbound_message(body)
    category = result["category"]

    if category == "tcpa_opt_out":
        update_customer_opt_in(from_phone, False)
        reply_text = "You have been unsubscribed from SMS notifications. Reply START to resubscribe."
        client.send_sms(to=from_phone, body=reply_text, template_type="opt_out_receipt")
        add_sms_message(conv_id, "outbound", "system", "System", reply_text)
        return {"status": "processed", "category": category, "reply": reply_text}

    elif category == "tcpa_opt_in":
        update_customer_opt_in(from_phone, True)
        reply_text = "You have re-subscribed to SMS notifications. Reply STOP at any time to opt out."
        client.send_sms(to=from_phone, body=reply_text, template_type="opt_in_receipt")
        add_sms_message(conv_id, "outbound", "system", "System", reply_text)
        return {"status": "processed", "category": category, "reply": reply_text}

    elif category == "help":
        reply_text = f"ServiceBot Support: For help, please contact our support team at {support_number}."
        if get_customer_opt_in(from_phone):
            client.send_sms(to=from_phone, body=reply_text, template_type="help_reply")
            add_sms_message(conv_id, "outbound", "system", "System", reply_text)
        return {"status": "processed", "category": category, "reply": reply_text}

    elif category in ("action_confirm", "action_cancel"):
        from serviceBot.db.connection import get_db_connection, dict_cursor
        target_sr_id = conv.get("context_appointment_id")

        with get_db_connection() as conn:
            with dict_cursor(conn) as cursor:
                if not target_sr_id:
                    cursor.execute(
                        """
                        SELECT sr.id 
                        FROM service_requests sr
                        JOIN customers c ON sr.customer_id = c.id
                        WHERE (c.phone = %s OR REPLACE(REPLACE(REPLACE(c.phone, '-', ''), ' ', ''), '+1', '') = REPLACE(REPLACE(REPLACE(%s, '-', ''), ' ', ''), '+1', ''))
                          AND sr.status NOT IN ('completed', 'cancelled', 'cancelled_by_customer')
                        ORDER BY sr.created_at DESC LIMIT 1;
                        """,
                        (from_phone, from_phone)
                    )
                    row = cursor.fetchone()
                    if row:
                        target_sr_id = row["id"]

                if target_sr_id:
                    new_status = "confirmed" if category == "action_confirm" else "cancelled_by_customer"
                    cursor.execute("UPDATE service_requests SET status = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s;", (new_status, target_sr_id))
                    conn.commit()

                    reply_text = (
                        f"Your appointment #{target_sr_id} has been confirmed. Thank you!"
                        if category == "action_confirm"
                        else f"Your appointment #{target_sr_id} has been cancelled as requested."
                    )
                    if get_customer_opt_in(from_phone):
                        client.send_sms(to=from_phone, body=reply_text, template_type="action_receipt", appointment_id=target_sr_id)
                        add_sms_message(conv_id, "outbound", "system", "System", reply_text)
                    return {"status": "processed", "category": category, "appointment_id": target_sr_id, "new_status": new_status}

        # Fallback to handoff if no appointment found
        category = "free_text"

    # Conversational message (Free-text -> Human Handoff)
    from serviceBot.services.handoff_service import trigger_human_handoff
    handoff_res = trigger_human_handoff(conv_id, from_phone, body)
    return {"status": "handoff_triggered", "category": "free_text", "details": handoff_res}
