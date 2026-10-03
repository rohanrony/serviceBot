import datetime as dt_mod
import threading
import time
from serviceBot.logger import get_logger
from serviceBot.db.queries import (
    schedule_sms_reminder,
    cancel_pending_sms_reminders,
    get_due_sms_reminders,
    mark_sms_reminder_status,
    get_customer_opt_in
)
from serviceBot.services.twilio_sms import TwilioSMSClient
from serviceBot.services.booking import BUSINESS_TZ

logger = get_logger("sms_reminders")


def get_current_business_time() -> dt_mod.datetime:
    """Returns current naive datetime in the shop's operational timezone (America/New_York)."""
    return dt_mod.datetime.now(BUSINESS_TZ).replace(tzinfo=None)


def parse_booking_datetime(dt_str: str) -> dt_mod.datetime:
    """Parses various date/time formats into naive datetime in business timezone."""
    if not dt_str:
        return None
    for fmt in [
        "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M",
        "%Y-%m-%d", "%I:%M %p", "%Y-%m-%dT%H:%M:%SZ"
    ]:
        try:
            dt = dt_mod.datetime.strptime(dt_str.strip(), fmt)
            if dt.year == 1900:
                now = get_current_business_time()
                dt = dt.replace(year=now.year, month=now.month, day=now.day)
            return dt
        except ValueError:
            pass
    return None


