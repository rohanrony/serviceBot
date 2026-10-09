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

from serviceBot.services import timezone_service

logger = get_logger("sms_reminders")


def get_current_business_time() -> dt_mod.datetime:
    """Returns current naive datetime in the shop's operational timezone."""
    return timezone_service.now_in_business_tz().replace(tzinfo=None)


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


def format_time_slot_range(raw_time_str: str, duration_minutes: int = 60) -> str:
    """Formats raw datetime or time string into start & end time slot (e.g., Jul 23, 2026 (2:00 PM - 3:00 PM))."""
    if not raw_time_str or str(raw_time_str).strip().upper() in ("N/A", "ASAP", "NONE"):
        return str(raw_time_str) if raw_time_str else "N/A"
    clean_str = str(raw_time_str).strip()
    dt = parse_booking_datetime(clean_str)
    if not dt:
        return clean_str
    end_dt = dt + dt_mod.timedelta(minutes=duration_minutes)
    date_part = dt.strftime("%b %d, %Y")
    start_time_part = dt.strftime("%I:%M %p").lstrip("0")
    end_time_part = end_dt.strftime("%I:%M %p").lstrip("0")
    return f"{date_part} ({start_time_part} - {end_time_part})"


def get_shop_address_and_map_url(cfg: dict = None) -> tuple[str, str]:
    """Retrieves configured shop address and Google Maps navigation link."""
    import urllib.parse
    if cfg is None:
        from serviceBot.api.portal import load_config
        cfg = load_config()
    address = (cfg.get("business_address") or "123 Main St, Springfield, NC 27513").strip()
    map_url = (cfg.get("google_maps_url") or "").strip()
    if not map_url and address:
        map_url = f"https://maps.google.com/?q={urllib.parse.quote_plus(address)}"
    return address, map_url


