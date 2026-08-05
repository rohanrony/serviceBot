import time
import json
import traceback
import threading
from datetime import datetime, timedelta
from typing import Optional

from serviceBot.logger import get_logger
from serviceBot.db.connection import get_db_connection, dict_cursor
from serviceBot.services.gmail import (
    send_booking_notification,
    send_admin_notification,
    create_admin_calendar_event,
    delete_admin_calendar_event
)
from serviceBot.services.google_calendar import (
    create_agent_calendar_event,
    delete_agent_calendar_event
)

logger = get_logger("outbox_worker")


def enqueue_outbox_event(cursor, event_type: str, request_id: Optional[int], payload: dict):
    """
    Inserts a new notification event into the outbox table within an existing DB transaction.
    Guarantees ACID atomicity with database updates.
    """
    cursor.execute(
        """
        INSERT INTO outbox_notifications (event_type, request_id, payload, status, next_retry_at)
        VALUES (%s, %s, %s, 'PENDING', CURRENT_TIMESTAMP);
        """,
        (event_type, request_id, json.dumps(payload))
    )


def process_outbox_batch(batch_size: int = 10) -> int:
    """
    Processes pending outbox items with exponential backoff retries and 7-failure automated revert.
    Returns the number of processed outbox events.
    """
    processed_count = 0
    try:
        with get_db_connection() as conn:
            with dict_cursor(conn) as cursor:
                cursor.execute(
                    """
                    SELECT id, event_type, request_id, payload, attempts, max_attempts
                    FROM outbox_notifications
                    WHERE (status = 'PENDING' AND next_retry_at <= CURRENT_TIMESTAMP)
                       OR (status = 'PROCESSING' AND updated_at < CURRENT_TIMESTAMP - INTERVAL '5 minutes')
                    ORDER BY id ASC
                    LIMIT %s
                    FOR UPDATE SKIP LOCKED;
                    """,
                    (batch_size,)
                )
                items = cursor.fetchall()

                if not items:
                    return 0

                for item in items:
                    item_id = item["id"]
                    event_type = item["event_type"]
                    request_id = item["request_id"]
                    payload = item["payload"] if isinstance(item["payload"], dict) else json.loads(item["payload"])
                    attempts = item["attempts"]
                    max_attempts = item.get("max_attempts", 7)

                    # Atomically claim status as PROCESSING and push next_retry_at into the future to prevent duplicate worker pickups
                    cursor.execute(
                        """
                        UPDATE outbox_notifications
                        SET status = 'PROCESSING',
                            updated_at = CURRENT_TIMESTAMP,
                            next_retry_at = CURRENT_TIMESTAMP + INTERVAL '5 minutes'
                        WHERE id = %s AND (status = 'PENDING' OR (status = 'PROCESSING' AND updated_at < CURRENT_TIMESTAMP - INTERVAL '5 minutes'));
                        """,
                        (item_id,)
                    )
                    if cursor.rowcount == 0:
                        continue
                    conn.commit()

                    processed_count += 1

                    try:
                        _dispatch_outbox_event(event_type, request_id, payload)
                        # Success: Mark DELIVERED
                        with dict_cursor(conn) as cursor:
                            cursor.execute(
                                "UPDATE outbox_notifications SET status = 'DELIVERED', updated_at = CURRENT_TIMESTAMP WHERE id = %s;",
                                (item_id,)
                            )
                        conn.commit()
                        logger.info(
                            f"Event {item_id} ({event_type}) delivered successfully.",
                            extra={"extra_payload": {"item_id": item_id, "event_type": event_type, "request_id": request_id}}
                        )
                    except Exception as err:
                        err_msg = f"{type(err).__name__}: {str(err)}\n{traceback.format_exc()}"
                        new_attempts = attempts + 1

                        # Hard failure error codes (30003, 30005, 30006, 21610) terminate retry loop immediately
                        is_hard_failure = any(code in str(err) for code in ["30003", "30005", "30006", "21610"])

                        if new_attempts >= max_attempts or is_hard_failure:
                            # --- REVERT & COMPENSATION ON FAILURES ---
                            logger.error(
                                f"CRITICAL: Outbox event {item_id} ({event_type}) failed maximum retries or hard error! Hard Failure: {is_hard_failure}. Executing compensating transaction...",
                                exc_info=err,
                                extra={"extra_payload": {
                                    "item_id": item_id,
                                    "event_type": event_type,
                                    "request_id": request_id,
                                    "attempts": new_attempts,
                                    "is_hard_failure": is_hard_failure
                                }}
                            )
                            _execute_revert_compensation(conn, event_type, request_id, payload, err_msg)
                            with dict_cursor(conn) as cursor:
                                cursor.execute(
                                    """
                                    UPDATE outbox_notifications
                                    SET status = 'FAILED_REVERTED', attempts = %s, error_log = %s, updated_at = CURRENT_TIMESTAMP
                                    WHERE id = %s;
                                    """,
                                    (new_attempts, err_msg, item_id)
                                )
                            conn.commit()
                        else:
                            # --- EXPONENTIAL / SMS BACKOFF RETRY ---
                            if event_type.startswith("sms_"):
                                sms_backoffs = {1: 30, 2: 120, 3: 600}
                                delay_seconds = sms_backoffs.get(new_attempts, 600)
                            else:
                                delay_seconds = 2 ** new_attempts  # 2s, 4s, 8s, 16s, 32s, 64s, 128s

                            logger.warning(
                                f"Outbox event {item_id} ({event_type}) failed attempt {new_attempts}/{max_attempts}. Retrying in {delay_seconds}s. Error: {err}",
                                extra={"extra_payload": {
                                    "item_id": item_id,
                                    "event_type": event_type,
                                    "attempts": new_attempts,
                                    "next_retry_delay": delay_seconds,
                                    "error": str(err)
                                }}
                            )
                            with dict_cursor(conn) as cursor:
                                cursor.execute(
                                    """
                                    UPDATE outbox_notifications
                                    SET status = 'PENDING',
                                        attempts = %s,
                                        next_retry_at = CURRENT_TIMESTAMP + (%s || ' seconds')::INTERVAL,
                                        error_log = %s,
                                        updated_at = CURRENT_TIMESTAMP
                                    WHERE id = %s;
                                    """,
                                    (new_attempts, str(delay_seconds), err_msg, item_id)
                                )
                            conn.commit()

    except Exception as outer_err:
        logger.error(f"Outbox batch processing exception: {outer_err}", exc_info=outer_err)

    return processed_count