def compute_business_hours_deadline(
    start_time: dt_mod.datetime,
    duration_hours: float,
    business_days: list = None,
    business_hours: list = None,
) -> dt_mod.datetime:
    """
    Accumulates `duration_hours` strictly during configured shop operating business hours.
    Pauses overnight when business hours end, freezes across weekends/non-business days,
    and resumes ticking at shop opening on the next business day.
    """
    if duration_hours <= 0:
        return start_time

    from serviceBot.services.calendar_sync import (
        get_configured_business_days,
        get_configured_business_hours,
    )

    if business_days is None:
        business_days = get_configured_business_days()
    if business_hours is None:
        business_hours = get_configured_business_hours()

    business_days_set = set(business_days)
    if not business_days_set or not business_hours:
        return start_time + dt_mod.timedelta(hours=duration_hours)

    start_hour = min(business_hours)
    end_hour = max(business_hours) + 1  # e.g., if hours 7..17, close is 18:00

    cursor = start_time.replace(second=0, microsecond=0)
    remaining_minutes = int(round(duration_hours * 60))

    while remaining_minutes > 0:
        # Check if cursor is on a non-business day or after closing today
        if cursor.weekday() not in business_days_set or cursor.hour >= end_hour:
            cursor = (cursor + dt_mod.timedelta(days=1)).replace(
                hour=start_hour, minute=0, second=0
            )
            continue

        if cursor.hour < start_hour:
            cursor = cursor.replace(hour=start_hour, minute=0, second=0)

        # Cursor is now inside business hours on a business day
        closing_time_today = cursor.replace(hour=end_hour, minute=0, second=0)
        minutes_until_closing = int((closing_time_today - cursor).total_seconds() // 60)

        if remaining_minutes <= minutes_until_closing:
            cursor = cursor + dt_mod.timedelta(minutes=remaining_minutes)
            remaining_minutes = 0
        else:
            remaining_minutes -= minutes_until_closing
            cursor = (cursor + dt_mod.timedelta(days=1)).replace(
                hour=start_hour, minute=0, second=0
            )

    return cursor


def calculate_effective_confirmation_cutoff(
    booked_at: dt_mod.datetime,
    appt_time: dt_mod.datetime,
    config: dict = None,
) -> dt_mod.datetime:
    """
    Computes the effective confirmation deadline for an assigned staff agent using the
    Two-Factor Horizon-Adaptive Model:
    1. Assignment Acceptance SLA based on booking horizon.
    2. Pre-appointment safety net ceiling (T - final_reminder_hours).
    3. Morning Opening Grace protection for early morning visits.
    """
    if isinstance(booked_at, str):
        booked_at = parse_booking_datetime(booked_at)
    if isinstance(appt_time, str):
        appt_time = parse_booking_datetime(appt_time)

    if not booked_at or not appt_time:
        return appt_time

    if config is None:
        try:
            from serviceBot.api.portal import load_config
            config = load_config()
        except Exception:
            config = {}

    horizon_hours = max(0.0, (appt_time - booked_at).total_seconds() / 3600.0)

    start_h = config.get("business_hours_start")
    end_h = config.get("business_hours_end")
    if start_h is not None and end_h is not None:
        b_hours = list(range(int(start_h), int(end_h)))
    else:
        from serviceBot.services.calendar_sync import get_configured_business_hours
        b_hours = get_configured_business_hours()

    b_days = config.get("business_days")
    if b_days is None:
        from serviceBot.services.calendar_sync import get_configured_business_days
        b_days = get_configured_business_days()

    # 1. Determine Acceptance SLA duration
    if horizon_hours >= 24.0:
        sla_hours = float(config.get("sla_advance_booking_hours", 4.0))
    elif horizon_hours >= 6.0:
        sla_hours = float(config.get("sla_medium_booking_hours", 3.0))
    else:
        sla_hours = float(config.get("sla_short_booking_hours", 1.5))

    acceptance_deadline = compute_business_hours_deadline(
        booked_at, sla_hours, business_days=b_days, business_hours=b_hours
    )

    # 2. Pre-appointment ceiling (default: T - 2h)
    final_reminder_hours = float(config.get("final_reminder_hours", 2.0))
    pre_appt_ceiling = appt_time - dt_mod.timedelta(hours=final_reminder_hours)

    # 3. Morning Opening Grace Rule for early morning appointments
    open_hour = min(b_hours) if b_hours else 8
    overnight_grace_min = int(config.get("overnight_grace_minutes", 30))
    appt_day_open = appt_time.replace(hour=open_hour, minute=0, second=0, microsecond=0)
    morning_grace_deadline = appt_day_open + dt_mod.timedelta(minutes=overnight_grace_min)

    if pre_appt_ceiling.date() == appt_time.date() and pre_appt_ceiling < morning_grace_deadline:
        pre_appt_ceiling = min(appt_time - dt_mod.timedelta(minutes=30), morning_grace_deadline)

    # Effective Cutoff is the minimum of acceptance SLA and pre-appointment ceiling
    cutoff = min(acceptance_deadline, pre_appt_ceiling)

    # Hard ceiling: cutoff must never exceed appt_time - 30 minutes
    max_allowed = appt_time - dt_mod.timedelta(minutes=30)
    if cutoff > max_allowed:
        cutoff = max_allowed

    return cutoff


def schedule_appointment_reminders(
    appointment_id: int,
    booking_time_str: str,
    customer_phone: str,
    agent_phone: str = None,
    booked_at: dt_mod.datetime = None,
    trigger_immediate: bool = False,
):
    """
    Schedules 3-attempt reminder cadence:
    Attempt 1 (Immediate on booking): Outbound notification to customer and confirmation prompt to agent.
    Attempt 2 (Intermediate follow-up): Midpoint business hours checkpoint.
    Attempt 3 (Final pre-appointment / cutoff): Prompt at cutoff for agent; pre-visit reminder for customer.
    Computes and persists confirmation_cutoff_at on the service request.
    """
    apt_dt = parse_booking_datetime(booking_time_str)
    if not apt_dt:
        return

    now = get_current_business_time()
    if booked_at is None:
        booked_at = now

    from serviceBot.api.portal import load_config
    cfg = load_config()

    # 1. Compute effective confirmation cutoff
    cutoff = calculate_effective_confirmation_cutoff(booked_at, apt_dt, cfg)

    # 2. Persist confirmation_cutoff_at on service request
    from serviceBot.db.connection import get_db_connection, dict_cursor
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                """
                UPDATE service_requests
                SET confirmation_cutoff_at = %s,
                    confirmation_status = COALESCE(confirmation_status, 'pending_agent_confirmation'),
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s;
                """,
                (cutoff, appointment_id),
            )
            conn.commit()

    # 3. Attempt 1 (Immediate)
    if customer_phone:
        schedule_sms_reminder(
            appointment_id=appointment_id,
            recipient_type="customer",
            recipient_phone=customer_phone,
            reminder_type="immediate",
            scheduled_at=now,
            attempt_number=1,
            attempt_kind="immediate_booking",
        )

    if agent_phone:
        schedule_sms_reminder(
            appointment_id=appointment_id,
            recipient_type="agent",
            recipient_phone=agent_phone,
            reminder_type="immediate",
            scheduled_at=now,
            attempt_number=1,
            attempt_kind="immediate_booking",
        )

    # 4. Attempt 2 (Intermediate Follow-up)
    horizon_hours = (apt_dt - booked_at).total_seconds() / 3600.0
    if horizon_hours >= 6.0 and cutoff > now:
        t_mid = now + (cutoff - now) / 2
        if t_mid > now + dt_mod.timedelta(minutes=15) and t_mid < cutoff:
            if agent_phone:
                schedule_sms_reminder(
                    appointment_id=appointment_id,
                    recipient_type="agent",
                    recipient_phone=agent_phone,
                    reminder_type="followup",
                    scheduled_at=t_mid,
                    attempt_number=2,
                    attempt_kind="intermediate_followup",
                )

    if horizon_hours >= 24.0 and customer_phone:
        t_24h = apt_dt - dt_mod.timedelta(hours=24)
        if t_24h > now:
            schedule_sms_reminder(
                appointment_id=appointment_id,
                recipient_type="customer",
                recipient_phone=customer_phone,
                reminder_type="24h",
                scheduled_at=t_24h,
                attempt_number=2,
                attempt_kind="intermediate_followup",
            )

    # 5. Attempt 3 (Final Reminder at Cutoff / pre-visit)
    if agent_phone and cutoff > now:
        schedule_sms_reminder(
            appointment_id=appointment_id,
            recipient_type="agent",
            recipient_phone=agent_phone,
            reminder_type="final",
            scheduled_at=cutoff,
            attempt_number=3,
            attempt_kind="final_reminder",
        )

    if customer_phone:
        t_2h = apt_dt - dt_mod.timedelta(hours=2)
        if t_2h > now:
            schedule_sms_reminder(
                appointment_id=appointment_id,
                recipient_type="customer",
                recipient_phone=customer_phone,
                reminder_type="2h",
                scheduled_at=t_2h,
                attempt_number=3,
                attempt_kind="final_reminder",
            )

    if trigger_immediate:
        try:
            run_reminder_polling_worker_cycle()
        except Exception as imm_err:
            logger.warning(f"Immediate reminder cycle execution failed for appt #{appointment_id}: {imm_err}")


