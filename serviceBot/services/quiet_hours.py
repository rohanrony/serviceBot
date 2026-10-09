import datetime as dt_mod
import zoneinfo
import threading
import time
from serviceBot.db.queries import get_sms_config
from serviceBot.services.twilio_sms import TwilioSMSClient

from serviceBot.services import timezone_service


def _get_quiet_hours_tz() -> zoneinfo.ZoneInfo:
    return timezone_service.get_business_zoneinfo()


def parse_time_str(time_val) -> dt_mod.time:
    if isinstance(time_val, dt_mod.time):
        return time_val
    if isinstance(time_val, str):
        parts = time_val.split(":")
        return dt_mod.time(hour=int(parts[0]), minute=int(parts[1]), second=int(parts[2]) if len(parts) > 2 else 0)
    return dt_mod.time(21, 0)


def is_in_quiet_hours(now_dt: dt_mod.datetime = None, config: dict = None) -> bool:
    """
    Evaluates whether a timestamp is inside quiet hours in the business timezone.
    Boundary rule: inclusive-exclusive (21:00:00 is inside, 08:00:00 is outside).
    """
    if config is None:
        config = get_sms_config()

    if not config.get("quiet_hours_enabled", True):
        return False

    start_t = parse_time_str(config.get("quiet_start_time", "21:00"))
    end_t = parse_time_str(config.get("quiet_end_time", "08:00"))

    biz_tz = _get_quiet_hours_tz()
    if now_dt is None:
        now_dt = timezone_service.now_in_business_tz()
    elif now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=dt_mod.timezone.utc).astimezone(biz_tz)
    else:
        now_dt = now_dt.astimezone(biz_tz)

    current_t = now_dt.time()

    if start_t > end_t:
        # Overnight window (e.g. 21:00 to 08:00)
        return current_t >= start_t or current_t < end_t
    else:
        # Daytime window
        return start_t <= current_t < end_t


def should_bypass_quiet_hours(appointment_datetime: dt_mod.datetime, config: dict = None) -> bool:
    """
    Urgent Event Override Rule:
    If an appointment change or alert occurs within urgent_threshold_hours (default 12h) of appointment start time,
    SMS dispatches immediately regardless of quiet hours.
    """
    if not appointment_datetime:
        return False
    if config is None:
        config = get_sms_config()

    threshold_hours = config.get("urgent_threshold_hours", 12)
    now_utc = dt_mod.datetime.now(dt_mod.timezone.utc)

    if appointment_datetime.tzinfo is None:
        apt_utc = appointment_datetime.replace(tzinfo=dt_mod.timezone.utc)
    else:
        apt_utc = appointment_datetime.astimezone(dt_mod.timezone.utc)

    diff = (apt_utc - now_utc).total_seconds() / 3600.0
    return 0 <= diff <= threshold_hours


def calculate_quiet_hours_release_time(now_dt: dt_mod.datetime = None, config: dict = None) -> dt_mod.datetime:
    """Calculates next quiet_end_time (e.g. 08:00 AM NY time) converted to UTC naive/aware datetime."""
    if config is None:
        config = get_sms_config()

    end_t = parse_time_str(config.get("quiet_end_time", "08:00"))

    biz_tz = _get_quiet_hours_tz()
    if now_dt is None:
        now_biz = timezone_service.now_in_business_tz()
    elif now_dt.tzinfo is None:
        now_biz = now_dt.replace(tzinfo=dt_mod.timezone.utc).astimezone(biz_tz)
    else:
        now_biz = now_dt.astimezone(biz_tz)

    release_biz = now_biz.replace(hour=end_t.hour, minute=end_t.minute, second=0, microsecond=0)
    if release_biz <= now_biz:
        release_biz += dt_mod.timedelta(days=1)

    return release_biz.astimezone(dt_mod.timezone.utc).replace(tzinfo=None)


_worker_started = False

def run_quiet_hours_queue_worker_cycle():
    """Polls queued SMS logs and dispatches those whose release time has arrived."""
    from serviceBot.db.connection import get_db_connection, dict_cursor
    due_logs = []
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                """
                SELECT * FROM sms_log
                WHERE status = 'QUEUED' AND scheduled_send_at <= (CURRENT_TIMESTAMP AT TIME ZONE 'UTC')
                ORDER BY scheduled_send_at ASC
                FOR UPDATE SKIP LOCKED;
                """
            )
            due_logs = [dict(r) for r in cursor.fetchall()]
            if not due_logs:
                return 0
            for item in due_logs:
                cursor.execute(
                    "UPDATE sms_log SET status = 'PROCESSING' WHERE id = %s AND status = 'QUEUED';",
                    (item["id"],)
                )
            conn.commit()

    from serviceBot.db.queries import get_customer_opt_in, update_sms_log_status

    client = TwilioSMSClient()
    dispatched_count = 0
    for log_item in due_logs:
        phone = log_item["recipient_phone"]
        rec_type = (log_item.get("recipient_type") or "customer").lower()
        if rec_type == "customer" and not get_customer_opt_in(phone):
            logger.info(f"Skipping quiet hours release for opted-out customer {phone} (log_id={log_item['id']})")
            update_sms_log_status(
                log_id=log_item["id"],
                status="SKIPPED_OPT_OUT",
                error_message="Customer opted out of SMS notifications.",
            )
            continue

        body = log_item.get("body") or (
            f"Appointment Notification for Appointment #{log_item.get('appointment_id')}."
        )
        channel = (log_item.get("channel") or "SMS").upper()
        kwargs = {
            "to": phone,
            "body": body,
            "template_type": log_item.get("template_type", "notification"),
            "appointment_id": log_item.get("appointment_id"),
            "recipient_type": log_item.get("recipient_type") or "customer",
            "dispatch_log_id": log_item["id"],
        }
        if channel == "WHATSAPP":
            client.send_whatsapp(**kwargs)
        else:
            client.send_sms(**kwargs, channel="SMS")
        dispatched_count += 1
    return dispatched_count


from serviceBot.logger import get_logger

logger = get_logger("services.quiet_hours")

def start_quiet_hours_queue_worker(interval_seconds: int = 30):
    global _worker_started
    if _worker_started:
        return
    _worker_started = True

    def _loop():
        logger.info("Quiet hours queue release worker thread started.")
        consecutive_errors = 0
        while True:
            try:
                run_quiet_hours_queue_worker_cycle()
                consecutive_errors = 0
                time.sleep(interval_seconds)
            except Exception as e:
                consecutive_errors += 1
                sleep_time = min(120.0, float(interval_seconds) * (2 ** min(consecutive_errors, 4)))
                logger.error(f"Error in quiet hours polling cycle (backing off for {sleep_time}s): {e}", exc_info=e)
                time.sleep(sleep_time)

    t = threading.Thread(target=_loop, daemon=True, name="quiet-hours-queue-release")
    t.start()
