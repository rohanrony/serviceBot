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

    def process_event(
        self,
        event_type: str,
        appointment_id: int,
        customer_phone: str = None,
        agent_phone: str = None,
        previous_agent_phone: str = None,
        admin_phone: str = None,
        booking_time: str = None
    ) -> dict:
        rules = get_sms_matrix_rules()
        dispatches = []

        apt_dt = parse_booking_datetime(booking_time)
        is_urgent = should_bypass_quiet_hours(apt_dt) if apt_dt else False
        in_quiet = is_in_quiet_hours() if not is_urgent else False

        # Schedule or update reminders on booking / reschedule / cancel
        if event_type == "BOOKING" and booking_time:
            schedule_appointment_reminders(appointment_id, booking_time, customer_phone, agent_phone)
        elif event_type in ("RESCHEDULED", "RESCHEDULED_REASSIGNED") and booking_time:
            update_or_cancel_appointment_reminders(appointment_id, booking_time, customer_phone, agent_phone)
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
                body = f"Appointment Update #{appointment_id}: Event {event_type} processed."
                res = self.twilio_client.send_sms(
                    to=customer_phone,
                    body=body,
                    template_type=event_type.lower(),
                    appointment_id=appointment_id
                )
                dispatches.append({"recipient": "customer", **res})

        # 2. Agent Dispatch (Current / New Agent)
        if agent_phone and self._is_rule_enabled(event_type, "agent", rules):
            body = f"Agent Alert for Appointment #{appointment_id}: Event {event_type}."
            res = self.twilio_client.send_sms(
                to=agent_phone,
                body=body,
                template_type=f"agent_{event_type.lower()}",
                appointment_id=appointment_id
            )
            dispatches.append({"recipient": "agent", **res})

        # 3. Previous Agent Dispatch (on Reassignment)
        if previous_agent_phone and self._is_rule_enabled(event_type, "previous_agent", rules):
            body = f"Agent Unassignment Alert: Appointment #{appointment_id} has been reassigned to another advisor."
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
                body = f"Admin Alert for Appointment #{appointment_id}: Event {event_type}."
                res = self.twilio_client.send_sms(
                    to=target_admin_phone,
                    body=body,
                    template_type=f"admin_{event_type.lower()}",
                    appointment_id=appointment_id
                )
                dispatches.append({"recipient": "admin", **res})

        return {"event_type": event_type, "appointment_id": appointment_id, "dispatches": dispatches}
