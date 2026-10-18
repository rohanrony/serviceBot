import time
import json
import traceback
import threading
from datetime import datetime, timedelta
from contextlib import contextmanager
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
    delete_agent_calendar_event,
    delete_agent_calendar_event_by_id,
)

logger = get_logger("outbox_worker")


class NotificationDeliveryError(RuntimeError):
    """Raised when an enabled notification dispatch failed and must be retried."""


def _require_notification_delivery(result: dict) -> None:
    """Treat actual channel failures as outbox failures; skips and queues are terminal states."""
    failed = []
    for dispatch in (result or {}).get("dispatches", []):
        status = str(dispatch.get("status") or "").upper()
        if status == "FAILED":
            failed.append(dispatch.get("recipient") or "recipient")
            continue
        if dispatch.get("success") is False and not (
            status.startswith("SKIPPED") or status == "QUEUED"
        ):
            failed.append(dispatch.get("recipient") or "recipient")
    if failed:
        raise NotificationDeliveryError(
            f"Notification delivery failed for: {', '.join(sorted(set(failed)))}"
        )


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


def _set_calendar_projection_status(
    request_id: Optional[int],
    reservation_id: Optional[int],
    status: str,
    calendar_event_id: Optional[str],
    *, cursor=None,
) -> None:
    """Persist asynchronous provider state without changing the local reservation."""
    if not request_id:
        return
    if cursor is None:
        with get_db_connection() as conn:
            with dict_cursor(conn) as owned_cursor:
                _set_calendar_projection_status(request_id, reservation_id, status, calendar_event_id, cursor=owned_cursor)
        return
    cursor.execute(
        """
        UPDATE service_requests
        SET calendar_integration_status = %s,
            calendar_event_id = COALESCE(%s, calendar_event_id),
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s;
        """,
        (status, calendar_event_id, request_id),
    )
    if reservation_id:
        cursor.execute(
            """
            UPDATE appointment_reservations
            SET calendar_integration_status = %s,
                calendar_event_id = COALESCE(%s, calendar_event_id),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s;
            """,
            (status, calendar_event_id, reservation_id),
        )
    cursor.execute(
        """
        UPDATE mock_calendar_slots
        SET calendar_integration_status = %s,
            calendar_event_id = COALESCE(%s, calendar_event_id),
            updated_at = CURRENT_TIMESTAMP
        WHERE service_request_id = %s;
        """,
        (status, calendar_event_id, request_id),
    )


@contextmanager
def _locked_calendar_projection(request_id, payload, *, retire_previous=False):
    """Keep reservation ownership stable through native effects and status writes."""
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                "SELECT status, booking_type, duration_minutes FROM service_requests WHERE id=%s FOR UPDATE;",
                (request_id,),
            )
            request = cursor.fetchone()
            cursor.execute(
                "SELECT id, status, staff_agent_id, starts_at, ends_at, calendar_event_id FROM appointment_reservations WHERE id=%s AND service_request_id=%s FOR UPDATE;",
                (payload.get('reservation_id'), request_id),
            )
            reservation = cursor.fetchone()
            current = bool(request and reservation)
            if current and payload.get('action') == 'delete':
                event_id = reservation.get('calendar_event_id') or f"servicebot{reservation['id']}{reservation['starts_at']:%Y%m%d%H%M}"
                current = (reservation['status'] == 'CANCELLED'
                    and request['status'] in ('cancelled', 'cancelled_by_customer', 'cancelled_by_admin')
                    and payload.get('agent_id') == reservation['staff_agent_id']
                    and payload.get('calendar_event_id') == event_id)
            elif current:
                try:
                    start = datetime.fromisoformat(str(payload.get('booking_time_str')))
                    duration = int(payload.get('duration_minutes') or 60)
                    current = (reservation['status'] == 'ACTIVE'
                        and request['status'] not in ('cancelled', 'cancelled_by_customer', 'cancelled_by_admin')
                        and payload.get('agent_id') == reservation['staff_agent_id']
                        and start == reservation['starts_at']
                        and start + timedelta(minutes=duration) == reservation['ends_at']
                        and duration == request['duration_minutes']
                        and payload.get('booking_type', 'appointment') == request['booking_type'])
                except (TypeError, ValueError, OverflowError):
                    current = False
            if retire_previous and request and reservation and payload.get('action') != 'delete':
                _retire_previous_calendar_projection(payload, cursor)
            yield cursor if current else None


def _mark_calendar_projection_failed(request_id, payload):
    with _locked_calendar_projection(request_id, payload) as cursor:
        if cursor is not None:
            _set_calendar_projection_status(request_id, payload.get('reservation_id'),
                'FAILED', payload.get('calendar_event_id'), cursor=cursor)


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
                with dict_cursor(conn) as cursor:
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
                    if event_type == "calendar_projection":
                        try:
                            _mark_calendar_projection_failed(request_id, payload)
                        except Exception as status_err:
                            logger.warning(f"Could not record calendar projection failure: {status_err}")
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
        raise

    return processed_count


