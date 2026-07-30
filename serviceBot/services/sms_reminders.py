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

logger = get_logger("sms_reminders")


def parse_booking_datetime(dt_str: str) -> dt_mod.datetime:
    """Parses various date/time formats into naive UTC datetime."""
    if not dt_str:
        return None
    for fmt in [
        "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M",
        "%Y-%m-%d", "%I:%M %p", "%Y-%m-%dT%H:%M:%SZ"
    ]:
        try:
            dt = dt_mod.datetime.strptime(dt_str.strip(), fmt)
            if dt.year == 1900:
                now = dt_mod.datetime.now()
                dt = dt.replace(year=now.year, month=now.month, day=now.day)
            return dt
        except ValueError:
            pass
    return None


def schedule_appointment_reminders(appointment_id: int, booking_time_str: str, customer_phone: str, agent_phone: str = None):
    """
    Schedules 24-hour and 2-hour pre-appointment reminders for Customer,
    and 2-hour pre-appointment reminder for Service Agent.
    """
    apt_dt = parse_booking_datetime(booking_time_str)
    if not apt_dt:
        return

    now = dt_mod.datetime.now()

    # Customer 24h Reminder
    if customer_phone:
        t_24h = apt_dt - dt_mod.timedelta(hours=24)
        if t_24h > now:
            schedule_sms_reminder(appointment_id, "customer", customer_phone, "24h", t_24h)

    # Customer 2h Reminder
    if customer_phone:
        t_2h = apt_dt - dt_mod.timedelta(hours=2)
        if t_2h > now:
            schedule_sms_reminder(appointment_id, "customer", customer_phone, "2h", t_2h)

    # Agent 2h Reminder
    if agent_phone:
        t_agent_2h = apt_dt - dt_mod.timedelta(hours=2)
        if t_agent_2h > now:
            schedule_sms_reminder(appointment_id, "agent", agent_phone, "2h", t_agent_2h)


def update_or_cancel_appointment_reminders(appointment_id: int, new_booking_time_str: str = None, customer_phone: str = None, agent_phone: str = None):
    """Cancels pending reminders for an appointment and reschedules if a new booking time is given."""
    cancel_pending_sms_reminders(appointment_id)
    if new_booking_time_str and customer_phone:
        schedule_appointment_reminders(appointment_id, new_booking_time_str, customer_phone, agent_phone)


def check_and_send_due_reminders() -> int:
    """Alias for run_reminder_polling_worker_cycle for cron execution."""
    return run_reminder_polling_worker_cycle()


def run_reminder_polling_worker_cycle() -> int:
    """Polls due reminders in sms_reminders and dispatches SMS."""
    due_reminders = get_due_sms_reminders()
    if not due_reminders:
        return 0

    client = TwilioSMSClient()
    dispatched_count = 0

    for rem in due_reminders:
        phone = rem["recipient_phone"]
        rec_type = rem["recipient_type"]
        rem_type = rem["reminder_type"]

        if rec_type == "customer" and not get_customer_opt_in(phone):
            mark_sms_reminder_status(rem["id"], "SKIPPED_OPT_OUT")
            logger.info(f"Skipped SMS reminder {rem['id']} due to customer opt-out for {phone}.")
            continue

        body = (
            f"Reminder: You have an upcoming appointment in {rem_type} (Appointment #{rem['appointment_id']})."
            if rec_type == "customer"
            else f"Agent Reminder: You have an upcoming service request #{rem['appointment_id']} in {rem_type}."
        )

        res = client.send_sms(
            to=phone,
            body=body,
            template_type=f"reminder_{rem_type}",
            appointment_id=rem["appointment_id"]
        )

        mark_sms_reminder_status(rem["id"], res["status"])
        logger.info(f"Dispatched SMS reminder {rem['id']} to {phone} ({res['status']}).")
        dispatched_count += 1

    return dispatched_count


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
            time.sleep(interval_seconds)

    t = threading.Thread(target=_loop, daemon=True, name="sms-reminder-polling")
    t.start()
