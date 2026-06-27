import os
import sys
import sqlite3
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["DATABASE_URL"] = "/Users/rohanroy/.gemini/antigravity-ide/scratch/test_voice_service.db"

from serviceBot.db.connection import get_db_connection
from serviceBot.db.queries import book_appointment, seed_db

with get_db_connection() as conn:
    cursor = conn.cursor()
    cursor.execute("DELETE FROM customers WHERE id = 15 OR phone IN ('555-987-6543', '5559876543')")
    cursor.execute("DELETE FROM vehicles WHERE customer_id = 15")
    cursor.execute("DELETE FROM service_requests WHERE customer_id = 15")
    
    cursor.execute("INSERT INTO customers (id, name, phone) VALUES (15, 'Booking Tester', '5559876543')")
    cursor.execute("INSERT INTO vehicles (id, customer_id, make, model, year) VALUES (5, 15, 'Honda', 'Civic', 2018)")
    cursor.execute("""
        INSERT INTO service_requests (id, customer_id, vehicle_id, service_type, issue_description, status)
        VALUES (30, 15, 5, 'Brakes', 'Grinding noise', 'pending')
    """)
    cursor.execute("UPDATE staff_agents SET email = 'john@example.com' WHERE id = 1;")
    cursor.execute("INSERT OR IGNORE INTO mock_calendar_slots (slot_datetime, is_booked, staff_agent_id) VALUES ('2026-06-25 14:00:00', 0, 1);")
    conn.commit()

try:
    print("Calling book_appointment...")
    res = book_appointment(
        customer_id=15,
        service_request_id=30,
        appointment_datetime="2026-06-25 14:00:00",
        service_type="Brake Service & Repair"
    )
    print("Success, returned appt_id:", res)
except Exception as e:
    print("Failed with exception:", repr(e))
