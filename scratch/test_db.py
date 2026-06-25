import sqlite3

def run():
    conn = sqlite3.connect('voice_service.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    print("--- service_requests count ---")
    cursor.execute("SELECT COUNT(*) FROM service_requests;")
    print("Total service requests:", cursor.fetchone()[0])
    
    print("\n--- all service_requests raw ---")
    cursor.execute("SELECT id, customer_id, vehicle_id, booking_type, booking_time, created_at FROM service_requests;")
    for row in cursor.fetchall():
        print(dict(row))
        
    print("\n--- get_service_requests query results ---")
    cursor.execute("""
        SELECT sr.id, sr.service_type, sr.issue_description, sr.status, sr.time_slot, sr.created_at,
               sr.booking_type, sr.booking_time,
               c.name AS customer_name, c.phone,
               v.make, v.model, v.year
        FROM service_requests sr
        JOIN customers c ON sr.customer_id = c.id
        JOIN vehicles v ON sr.vehicle_id = v.id
        ORDER BY sr.created_at DESC
    """)
    rows = cursor.fetchall()
    print(f"Query returned {len(rows)} rows:")
    for row in rows:
        print(dict(row))

if __name__ == '__main__':
    run()