def _dispatch_outbox_event(event_type: str, request_id: Optional[int], payload: dict):
    """
    Executes external API side effects for a given outbox event.
    Raises an exception if any operation fails so the worker can retry or revert.
    """
    if event_type == "agent_reassignment":
        old_agent_id = payload.get("old_agent_id")
        new_agent_id = payload.get("new_agent_id")
        booking_time_str = payload.get("booking_time_str")
        details = payload.get("details", {})
        new_agent_email = payload.get("new_agent_email")
        new_agent_name = payload.get("new_agent_name")
        old_agent_name = payload.get("old_agent_name")

        # Update notification_dispatched_at
        if request_id:
            from serviceBot.db.connection import get_db_connection, dict_cursor
            with get_db_connection() as conn:
                with dict_cursor(conn) as cursor:
                    cursor.execute("UPDATE service_requests SET notification_dispatched_at = CURRENT_TIMESTAMP WHERE id = %s;", (request_id,))

        # 1. Cancel old agent Google Calendar event
        if old_agent_id is not None and booking_time_str:
            try:
                delete_agent_calendar_event(old_agent_id, str(booking_time_str)[:19])
            except Exception as cal_err:
                logger.warning(f"[OUTBOX CALENDAR WARNING] Failed to delete old agent calendar event for agent {old_agent_id}: {cal_err}")

        # 2. Create new agent Google Calendar event
        if new_agent_id is not None and booking_time_str:
            try:
                create_agent_calendar_event(
                    agent_id=new_agent_id,
                    customer_name=details.get("customer_name") or "Customer",
                    service_type=details.get("service_type") or "Service Request",
                    issue_description=details.get("issue") or "",
                    slot_datetime_str=str(booking_time_str)[:19]
                )
            except Exception as cal_err:
                logger.warning(f"[OUTBOX CALENDAR WARNING] Failed to create new agent calendar event for agent {new_agent_id}: {cal_err}")

        # 3. Send email to new agent if present
        if new_agent_email:
            try:
                send_booking_notification("appointment", details, agent_email=new_agent_email)
            except Exception as email_err:
                logger.warning(f"[OUTBOX EMAIL WARNING] Failed to send email to new agent {new_agent_email}: {email_err}")

        # 4. Admin Calendar & Admin Notification Email
        if booking_time_str:
            try:
                delete_admin_calendar_event(str(booking_time_str)[:19])
                create_admin_calendar_event(
                    customer_name=details.get("customer_name") or "Customer",
                    service_type=details.get("service_type") or "Service Request",
                    issue_description=details.get("issue") or "",
                    slot_datetime_str=str(booking_time_str)[:19],
                    agent_name=new_agent_name
                )
            except Exception as admin_cal_err:
                logger.warning(f"[OUTBOX CALENDAR WARNING] Failed to update admin calendar event: {admin_cal_err}")

        try:
            send_admin_notification("reassign", details, agent_name=new_agent_name, agent_email=new_agent_email)
        except Exception as admin_email_err:
            logger.warning(f"[OUTBOX EMAIL WARNING] Failed to send admin notification: {admin_email_err}")

        # 5. SMS Notifications (customer, new agent, previous agent)
        from serviceBot.services.sms_router import SMSNotificationRouter
        reassign_details = {
            **(details or {}),
            "new_agent_name": new_agent_name,
            "old_agent_name": old_agent_name,
            "previous_agent_name": old_agent_name
        }
        sms_router = SMSNotificationRouter()
        sms_router.process_event(
            event_type="REASSIGNED",
            appointment_id=request_id,
            customer_phone=details.get("phone"),
            agent_phone=payload.get("agent_phone"),
            previous_agent_phone=payload.get("previous_agent_phone"),
            booking_time=booking_time_str,
            details=reassign_details
        )

    elif event_type == "booking_notification":
        booking_type = payload.get("booking_type", "appointment")
        details = payload.get("details", {})
        agent_email = payload.get("agent_email")
        agent_name = payload.get("agent_name")
        slot_datetime_str = payload.get("booking_time_str")

        # Update notification_dispatched_at
        if request_id:
            from serviceBot.db.connection import get_db_connection, dict_cursor
            with get_db_connection() as conn:
                with dict_cursor(conn) as cursor:
                    cursor.execute("UPDATE service_requests SET notification_dispatched_at = CURRENT_TIMESTAMP WHERE id = %s;", (request_id,))

        if agent_email:
            try:
                send_booking_notification(booking_type, details, agent_email=agent_email)
            except Exception as email_err:
                logger.warning(f"[OUTBOX EMAIL WARNING] Failed to send booking notification email: {email_err}")

        if slot_datetime_str:
            try:
                clean_slot_str = str(slot_datetime_str)[:19]
                delete_admin_calendar_event(clean_slot_str)
                create_admin_calendar_event(
                    customer_name=details.get("customer_name") or "Customer",
                    service_type=details.get("service_type") or "Service Request",
                    issue_description=details.get("issue") or "",
                    slot_datetime_str=clean_slot_str,
                    agent_name=agent_name
                )
            except Exception as cal_err:
                logger.warning(f"[OUTBOX CALENDAR WARNING] Failed to update admin calendar event: {cal_err}")

        try:
            send_admin_notification(booking_type, details, agent_name=agent_name, agent_email=agent_email)
        except Exception as admin_email_err:
            logger.warning(f"[OUTBOX EMAIL WARNING] Failed to send admin notification: {admin_email_err}")

        # SMS Notification (customer + agent)
        agent_phone = payload.get("agent_phone")
        customer_phone = details.get("phone")
        if customer_phone or agent_phone:
            sms_event = "BOOKING" if booking_type in ("appointment", "callback") else "RESCHEDULED"
            from serviceBot.services.sms_router import SMSNotificationRouter
            sms_router = SMSNotificationRouter()
            sms_router.process_event(
                event_type=sms_event,
                appointment_id=request_id,
                customer_phone=customer_phone,
                agent_phone=agent_phone,
                booking_time=slot_datetime_str
            )

    elif event_type.startswith("sms_"):
        from serviceBot.services.sms_router import SMSNotificationRouter
        router_svc = SMSNotificationRouter()
        sms_event_type = payload.get("sms_event_type", event_type.replace("sms_", "").upper())
        router_svc.process_event(
            event_type=sms_event_type,
            appointment_id=request_id or payload.get("appointment_id"),
            customer_phone=payload.get("customer_phone"),
            agent_phone=payload.get("agent_phone"),
            previous_agent_phone=payload.get("previous_agent_phone"),
            admin_phone=payload.get("admin_phone"),
            booking_time=payload.get("booking_time")
        )


