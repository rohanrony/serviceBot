#!/usr/bin/env python3
"""
scripts/validate_customer_flow.py
==============================================================================
Validates the end-to-end appointment notification pipeline using the designated
test customer: Rohan Roy (+14242704893).

Triggers booking, status updates, or cancellations, flushes the PostgreSQL
outbox_notifications queue, and prints Twilio dispatch status (WhatsApp / SMS).

Usage:
    .venv/bin/python scripts/validate_customer_flow.py --action audit
    .venv/bin/python scripts/validate_customer_flow.py --action book --channel WHATSAPP
    .venv/bin/python scripts/validate_customer_flow.py --action cancel --channel WHATSAPP
==============================================================================
"""

import os
import sys
import argparse
import json
import datetime
from pathlib import Path

# Ensure repo root is on sys.path
REPO_ROOT = Path(__file__).parent.parent.resolve()
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Load environment
from dotenv import load_dotenv, find_dotenv
env_file = find_dotenv()
if env_file:
    load_dotenv(env_file, override=True)
else:
    load_dotenv(REPO_ROOT / ".env", override=True)

os.environ["LOG_FILE"] = ""

from serviceBot.logger import get_logger
from serviceBot.db.connection import get_db_connection, dict_cursor
from serviceBot.services.outbox_worker import process_outbox_batch

logger = get_logger("validate_customer")

CUSTOMER_NAME = "Rohan Roy"
CUSTOMER_PHONE = "+14242704893"
VEHICLE_MAKE = "Toyota"
VEHICLE_MODEL = "RAV4"
VEHICLE_YEAR = 2021


def ensure_customer_and_vehicle() -> tuple[int, int]:
    """Ensures customer Rohan Roy and their vehicle exist in the database."""
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            # 1. Customer
            cursor.execute("SELECT id FROM customers WHERE phone = %s LIMIT 1;", (CUSTOMER_PHONE,))
            row = cursor.fetchone()
            if row:
                customer_id = row["id"]
            else:
                cursor.execute(
                    """
                    INSERT INTO customers (name, phone, created_at)
                    VALUES (%s, %s, CURRENT_TIMESTAMP)
                    RETURNING id;
                    """,
                    (CUSTOMER_NAME, CUSTOMER_PHONE)
                )
                customer_id = cursor.fetchone()["id"]

            # 2. Vehicle
            cursor.execute(
                "SELECT id FROM vehicles WHERE customer_id = %s LIMIT 1;",
                (customer_id,)
            )
            v_row = cursor.fetchone()
            if v_row:
                vehicle_id = v_row["id"]
            else:
                cursor.execute(
                    """
                    INSERT INTO vehicles (customer_id, make, model, year, created_at)
                    VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
                    RETURNING id;
                    """,
                    (customer_id, VEHICLE_MAKE, VEHICLE_MODEL, VEHICLE_YEAR)
                )
                vehicle_id = cursor.fetchone()["id"]

            conn.commit()

            # 3. Whitelist ensure
            try:
                cursor.execute(
                    """
                    INSERT INTO sms_whitelist (phone_number, friendly_name, recipient_role, twilio_verified, whatsapp_onboarded)
                    VALUES (%s, %s, 'CUSTOMER', TRUE, TRUE)
                    ON CONFLICT (phone_number) DO UPDATE SET whatsapp_onboarded = TRUE;
                    """,
                    (CUSTOMER_PHONE, CUSTOMER_NAME)
                )
                conn.commit()
            except Exception:
                conn.rollback()

            return customer_id, vehicle_id


def print_sandbox_info():
    """Prints Twilio WhatsApp Sandbox info."""
    sandbox_number = os.getenv("TWILIO_WHATSAPP_SANDBOX_NUMBER", "+14155238886")
    join_code = os.getenv("TWILIO_WHATSAPP_JOIN_CODE", "join evidence-lips")
    print("\n" + "=" * 65)
    print("📲 TWILIO WHATSAPP SANDBOX NOTICE")
    print(f"To receive WhatsApp messages on {CUSTOMER_PHONE}:")
    print(f"1. Open WhatsApp on your phone.")
    print(f"2. Send message: \"{join_code}\" to {sandbox_number}")
    print(f"3. Twilio sandbox sessions remain active for 72 hours.")
    print("=" * 65 + "\n")


