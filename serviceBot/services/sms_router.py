import datetime as dt_mod
from serviceBot.db.queries import (
    get_sms_matrix_rules,
    get_customer_opt_in,
    log_sms_dispatch
)
from serviceBot.services.quiet_hours import (
    is_in_quiet_hours,
    should_bypass_quiet_hours,
    calculate_quiet_hours_release_time,
    parse_time_str
)
from serviceBot.services.twilio_sms import TwilioSMSClient
from serviceBot.services.sms_reminders import parse_booking_datetime, schedule_appointment_reminders, update_or_cancel_appointment_reminders


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


class SMSNotificationRouter:
    """
    Core Event Notification Router.
    Processes appointment lifecycle events (BOOKING, RESCHEDULED, REASSIGNED, RESCHEDULED_REASSIGNED, CANCELLED_BY_CUSTOMER, CANCELLED_BY_ADMIN),
    applies notification matrix rules, checks TCPA opt-in status, evaluates Quiet Hours & Urgent Override, and dispatches SMS.
    """

    def __init__(self):
        self.twilio_client = TwilioSMSClient()

    def _is_rule_enabled(self, event_type: str, recipient_role: str, rules_list: list) -> bool:
        for r in rules_list:
            if r["event_type"] == event_type and r["recipient_role"] == recipient_role:
                return bool(r["enabled"])
        # Defaults if not found in DB
        if recipient_role == "admin":
            return False
        if event_type == "REASSIGNED" and recipient_role == "customer":
            return False
        return True

    def _fetch_details_if_missing(self, appointment_id: int, details: dict = None) -> dict:
        if details:
            return details
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
                               sa.name AS agent_name
                        FROM service_requests sr
                        LEFT JOIN customers c ON sr.customer_id = c.id
                        LEFT JOIN vehicles v ON sr.vehicle_id = v.id
                        LEFT JOIN staff_agents sa ON sr.staff_agent_id = sa.id
                        WHERE sr.id = %s;
                    """, (appointment_id,))
                    sr = cursor.fetchone()
                    if not sr:
                        return {}
                    v_parts = [sr.get("vehicle_year"), sr.get("vehicle_make"), sr.get("vehicle_model")]
                    v_str = " ".join([str(p) for p in v_parts if p]).strip() or "N/A"
                    b_time = sr.get("booking_time") or sr.get("time_slot") or "N/A"
                    return {
                        "customer_name": sr.get("customer_name") or "Customer",
                        "phone": sr.get("customer_phone") or "N/A",
                        "vehicle": v_str,
                        "service_type": sr.get("service_type") or "Service",
                        "time": str(b_time)[:19],
                        "duration_minutes": sr.get("duration_minutes"),
                        "issue": sr.get("issue_description") or "N/A",
                        "new_agent_name": sr.get("agent_name") or "Assigned Advisor"
                    }
        except Exception:
            return {}

    def process_event(
        self,
        event_type: str,
        appointment_id: int,
        customer_phone: str = None,
        agent_phone: str = None,
        previous_agent_phone: str = None,
        admin_phone: str = None,
        booking_time: str = None,
        details: dict = None
    ) -> dict:
        import os
        rules = get_sms_matrix_rules()
        dispatches = []

        # Enrich details for clear, professional notifications
        info = self._fetch_details_if_missing(appointment_id, details)
        cust_name = info.get("customer_name") or "Customer"
        cust_ph = info.get("phone") or customer_phone or ""
        veh = info.get("vehicle") or "N/A"
        srv = info.get("service_type") or "Service"
        raw_t_str = booking_time or info.get("time") or "N/A"
        
        # Resolve duration for accurate time range
        dur_min = info.get("duration_minutes") or (details.get("duration_minutes") if details else None)
        if not dur_min and srv:
            from serviceBot.db.queries import get_service_required_fields
            svc_fields = get_service_required_fields(srv)
            if svc_fields and svc_fields.get("duration_minutes"):
                dur_min = svc_fields["duration_minutes"]
        dur_min = dur_min or 60

        slot_range_str = format_time_slot_range(raw_t_str, duration_minutes=dur_min)
        iss = info.get("issue") or "N/A"
        new_ag = info.get("new_agent_name") or info.get("agent_name") or "Assigned Advisor"
        old_ag = info.get("previous_agent_name") or info.get("old_agent_name") or "Previous Advisor"

        apt_dt = parse_booking_datetime(raw_t_str)
        is_urgent = should_bypass_quiet_hours(apt_dt) if apt_dt else False
        in_quiet = is_in_quiet_hours() if not is_urgent else False

        # Schedule or update reminders on booking / reschedule / cancel
        if event_type == "BOOKING" and raw_t_str:
            schedule_appointment_reminders(appointment_id, raw_t_str, customer_phone, agent_phone)
        elif event_type in ("RESCHEDULED", "RESCHEDULED_REASSIGNED") and raw_t_str:
            update_or_cancel_appointment_reminders(appointment_id, raw_t_str, customer_phone, agent_phone)
        elif event_type in ("CANCELLED_BY_CUSTOMER", "CANCELLED_BY_ADMIN"):
            update_or_cancel_appointment_reminders(appointment_id)

        # 1. Customer Dispatch
        if customer_phone and self._is_rule_enabled(event_type, "customer", rules):
            if not get_customer_opt_in(customer_phone):
                log_id = log_sms_dispatch(
                    appointment_id=appointment_id,
                    recipient_type="customer",
                    recipient_phone=customer_phone,
                    template_type=event_type.lower(),
                    status="SKIPPED_OPT_OUT",
                    error_message="Customer has opted out of SMS notifications."
                )
                dispatches.append({"recipient": "customer", "status": "SKIPPED_OPT_OUT", "log_id": log_id})
            elif in_quiet:
                rel_time = calculate_quiet_hours_release_time()
                log_id = log_sms_dispatch(
                    appointment_id=appointment_id,
                    recipient_type="customer",
                    recipient_phone=customer_phone,
                    template_type=event_type.lower(),
                    status="QUEUED",
                    scheduled_send_at=rel_time
                )
                dispatches.append({"recipient": "customer", "status": "QUEUED", "scheduled_send_at": str(rel_time), "log_id": log_id})
            else:
                body = (
                    f"🚗 [CUSTOMER UPDATE] Appt #{appointment_id}\n"
                    f"Service: {srv}\n"
                    f"Slot: {slot_range_str}\n"
                    f"Assigned Advisor: {new_ag}\n"
                    f"Vehicle: {veh}"
                )
                res = self.twilio_client.send_sms(
                    to=customer_phone,
                    body=body,
                    template_type=event_type.lower(),
                    appointment_id=appointment_id
                )
                dispatches.append({"recipient": "customer", **res})

                if res.get("success"):
                    try:
                        from serviceBot.db.queries import get_or_create_sms_conversation, add_sms_message
                        conv = get_or_create_sms_conversation(customer_phone, context_appointment_id=appointment_id)
                        add_sms_message(
                            conversation_id=conv["id"],
                            direction="outbound",
                            sender_type="system",
                            sender_name="System Notification",
                            body=body,
                            twilio_message_sid=res.get("sid")
                        )
                    except Exception as ex:
                        pass


        # 2. Agent Dispatch (Current / New Agent)
        if agent_phone and self._is_rule_enabled(event_type, "agent", rules):
            body = (
                f"🚨 [NEW ADVISOR ALERT] Appt #{appointment_id}\n"
                f"Status: {event_type}\n"
                f"Customer: {cust_name} ({cust_ph})\n"
                f"Vehicle: {veh}\n"
                f"Service: {srv}\n"
                f"Slot: {slot_range_str}\n"
                f"Issue: {iss}"
            )
            if event_type == "REASSIGNED":
                body += f"\nReassigned from: {old_ag}"

            res = self.twilio_client.send_sms(
                to=agent_phone,
                body=body,
                template_type=f"agent_{event_type.lower()}",
                appointment_id=appointment_id
            )
            dispatches.append({"recipient": "agent", **res})

        # 3. Previous Agent Dispatch (on Reassignment)
        if previous_agent_phone and self._is_rule_enabled(event_type, "previous_agent", rules):
            body = (
                f"ℹ️ [PREVIOUS ADVISOR NOTICE]\n"
                f"Service Request #{appointment_id} ({srv} for {cust_name}) "
                f"has been reassigned to {new_ag}.\n"
                f"Slot: {slot_range_str}"
            )
            res = self.twilio_client.send_sms(
                to=previous_agent_phone,
                body=body,
                template_type="unassignment",
                appointment_id=appointment_id
            )
            dispatches.append({"recipient": "previous_agent", **res})

        # 4. Admin Dispatch
        if self._is_rule_enabled(event_type, "admin", rules):
            target_admin_phone = admin_phone
            if not target_admin_phone:
                from serviceBot.db.queries import get_sms_config
                cfg = get_sms_config()
                target_admin_phone = cfg.get("admin_phone_number") or cfg.get("support_phone_number") or os.getenv("NOTIFICATION_PHONE_NUMBER") or os.getenv("ADMIN_PHONE_NUMBER")
            if target_admin_phone:
                body = (
                    f"📋 [ADMIN ALERT] Appt #{appointment_id} {event_type}\n"
                    f"New Advisor: {new_ag} | Prev: {old_ag}\n"
                    f"Customer: {cust_name} ({cust_ph})\n"
                    f"Vehicle: {veh} | Service: {srv}\n"
                    f"Slot: {slot_range_str}"
                )
                res = self.twilio_client.send_sms(
                    to=target_admin_phone,
                    body=body,
                    template_type=f"admin_{event_type.lower()}",
                    appointment_id=appointment_id
                )
                dispatches.append({"recipient": "admin", **res})

        return {"event_type": event_type, "appointment_id": appointment_id, "dispatches": dispatches}