def update_or_cancel_appointment_reminders(
    appointment_id: int,
    new_booking_time_str: str = None,
    customer_phone: str = None,
    agent_phone: str = None,
    reassign_only: bool = False,
):
    """Cancels pending reminders for an appointment and reschedules if a new booking time is given."""
    if reassign_only:
        cancel_pending_sms_reminders(appointment_id, recipient_type="agent")
        if new_booking_time_str and agent_phone:
            schedule_appointment_reminders(
                appointment_id,
                new_booking_time_str,
                customer_phone=None,
                agent_phone=agent_phone,
                trigger_immediate=True,
            )
        return

    cancel_pending_sms_reminders(appointment_id)
    if new_booking_time_str and customer_phone:
        schedule_appointment_reminders(appointment_id, new_booking_time_str, customer_phone, agent_phone)


def check_and_send_due_reminders() -> int:
    """Alias for run_reminder_polling_worker_cycle for cron execution."""
    return run_reminder_polling_worker_cycle()


def run_reminder_polling_worker_cycle() -> int:
    """Polls due reminders in sms_reminders and dispatches SMS with retry backoff."""
    from serviceBot.db.connection import get_db_connection, dict_cursor
    from serviceBot.api.portal import load_config
    cfg = load_config()

    now_business = get_current_business_time()
    due_reminders = []
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                """
                SELECT * FROM sms_reminders
                WHERE status = 'PENDING' AND scheduled_at <= %s
                ORDER BY scheduled_at ASC
                FOR UPDATE SKIP LOCKED;
                """,
                (now_business,)
            )
            due_reminders = [dict(r) for r in cursor.fetchall()]
            if not due_reminders:
                return 0
            for rem in due_reminders:
                cursor.execute(
                    "UPDATE sms_reminders SET status = 'PROCESSING' WHERE id = %s AND status = 'PENDING';",
                    (rem["id"],)
                )
            conn.commit()

    client = TwilioSMSClient()
    dispatched_count = 0

    max_retries = int(cfg.get("max_dispatch_retries", 3))
    backoff_list = cfg.get("retry_backoff_minutes", [1, 5, 15])

    for rem in due_reminders:
        phone = rem["recipient_phone"]
        rec_type = rem["recipient_type"]
        rem_type = rem["reminder_type"]
        att_kind = rem.get("attempt_kind") or "final_reminder"
        retry_count = rem.get("retry_count") or 0

        if rec_type == "customer" and not get_customer_opt_in(phone):
            mark_sms_reminder_status(rem["id"], "SKIPPED_OPT_OUT")
            logger.info(f"Skipped SMS reminder {rem['id']} due to customer opt-out for {phone}.")
            continue

        # Dynamic body generation
        if rec_type == "customer":
            if att_kind == "immediate_booking":
                body = f"Confirmation: Your appointment is scheduled (Appointment #{rem['appointment_id']}). Address: Davidson Car Care. Reply STOP to opt out."
            elif att_kind == "intermediate_followup":
                body = f"Reminder: Your upcoming appointment #{rem['appointment_id']} is scheduled. Please let us know if you need to reschedule."
            else:
                body = f"Reminder: You have an upcoming appointment in {rem_type} (Appointment #{rem['appointment_id']})."
        elif rec_type == "agent":
            if att_kind == "immediate_booking":
                body = f"New Assignment: Service request #{rem['appointment_id']}. Please reply CONFIRM or C to accept, or DECLINE if unavailable."
            elif att_kind == "intermediate_followup":
                body = f"Follow-up: Service request #{rem['appointment_id']} is awaiting your confirmation. Reply CONFIRM or DECLINE."
            elif att_kind == "final_reminder":
                body = f"URGENT: Service request #{rem['appointment_id']} must be confirmed immediately or it will be escalated to a supervisor. Reply CONFIRM or DECLINE."
            else:
                body = f"Agent Reminder: You have an upcoming service request #{rem['appointment_id']} in {rem_type}."
        elif rec_type == "supervisor":
            body = f"ESCALATION ALERT: Service request #{rem['appointment_id']} unconfirmed. Please take action in the portal."
        else:
            body = f"Reminder: Appointment #{rem['appointment_id']}."

        # Determine dispatch channel from matrix rules (default to WHATSAPP)
        channel = "WHATSAPP"
        try:
            from serviceBot.db.queries import get_sms_matrix_rules, is_agent_whatsapp_connected
            event_name = "BOOKING" if att_kind == "immediate_booking" else f"REMINDER_{rem_type.upper()}"
            rules = get_sms_matrix_rules()
            matching_rules = [
                r for r in rules
                if r.get("event_type") == event_name and r.get("recipient_role") == rec_type
            ]
            enabled_channels = [
                (r.get("channel") or "WHATSAPP").upper()
                for r in matching_rules
                if r.get("enabled")
            ]
            if "WHATSAPP" in enabled_channels and (rec_type != "agent" or is_agent_whatsapp_connected(phone)):
                channel = "WHATSAPP"
            elif enabled_channels:
                channel = enabled_channels[0]
            elif matching_rules:
                channel = None
            else:
                channel = "WHATSAPP"
        except Exception:
            channel = "WHATSAPP"

        if not channel:
            logger.info(f"Skipping reminder #{rem['id']} because {event_name} is disabled for {rec_type} in SMS matrix rules.")
            with get_db_connection() as conn:
                with dict_cursor(conn) as cursor:
                    cursor.execute(
                        "UPDATE sms_reminders SET status = 'CANCELLED', last_error = 'Disabled in SMS matrix rules' WHERE id = %s;",
                        (rem["id"],)
                    )
                conn.commit()
            continue

        if channel == "WHATSAPP":
            res = client.send_whatsapp(
                to=phone,
                body=body,
                template_type=f"reminder_{rem_type}",
                appointment_id=rem["appointment_id"],
                recipient_type=rec_type,
            )
        else:
            res = client.send_sms(
                to=phone,
                body=body,
                template_type=f"reminder_{rem_type}",
                appointment_id=rem["appointment_id"],
                recipient_type=rec_type,
            )

        is_success = bool(res.get("success") or res.get("status") in ("DELIVERED", "SENT"))
        error_msg = res.get("error")

        with get_db_connection() as conn:
            with dict_cursor(conn) as cursor:
                if is_success:
                    cursor.execute(
                        "UPDATE sms_reminders SET status = %s WHERE id = %s;",
                        (res.get("status", "SENT"), rem["id"])
                    )
                    if rec_type == "customer":
                        try:
                            from serviceBot.db.queries import get_or_create_sms_conversation, add_sms_message
                            conv = get_or_create_sms_conversation(phone, context_appointment_id=rem["appointment_id"])
                            add_sms_message(
                                conversation_id=conv["id"],
                                direction="outbound",
                                sender_type="system",
                                sender_name="System Reminder",
                                body=body,
                                twilio_message_sid=res.get("sid")
                            )
                        except Exception:
                            pass
                else:
                    # Failure handling with retry backoff
                    if retry_count < max_retries:
                        new_retries = retry_count + 1
                        backoff_idx = min(retry_count, len(backoff_list) - 1)
                        backoff_mins = backoff_list[backoff_idx]
                        next_time = get_current_business_time() + dt_mod.timedelta(minutes=backoff_mins)
                        cursor.execute(
                            """
                            UPDATE sms_reminders
                            SET status = 'PENDING',
                                retry_count = %s,
                                scheduled_at = %s,
                                last_error = %s
                            WHERE id = %s;
                            """,
                            (new_retries, next_time, error_msg or "Carrier failure", rem["id"])
                        )
                        logger.warning(f"Reminder {rem['id']} failed ({error_msg}). Rescheduled retry #{new_retries} at {next_time}.")
                    else:
                        cursor.execute(
                            """
                            UPDATE sms_reminders
                            SET status = 'FAILED',
                                retry_count = %s,
                                last_error = %s
                            WHERE id = %s;
                            """,
                            (retry_count, error_msg or "Max retries exceeded", rem["id"])
                        )
                        logger.error(f"Reminder {rem['id']} permanently failed after {retry_count} retries: {error_msg}")
                        if rec_type == "agent":
                            try:
                                from serviceBot.db.queries import escalate_service_request
                                escalate_service_request(rem["appointment_id"], reason="DELIVERY_FAILED", triggered_by="sms_worker")
                            except Exception as esc_err:
                                logger.warning(f"Failed to auto-escalate delivery failure for #{rem['appointment_id']}: {esc_err}")
                conn.commit()

        logger.info(f"Dispatched SMS reminder {rem['id']} to {phone} (success={is_success}).")
        dispatched_count += 1

    return dispatched_count


