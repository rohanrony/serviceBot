import json
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


def parse_agent_confirmation_intent(body: str) -> dict:
    """
    Parses staff agent / technician confirmation replies:
    - Batch: 'CONFIRM ALL', 'ACCEPT ALL', 'C ALL', 'YES ALL' -> CONFIRM_ALL
             'DECLINE ALL', 'REJECT ALL', 'NO ALL' -> DECLINE_ALL
    - Numeric selection: 'CONFIRM 1', 'C 1', 'CONFIRM #101', 'DECLINE 2', etc.
    - Pure number: '1', '2' -> CONFIRM (index)
    - Bare actions: 'CONFIRM', 'C', 'YES', 'ACCEPT' -> CONFIRM
                    'DECLINE', 'UNAVAILABLE', 'NO', 'CANNOT' -> DECLINE
    - Fallback: UNKNOWN
    """
    import re
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


def handle_agent_confirmation_action(staff_agent: dict, body: str, twilio_message_sid: str = None, from_phone: str = None) -> dict:
    """
    Handles inbound SMS replies from staff agents / technicians:
    - Confirms assignment on 'CONFIRM', 'C', 'YES', 'ACCEPT' (or targeted selection)
    - Declines assignment and triggers supervisor escalation on 'DECLINE', 'UNAVAILABLE', 'NO', 'CANNOT'
    - Presents disambiguation menu when technician has >1 pending assignments and sends bare response
    - Atomically confirms all assignments on 'CONFIRM ALL'
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

    intent = parse_agent_confirmation_intent(body)
    action = intent["action"]
    selector_type = intent["selector_type"]
    value = intent["value"]

    if action == "UNKNOWN":
        # Free-text from staff agent
        reply_text = "Message received. For urgent scheduling assistance, please contact dispatch."
        dispatch_agent_receipt(reply_text)
        return {"status": "processed", "category": "agent_free_text", "reply": reply_text}

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

    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            # 1. Fetch all currently assigned active appointments pending confirmation, sorted deterministically
            cursor.execute(
                """
                SELECT sr.id, sr.staff_agent_id, sr.confirmation_status, sr.escalation_status, sr.created_at,
                       sr.booking_time, sr.time_slot, sr.duration_minutes, sr.service_type, sr.issue_description,
                       v.year AS vehicle_year, v.make AS vehicle_make, v.model AS vehicle_model,
                       c.name AS customer_name, c.phone AS customer_phone,
                       sa.name AS agent_name
                FROM service_requests sr
                LEFT JOIN staff_agents sa ON sa.id = sr.staff_agent_id
                LEFT JOIN vehicles v ON sr.vehicle_id = v.id
                LEFT JOIN customers c ON sr.customer_id = c.id
                WHERE sr.staff_agent_id = ANY(%s)
                  AND sr.confirmation_status = 'pending_agent_confirmation'
                  AND sr.status NOT IN ('completed', 'cancelled', 'cancelled_by_customer')
                ORDER BY sr.booking_time ASC NULLS LAST, sr.created_at ASC;
                """,
                (candidate_agent_ids,)
            )
            pending_list = cursor.fetchall() or []

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

    # If appointment was already reassigned to another agent and no pending appointments exist
    if superseded_sr and not pending_list:
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

    if not pending_list:
        reply_text = "No pending appointments found assigned to your mobile number."
        dispatch_agent_receipt(reply_text)
        category = "agent_confirm_noop" if "CONFIRM" in action else "agent_decline_noop"
        return {"status": "processed", "category": category, "reply": reply_text}

    agent_name = staff_agent.get("name") or "Technician"
    now_ts = dt_mod.datetime.now()

    # --- Case 1: Batch Actions ---
    if action == "CONFIRM_ALL":
        for sr in pending_list:
            update_appointment_confirmation_status(sr["id"], "confirmed", confirmed_at=now_ts)
            cancel_pending_sms_reminders(sr["id"], recipient_type="agent")
        ids_str = ", ".join(f"#{sr['id']}" for sr in pending_list)
        reply_text = f"✅ Confirmed all {len(pending_list)} assignments ({ids_str}). Your schedule is up to date!"
        dispatch_agent_receipt(reply_text)
        return {
            "status": "processed",
            "category": "agent_confirmed_all",
            "confirmed_count": len(pending_list),
            "appointment_ids": [sr["id"] for sr in pending_list],
            "reply": reply_text,
        }

    if action == "DECLINE_ALL":
        for sr in pending_list:
            update_appointment_confirmation_status(sr["id"], "declined")
            escalate_service_request(sr["id"], reason="AGENT_DECLINED", triggered_by="agent_sms")
            cancel_pending_sms_reminders(sr["id"], recipient_type="agent")
            try:
                from serviceBot.services.sms_reminders import dispatch_supervisor_escalation_alert
                dispatch_supervisor_escalation_alert(sr["id"], reason="AGENT_DECLINED")
            except Exception:
                pass
        ids_str = ", ".join(f"#{sr['id']}" for sr in pending_list)
        reply_text = f"❌ Declined all {len(pending_list)} assignments ({ids_str}). Supervisor notified."
        dispatch_agent_receipt(reply_text)
        return {
            "status": "processed",
            "category": "agent_declined_all",
            "declined_count": len(pending_list),
            "appointment_ids": [sr["id"] for sr in pending_list],
            "reply": reply_text,
        }

    # --- Case 2: Multiple Jobs with Bare Action -> Disambiguation Menu ---
    if len(pending_list) > 1 and selector_type == "bare":
        from serviceBot.services.sms_reminders import parse_booking_datetime
        number_emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
        item_lines = []
        for idx, sr in enumerate(pending_list):
            emoji = number_emojis[idx] if idx < len(number_emojis) else f"{idx + 1}."
            v_parts = [sr.get("vehicle_year"), sr.get("vehicle_make"), sr.get("vehicle_model")]
            v_str = " ".join([str(p).strip() for p in v_parts if p and str(p).strip().upper() not in ("NONE", "NULL", "N/A")]).strip()
            if not v_str:
                v_str = sr.get("vehicle") or sr.get("service_type") or "Service"

            b_time_val = sr.get("booking_time") or sr.get("time_slot") or ""
            dt = parse_booking_datetime(b_time_val) if b_time_val else None
            t_str = dt.strftime("%b %d, %I:%M %p").replace(" 0", " ") if dt else (str(b_time_val)[:16] if b_time_val else "Scheduled")
            item_lines.append(f"{emoji} #{sr['id']} - {v_str} ({t_str})")

        items_block = "\n".join(item_lines)
        menu_text = (
            f"⚠️ You have {len(pending_list)} assignments awaiting confirmation:\n"
            f"{items_block}\n\n"
            f"Reply CONFIRM 1 (or C 1), CONFIRM 2, or CONFIRM ALL.\n"
            f"(Or reply DECLINE 1 / DECLINE 2)."
        )
        dispatch_agent_receipt(menu_text)
        return {
            "status": "disambiguation_requested",
            "category": "agent_disambiguation_menu",
            "pending_count": len(pending_list),
            "reply": menu_text,
        }

    # --- Case 3: Target Resolution (Single Job Fast Path or Index/ID Selection) ---
    if len(pending_list) == 1:
        target_sr = pending_list[0]
    else:
        # Multiple jobs, selector_type in ('numeric', 'index') with value
        target_sr = None
        if value is not None:
            if 1 <= value <= len(pending_list):
                target_sr = pending_list[value - 1]
            else:
                for sr in pending_list:
                    if sr["id"] == value:
                        target_sr = sr
                        break
        if not target_sr:
            valid_ids = ", ".join(f"#{sr['id']}" for sr in pending_list)
            reply_text = (
                f"Invalid choice. You have {len(pending_list)} pending assignments ({valid_ids}). "
                f"Reply CONFIRM 1, CONFIRM 2, or CONFIRM ALL."
            )
            dispatch_agent_receipt(reply_text)
            return {
                "status": "error_out_of_bounds",
                "category": "agent_out_of_bounds",
                "reply": reply_text,
            }

    sr_id = target_sr["id"]
    remaining = [sr for sr in pending_list if sr["id"] != sr_id]
    rem_suffix = ""
    if remaining:
        if len(remaining) == 1:
            rem_suffix = f" (1 assignment remaining: #{remaining[0]['id']})"
        else:
            rem_ids = ", ".join(f"#{r['id']}" for r in remaining)
            rem_suffix = f" ({len(remaining)} assignments remaining: {rem_ids})"

    if action == "CONFIRM":
        # Check late confirmation
        if target_sr.get("escalation_status") == "escalated":
            update_appointment_confirmation_status(sr_id, "confirmed", confirmed_at=now_ts)
            with get_db_connection() as conn:
                with dict_cursor(conn) as cursor:
                    cursor.execute("UPDATE service_requests SET escalation_status = 'resolved' WHERE id = %s;", (sr_id,))
                    conn.commit()
            cancel_pending_sms_reminders(sr_id, recipient_type="agent")
            reply_text = f"Late confirmation accepted for Appointment #{sr_id}. Thank you!{rem_suffix}"
            dispatch_agent_receipt(reply_text)
            return {
                "status": "processed",
                "category": "agent_confirm_late",
                "appointment_id": sr_id,
                "reply": reply_text,
            }

        update_appointment_confirmation_status(sr_id, "confirmed", confirmed_at=now_ts)
        cancel_pending_sms_reminders(sr_id, recipient_type="agent")
        try:
            with get_db_connection() as conn:
                with dict_cursor(conn) as cursor:
                    cursor.execute(
                        """
                        INSERT INTO service_request_audit_log 
                        (request_id, event_type, from_status, to_status, triggered_by, actor_name, notes, metadata)
                        VALUES (%s, 'AGENT_CONFIRMED', %s, 'confirmed', 'agent_sms', %s, %s, %s);
                        """,
                        (
                            sr_id,
                            target_sr.get("confirmation_status") or "pending_agent_confirmation",
                            agent_name,
                            f"Technician {agent_name} replied '{body.strip()}' via SMS. Assignment confirmed.",
                            json.dumps({"agent_id": staff_agent.get("id"), "agent_name": agent_name, "reply": body.strip(), "phone": from_phone})
                        )
                    )
                    conn.commit()
        except Exception:
            pass
        reply_text = f"Appointment #{sr_id} confirmed. Thank you!{rem_suffix}"
        dispatch_agent_receipt(reply_text)
        return {
            "status": "processed",
            "category": "agent_confirm",
            "appointment_id": sr_id,
            "reply": reply_text,
        }

    elif action == "DECLINE":
        update_appointment_confirmation_status(sr_id, "declined")
        escalate_service_request(sr_id, reason="AGENT_DECLINED", triggered_by="agent_sms")
        cancel_pending_sms_reminders(sr_id, recipient_type="agent")
        try:
            with get_db_connection() as conn:
                with dict_cursor(conn) as cursor:
                    cursor.execute(
                        """
                        INSERT INTO service_request_audit_log 
                        (request_id, event_type, from_status, to_status, triggered_by, actor_name, notes, metadata)
                        VALUES (%s, 'AGENT_DECLINED', %s, 'declined', 'agent_sms', %s, %s, %s);
                        """,
                        (
                            sr_id,
                            target_sr.get("confirmation_status") or "pending_agent_confirmation",
                            agent_name,
                            f"Technician {agent_name} replied '{body.strip()}' via SMS. Assignment declined.",
                            json.dumps({"agent_id": staff_agent.get("id"), "agent_name": agent_name, "reply": body.strip(), "phone": from_phone})
                        )
                    )
                    conn.commit()
        except Exception:
            pass
        try:
            from serviceBot.services.sms_reminders import dispatch_supervisor_escalation_alert
            dispatch_supervisor_escalation_alert(sr_id, reason="AGENT_DECLINED")
        except Exception:
            pass
        reply_text = f"Appointment #{sr_id} marked declined. Supervisor notified.{rem_suffix}"
        dispatch_agent_receipt(reply_text)
        return {
            "status": "processed",
            "category": "agent_decline",
            "appointment_id": sr_id,
            "reply": reply_text,
        }


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
