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


HANDOFF_PROMPT_KEYWORDS = {
    "HUMAN", "AGENT", "REPRESENTATIVE", "REP", "PERSON", "MANAGER", 
    "OPERATOR", "LIVE SUPPORT", "HANDOFF", "TRANSFER"
}
HANDOFF_PROMPT_PHRASES = [
    "SPEAK TO A", "TALK TO A", "SPEAK TO SOMEONE", "TALK TO SOMEONE", 
    "REAL PERSON", "LIVE AGENT", "LIVE PERSON"
]


def is_explicit_handoff_request(body: str) -> bool:
    if not body:
        return False
    upper_body = body.strip().upper()
    tokens = set(upper_body.split())
    if any(kw in tokens for kw in HANDOFF_PROMPT_KEYWORDS):
        return True
    if any(phrase in upper_body for phrase in HANDOFF_PROMPT_PHRASES):
        return True
    return False


def classify_inbound_message(body: str) -> dict:
    """
    Classifies an inbound SMS body into:
    - 'tcpa_opt_out'
    - 'tcpa_opt_in'
    - 'help'
    - 'action_confirm'
    - 'action_cancel'
    - 'free_text' (human handoff only if requested)
    """
    if not body:
        return {"category": "free_text", "normalized": "", "is_handoff_requested": False}

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

    is_handoff_req = is_explicit_handoff_request(body)
    return {"category": "free_text", "raw": body, "normalized": normalized, "is_handoff_requested": is_handoff_req}