def action_audit():
    """Prints recent outbox notifications and SMS/WhatsApp logs for the test customer."""
    print_sandbox_info()
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            # Recent Outbox Notifications
            cursor.execute(
                """
                SELECT id, event_type, status, attempts, error_log, created_at, updated_at
                FROM outbox_notifications
                ORDER BY id DESC
                LIMIT 10;
                """
            )
            outbox_rows = cursor.fetchall()

            print(f"📋 LAST 10 OUTBOX NOTIFICATIONS:")
            print("-" * 80)
            if not outbox_rows:
                print("No outbox notifications found.")
            else:
                for r in outbox_rows:
                    err = f" | Err: {r['error_log'][:50]}..." if r["error_log"] else ""
                    print(f"ID #{r['id']} | Type: {r['event_type']} | Status: {r['status']} | Attempts: {r['attempts']} | Time: {r['updated_at']}{err}")

            # Recent SMS/WhatsApp Logs
            cursor.execute(
                """
                SELECT id, recipient_phone, template_type, status, twilio_message_sid, error_message, created_at
                FROM sms_log
                WHERE recipient_phone LIKE %s
                ORDER BY id DESC
                LIMIT 5;
                """,
                (f"%{CUSTOMER_PHONE[-10:]}%",)
            )
            sms_rows = cursor.fetchall()

            print("\n" + "-" * 80)
            print(f"💬 RECENT DISPATCH LOGS FOR {CUSTOMER_PHONE} ({CUSTOMER_NAME}):")
            print("-" * 80)
            if not sms_rows:
                print(f"No dispatch logs found targeting {CUSTOMER_PHONE}.")
            else:
                for s in sms_rows:
                    sid = s["twilio_message_sid"] or "N/A"
                    err = f" | Error: {s['error_message']}" if s["error_message"] else ""
                    print(f"Log #{s['id']} | {s['template_type']} -> {s['status']} | SID: {sid}{err}")
            print("-" * 80)


def action_book(channel: str = "WHATSAPP"):
    """Creates an appointment booking for Rohan Roy and dispatches outbox notification."""
    customer_id, vehicle_id = ensure_customer_and_vehicle()

    # Calculate tomorrow at 10:00 AM
    tomorrow = datetime.datetime.now() + datetime.timedelta(days=1)
    booking_time = tomorrow.strftime("%Y-%m-%d 10:00:00")

    print(f"Creating appointment booking for {CUSTOMER_NAME} at {booking_time}...")

    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                """
                INSERT INTO service_requests (
                    customer_id, vehicle_id, service_type, issue_description,
                    booking_type, booking_time, status, confirmation_status,
                    created_at, updated_at
                ) VALUES (
                    %s, %s, %s, %s,
                    'appointment', %s, 'confirmed', 'confirmed',
                    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                ) RETURNING id;
                """,
                (
                    customer_id,
                    vehicle_id,
                    "Synthetic Validation Service",
                    "Customer Validation: Brake inspection and engine diagnostics check.",
                    booking_time
                )
            )
            sr_id = cursor.fetchone()["id"]

            payload = {
                "booking_type": "appointment",
                "notification_event": "BOOKING",
                "channel": channel,
                "details": {
                    "request_id": sr_id,
                    "customer_name": CUSTOMER_NAME,
                    "phone": CUSTOMER_PHONE,
                    "service_type": "Synthetic Validation Service",
                    "vehicle": f"{VEHICLE_YEAR} {VEHICLE_MAKE} {VEHICLE_MODEL}",
                    "booking_time": booking_time,
                    "issue": "Brake inspection and engine diagnostics check."
                }
            }

            cursor.execute(
                """
                INSERT INTO outbox_notifications (event_type, request_id, payload, status, next_retry_at)
                VALUES ('booking_notification', %s, %s, 'PENDING', CURRENT_TIMESTAMP);
                """,
                (sr_id, json.dumps(payload))
            )
            conn.commit()

    print(f"✅ Created Service Request #{sr_id} with pending outbox notification.")
    print("Processing outbox notifications batch...")
    processed = process_outbox_batch()
    print(f"Processed {processed} event(s).")
    action_audit()


