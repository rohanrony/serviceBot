import json
import time
from serviceBot.db.connection import get_db_connection, dict_cursor, init_db
from serviceBot.services.outbox_worker import enqueue_outbox_event, _execute_revert_compensation, process_outbox_batch

def test_outbox_flow():
    print("Testing init_db & outbox_notifications table...")
    init_db()

    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            # Check table exists
            cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'outbox_notifications';")
            cols = [r["column_name"] for r in cursor.fetchall()]
            print("outbox_notifications columns:", cols)
            assert "attempts" in cols
            assert "max_attempts" in cols
            assert "next_retry_at" in cols
            assert "status" in cols

            # Test enqueue
            payload = {
                "old_agent_id": 7,
                "old_agent_name": "John Doe",
                "new_agent_id": 8,
                "new_agent_name": "Tim Williams",
                "booking_time_str": "2026-07-25 10:00:00",
                "details": {"customer_name": "Test Customer"}
            }
            enqueue_outbox_event(cursor, "agent_reassignment", 1, payload)
        conn.commit()

        # Query enqueued item
        with dict_cursor(conn) as cursor:
            cursor.execute("SELECT id, event_type, status, attempts, max_attempts FROM outbox_notifications WHERE event_type = 'agent_reassignment' ORDER BY id DESC LIMIT 1;")
            row = cursor.fetchone()
            print("Enqueued Outbox Row:", dict(row))
            assert row["status"] == "PENDING"
            assert row["attempts"] == 0
            assert row["max_attempts"] == 7

        # Test Revert Compensation Function
        _execute_revert_compensation(conn, "agent_reassignment", 1, payload, "Test Error Log")
        print("Revert compensation test passed!")

    print("ALL OUTBOX TESTS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    test_outbox_flow()