def _dispatch_outbox_event(event_type: str, request_id: Optional[int], payload: dict):
    """
    Executes external API side effects for a given outbox event.
    Raises an exception if any operation fails so the worker can retry or revert.
    """
    if event_type == "calendar_projection":
        with _locked_calendar_projection(request_id, payload, retire_previous=True) as cursor:
            if cursor is not None:
                _apply_calendar_projection(request_id, payload, cursor)

    elif event_type == "agent_reassignment":
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
        sms_result = sms_router.process_event(
            event_type="REASSIGNED",
            appointment_id=request_id,
            customer_phone=details.get("phone"),
            agent_phone=payload.get("agent_phone"),
            previous_agent_phone=payload.get("previous_agent_phone"),
            booking_time=booking_time_str,
            details=reassign_details
        )
        _require_notification_delivery(sms_result)

    elif event_type == "booking_notification":
        booking_type = payload.get("booking_type", "appointment")
        notification_event = payload.get("notification_event")
        details = payload.get("details", {})
        agent_email = payload.get("agent_email")
        agent_name = payload.get("agent_name")
        agent_phone = payload.get("agent_phone")
        slot_datetime_str = payload.get("booking_time_str")

        # Update notification_dispatched_at
        if request_id:
            from serviceBot.db.connection import get_db_connection, dict_cursor
            with get_db_connection() as conn:
                with dict_cursor(conn) as cursor:
                    cursor.execute("UPDATE service_requests SET notification_dispatched_at = CURRENT_TIMESTAMP WHERE id = %s;", (request_id,))

        if agent_email:
            try:
                email_event_type = (
                    "cancel"
                    if notification_event in {"CANCELLED_BY_CUSTOMER", "CANCELLED_BY_ADMIN"}
                    else "reschedule"
                    if notification_event in {"RESCHEDULED", "RESCHEDULED_REASSIGNED"}
                    else booking_type
                )
                send_booking_notification(
                    email_event_type,
                    details,
                    agent_email=agent_email,
                )
            except Exception as email_err:
                logger.warning(f"[OUTBOX EMAIL WARNING] Failed to send booking notification email: {email_err}")

        if slot_datetime_str:
            try:
                clean_slot_str = str(slot_datetime_str)[:19]
                delete_admin_calendar_event(clean_slot_str)
                if notification_event not in {"CANCELLED_BY_CUSTOMER", "CANCELLED_BY_ADMIN"}:
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
            admin_event_type = (
                "cancel"
                if notification_event in {"CANCELLED_BY_CUSTOMER", "CANCELLED_BY_ADMIN"}
                else "reschedule"
                if notification_event in {"RESCHEDULED", "RESCHEDULED_REASSIGNED"}
                else booking_type
            )
            send_admin_notification(
                admin_event_type,
                details,
                agent_name=agent_name,
                agent_email=agent_email,
            )
        except Exception as admin_email_err:
            logger.warning(f"[OUTBOX EMAIL WARNING] Failed to send admin notification: {admin_email_err}")

        # SMS Notification (customer + agent)
        customer_phone = details.get("phone")
        if customer_phone or agent_phone:
            sms_event = notification_event or (
                "BOOKING" if booking_type in ("appointment", "callback") else "RESCHEDULED"
            )
            bypass_qh = bool(
                payload.get("bypass_quiet_hours") or
                payload.get("triggered_by") in ("voice_agent", "telephony_voice_assistant", "voice_tool", "customer") or
                details.get("bypass_quiet_hours") or
                details.get("triggered_by") in ("voice_agent", "telephony_voice_assistant", "voice_tool", "customer")
            )
            from serviceBot.services.sms_router import SMSNotificationRouter
            sms_router = SMSNotificationRouter()
            extra_kwargs = {"bypass_quiet_hours": True} if bypass_qh else {}
            sms_result = sms_router.process_event(
                event_type=sms_event,
                appointment_id=request_id,
                customer_phone=customer_phone,
                agent_phone=agent_phone,
                previous_agent_phone=payload.get("previous_agent_phone"),
                booking_time=slot_datetime_str,
                details=details,
                **extra_kwargs,
            )
            _require_notification_delivery(sms_result)

    elif event_type == "sms_delivery_fallback":
        from serviceBot.services.sms_delivery import dispatch_sms_fallback
        dispatch_sms_fallback(payload)

    elif event_type.startswith("sms_"):
        from serviceBot.services.sms_router import SMSNotificationRouter
        router_svc = SMSNotificationRouter()
        sms_event_type = payload.get("sms_event_type", event_type.replace("sms_", "").upper())
        bypass_qh = bool(
            payload.get("bypass_quiet_hours") or
            payload.get("triggered_by") in ("voice_agent", "telephony_voice_assistant", "voice_tool", "customer") or
            payload.get("details", {}).get("bypass_quiet_hours") or
            payload.get("details", {}).get("triggered_by") in ("voice_agent", "telephony_voice_assistant", "voice_tool", "customer")
        )
        extra_kwargs = {"bypass_quiet_hours": True} if bypass_qh else {}
        sms_result = router_svc.process_event(
            event_type=sms_event_type,
            appointment_id=request_id or payload.get("appointment_id"),
            customer_phone=payload.get("customer_phone"),
            agent_phone=payload.get("agent_phone"),
            previous_agent_phone=payload.get("previous_agent_phone"),
            admin_phone=payload.get("admin_phone"),
            booking_time=payload.get("booking_time_str") or payload.get("booking_time"),
            details=payload.get("details", {}),
            **extra_kwargs,
        )
        _require_notification_delivery(sms_result)

    elif event_type in ("escalation_alert", "sla_escalation"):
        from serviceBot.services.sms_reminders import dispatch_supervisor_escalation_alert
        reason = payload.get("reason") or payload.get("escalation_reason") or "TIMEOUT_NO_RESPONSE"
        appt_id = request_id or payload.get("appointment_id")
        if appt_id:
            dispatch_supervisor_escalation_alert(appt_id, reason=reason)


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
    consecutive_failures = 0
    while True:
        try:
            processed = process_outbox_batch()
            if processed > 0:
                consecutive_failures = 0
        except Exception as e:
            consecutive_failures += 1
            sleep_time = min(60.0, 2.0 * (2 ** min(consecutive_failures, 5)))
            logger.error(f"Worker loop error (backing off for {sleep_time}s): {e}", exc_info=e)
            time.sleep(sleep_time)
            continue
        time.sleep(2.0)