def fetch_appointment_customer_details(appointment_id: int) -> dict:
    """Fetches customer, vehicle, and booking details for appointment notification formatting."""
    if not appointment_id:
        return {}
    try:
        from serviceBot.db.connection import get_db_connection, dict_cursor
        with get_db_connection() as conn:
            with dict_cursor(conn) as cursor:
                cursor.execute("""
                    SELECT sr.id, sr.service_type, sr.issue_description, sr.booking_time, sr.time_slot, sr.duration_minutes,
                           c.name AS customer_name, c.phone AS customer_phone,
                           v.year AS vehicle_year, v.make AS vehicle_make, v.model AS vehicle_model,
                           sa.id AS agent_id, sa.name AS agent_name
                    FROM service_requests sr
                    LEFT JOIN customers c ON sr.customer_id = c.id
                    LEFT JOIN vehicles v ON sr.vehicle_id = v.id
                    LEFT JOIN staff_agents sa ON sr.staff_agent_id = sa.id
                    WHERE sr.id = %s;
                """, (appointment_id,))
                row = cursor.fetchone()
                if not row:
                    return {}
                v_parts = [row.get("vehicle_year"), row.get("vehicle_make"), row.get("vehicle_model")]
                v_str = " ".join([str(p).strip() for p in v_parts if p and str(p).strip().upper() not in ("NONE", "NULL", "N/A")]).strip()
                b_time = row.get("booking_time") or row.get("time_slot") or ""
                return {
                    "customer_name": row.get("customer_name") or "there",
                    "customer_phone": row.get("customer_phone") or "",
                    "service_type": row.get("service_type") or "Service",
                    "booking_time": str(b_time)[:19] if b_time else "",
                    "duration_minutes": row.get("duration_minutes") or 60,
                    "vehicle": v_str or "Vehicle on file",
                    "agent_name": row.get("agent_name"),
                    "issue": row.get("issue_description") or "",
                }
    except Exception as e:
        logger.warning(f"Failed to fetch appointment details for appointment #{appointment_id}: {e}")
        return {}


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
        sla_hours = float(config.get("sla_short_booking_hours", 2.0))

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
    customer_phone: str = None,
    agent_phone: str = None,
    booked_at: dt_mod.datetime = None,
    trigger_immediate: bool = False,
    reassign_only: bool = False,
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
    if reassign_only:
        reassign_window = int(cfg.get("reassignment_confirmation_window_minutes", 15))
        cutoff = now + dt_mod.timedelta(minutes=reassign_window)
    else:
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

    # 3. Attempt 1 (Immediate) - recorded as SENT since initial booking dispatch is handled directly by router
    if not reassign_only and customer_phone:
        schedule_sms_reminder(
            appointment_id=appointment_id,
            recipient_type="customer",
            recipient_phone=customer_phone,
            reminder_type="immediate",
            scheduled_at=now,
            attempt_number=1,
            attempt_kind="immediate_booking",
            status="SENT",
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
            status="SENT",
        )

    # 4. Attempt 2 (Intermediate Follow-up)
    horizon_hours = (apt_dt - booked_at).total_seconds() / 3600.0
    if not reassign_only and agent_phone and cutoff > now:
        if horizon_hours >= 24.0:
            followup_sla = 2.0
        elif horizon_hours >= 6.0:
            followup_sla = 1.5
        else:
            followup_sla = 0.75
        from serviceBot.services.calendar_sync import get_configured_business_hours, get_configured_business_days
        start_h = cfg.get("business_hours_start")
        end_h = cfg.get("business_hours_end")
        if start_h is not None and end_h is not None:
            b_hours = list(range(int(start_h), int(end_h)))
        else:
            b_hours = get_configured_business_hours()
        b_days = cfg.get("business_days") if cfg.get("business_days") is not None else get_configured_business_days()
        t_mid = compute_business_hours_deadline(now, followup_sla, business_days=b_days, business_hours=b_hours)
        if t_mid < cutoff and t_mid > now:
            schedule_sms_reminder(
                appointment_id=appointment_id,
                recipient_type="agent",
                recipient_phone=agent_phone,
                reminder_type="followup",
                scheduled_at=t_mid,
                attempt_number=2,
                attempt_kind="intermediate_followup",
            )

    if not reassign_only and horizon_hours >= 24.0 and customer_phone:
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

    if not reassign_only and customer_phone:
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
                trigger_immediate=False,
                reassign_only=True,
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
        apt_details = fetch_appointment_customer_details(rem["appointment_id"])
        cust_name = apt_details.get("customer_name") or "there"
        srv = apt_details.get("service_type") or "Service"
        veh = apt_details.get("vehicle") or ""
        iss = apt_details.get("issue") or ""
        raw_time = apt_details.get("booking_time") or ""
        dur = apt_details.get("duration_minutes") or 60
        slot_str = format_time_slot_range(raw_time, dur) if raw_time else ""
        ag_name = apt_details.get("agent_name") or ""
        shop_addr, shop_map = get_shop_address_and_map_url(cfg)

        loc_lines = []
        if shop_addr:
            loc_lines.append(f"📍 Location: {shop_addr}")
        if shop_map:
            loc_lines.append(f"🗺️ Map: {shop_map}")
        loc_block = ("\n" + "\n".join(loc_lines)) if loc_lines else ""

        veh_clean = veh if veh and str(veh).lower() not in ("n/a", "none") else ""
        veh_line = f"\n🚘 Vehicle: {veh_clean}" if veh_clean else ""
        iss_clean = iss if iss and str(iss).lower() not in ("n/a", "none") else ""
        iss_line = f"\n🔧 Issue: {iss_clean}" if iss_clean else ""
        slot_line = f"\n📅 When: {slot_str}" if slot_str and slot_str != "N/A" else ""
        ag_line = f"\n👤 Advisor: {ag_name}" if ag_name else ""

        if rec_type == "customer":
            if att_kind == "immediate_booking":
                body = (
                    f"🚗 [APPOINTMENT CONFIRMED]\n"
                    f"Hi {cust_name}, your appointment is scheduled!\n"
                    f"🔧 Service: {srv}"
                    f"{slot_line}"
                    f"{veh_line}"
                    f"{iss_line}"
                    f"{ag_line}"
                    f"{loc_block}\n\n"
                    f"Reply STOP to opt out."
                )
            elif att_kind == "intermediate_followup":
                body = (
                    f"🗓️ [APPOINTMENT REMINDER]\n"
                    f"Hi {cust_name}, reminding you of your upcoming appointment:\n"
                    f"🔧 Service: {srv}"
                    f"{slot_line}"
                    f"{veh_line}"
                    f"{iss_line}"
                    f"{ag_line}"
                    f"{loc_block}\n\n"
                    f"Please let us know if you need to reschedule."
                )
            else:
                rem_label = f"in {rem_type}" if rem_type and rem_type != "final" else "soon"
                body = (
                    f"⏰ [UPCOMING APPOINTMENT]\n"
                    f"Hi {cust_name}, your appointment is coming up {rem_label}!\n"
                    f"🔧 Service: {srv}"
                    f"{slot_line}"
                    f"{veh_line}"
                    f"{iss_line}"
                    f"{ag_line}"
                    f"{loc_block}\n\n"
                    f"We look forward to seeing you!"
                )
        elif rec_type == "agent":
            cust_ph = apt_details.get("customer_phone") or ""
            cust_line = f"Customer: {cust_name}" + (f" ({cust_ph})" if cust_ph else "")
            v_line = f"\nVehicle: {veh_clean}" if veh_clean else ""
            i_line = f"\nIssue: {iss_clean}" if iss_clean else ""
            s_line = f"\nSlot: {slot_str}" if slot_str and slot_str != "N/A" else ""

            if att_kind == "immediate_booking":
                body = (
                    f"🚨 [NEW ADVISOR ALERT] Service request #{rem['appointment_id']} (Appt #{rem['appointment_id']})\n"
                    f"{cust_line}"
                    f"{v_line}\n"
                    f"Service: {srv}"
                    f"{s_line}"
                    f"{i_line}\n"
                    f"Reply CONFIRM or C to accept, or DECLINE if unavailable."
                )
            elif att_kind == "intermediate_followup":
                body = (
                    f"🚨 [ADVISOR FOLLOW-UP] Appt #{rem['appointment_id']} (Service request #{rem['appointment_id']})\n"
                    f"{cust_line}"
                    f"{v_line}\n"
                    f"Service: {srv}"
                    f"{s_line}"
                    f"{i_line}\n"
                    f"Status: Awaiting confirmation\n"
                    f"Reply CONFIRM or C to accept, or DECLINE if unavailable."
                )
            elif att_kind == "final_reminder":
                body = (
                    f"🚨 [URGENT ADVISOR ALERT] Appt #{rem['appointment_id']} (Service request #{rem['appointment_id']})\n"
                    f"{cust_line}"
                    f"{v_line}\n"
                    f"Service: {srv}"
                    f"{s_line}"
                    f"{i_line}\n"
                    f"URGENT: Must be confirmed immediately or it will be escalated to a supervisor.\n"
                    f"Reply CONFIRM or C to accept, or DECLINE."
                )
            else:
                body = (
                    f"⏰ [UPCOMING APPOINTMENT] Appt #{rem['appointment_id']} (Service request #{rem['appointment_id']})\n"
                    f"{cust_line}"
                    f"{v_line}\n"
                    f"Service: {srv}"
                    f"{s_line}"
                    f"{i_line}"
                )
        elif rec_type == "supervisor":
            cust_ph = apt_details.get("customer_phone") or ""
            cust_line = f"Customer: {cust_name}" + (f" ({cust_ph})" if cust_ph else "")
            v_line = f"\nVehicle: {veh_clean}" if veh_clean else ""
            i_line = f"\nIssue: {iss_clean}" if iss_clean else ""
            s_line = f"\nSlot: {slot_str}" if slot_str and slot_str != "N/A" else ""
            body = (
                f"🚨 [ESCALATION ALERT] Appt #{rem['appointment_id']} (Service request #{rem['appointment_id']})\n"
                f"{cust_line}"
                f"{v_line}\n"
                f"Service: {srv}"
                f"{s_line}"
                f"{i_line}\n"
                f"Notice: Unconfirmed by assigned advisor. Please take action in the portal."
            )
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
                                dispatch_supervisor_escalation_alert(rem["appointment_id"], reason="DELIVERY_FAILED")
                            except Exception as esc_err:
                                logger.warning(f"Failed to auto-escalate delivery failure for #{rem['appointment_id']}: {esc_err}")
                conn.commit()

        logger.info(f"Dispatched SMS reminder {rem['id']} to {phone} (success={is_success}).")
        dispatched_count += 1

    return dispatched_count