def action_reschedule(channel: str = "WHATSAPP"):
    """Reschedules the latest active appointment for Rohan Roy to a new time."""
    customer_id, _ = ensure_customer_and_vehicle()

    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                """
                SELECT id, booking_time FROM service_requests
                WHERE customer_id = %s AND status != 'cancelled'
                ORDER BY id DESC LIMIT 1;
                """,
                (customer_id,)
            )
            sr_row = cursor.fetchone()
            if not sr_row:
                print(f"No active service request found for {CUSTOMER_NAME}. Booking one first...")
                action_book(channel=channel)
                return

            sr_id = sr_row["id"]
            # Set new slot to 2 days ahead at 14:00:00
            new_date = datetime.datetime.now() + datetime.timedelta(days=2)
            new_time_str = new_date.strftime("%Y-%m-%d 14:00:00")

            cursor.execute(
                """
                UPDATE service_requests
                SET booking_time = %s, status = 'confirmed', updated_at = CURRENT_TIMESTAMP
                WHERE id = %s;
                """,
                (new_time_str, sr_id)
            )

            payload = {
                "sms_event_type": "RESCHEDULED",
                "appointment_id": sr_id,
                "customer_phone": CUSTOMER_PHONE,
                "booking_time_str": new_time_str,
                "channel": channel,
                "details": {
                    "customer_name": CUSTOMER_NAME,
                    "phone": CUSTOMER_PHONE,
                    "service_type": "Synthetic Validation Service",
                    "vehicle": f"{VEHICLE_YEAR} {VEHICLE_MAKE} {VEHICLE_MODEL}",
                    "booking_time": new_time_str,
                    "issue": "Customer rescheduled test appointment to new window."
                }
            }

            cursor.execute(
                """
                INSERT INTO outbox_notifications (event_type, request_id, payload, status, next_retry_at)
                VALUES ('sms_status_change', %s, %s, 'PENDING', CURRENT_TIMESTAMP);
                """,
                (sr_id, json.dumps(payload))
            )
            conn.commit()

    print(f"✅ Rescheduled Service Request #{sr_id} to {new_time_str}.")
    print("Processing outbox notifications batch...")
    processed = process_outbox_batch()
    print(f"Processed {processed} event(s).")
    action_audit()


def action_status_change(status: str = "confirmed", channel: str = "WHATSAPP"):
    """Updates service request status and triggers status update notification."""
    customer_id, _ = ensure_customer_and_vehicle()

    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                """
                SELECT id, booking_time FROM service_requests
                WHERE customer_id = %s
                ORDER BY id DESC LIMIT 1;
                """,
                (customer_id,)
            )
            sr_row = cursor.fetchone()
            if not sr_row:
                print(f"No service request found for {CUSTOMER_NAME}. Booking one first...")
                action_book(channel=channel)
                return

            sr_id = sr_row["id"]
            booking_time = str(sr_row["booking_time"] or "")

            cursor.execute(
                """
                UPDATE service_requests
                SET status = %s, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s;
                """,
                (status, sr_id)
            )

            payload = {
                "sms_event_type": f"STATUS_{status.upper()}",
                "appointment_id": sr_id,
                "customer_phone": CUSTOMER_PHONE,
                "booking_time_str": booking_time,
                "channel": channel,
                "details": {
                    "customer_name": CUSTOMER_NAME,
                    "phone": CUSTOMER_PHONE,
                    "service_type": "Synthetic Validation Service",
                    "vehicle": f"{VEHICLE_YEAR} {VEHICLE_MAKE} {VEHICLE_MODEL}",
                    "booking_time": booking_time,
                    "issue": f"Status updated to {status}."
                }
            }

            cursor.execute(
                """
                INSERT INTO outbox_notifications (event_type, request_id, payload, status, next_retry_at)
                VALUES ('sms_status_change', %s, %s, 'PENDING', CURRENT_TIMESTAMP);
                """,
                (sr_id, json.dumps(payload))
            )
            conn.commit()

    print(f"✅ Updated Service Request #{sr_id} status to '{status}'.")
    print("Processing outbox notifications batch...")
    processed = process_outbox_batch()
    print(f"Processed {processed} event(s).")
    action_audit()