_worker_thread = None


def start_outbox_worker():
    """Starts the outbox background worker thread if not already running."""
    global _worker_thread
    if _worker_thread is None or not _worker_thread.is_alive():
        _worker_thread = threading.Thread(target=_worker_loop, daemon=True, name="OutboxWorkerThread")
        _worker_thread.start()
        logger.info("Outbox worker thread launched.")


def _retire_previous_calendar_projection(payload, cursor):
    """Retire historical effects even when their replacement upsert is obsolete."""
    reservation_id = payload.get("reservation_id")
    agent_id = payload.get("agent_id")
    calendar_event_id = payload.get("calendar_event_id")
    old_agent_id = payload.get("old_agent_id")
    old_booking_time = payload.get("old_booking_time_str")
    if not (reservation_id and agent_id and calendar_event_id
            and payload.get("booking_time_str") and old_agent_id and old_booking_time):
        return
    old_event_id = payload.get("old_calendar_event_id") or (
        f"servicebot{reservation_id}"
        f"{datetime.fromisoformat(str(old_booking_time)).strftime('%Y%m%d%H%M')}"
    )
    if old_agent_id == agent_id and old_event_id == calendar_event_id:
        return
    # A later move may return to this identity, before or after its upsert runs.
    # Preserve both the recorded and deterministic identities of every active owner.
    cursor.execute(
        """
        SELECT 1 FROM appointment_reservations
        WHERE status = 'ACTIVE' AND staff_agent_id = %s
          AND (calendar_event_id = %s
               OR 'servicebot' || id::text || to_char(starts_at, 'YYYYMMDDHH24MI') = %s)
        LIMIT 1;
        """,
        (old_agent_id, old_event_id, old_event_id),
    )
    if cursor.fetchone():
        return
    if not delete_agent_calendar_event_by_id(agent_id=old_agent_id, event_id=old_event_id):
        raise RuntimeError("Google Calendar did not confirm deletion of the previous projection")


def _apply_calendar_projection(request_id, payload, cursor):
    action = payload.get("action", "upsert")
    reservation_id = payload.get("reservation_id")
    agent_id = payload.get("agent_id")
    booking_time = payload.get("booking_time_str")
    calendar_event_id = payload.get("calendar_event_id")
    details = payload.get("details", {})

    if action == "delete":
        if not agent_id or not calendar_event_id:
            raise ValueError("calendar_projection deletion requires an agent and exact event ID")
        if not delete_agent_calendar_event_by_id(agent_id=agent_id, event_id=calendar_event_id):
            raise RuntimeError("Google Calendar did not confirm deletion of the booking projection")
        if request_id and reservation_id:
            _set_calendar_projection_status(request_id, reservation_id, "DELETED", calendar_event_id, cursor=cursor)
        return

    if not request_id or not reservation_id or not agent_id or not booking_time or not calendar_event_id:
        raise ValueError("calendar_projection payload is missing a required reservation field")

    created = create_agent_calendar_event(
        agent_id=agent_id,
        customer_name=details.get("customer_name") or "Customer",
        service_type=details.get("service_type") or "Service Request",
        issue_description=details.get("issue") or "",
        slot_datetime_str=str(booking_time)[:19],
        duration_minutes=payload.get("duration_minutes") or 60,
        booking_type=payload.get("booking_type") or "appointment",
        external_event_id=calendar_event_id,
    )
    if not created:
        raise RuntimeError("Google Calendar did not confirm the booking projection")
    _set_calendar_projection_status(request_id, reservation_id, "CREATED", calendar_event_id, cursor=cursor)
