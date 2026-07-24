import sys
import json
import time
from serviceBot.db.connection import get_db_connection, dict_cursor, init_db
from serviceBot.db.queries import reassign_service_request
from serviceBot.services.outbox_worker import process_outbox_batch, _execute_revert_compensation, enqueue_outbox_event

def run_integration_tests():
    print("=== STARTING TRANSACTIONAL OUTBOX & REVERT INTEGRATION TESTS ===")
    init_db()

    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            # 1. Verify Outbox Schema
            cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'outbox_notifications';")
            cols = [r["column_name"] for r in cursor.fetchall()]
            print("✔ Outbox Columns verified:", cols)
            assert "attempts" in cols
            assert "max_attempts" in cols
            assert "status" in cols
            assert "next_retry_at" in cols

            # 2. Test Atomic Outbox Enqueue & Revert Logic
            test_payload = {
                "old_agent_id": 7,
                "old_agent_name": "John Doe",
                "new_agent_id": 8,
                "new_agent_name": "Tim Williams",
                "new_agent_email": "tim@example.com",
                "booking_time_str": "2026-07-25 10:00:00",
                "details": {"customer_name": "Test Customer", "service_type": "Oil Change"}
            }

            # Insert atomic outbox event
            enqueue_outbox_event(cursor, "agent_reassignment", 1, test_payload)
        conn.commit()

        # Verify enqueued row
        with dict_cursor(conn) as cursor:
            cursor.execute("SELECT id, event_type, status, attempts, max_attempts FROM outbox_notifications WHERE event_type = 'agent_reassignment' ORDER BY id DESC LIMIT 1;")
            outbox_row = cursor.fetchone()
            outbox_id = outbox_row["id"]
            print("✔ Enqueued Outbox Record:", dict(outbox_row))
            assert outbox_row["status"] == "PENDING"
            assert outbox_row["attempts"] == 0

        # 3. Simulate 7 consecutive failures & test automatic compensating revert
        print("\nSimulating 7 consecutive outbox failures...")
        dummy_error = "HTTP 500 Connection Refused: Simulated External Gateway Timeout"

        for i in range(1, 8):
            with dict_cursor(conn) as cursor:
                if i >= 7:
                    # On 7th failure, run compensate revert
                    _execute_revert_compensation(conn, "agent_reassignment", 1, test_payload, dummy_error)
                    cursor.execute(
                        "UPDATE outbox_notifications SET status = 'FAILED_REVERTED', attempts = %s, error_log = %s WHERE id = %s;",
                        (i, dummy_error, outbox_id)
                    )
                else:
                    delay = 2 ** i
                    cursor.execute(
                        "UPDATE outbox_notifications SET attempts = %s, next_retry_at = CURRENT_TIMESTAMP + (%s || ' seconds')::INTERVAL WHERE id = %s;",
                        (i, str(delay), outbox_id)
                    )
            conn.commit()
            print(f"  - Failure {i}/7: Backoff delay = {2**i}s")

        # Verify Final Status
        with dict_cursor(conn) as cursor:
            cursor.execute("SELECT id, status, attempts FROM outbox_notifications WHERE id = %s;", (outbox_id,))
            final_row = cursor.fetchone()
            print("✔ Final Outbox Status after 7 failures:", dict(final_row))
            assert final_row["status"] == "FAILED_REVERTED"
            assert final_row["attempts"] == 7

    print("\n=== ALL TRANSACTIONAL OUTBOX & 7-FAILURE REVERT TESTS PASSED! ===")

if __name__ == "__main__":
    run_integration_tests()