def dispatch_supervisor_escalation_alert(service_request_id: int, reason: str = "TIMEOUT_NO_RESPONSE") -> dict:
    """
    Dispatches an urgent escalation alert (SMS/WhatsApp) and admin notification email to the supervisor/admin
    when an appointment confirmation times out, is declined, or fails delivery.
    Adheres to the notification matrix and admin's configured phone number.
    """
    from serviceBot.api.portal import load_config
    from serviceBot.db.connection import get_db_connection, dict_cursor
    from serviceBot.db.queries import get_sms_config, get_sms_matrix_rules

    cfg = load_config()

    sms_cfg = {}
    try:
        sms_cfg = get_sms_config() or {}
    except Exception as err:
        logger.warning(f"Could not read sms_config for admin phone: {err}")

    # Resolve phone number provided by the admin; NEVER default to +19195550199
    admin_phone = (
        sms_cfg.get("admin_phone_number")
        or cfg.get("admin_phone_number")
        or cfg.get("supervisor_alert_phone")
        or ""
    ).strip()

    if admin_phone == "+19195550199":
        admin_phone = ""

    customer_name = "Customer"
    customer_phone = None
    technician_name = "Unassigned"
    agent_email = None
    vehicle_str = ""
    service_type = "Service Request"
    issue_desc = ""
    time_str = "Scheduled Time"

    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                """
                SELECT sr.id, sr.status, sr.staff_agent_id, sr.service_type, sr.issue_description, sr.booking_time,
                       c.name AS customer_name, c.phone AS customer_phone,
                       sa.name AS agent_name, sa.email AS agent_email,
                       v.year AS vehicle_year, v.make AS vehicle_make, v.model AS vehicle_model,
                       ar.starts_at
                FROM service_requests sr
                LEFT JOIN customers c ON c.id = sr.customer_id
                LEFT JOIN staff_agents sa ON sa.id = sr.staff_agent_id
                LEFT JOIN vehicles v ON v.id = sr.vehicle_id
                LEFT JOIN appointment_reservations ar ON ar.service_request_id = sr.id AND ar.status = 'ACTIVE'
                WHERE sr.id = %s;
                """,
                (service_request_id,)
            )
            row = cursor.fetchone()
            if not row or (row.get("status") or "").lower() in ("completed", "done", "cancelled", "cancelled_by_customer"):
                logger.info(f"Skipping supervisor escalation alert for completed, cancelled or missing appointment #{service_request_id}")
                return {
                    "success": False,
                    "skipped": True,
                    "reason": "Appointment is completed, cancelled or not found"
                }

            if row:
                if row.get("customer_name"):
                    customer_name = row["customer_name"]
                if row.get("customer_phone"):
                    customer_phone = row["customer_phone"]
                if row.get("agent_name"):
                    technician_name = row["agent_name"]
                if row.get("agent_email"):
                    agent_email = row["agent_email"]
                if row.get("service_type"):
                    service_type = row["service_type"]
                if row.get("issue_description"):
                    issue_desc = row["issue_description"]
                if row.get("vehicle_make"):
                    vehicle_str = f"{row.get('vehicle_year') or ''} {row['vehicle_make']} {row.get('vehicle_model') or ''}".strip()
                if row.get("starts_at"):
                    time_str = row["starts_at"].strftime("%b %-d at %-I:%M %p")
                elif row.get("booking_time"):
                    time_str = str(row["booking_time"])

    body = (
        f"URGENT ESCALATION: Appointment #{service_request_id} ({customer_name} at {time_str}) "
        f"is UNCONFIRMED by technician {technician_name} (Reason: {reason}). "
        f"Review & reassign: https://davidson.carcare/portal/reassign/{service_request_id}"
    )

    # Determine enabled channels from Notification Matrix
    rules = []
    try:
        rules = get_sms_matrix_rules() or []
    except Exception as e:
        logger.warning(f"Could not load matrix rules: {e}")

    admin_rules = [
        r for r in rules
        if (r.get("event_type") or "").upper() == "ESCALATION"
        and (r.get("recipient_role") or "").lower() == "admin"
    ]

    if admin_rules:
        sms_enabled = any((r.get("channel") or "").upper() == "SMS" and r.get("enabled") for r in admin_rules)
        whatsapp_enabled = any((r.get("channel") or "").upper() == "WHATSAPP" and r.get("enabled") for r in admin_rules)
        has_email_rule = any((r.get("channel") or "").upper() == "EMAIL" for r in admin_rules)
        if has_email_rule:
            email_enabled = any((r.get("channel") or "").upper() == "EMAIL" and r.get("enabled") for r in admin_rules)
        else:
            email_enabled = bool(cfg.get("gmail_enabled", True))
    else:
        # Default policy: on escalation, notify admin via email and message (SMS by default)
        sms_enabled = True
        whatsapp_enabled = False
        email_enabled = bool(cfg.get("gmail_enabled", True))

    # Send message (SMS and/or WhatsApp)
    client = TwilioSMSClient()
    dispatches = []
    primary_msg_res = {}

    if admin_phone:
        if sms_enabled:
            res_sms = client.send_sms(
                to=admin_phone,
                body=body,
                template_type="supervisor_alert",
                appointment_id=service_request_id,
                recipient_type="admin"
            )
            primary_msg_res = res_sms
            dispatches.append({"channel": "SMS", "result": res_sms})

        if whatsapp_enabled:
            res_wa = client.send_whatsapp(
                to=admin_phone,
                body=body,
                template_type="supervisor_alert",
                appointment_id=service_request_id,
                recipient_type="admin"
            )
            if not primary_msg_res:
                primary_msg_res = res_wa
            dispatches.append({"channel": "WHATSAPP", "result": res_wa})
    else:
        logger.warning(
            f"[ESCALATION ALERT] No admin phone number configured by admin; "
            f"skipping message alert for appointment #{service_request_id}."
        )

    # Send Email
    details = {
        "appointment_id": service_request_id,
        "customer_name": customer_name,
        "phone": customer_phone,
        "vehicle": vehicle_str,
        "service_type": service_type,
        "time": time_str,
        "issue": issue_desc,
        "escalation_reason": reason,
        "reason": reason,
    }

    email_sent = False
    if email_enabled:
        try:
            from serviceBot.services.gmail import send_admin_notification
            email_sent = send_admin_notification(
                booking_type="escalation",
                details=details,
                agent_name=technician_name,
                agent_email=agent_email
            )
        except Exception as email_err:
            logger.warning(f"[ESCALATION EMAIL WARNING] Failed to send admin escalation email for #{service_request_id}: {email_err}")
    else:
        logger.info(f"[ESCALATION ALERT] Admin email notification disabled in matrix for escalation #{service_request_id}")

    channels_dispatched = [d["channel"] for d in dispatches]
    if email_sent:
        channels_dispatched.append("EMAIL")

    audit_note = (
        f"Supervisor/admin escalation alert processed for {admin_phone or 'unconfigured phone'} "
        f"(reason={reason}, channels={','.join(channels_dispatched) if channels_dispatched else 'none'})"
    )
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                """
                INSERT INTO service_request_audit_log (request_id, triggered_by, from_status, to_status, notes)
                VALUES (%s, 'supervisor_escalation', 'escalated', 'escalated', %s);
                """,
                (service_request_id, audit_note)
            )
            conn.commit()

    message_sent = any(
        bool(d.get("result", {}).get("success") or d.get("result", {}).get("status") in ("DELIVERED", "SENT"))
        for d in dispatches
    )
    is_success = bool(message_sent or email_sent)

    logger.warning(
        f"[ESCALATION ALERT] Supervisor/Admin notified for appt #{service_request_id} "
        f"at phone={admin_phone or 'none'} (reason={reason}, message_sent={message_sent}, email_sent={email_sent}, channels={channels_dispatched})"
    )

    return {
        "success": is_success,
        "admin_phone": admin_phone or None,
        "supervisor_phone": admin_phone or None,
        "body": body,
        "sid": primary_msg_res.get("sid"),
        "email_sent": bool(email_sent),
        "message_sent": bool(message_sent),
        "dispatches": dispatches,
        "channels": channels_dispatched
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
        consecutive_errors = 0
        while True:
            has_error = False
            try:
                run_reminder_polling_worker_cycle()
            except Exception as e:
                has_error = True
                logger.error(f"Error in reminder worker cycle: {e}", exc_info=e)
            try:
                check_and_escalate_unconfirmed_appointments()
            except Exception as esc_err:
                has_error = True
                logger.error(f"Error in unconfirmed escalation check: {esc_err}", exc_info=esc_err)
            if has_error:
                consecutive_errors += 1
                sleep_time = min(120.0, float(interval_seconds) * (2 ** min(consecutive_errors, 4)))
                time.sleep(sleep_time)
            else:
                consecutive_errors = 0
                time.sleep(interval_seconds)

    t = threading.Thread(target=_loop, daemon=True, name="sms-reminder-polling")
    t.start()
