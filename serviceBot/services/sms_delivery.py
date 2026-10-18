"""Durable recovery of WhatsApp session-window failures through permitted SMS."""

from serviceBot.db.connection import dict_cursor, get_db_connection


def _sms_allowed(cursor, dispatch):
    event_type = dispatch["template_type"].upper()
    role = dispatch["recipient_type"]
    # Native router templates prefix staff roles; matrix events do not.
    if role in ("agent", "admin"):
        event_type = event_type.removeprefix(f"{role.upper()}_")
    cursor.execute(
        "SELECT enabled FROM sms_matrix_rules WHERE event_type=%s AND recipient_role=%s AND channel='SMS';",
        (event_type, role),
    )
    rule = cursor.fetchone()
    if not rule or not rule["enabled"]:
        return False, "SKIPPED_SMS_DISABLED"
    if dispatch["recipient_type"] == "customer":
        import re

        digits = re.sub(r"\D", "", dispatch["recipient_phone"])
        local = digits[1:] if len(digits) == 11 and digits.startswith("1") else digits
        international = f"1{local}" if len(local) == 10 else digits
        cursor.execute(
            r"SELECT sms_opt_in FROM customers WHERE regexp_replace(phone, '\D', '', 'g') IN (%s,%s,%s);",
            (digits, local, international),
        )
        if any(row.get("sms_opt_in") is False for row in cursor.fetchall()):
            return False, "SKIPPED_OPT_OUT"
    return True, None


def record_delivery_status(cursor, original, status, error_code=None, error_message=None):
    """Caller holds the original log row lock; status and admission share its transaction."""
    previous = original.get("status")
    if previous in ("DELIVERED", "FAILED") and status == "SENT":
        return
    # A late failure must not override demonstrated delivery or start recovery.
    if previous == "DELIVERED" and status == "FAILED":
        return
    cursor.execute(
        """UPDATE sms_log SET status=%s,error_code=COALESCE(%s,error_code),error_message=COALESCE(%s,error_message),
           sent_at=CASE WHEN %s IN ('SENT','DELIVERED') THEN CURRENT_TIMESTAMP ELSE sent_at END WHERE id=%s;""",
        (status, error_code, error_message, status, original["id"]),
    )
    if status != "FAILED" or str(error_code) != "63016" or original.get("channel") != "WHATSAPP" or not original.get("body"):
        return
    allowed, _ = _sms_allowed(cursor, original)
    if not allowed:
        return
    cursor.execute(
        "SELECT id FROM outbox_notifications WHERE event_type='sms_delivery_fallback' AND payload->>'source_log_id'=%s LIMIT 1;",
        (str(original["id"]),),
    )
    if cursor.fetchone():
        return
    cursor.execute(
        """INSERT INTO sms_log (appointment_id,recipient_type,recipient_phone,template_type,status,body,channel)
           VALUES (%s,%s,%s,%s,'PENDING',%s,'SMS') RETURNING id;""",
        (original["appointment_id"], original["recipient_type"], original["recipient_phone"].removeprefix("whatsapp:"), original["template_type"], original["body"]),
    )
    fallback_id = cursor.fetchone()["id"]
    from serviceBot.services.outbox_worker import enqueue_outbox_event

    enqueue_outbox_event(cursor, "sms_delivery_fallback", original["appointment_id"], {
        "source_log_id": original["id"], "fallback_log_id": fallback_id,
    })


def dispatch_sms_fallback(payload):
    """Use one durable log; provider calls occur after the policy transaction releases locks."""
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("SELECT * FROM sms_log WHERE id=%s FOR UPDATE;", (payload["fallback_log_id"],))
            dispatch = cursor.fetchone()
            if not dispatch or dispatch.get("channel") != "SMS":
                raise ValueError("SMS fallback log is missing or invalid")
            if dispatch.get("twilio_message_sid"):
                return
            allowed, skipped = _sms_allowed(cursor, dispatch)
            if not allowed:
                cursor.execute("UPDATE sms_log SET status=%s WHERE id=%s;", (skipped, dispatch["id"]))
                return
    from serviceBot.services.twilio_sms import TwilioSMSClient

    result = TwilioSMSClient().send_sms(
        to=dispatch["recipient_phone"], body=dispatch["body"],
        template_type=dispatch["template_type"], appointment_id=dispatch["appointment_id"],
        recipient_type=dispatch["recipient_type"], dispatch_log_id=dispatch["id"], channel="SMS",
    )
    if result.get("success") is False and not str(result.get("status", "")).startswith("SKIPPED"):
        raise RuntimeError("SMS delivery fallback failed")