def handle_agent_confirmation_action(staff_agent: dict, body: str, twilio_message_sid: str = None, from_phone: str = None) -> dict:
    """
    Handles inbound SMS replies from staff agents / technicians:
    - Confirms assignment on 'CONFIRM', 'C', 'YES', 'ACCEPT'
    - Declines assignment and triggers supervisor escalation on 'DECLINE', 'UNAVAILABLE', 'NO', 'CANNOT'
    - Accepts late confirmation if appointment escalated but not yet reassigned ('agent_confirm_late')
    - Rejects late confirmation if appointment already reassigned to someone else ('agent_confirm_superseded')
    """
    client = TwilioSMSClient()
    agent_id = staff_agent["id"]
    agent_phone = staff_agent.get("phone_number")
    reply_target = from_phone.strip() if (from_phone and from_phone.strip()) else agent_phone
    is_whatsapp_reply = reply_target.startswith("whatsapp:")

    def dispatch_agent_receipt(msg_body: str, template_type: str = "agent_action_receipt"):
        if is_whatsapp_reply:
            return client.send_whatsapp(to=reply_target, body=msg_body, template_type=template_type)
        return client.send_sms(to=reply_target, body=msg_body, template_type=template_type)

    clean_body = (body or "").strip()
    norm = clean_body.upper()
    tokens = set(norm.split())

    # 1. Classification
    is_confirm = any(kw in tokens for kw in {"CONFIRM", "C", "YES", "ACCEPT"})
    is_decline = any(kw in tokens for kw in {"DECLINE", "UNAVAILABLE", "NO", "CANNOT"})

    from serviceBot.db.connection import get_db_connection, dict_cursor
    from serviceBot.db.queries import (
        update_appointment_confirmation_status,
        escalate_service_request,
        cancel_pending_sms_reminders,
    )

    # Resolve all agent IDs sharing this phone number to handle multi-advisor demo/test setups cleanly
    candidate_agent_ids = [agent_id]
    lookup_phone = agent_phone or from_phone
    if lookup_phone:
        import re
        cl = re.sub(r"\D", "", lookup_phone)
        cl10 = cl[1:] if len(cl) == 11 and cl.startswith("1") else (cl if len(cl) == 10 else "")
        e164_norm = f"+1{cl10}" if cl10 else lookup_phone.strip()
        with get_db_connection() as conn:
            with dict_cursor(conn) as c_cur:
                c_cur.execute(
                    """
                    SELECT id FROM staff_agents
                    WHERE phone_number = %s OR phone_number = %s
                       OR REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(phone_number, '-', ''), ' ', ''), '(', ''), ')', ''), '+1', '') = %s;
                    """,
                    (lookup_phone.strip(), e164_norm, cl10 or cl)
                )
                rows = c_cur.fetchall()
                if rows:
                    candidate_agent_ids = [r["id"] for r in rows]

    if is_confirm:
        with get_db_connection() as conn:
            with dict_cursor(conn) as cursor:
                # 1. Check for currently assigned active appointment pending confirmation or escalated
                cursor.execute(
                    """
                    SELECT sr.id, sr.staff_agent_id, sr.confirmation_status, sr.escalation_status, sr.created_at,
                           sa.name AS agent_name
                    FROM service_requests sr
                    LEFT JOIN staff_agents sa ON sa.id = sr.staff_agent_id
                    WHERE sr.staff_agent_id = ANY(%s)
                      AND sr.confirmation_status = 'pending_agent_confirmation'
                      AND sr.status NOT IN ('completed', 'cancelled', 'cancelled_by_customer')
                    ORDER BY sr.created_at DESC LIMIT 1;
                    """,
                    (candidate_agent_ids,)
                )
                curr_sr = cursor.fetchone()

                # 2. Check for reassigned appointment where this agent was superseded
                cursor.execute(
                    """
                    SELECT sr.id, sr.staff_agent_id, sr.confirmation_status, sr.escalation_status, sr.created_at,
                           sa.name AS new_agent_name
                    FROM service_requests sr
                    JOIN staff_agents sa ON sa.id = sr.staff_agent_id
                    WHERE sr.escalation_status = 'reassigned'
                      AND NOT (sr.staff_agent_id = ANY(%s))
                      AND sr.status NOT IN ('completed', 'cancelled', 'cancelled_by_customer')
                    ORDER BY sr.created_at DESC LIMIT 1;
                    """,
                    (candidate_agent_ids,)
                )
                superseded_sr = cursor.fetchone()

        # If appointment was already reassigned to another agent
        if superseded_sr and (
            not curr_sr
            or curr_sr["escalation_status"] == "reassigned"
            or (superseded_sr.get("created_at") and curr_sr.get("created_at") and superseded_sr["created_at"] >= curr_sr["created_at"])
        ):
            target_sr = superseded_sr
            new_name = target_sr.get("new_agent_name") or "another technician"
            reply_text = f"Appointment #{target_sr['id']} was already reassigned to {new_name}. No action required."
            dispatch_agent_receipt(reply_text)
            return {
                "status": "processed",
                "category": "agent_confirm_superseded",
                "appointment_id": target_sr["id"],
                "reply": reply_text
            }

        if curr_sr:
            sr_id = curr_sr["id"]
            now_ts = dt_mod.datetime.now()

            # Case: Late confirmation accepted prior to reassignment
            if curr_sr["escalation_status"] == "escalated":
                update_appointment_confirmation_status(sr_id, "confirmed", confirmed_at=now_ts)
                with get_db_connection() as conn:
                    with dict_cursor(conn) as cursor:
                        cursor.execute(
                            """
                            UPDATE service_requests
                            SET escalation_status = 'resolved'
                            WHERE id = %s;
                            """,
                            (sr_id,)
                        )
                        cursor.execute(
                            """
                            INSERT INTO service_request_audit_log (request_id, triggered_by, from_status, to_status, notes)
                            VALUES (%s, 'agent_sms', 'escalated', 'resolved', 'Late confirmation accepted prior to reassignment');
                            """,
                            (sr_id,)
                        )
                        conn.commit()
                cancel_pending_sms_reminders(sr_id, recipient_type="agent")
                reply_text = f"Late confirmation accepted for Appointment #{sr_id}. Thank you!"
                dispatch_agent_receipt(reply_text)
                return {
                    "status": "processed",
                    "category": "agent_confirm_late",
                    "appointment_id": sr_id,
                    "reply": reply_text
                }

            # Case: Normal timely confirmation
            update_appointment_confirmation_status(sr_id, "confirmed", confirmed_at=now_ts)
            cancel_pending_sms_reminders(sr_id, recipient_type="agent")
            reply_text = f"Appointment #{sr_id} confirmed. Thank you!"
            dispatch_agent_receipt(reply_text)
            return {
                "status": "processed",
                "category": "agent_confirm",
                "appointment_id": sr_id,
                "reply": reply_text
            }

        reply_text = "No pending appointments found assigned to your mobile number."
        dispatch_agent_receipt(reply_text)
        return {"status": "processed", "category": "agent_confirm_noop", "reply": reply_text}

    elif is_decline:
        with get_db_connection() as conn:
            with dict_cursor(conn) as cursor:
                cursor.execute(
                    """
                    SELECT sr.id, sr.staff_agent_id, sr.confirmation_status, sr.escalation_status
                    FROM service_requests sr
                    WHERE sr.staff_agent_id = ANY(%s)
                      AND sr.status NOT IN ('completed', 'cancelled', 'cancelled_by_customer')
                    ORDER BY sr.created_at DESC LIMIT 1;
                    """,
                    (candidate_agent_ids,)
                )
                curr_sr = cursor.fetchone()

        if curr_sr:
            sr_id = curr_sr["id"]
            update_appointment_confirmation_status(sr_id, "declined")
            escalate_service_request(sr_id, reason="AGENT_DECLINED", triggered_by="agent_sms")
            cancel_pending_sms_reminders(sr_id, recipient_type="agent")

            from serviceBot.services.sms_reminders import dispatch_supervisor_escalation_alert
            dispatch_supervisor_escalation_alert(sr_id, reason="AGENT_DECLINED")

            reply_text = f"Appointment #{sr_id} has been marked declined. Supervisor notified."
            dispatch_agent_receipt(reply_text)
            return {
                "status": "processed",
                "category": "agent_decline",
                "appointment_id": sr_id,
                "reply": reply_text
            }

        reply_text = "No pending appointments found assigned to your mobile number."
        dispatch_agent_receipt(reply_text)
        return {"status": "processed", "category": "agent_decline_noop", "reply": reply_text}

    else:
        # Free-text from staff agent
        reply_text = "Message received. For urgent scheduling assistance, please contact dispatch."
        dispatch_agent_receipt(reply_text)
        return {"status": "processed", "category": "agent_free_text", "reply": reply_text}


