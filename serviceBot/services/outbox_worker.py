import time
import json
import traceback
import threading
from datetime import datetime, timedelta
from typing import Optional

from serviceBot.db.connection import get_db_connection, dict_cursor
from serviceBot.services.gmail import (
    send_booking_notification,
    send_admin_notification,
    create_admin_calendar_event
)
from serviceBot.services.google_calendar import (
    create_agent_calendar_event,
    delete_agent_calendar_event
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


def process_outbox_batch(batch_size: int = 10):
    """
    Processes pending outbox items with exponential backoff retries and 7-failure automated revert.
    """
    try:
        with get_db_connection() as conn:
            with dict_cursor(conn) as cursor:
                cursor.execute(
                    """
                    SELECT id, event_type, request_id, payload, attempts, max_attempts
                    FROM outbox_notifications
                    WHERE status IN ('PENDING', 'PROCESSING')
                      AND next_retry_at <= CURRENT_TIMESTAMP
                    ORDER BY id ASC
                    LIMIT %s;
                    """,
                    (batch_size,)
                )
                items = cursor.fetchall()

            if not items:
                return

            for item in items:
                item_id = item["id"]
                event_type = item["event_type"]
                request_id = item["request_id"]
                payload = item["payload"] if isinstance(item["payload"], dict) else json.loads(item["payload"])
                attempts = item["attempts"]
                max_attempts = item.get("max_attempts", 7)

                # Mark status as PROCESSING
                with dict_cursor(conn) as cursor:
                    cursor.execute(
                        "UPDATE outbox_notifications SET status = 'PROCESSING', updated_at = CURRENT_TIMESTAMP WHERE id = %s;",
                        (item_id,)
                    )
                conn.commit()

                try:
                    _dispatch_outbox_event(event_type, request_id, payload)
                    # Success: Mark DELIVERED
                    with dict_cursor(conn) as cursor:
                        cursor.execute(
                            "UPDATE outbox_notifications SET status = 'DELIVERED', updated_at = CURRENT_TIMESTAMP WHERE id = %s;",
                            (item_id,)
                        )
                    conn.commit()
                    print(f"[outbox] Event {item_id} ({event_type}) delivered successfully.")

                except Exception as err:
                    err_msg = f"{type(err).__name__}: {str(err)}\n{traceback.format_exc()}"
                    new_attempts = attempts + 1

                    if new_attempts >= max_attempts:
                        # --- REVERT & COMPENSATION ON 7 FAILURES ---
                        print(f"[OUTBOX CRITICAL] Event {item_id} ({event_type}) reached {max_attempts} failures! Executing compensating transaction...")
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
                        # --- EXPONENTIAL BACKOFF RETRY ---
                        delay_seconds = 2 ** new_attempts  # 2s, 4s, 8s, 16s, 32s, 64s, 128s
                        print(f"[outbox] Event {item_id} failed attempt {new_attempts}/{max_attempts}. Retrying in {delay_seconds}s. Error: {err}")
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
        print(f"[outbox_worker] Batch processing exception: {outer_err}")


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

        # 1. Cancel old agent Google Calendar event
        if old_agent_id is not None and booking_time_str:
            delete_agent_calendar_event(old_agent_id, str(booking_time_str)[:19])

        # 2. Create new agent Google Calendar event
        if new_agent_id is not None and booking_time_str:
            create_agent_calendar_event(
                agent_id=new_agent_id,
                customer_name=details.get("customer_name") or "Customer",
                service_type=details.get("service_type") or "Service Request",
                issue_description=details.get("issue") or "",
                slot_datetime_str=str(booking_time_str)[:19]
            )

        # 3. Send email to new agent if present
        if new_agent_email:
            send_booking_notification("appointment", details, agent_email=new_agent_email)

        # 4. Admin Calendar & Admin Notification Email
        if booking_time_str:
            create_admin_calendar_event(
                customer_name=details.get("customer_name") or "Customer",
                service_type=details.get("service_type") or "Service Request",
                issue_description=details.get("issue") or "",
                slot_datetime_str=str(booking_time_str)[:19],
                mechanic_name=new_agent_name
            )

        send_admin_notification("reassign", details, mechanic_name=new_agent_name, mechanic_email=new_agent_email)

    elif event_type == "booking_notification":
        booking_type = payload.get("booking_type", "appointment")
        details = payload.get("details", {})
        agent_email = payload.get("agent_email")
        agent_name = payload.get("agent_name")
        slot_datetime_str = payload.get("booking_time_str")

        if agent_email:
            send_booking_notification(booking_type, details, agent_email=agent_email)

        if slot_datetime_str:
            create_admin_calendar_event(
                customer_name=details.get("customer_name") or "Customer",
                service_type=details.get("service_type") or "Service Request",
                issue_description=details.get("issue") or "",
                slot_datetime_str=str(slot_datetime_str)[:19],
                mechanic_name=agent_name
            )

        send_admin_notification(booking_type, details, mechanic_name=agent_name, mechanic_email=agent_email)


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
        print(f"[OUTBOX REVERT SUCCESS] Service request {request_id} staff assignment reverted back to agent_id={old_agent_id} ({old_agent_name}).")


def _worker_loop():
    """Background polling loop for outbox processing."""
    print("[outbox_worker] Outbox processing background thread started.")
    while True:
        try:
            process_outbox_batch()
        except Exception as e:
            print(f"[outbox_worker] Worker loop error: {e}")
        time.sleep(2.0)


_worker_thread = None


def start_outbox_worker():
    """Starts the outbox background worker thread if not already running."""
    global _worker_thread
    if _worker_thread is None or not _worker_thread.is_alive():
        _worker_thread = threading.Thread(target=_worker_loop, daemon=True, name="OutboxWorkerThread")
        _worker_thread.start()
        print("[outbox_worker] Outbox worker thread launched.")