def dispatch_supervisor_escalation_alert(service_request_id: int, reason: str = "TIMEOUT_NO_RESPONSE") -> dict:
    """
    Dispatches an urgent escalation SMS to the supervisor alert mobile phone
    when an appointment confirmation times out, is declined, or fails delivery.
    """
    from serviceBot.api.portal import load_config
    from serviceBot.db.connection import get_db_connection, dict_cursor

    cfg = load_config()
    supervisor_phone = cfg.get("supervisor_alert_phone") or "+19195550199"

    customer_name = "Customer"
    technician_name = "Unassigned"
    time_str = "Scheduled Time"

    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                """
                SELECT sr.id, sr.status, sr.staff_agent_id, c.name AS customer_name,
                       sa.name AS agent_name, ar.starts_at
                FROM service_requests sr
                LEFT JOIN customers c ON c.id = sr.customer_id
                LEFT JOIN staff_agents sa ON sa.id = sr.staff_agent_id
                LEFT JOIN appointment_reservations ar ON ar.service_request_id = sr.id AND ar.status = 'ACTIVE'
                WHERE sr.id = %s;
                """,
                (service_request_id,)
            )
            row = cursor.fetchone()
            if not row or (row.get("status") or "").lower() in ("cancelled", "cancelled_by_customer"):
                logger.info(f"Skipping supervisor escalation alert for cancelled or missing appointment #{service_request_id}")
                return {
                    "success": False,
                    "skipped": True,
                    "reason": "Appointment is cancelled or not found"
                }

            if row:
                if row.get("customer_name"):
                    customer_name = row["customer_name"]
                if row.get("agent_name"):
                    technician_name = row["agent_name"]
                if row.get("starts_at"):
                    time_str = row["starts_at"].strftime("%b %-d at %-I:%M %p")

            # Audit log entry
            cursor.execute(
                """
                INSERT INTO service_request_audit_log (request_id, triggered_by, from_status, to_status, notes)
                VALUES (%s, 'supervisor_escalation', NULL, NULL, %s);
                """,
                (service_request_id, f"Supervisor escalation alert sent to {supervisor_phone} (reason={reason})")
            )
            conn.commit()

    body = (
        f"URGENT ESCALATION: Appointment #{service_request_id} ({customer_name} at {time_str}) "
        f"is UNCONFIRMED by technician {technician_name} (Reason: {reason}). "
        f"Review & reassign: https://davidson.carcare/portal/reassign/{service_request_id}"
    )

    client = TwilioSMSClient()
    sms_res = client.send_sms(
        to=supervisor_phone,
        body=body,
        template_type="supervisor_alert",
        appointment_id=service_request_id
    )

    logger.warning(
        f"[ESCALATION ALERT] Supervisor notified for appt #{service_request_id} "
        f"at {supervisor_phone} (reason={reason}, status={sms_res.get('status')})"
    )

    return {
        "success": bool(sms_res.get("success") or sms_res.get("status") in ("DELIVERED", "SENT")),
        "supervisor_phone": supervisor_phone,
        "body": body,
        "sid": sms_res.get("sid")
    }


