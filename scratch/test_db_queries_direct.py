import sqlite3
import os

db_path = "/Users/rohanroy/Coding/voiceService/voice_service.db"
print("DB Path exists:", os.path.exists(db_path))

conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row

print("\n--- 1. Stats ---")
cursor = conn.cursor()
cursor.execute("SELECT COUNT(*) FROM crm_notes")
total_calls = cursor.fetchone()[0]
cursor.execute("SELECT COUNT(*) FROM service_requests WHERE booking_type = 'appointment'")
total_appointments = cursor.fetchone()[0]
cursor.execute("SELECT COUNT(*) FROM service_requests")
total_requests = cursor.fetchone()[0]
cursor.execute("SELECT COUNT(*) FROM mock_calendar_slots WHERE is_booked = 0")
open_slots = cursor.fetchone()[0]
cursor.execute("SELECT COUNT(*) FROM service_requests WHERE booking_type = 'callback'")
total_callbacks = cursor.fetchone()[0]

print("Total Calls:", total_calls)
print("Total Appointments:", total_appointments)
print("Total Requests:", total_requests)
print("Open Slots:", open_slots)
print("Total Callbacks:", total_callbacks)

print("\n--- 2. Recent Calls ---")
cursor.execute("""
    SELECT cn.id, cn.call_id, c.name AS customer_name, c.phone, cn.summary, cn.created_at
    FROM crm_notes cn
    JOIN customers c ON cn.customer_id = c.id
    ORDER BY cn.created_at DESC LIMIT 5
""")
for row in cursor.fetchall():
    print(dict(row))

print("\n--- 3. Recent Service Requests ---")
cursor.execute("""
    SELECT sr.id, sr.service_type, sr.issue_description, sr.status, sr.time_slot, sr.created_at,
           sr.booking_type, sr.booking_time,
           c.name AS customer_name, c.phone,
           v.make, v.model, v.year
    FROM service_requests sr
    JOIN customers c ON sr.customer_id = c.id
    JOIN vehicles v ON sr.vehicle_id = v.id
    ORDER BY sr.created_at DESC LIMIT 5
""")
for row in cursor.fetchall():
    print(dict(row))

print("\n--- 4. Recent Callbacks ---")
cursor.execute("""
    SELECT sr.id, sr.status, sr.created_at, sr.booking_time AS preferred_time, c.name AS customer_name, c.phone, sr.service_type, sr.issue_description,
           v.make, v.model, v.year
    FROM service_requests sr
    JOIN customers c ON sr.customer_id = c.id
    LEFT JOIN vehicles v ON sr.vehicle_id = v.id
    WHERE sr.booking_type = 'callback'
    ORDER BY sr.created_at DESC LIMIT 5
""")
for row in cursor.fetchall():
    print(dict(row))

conn.close()