def process_inbound_sms(from_phone: str, body: str, twilio_message_sid: str = None) -> dict:
    """Processes an inbound SMS message through the classification pipeline."""
    # Check if sender is a staff agent / technician
    from serviceBot.db.queries import get_staff_agent_by_phone
    staff_agent = get_staff_agent_by_phone(from_phone)
    if staff_agent:
        return handle_agent_confirmation_action(staff_agent, body, twilio_message_sid, from_phone=from_phone)

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
                    new_status = "confirmed" if category == "action_confirm" else "cancelled"
                    try:
                        from serviceBot.db.queries import update_service_request_status
                        update_service_request_status(target_sr_id, new_status, triggered_by="customer_sms", notes="Status updated via customer SMS action")
                        reply_text = (
                            "Your appointment has been confirmed. Thank you!"
                            if category == "action_confirm"
                            else "Your appointment has been cancelled as requested."
                        )
                        if get_customer_opt_in(from_phone):
                            client.send_sms(to=from_phone, body=reply_text, template_type="action_receipt", appointment_id=target_sr_id)
                            add_sms_message(conv_id, "outbound", "system", "System", reply_text)
                        return {"status": "processed", "category": category, "appointment_id": target_sr_id, "new_status": new_status}
                    except ValueError as err:
                        reply_text = "Your appointment cannot be modified because its status is already closed."
                        if get_customer_opt_in(from_phone):
                            client.send_sms(to=from_phone, body=reply_text, template_type="action_receipt", appointment_id=target_sr_id)
                            add_sms_message(conv_id, "outbound", "system", "System", reply_text)
                        return {"status": "error", "category": category, "appointment_id": target_sr_id, "error": str(err)}

        # Fallback to free_text if no appointment found
        category = "free_text"

    # Conversational message (Free-text -> Human Handoff only if explicitly requested)
    if result.get("is_handoff_requested"):
        from serviceBot.services.handoff_service import trigger_human_handoff
        handoff_res = trigger_human_handoff(conv_id, from_phone, body)
        return {"status": "handoff_triggered", "category": "free_text", "details": handoff_res}
    else:
        return {"status": "processed", "category": "free_text", "message": "Message logged. Live handoff not requested."}
