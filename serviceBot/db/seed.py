from serviceBot.db.connection import get_db_connection

def seed_db():
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # Clear existing data using TRUNCATE CASCADE
        cursor.execute("""
            TRUNCATE TABLE 
                crm_notes, 
                service_requests, 
                vehicles, 
                customers, 
                mock_calendar_slots, 
                staff_agents, 
                services, 
                user_google_accounts, 
                oauth_states 
            CASCADE;
        """)
        conn.commit()
        
        # Insert Services
        cba_services = [
            (1, "Oil Change", "Full synthetic oil change, premium filter replacement, fluid top-off, and courtesy inspection", "$79-119", 45, True, True, True, True, True),
            (2, "Brake Service & Repair", "Complimentary brake inspection, pad/shoe replacement, and rotor/drum resurfacing or replacement", "$199-450 per axle", 90, True, True, True, True, True),
            (3, "Complimentary Courtesy Inspection", "Comprehensive multi-point visual inspection of major and minor vehicle systems", "$0", 20, True, True, True, True, True),
            (4, "AC Service & Repair", "System performance test, leak check, refrigerant evacuation, and recharge", "$149-399", 60, True, True, True, True, True),
            (5, "Engine Diagnostics", "Check engine light scanning, computerized diagnostics, and troubleshooting by ASE-certified technicians", "$119-189", 60, True, True, True, True, True)
        ]
        cursor.executemany(
            "INSERT INTO services (id, name, description, price_range, duration_minutes, req_customer_name, req_phone_number, req_vehicle_details, req_issue_description, req_location) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s);",
            cba_services
        )
        
        # Insert Customers
        cursor.execute(
            "INSERT INTO customers (id, name, phone, email) VALUES (%s, %s, %s, %s);",
            (1, 'Sarah Johnson', '555-123-4567', 'sarah.j@example.com')
        )
        cursor.execute(
            "INSERT INTO customers (id, name, phone, email) VALUES (%s, %s, %s, %s);",
            (2, 'David Smith', '555-987-6543', 'dsmith@example.com')
        )
        cursor.execute(
            "INSERT INTO customers (id, name, phone, email) VALUES (%s, %s, %s, %s);",
            (3, 'Emily Davis', '555-444-5555', 'emily.d@example.com')
        )
        cursor.execute(
            "INSERT INTO customers (id, name, phone, email) VALUES (%s, %s, %s, %s);",
            (4, 'Michael Miller', '555-222-3333', 'mmiller@example.com')
        )
        
        # Insert Vehicles
        cursor.execute(
            "INSERT INTO vehicles (id, customer_id, make, model, year, vin) VALUES (%s, %s, %s, %s, %s, %s);",
            (1, 1, 'Honda', 'Civic', 2020, '1HGCR2F8LAA123456')
        )
        cursor.execute(
            "INSERT INTO vehicles (id, customer_id, make, model, year, vin) VALUES (%s, %s, %s, %s, %s, %s);",
            (2, 2, 'Ford', 'F-150', 2018, '1FTFW1EF5JFC98765')
        )
        cursor.execute(
            "INSERT INTO vehicles (id, customer_id, make, model, year, vin) VALUES (%s, %s, %s, %s, %s, %s);",
            (3, 3, 'Toyota', 'RAV4', 2021, '4T1BD1FK1LU098765')
        )
        cursor.execute(
            "INSERT INTO vehicles (id, customer_id, make, model, year, vin) VALUES (%s, %s, %s, %s, %s, %s);",
            (4, 4, 'Chevrolet', 'Silverado', 2015, '1GCVKREC3FZ123456')
        )
        
        # Insert Service Requests
        cursor.execute(
            "INSERT INTO service_requests (id, customer_id, vehicle_id, service_type, issue_description, status, booking_type, booking_time) VALUES (%s, %s, %s, %s, %s, %s, %s, %s);",
            (1, 1, 1, 'Brake Service & Repair', 'Grinding noise when stopping, brake warning light is on.', 'pending', 'appointment', '2026-06-10 14:00:00')
        )
        cursor.execute(
            "INSERT INTO service_requests (id, customer_id, vehicle_id, service_type, issue_description, status, booking_type, booking_time) VALUES (%s, %s, %s, %s, %s, %s, %s, %s);",
            (2, 2, 2, 'Oil Change', 'Needs full synthetic oil change and filter replacement.', 'completed', 'callback', 'ASAP')
        )
        cursor.execute(
            "INSERT INTO service_requests (id, customer_id, vehicle_id, service_type, issue_description, status, booking_type, booking_time) VALUES (%s, %s, %s, %s, %s, %s, %s, %s);",
            (3, 3, 3, 'AC Service & Repair', 'Air conditioner is blowing warm air on hot days.', 'in_progress', 'appointment', '2026-06-10 10:00:00')
        )
        cursor.execute(
            "INSERT INTO service_requests (id, customer_id, vehicle_id, service_type, issue_description, status, booking_type, booking_time) VALUES (%s, %s, %s, %s, %s, %s, %s, %s);",
            (4, 4, 4, 'Engine Diagnostics', 'Check engine light is on, engine running rough.', 'pending', 'appointment', '2026-06-11 11:00:00')
        )

        # Insert CRM Notes (Intake Calls & Transcripts)
        cursor.execute(
            "INSERT INTO crm_notes (id, call_id, customer_id, summary, transcript, created_at) VALUES (%s, %s, %s, %s, %s, %s);",
            (
                1, 
                "call_sarah_101", 
                1, 
                "Customer Sarah Johnson reported grinding noise when stopping on her 2020 Honda Civic. Scheduled Brake Service & Repair and Courtesy Inspection for June 10th. Requested local shuttle service.",
                "Advisor: Thank you for calling Test in Springfield, home of the Nice Difference. This is John, how can I help you?\nSarah: Hi, my Honda Civic's brakes are making a loud grinding noise when I stop, and the brake light just came on.\nAdvisor: I understand, Sarah. Safety is our priority. We can get you in for our complimentary Courtesy Inspection to check out the brake pads and rotors. We also have a free shuttle if you need a ride back home or to work. Would you like to schedule that?\nSarah: Yes, please. Monday afternoon at 2:00 PM would work best.\nAdvisor: Perfect, we have you set for Wednesday, June 10th at 2:00 PM. See you then!",
                "2026-06-09 10:15:00"
            )
        )
        cursor.execute(
            "INSERT INTO crm_notes (id, call_id, customer_id, summary, transcript, created_at) VALUES (%s, %s, %s, %s, %s, %s);",
            (
                2, 
                "call_david_102", 
                2, 
                "David Smith requested a full synthetic oil change on his 2018 Ford F-150. Service completed on time. Courtesy inspection completed with green status overall.",
                "Advisor: Test, this is John. How can I serve you today?\nDavid: Hi, I need to schedule a full synthetic oil change for my Ford F-150.\nAdvisor: Absolutely, David. We can set that up for you. That will include our full synthetic oil, premium filter, fluid top-off, and our complimentary Courtesy Inspection to check your vehicle's overall health.\nDavid: That sounds great. Do you have anything open today?\nAdvisor: Yes, we have a slot at 4:00 PM.\nDavid: Perfect, see you then.",
                "2026-06-09 09:30:00"
            )
        )
        cursor.execute(
            "INSERT INTO crm_notes (id, call_id, customer_id, summary, transcript, created_at) VALUES (%s, %s, %s, %s, %s, %s);",
            (
                3, 
                "call_emily_103", 
                3, 
                "Emily Davis reported AC blowing warm air on her 2021 Toyota RAV4. Scheduled AC performance test and inspection. Customer will use the free local shuttle service.",
                "Advisor: Thank you for calling Test. This is John.\nEmily: Hi, my RAV4's air conditioner is blowing warm air, and it's really hot today.\nAdvisor: I hear you, Emily. We can run our AC performance test to check the refrigerant levels, scan for codes, and inspect components for leaks. We have an opening at 10:00 AM on Wednesday, June 10th.\nEmily: That works. Will I be able to get a ride to my office?\nAdvisor: Yes, our complimentary shuttle is happy to drop you off and pick you back up when the vehicle is ready.\nEmily: Wonderful, sign me up.",
                "2026-06-09 11:45:00"
            )
        )
        cursor.execute(
            "INSERT INTO crm_notes (id, call_id, customer_id, summary, transcript, created_at) VALUES (%s, %s, %s, %s, %s, %s);",
            (
                4, 
                "call_michael_104", 
                4, 
                "Michael Miller reported Check Engine light is on and engine running rough on 2015 Chevrolet Silverado. Scheduled Engine Diagnostics. Shuttle service coordinated.",
                "Advisor: Test, John speaking. How can I help you?\nMichael: Hi, my Silverado's check engine light is flashing and the engine feels like it is running rough.\nAdvisor: A flashing check engine light indicates a potential misfire, Michael, so we definitely want to check that out as soon as possible. We will perform an Engine Diagnostic scan and physical check. We have an open slot on Thursday at 11:00 AM.\nMichael: That works. I will need the shuttle back to my house.\nAdvisor: Not a problem, we will coordinate that. See you Thursday.",
                "2026-06-09 13:00:00"
            )
        )

        # Insert Staff Agents
        agents = [
            (1, 'John Doe', 'Service Advisor', 'john.doe@example.com'),
            (2, 'Jane Smith', 'Technician', 'jane.smith@example.com'),
            (3, 'Bob Johnson', 'Technician', 'bob.johnson@example.com')
        ]
        cursor.executemany(
            "INSERT INTO staff_agents (id, name, role, email) VALUES (%s, %s, %s, %s);",
            agents
        )
        
        # Insert Mock Calendar Slots dynamically for next 30 days mapped to staff agents
        import datetime
        import random
        
        start_date = datetime.date.today()
        slots = []
        for day_offset in range(30):
            current_day = start_date + datetime.timedelta(days=day_offset)
            if current_day.weekday() < 5:
                for hour in [9, 11, 14, 16]:
                    slot_dt = datetime.datetime.combine(current_day, datetime.time(hour, 0, 0))
                    slot_str = slot_dt.strftime("%Y-%m-%d %H:%M:%S")
                    for agent_id in [1, 2, 3]:
                        is_booked = random.random() < 0.3
                        slots.append((slot_str, is_booked, agent_id))
                        
        cursor.executemany(
            "INSERT INTO mock_calendar_slots (slot_datetime, is_booked, staff_agent_id) VALUES (%s, %s, %s) ON CONFLICT (slot_datetime, staff_agent_id) DO NOTHING;",
            slots
        )
        
        # Reset SERIAL sequences
        for table in ["customers", "vehicles", "service_requests", "crm_notes", "staff_agents", "services"]:
            cursor.execute(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), COALESCE(MAX(id), 1)) FROM {table};")
        
        conn.commit()
        print("Database seeded successfully with Test mock data!")

 
if __name__ == "__main__":
    seed_db()
