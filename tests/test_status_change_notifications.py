import pytest
from unittest.mock import patch, MagicMock
from serviceBot.db.connection import get_db_connection, dict_cursor
from serviceBot.db.queries import update_service_request_status
from serviceBot.services.sms_router import SMSNotificationRouter

def create_test_data(cust_name="Notification Test User", phone="+15551234567"):
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("INSERT INTO customers (name, phone) VALUES (%s, %s) RETURNING id;", (cust_name, phone))
            cust_id = cursor.fetchone()["id"]

            cursor.execute("INSERT INTO vehicles (customer_id, year, make, model) VALUES (%s, '2024', 'BMW', 'X5') RETURNING id;", (cust_id,))
            veh_id = cursor.fetchone()["id"]

            cursor.execute("""
                INSERT INTO service_requests (customer_id, vehicle_id, service_type, issue_description, booking_time, status)
                VALUES (%s, %s, 'Oil Change', 'Regular maintenance', '2026-08-10 10:00:00', 'pending')
                RETURNING id;
            """, (cust_id, veh_id))
            sr_id = cursor.fetchone()["id"]
            return cust_id, veh_id, sr_id

def test_status_update_queues_notifications_for_cancelled_and_rescheduled():
    cust_id, veh_id, sr_id = create_test_data("Cancelled Test User", "+15551234567")

    with patch("serviceBot.services.sms_router.SMSNotificationRouter.process_event") as mock_process_event:
        update_service_request_status(sr_id, "cancelled", triggered_by="admin")
        mock_process_event.assert_not_called()

    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("SELECT event_type, payload ->> 'sms_event_type' AS sms_event_type FROM outbox_notifications WHERE request_id = %s ORDER BY id;", (sr_id,))
            assert cursor.fetchall() == [{"event_type": "sms_status_change", "sms_event_type": "CANCELLED_BY_ADMIN"}]

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("UPDATE service_requests SET status = 'pending' WHERE id = %s;", (sr_id,))

    with patch("serviceBot.services.sms_router.SMSNotificationRouter.process_event") as mock_process_event:
        update_service_request_status(sr_id, "rescheduled", triggered_by="admin")
        mock_process_event.assert_not_called()

    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("SELECT payload ->> 'sms_event_type' AS sms_event_type FROM outbox_notifications WHERE request_id = %s ORDER BY id;", (sr_id,))
            assert [row["sms_event_type"] for row in cursor.fetchall()] == ["CANCELLED_BY_ADMIN", "RESCHEDULED"]

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("UPDATE service_requests SET status = 'pending' WHERE id = %s;", (sr_id,))

    with patch("serviceBot.services.sms_router.SMSNotificationRouter.process_event") as mock_process_event:
        update_service_request_status(sr_id, "confirmed", triggered_by="admin")
        mock_process_event.assert_not_called()

    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("SELECT COUNT(*) AS total FROM outbox_notifications WHERE request_id = %s;", (sr_id,))
            assert cursor.fetchone()["total"] == 2

def test_sms_router_resolves_customer_phone_from_db():
    router = SMSNotificationRouter()
    cust_id, veh_id, sr_id = create_test_data("Phone Resolution User", "+15559876543")

    with patch.object(router.twilio_client, "send_whatsapp") as mock_whatsapp, \
         patch("serviceBot.services.twilio_sms.is_phone_whitelisted", return_value=True), \
         patch("serviceBot.services.sms_router.get_customer_opt_in", return_value=True), \
         patch("serviceBot.services.sms_router.is_in_quiet_hours", return_value=False), \
         patch("serviceBot.services.sms_router.get_sms_matrix_rules", return_value=[{"event_type": "CANCELLED_BY_ADMIN", "recipient_role": "customer", "enabled": True}]):
        mock_whatsapp.return_value = {"success": True, "sid": "SMmock_test123"}
        
        # Calling process_event without customer_phone argument
        res = router.process_event(
            event_type="CANCELLED_BY_ADMIN",
            appointment_id=sr_id
        )
        print("ROUTER RES:", res)

        mock_whatsapp.assert_called_once()
        called_phone = mock_whatsapp.call_args.kwargs.get("to")
        assert "+15559876543" in called_phone