def action_matrix_test():
    """Validates Notification Matrix routing rules across different event and recipient permutations."""
    from serviceBot.services.sms_router import SMSNotificationRouter

    router = SMSNotificationRouter()
    print("\n" + "=" * 65)
    print("🧪 NOTIFICATION MATRIX PERMUTATION VALIDATION")
    print("=" * 65)

    test_matrix_cases = [
        ("BOOKING", "customer", True),
        ("RESCHEDULED", "customer", True),
        ("CANCELLED_BY_CUSTOMER", "customer", True),
        ("CANCELLED_BY_ADMIN", "customer", True),
        ("REASSIGNED", "customer", False),  # Customer not notified of internal staff swap
        ("ESCALATION", "admin", True),       # Admin receives urgent escalation
        ("AGENT_CONFIRMED", "customer", False),
    ]

    from serviceBot.db.queries import get_sms_matrix_rules
    rules = get_sms_matrix_rules()

    all_passed = True
    for event, role, expected_default in test_matrix_cases:
        enabled_channels = router._enabled_channels(event, role, rules)
        is_active = len(enabled_channels) > 0
        match = (is_active == expected_default)
        symbol = "✅" if match else "❌"
        ch_str = ", ".join(enabled_channels) if enabled_channels else "DISABLED"
        print(f" {symbol} Event: {event:<22} | Role: {role:<10} | Active: {str(is_active):<5} (Channels: {ch_str})")
        if not match:
            all_passed = False

    print("=" * 65)
    if all_passed:
        print("🎉 ALL MATRIX RULES MATCH EXPECTED SPECIFICATION!")
    else:
        print("⚠️ Some matrix rule permutations differed from default expectations.")
    print("=" * 65 + "\n")


def action_cancel(channel: str = "WHATSAPP"):
    """Finds the latest appointment for Rohan Roy and cancels it, triggering cancellation notification."""
    customer_id, _ = ensure_customer_and_vehicle()

    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                """
                SELECT id, booking_time FROM service_requests
                WHERE customer_id = %s AND status != 'cancelled'
                ORDER BY id DESC LIMIT 1;
                """,
                (customer_id,)
            )
            sr_row = cursor.fetchone()
            if not sr_row:
                print(f"No active service request found for {CUSTOMER_NAME} to cancel.")
                return

            sr_id = sr_row["id"]
            booking_time = str(sr_row["booking_time"] or "")

            cursor.execute(
                """
                UPDATE service_requests
                SET status = 'cancelled', confirmation_status = 'cancelled', updated_at = CURRENT_TIMESTAMP
                WHERE id = %s;
                """,
                (sr_id,)
            )

            payload = {
                "sms_event_type": "CANCELLED_BY_CUSTOMER",
                "appointment_id": sr_id,
                "customer_phone": CUSTOMER_PHONE,
                "booking_time_str": booking_time,
                "channel": channel,
                "details": {
                    "customer_name": CUSTOMER_NAME,
                    "phone": CUSTOMER_PHONE,
                    "service_type": "Service Request",
                    "issue": "Customer cancelled test appointment."
                }
            }

            cursor.execute(
                """
                INSERT INTO outbox_notifications (event_type, request_id, payload, status, next_retry_at)
                VALUES ('sms_status_change', %s, %s, 'PENDING', CURRENT_TIMESTAMP);
                """,
                (sr_id, json.dumps(payload))
            )
            conn.commit()

    print(f"✅ Cancelled Service Request #{sr_id}.")
    print("Processing outbox notifications batch...")
    processed = process_outbox_batch()
    print(f"Processed {processed} event(s).")
    action_audit()


def main():
    parser = argparse.ArgumentParser(description="Customer Rohan Roy Notification Validation")
    parser.add_argument(
        "--action",
        choices=["audit", "book", "reschedule", "status", "cancel", "matrix"],
        default="audit",
        help="Action to perform (audit, book, reschedule, status, cancel, matrix)"
    )
    parser.add_argument(
        "--status-value",
        type=str,
        default="confirmed",
        help="Target status for '--action status' (default: confirmed)"
    )
    parser.add_argument(
        "--channel",
        choices=["WHATSAPP", "SMS"],
        default="WHATSAPP",
        help="Target notification channel (default: WHATSAPP)"
    )
    parser.add_argument(
        "--local-db",
        action="store_true",
        help="Target local test DB (voice_service_test) instead of production/remote DATABASE_URL"
    )
    args = parser.parse_args()

    if args.local_db:
        local_url = os.getenv("TEST_DATABASE_URL", "postgresql://localhost/voice_service_test")
        os.environ["DATABASE_URL"] = local_url
        print(f"🔧 Target Database: Local ({local_url})")

    if args.action == "audit":
        action_audit()
    elif args.action == "book":
        action_book(channel=args.channel)
    elif args.action == "reschedule":
        action_reschedule(channel=args.channel)
    elif args.action == "status":
        action_status_change(status=args.status_value, channel=args.channel)
    elif args.action == "cancel":
        action_cancel(channel=args.channel)
    elif args.action == "matrix":
        action_matrix_test()


if __name__ == "__main__":
    main()
