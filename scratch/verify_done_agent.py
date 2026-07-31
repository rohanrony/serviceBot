import sys
import os

sys.path.insert(0, os.path.abspath('.'))

from serviceBot.db.connection import get_db_connection, dict_cursor
from serviceBot.db.queries import assign_staff_agent_to_service_request

def run_verification():
    print("--- Verifying Backend Logic ---")
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("INSERT INTO customers (name, phone) VALUES ('Completed Cust Test', '555-8888') RETURNING id;")
            cust_id = cursor.fetchone()["id"]
            cursor.execute("INSERT INTO staff_agents (name, role) VALUES ('Tech A', 'Mechanic') RETURNING id;")
            agent_id = cursor.fetchone()["id"]
            
            cursor.execute("INSERT INTO service_requests (customer_id, status, booking_type) VALUES (%s, 'completed', 'appointment') RETURNING id;", (cust_id,))
            done_id = cursor.fetchone()["id"]

            cursor.execute("INSERT INTO service_requests (customer_id, status, booking_type) VALUES (%s, 'cancelled', 'appointment') RETURNING id;", (cust_id,))
            cancelled_id = cursor.fetchone()["id"]

            cursor.execute("INSERT INTO service_requests (customer_id, status, booking_type) VALUES (%s, 'cancelled_by_customer', 'appointment') RETURNING id;", (cust_id,))
            cancelled_by_cust_id = cursor.fetchone()["id"]

    for req_id, st in [(done_id, 'completed'), (cancelled_id, 'cancelled'), (cancelled_by_cust_id, 'cancelled_by_customer')]:
        try:
            assign_staff_agent_to_service_request(req_id, agent_id)
            print(f"FAIL: Expected ValueError for status '{st}' was not raised!")
            sys.exit(1)
        except ValueError as val_err:
            print(f"SUCCESS: Status '{st}' properly blocked -> {val_err}")

    print("ALL VERIFICATIONS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    run_verification()