def check_and_escalate_unconfirmed_appointments(as_of_time: dt_mod.datetime = None) -> int:
    """
    Evaluates unconfirmed appointments against their confirmation_cutoff_at.
    Escalates breached appointments and alerts supervisor.
    """
    from serviceBot.db.queries import (
        get_breached_unconfirmed_appointments,
        escalate_service_request,
    )

    if as_of_time is None:
        as_of_time = get_current_business_time()

    breached = get_breached_unconfirmed_appointments(as_of_time=as_of_time)
    escalated_count = 0

    for item in breached:
        sr_id = item["id"]
        try:
            escalate_service_request(sr_id, reason="TIMEOUT_NO_RESPONSE", triggered_by="escalation_monitor")
            dispatch_supervisor_escalation_alert(sr_id, reason="TIMEOUT_NO_RESPONSE")
            escalated_count += 1
            logger.warning(f"Appointment #{sr_id} breached confirmation cutoff and was escalated.")
        except Exception as err:
            logger.error(f"Failed to escalate breached appointment #{sr_id}: {err}", exc_info=err)

    return escalated_count


_reminder_worker_started = False

def start_reminder_polling_worker(interval_seconds: int = 30):
    global _reminder_worker_started
    if _reminder_worker_started:
        return
    _reminder_worker_started = True

    def _loop():
        logger.info("SMS reminder polling worker thread started.")
        while True:
            try:
                run_reminder_polling_worker_cycle()
            except Exception as e:
                logger.error(f"Error in reminder worker cycle: {e}", exc_info=e)
            try:
                check_and_escalate_unconfirmed_appointments()
            except Exception as esc_err:
                logger.error(f"Error in unconfirmed escalation check: {esc_err}", exc_info=esc_err)
            time.sleep(interval_seconds)

    t = threading.Thread(target=_loop, daemon=True, name="sms-reminder-polling")
    t.start()