def _execute_revert_compensation(conn, event_type: str, request_id: Optional[int], payload: dict, err_log: str):
    """
    Executes a compensating database transaction when an outbox event fails 7 consecutive times.
    Reverts DB state back to the original assignment.
    """
    if event_type == "agent_reassignment" and request_id:
        old_agent_id = payload.get("old_agent_id")
        old_agent_name = payload.get("old_agent_name", "Previous Agent")
        
        with dict_cursor(conn) as cursor:
            # Revert staff_agent_id back to old_agent_id
            cursor.execute(
                "UPDATE service_requests SET staff_agent_id = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s;",
                (old_agent_id, request_id)
            )
        logger.info(f"[OUTBOX REVERT SUCCESS] Service request {request_id} staff assignment reverted back to agent_id={old_agent_id} ({old_agent_name}).")


def _worker_loop():
    """Background polling loop for outbox processing."""
    logger.info("Outbox processing background thread started.")
    while True:
        try:
            process_outbox_batch()
        except Exception as e:
            logger.error(f"Worker loop error: {e}", exc_info=e)
        time.sleep(2.0)


_worker_thread = None


def start_outbox_worker():
    """Starts the outbox background worker thread if not already running."""
    global _worker_thread
    if _worker_thread is None or not _worker_thread.is_alive():
        _worker_thread = threading.Thread(target=_worker_loop, daemon=True, name="OutboxWorkerThread")
        _worker_thread.start()
        logger.info("Outbox worker thread launched.")
