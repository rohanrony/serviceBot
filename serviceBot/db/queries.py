from serviceBot.db.connection import get_db_connection

def lookup_customer_by_phone(phone: str) -> dict:
    """
    Looks up a customer by phone number and returns their details,
    including vehicle and active/pending service requests.
    Handles various phone number formats robustly.
    """
    import re
    cleaned_phone = re.sub(r"\D", "", phone) if phone else ""
    if len(cleaned_phone) == 11 and cleaned_phone.startswith("1"):
        cleaned_phone = cleaned_phone[1:]

    query = """
    SELECT 
        c.id AS customer_id,
        c.name,
        c.phone,
        v.id AS vehicle_id,
        v.make,
        v.model,
        v.year,
        sr.id AS open_sr_id,
        sr.service_type AS open_sr_type,
        sr.status AS open_sr_status
    FROM customers c
    LEFT JOIN vehicles v ON c.id = v.customer_id
    LEFT JOIN service_requests sr ON c.id = sr.customer_id AND sr.status = 'pending'
    WHERE c.phone = ? 
       OR c.phone = ? 
       OR REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(c.phone, '-', ''), ' ', ''), '(', ''), ')', ''), '+1', '') = ?;
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, (phone, cleaned_phone, cleaned_phone))
        row = cursor.fetchone()
        if row is None or row['customer_id'] is None:
            return None
        return dict(row)

def create_service_request(customer_id: int, vehicle_details: dict, issue: str, service_type: str = "Repair", time_slot: str = None) -> int:
    """
    Creates a vehicle if it does not exist, and inserts a service request for the customer and vehicle.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # Check if vehicle exists
        cursor.execute(
            "SELECT id FROM vehicles WHERE customer_id = ? AND make = ? AND model = ? AND year = ?;",
            (customer_id, vehicle_details.get("make"), vehicle_details.get("model"), vehicle_details.get("year"))
        )
        row = cursor.fetchone()
        if row:
            vehicle_id = row['id']
        else:
            cursor.execute(
                "INSERT INTO vehicles (customer_id, make, model, year) VALUES (?, ?, ?, ?);",
                (customer_id, vehicle_details.get("make"), vehicle_details.get("model"), vehicle_details.get("year"))
            )
            vehicle_id = cursor.lastrowid
        
        # Insert service request
        cursor.execute(
            "INSERT INTO service_requests (customer_id, vehicle_id, service_type, issue_description, status, time_slot) VALUES (?, ?, ?, ?, ?, ?);",
            (customer_id, vehicle_id, service_type, issue, "pending", time_slot)
        )
        sr_id = cursor.lastrowid
        return sr_id


def _generate_dynamic_slots(preferred_date_str: str, duration_minutes: int) -> list:
    """
    Generates candidate work-hour slots dynamically for the next 14 business days,
    starting from preferred_date_str (or today). Used when mock_calendar_slots is empty.
    Returns a list of ISO datetime strings: YYYY-MM-DD HH:MM:SS.
    """
    import datetime as dt_mod
    
    if preferred_date_str and len(preferred_date_str) >= 10:
        try:
            start_date = dt_mod.date.fromisoformat(preferred_date_str[:10])
        except ValueError:
            start_date = dt_mod.date.today()
    else:
        start_date = dt_mod.date.today()

    # Ensure we don't start from a past date
    today = dt_mod.date.today()
    if start_date < today:
        start_date = today

    # Generate slots for up to 14 business days
    slots = []
    day_offset = 0
    while len(slots) < 60 and day_offset < 30:
        candidate_day = start_date + dt_mod.timedelta(days=day_offset)
        if candidate_day.weekday() < 5:  # Mon-Fri only
            for hour in [9, 11, 14, 16]:
                slot_dt = dt_mod.datetime.combine(candidate_day, dt_mod.time(hour, 0, 0))
                slots.append(slot_dt.strftime("%Y-%m-%d %H:%M:%S"))
        day_offset += 1
    return slots


def check_availability(service_type: str = None, preferred_date: str = None) -> list:
    """
    Checks available appointment slots on or after preferred_date.

    Two-mode operation:
    1. Mock-slot mode: If mock_calendar_slots rows exist, use them as the candidate pool
       and cross-reference connected agents' Google Calendars to filter busy slots.
    2. Live/dynamic mode: If no mock slots exist (e.g. mock data cleared or not seeded),
       and at least one agent has Google Calendar connected, generate candidate business-hour
       slots dynamically and check them against each agent's real Google Calendar.

    Returns up to 3 available slot datetime strings (YYYY-MM-DD HH:MM:SS).
    Always falls back gracefully — if no Google Calendar is connected and no mock slots exist,
    returns an empty list.
    """
    import zoneinfo
    from datetime import datetime, timedelta
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from serviceBot.services.google_calendar import fetch_agent_events, parse_google_datetime

    if not preferred_date:
        start_time = "1970-01-01 00:00:00"
    else:
        if len(preferred_date) == 10:
            start_time = f"{preferred_date} 00:00:00"
        else:
            start_time = preferred_date

    duration_minutes = 60
    if service_type:
        fields = get_service_required_fields(service_type)
        if fields and fields.get("duration_minutes"):
            duration_minutes = fields["duration_minutes"]

    # --- Fetch mock calendar slots ---
    query = """
    SELECT id, slot_datetime, staff_agent_id 
    FROM mock_calendar_slots 
    WHERE is_booked = 0 AND slot_datetime >= ? 
    ORDER BY slot_datetime ASC;
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, (start_time,))
        mock_rows = cursor.fetchall()

    # --- Get all Google Calendar connected agents ---
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT agent_id FROM user_google_accounts WHERE refresh_token IS NOT NULL;")
        connected_agent_ids = [r["agent_id"] for r in cursor.fetchall()]

    tz = zoneinfo.ZoneInfo("America/New_York")
    agent_events_map = {}

    # ===========================================================
    # MODE 1: Mock slot mode — slots exist in mock_calendar_slots
    # ===========================================================
    if mock_rows:
        candidate_rows = mock_rows[:100]

        if connected_agent_ids and candidate_rows:
            slot_dts = [datetime.strptime(r["slot_datetime"], "%Y-%m-%d %H:%M:%S") for r in candidate_rows]
            min_dt = min(slot_dts).replace(tzinfo=tz)
            max_dt = (max(slot_dts) + timedelta(minutes=duration_minutes)).replace(tzinfo=tz)
            start_iso = min_dt.isoformat()
            end_iso = max_dt.isoformat()

            with ThreadPoolExecutor(max_workers=max(1, len(connected_agent_ids))) as executor:
                future_to_agent = {
                    executor.submit(fetch_agent_events, aid, start_iso, end_iso): aid
                    for aid in connected_agent_ids
                }
                for future in as_completed(future_to_agent):
                    aid = future_to_agent[future]
                    try:
                        events = future.result()
                        if events is not None:
                            agent_events_map[aid] = events
                    except Exception as exc:
                        print(f"Error concurrent calendar fetch for agent {aid}: {exc}")
                        agent_events_map[aid] = []

        def is_agent_free_locally(agent_id: int, slot_dt_str: str) -> bool:
            if agent_id not in agent_events_map:
                return True
            slot_start = datetime.strptime(slot_dt_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=tz)
            slot_end = slot_start + timedelta(minutes=duration_minutes)
            for event in agent_events_map[agent_id]:
                evt_start = parse_google_datetime(event.get("start"), tz)
                evt_end = parse_google_datetime(event.get("end"), tz)
                if evt_start and evt_end:
                    if slot_start < evt_end and slot_end > evt_start:
                        return False
            return True

        from collections import defaultdict
        slots_by_time = defaultdict(list)
        for row in candidate_rows:
            slots_by_time[row["slot_datetime"]].append(row["staff_agent_id"])

        unique_datetimes = sorted(list(slots_by_time.keys()))
        available_datetimes = []
        for slot_dt in unique_datetimes:
            if len(available_datetimes) >= 3:
                break
            any_free = any(
                is_agent_free_locally(agent_id, slot_dt)
                for agent_id in slots_by_time[slot_dt]
            )
            if any_free:
                available_datetimes.append(slot_dt)

        return available_datetimes

    # =============================================================
    # MODE 2: Live/dynamic mode — no mock slots, use Google Calendar
    # =============================================================
    if not connected_agent_ids:
        # No mock slots and no connected calendars — nothing to offer
        print("[check_availability] No mock calendar slots and no connected Google Calendars. Returning empty.")
        return []

    print(f"[check_availability] No mock slots found. Falling back to live Google Calendar check for {len(connected_agent_ids)} connected agent(s).")

    preferred_date_for_gen = preferred_date if preferred_date else None
    candidate_slots = _generate_dynamic_slots(preferred_date_for_gen, duration_minutes)

    if not candidate_slots:
        return []

    # Pre-fetch events for all connected agents across the full candidate range
    slot_dts_parsed = [datetime.strptime(s, "%Y-%m-%d %H:%M:%S") for s in candidate_slots]
    min_dt = min(slot_dts_parsed).replace(tzinfo=tz)
    max_dt = (max(slot_dts_parsed) + timedelta(minutes=duration_minutes)).replace(tzinfo=tz)
    start_iso = min_dt.isoformat()
    end_iso = max_dt.isoformat()

    with ThreadPoolExecutor(max_workers=max(1, len(connected_agent_ids))) as executor:
        future_to_agent = {
            executor.submit(fetch_agent_events, aid, start_iso, end_iso): aid
            for aid in connected_agent_ids
        }
        for future in as_completed(future_to_agent):
            aid = future_to_agent[future]
            try:
                events = future.result()
                if events is not None:
                    agent_events_map[aid] = events
            except Exception as exc:
                print(f"Error live calendar fetch for agent {aid}: {exc}")
                agent_events_map[aid] = []

    def is_agent_free_live(agent_id: int, slot_dt_str: str) -> bool:
        """Returns True if agent has no Google Calendar event overlapping the slot."""
        if agent_id not in agent_events_map:
            # Agent connected but fetch failed — treat as free to avoid blocking all slots
            return True
        slot_start = datetime.strptime(slot_dt_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=tz)
        slot_end = slot_start + timedelta(minutes=duration_minutes)
        for event in agent_events_map[agent_id]:
            evt_start = parse_google_datetime(event.get("start"), tz)
            evt_end = parse_google_datetime(event.get("end"), tz)
            if evt_start and evt_end:
                if slot_start < evt_end and slot_end > evt_start:
                    return False
        return True

    available_datetimes = []
    for slot_dt_str in candidate_slots:
        if len(available_datetimes) >= 3:
            break
        # A slot is available if ANY connected agent is free at that time
        any_free = any(is_agent_free_live(aid, slot_dt_str) for aid in connected_agent_ids)
        if any_free:
            available_datetimes.append(slot_dt_str)

    return available_datetimes


def validate_booking_time(booking_time: str) -> bool:
    """
    Validates that a booking datetime or time slot string is within company workhours.
    Company workhours: Monday to Friday, 7:00 AM to 6:00 PM (Eastern Time).
    If booking_time is 'ASAP', it is always valid.
    """
    if not booking_time:
        return False
    
    cleaned = booking_time.strip()
    if cleaned.upper() == "ASAP":
        return True
        
    import re
    from datetime import datetime
    
    # Try parsing standard YYYY-MM-DD HH:MM:SS format
    dt = None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M"):
        try:
            dt = datetime.strptime(cleaned, fmt)
            break
        except ValueError:
            continue
            
    if not dt:
        # If we can't parse it as a standard datetime, let's check for loose format (e.g. HH:MM AM/PM)
        match = re.search(r"(\d{1,2}):(\d{2})\s*(AM|PM)?", cleaned, re.IGNORECASE)
        if match:
            hour = int(match.group(1))
            minute = int(match.group(2))
            ampm = match.group(3)
            if ampm:
                if ampm.upper() == "PM" and hour < 12:
                    hour += 12
                elif ampm.upper() == "AM" and hour == 12:
                    hour = 0
            # Try to see if there is a date
            date_match = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", cleaned)
            if date_match:
                try:
                    year, month, day = map(int, date_match.groups())
                    dt = datetime(year, month, day, hour, minute)
                except Exception:
                    pass
            else:
                if hour < 7 or hour >= 18:
                    return False
                return True
        else:
            return True
            
    if dt:
        # Check weekday: 0 = Monday, 4 = Friday. Weekend is weekday > 4
        if dt.weekday() > 4:
            return False
        # Check hour: 7:00 AM to 6:00 PM (hour must be between 7 and 17 inclusive)
        if dt.hour < 7 or dt.hour >= 18:
            return False
            
    return True


def book_appointment(customer_id: int, service_request_id: int, appointment_datetime: str, service_type: str) -> int:
    """
    Books an appointment and sets staff_agent_id.

    Two-mode operation:
    1. Mock-slot mode: If a matching mock_calendar_slots row exists, marks it as booked
       and (if the agent has Google Calendar connected) also creates a calendar event.
    2. Live/dynamic mode: If no mock slot row exists (mock data cleared), picks any
       connected agent who is free on Google Calendar at that time, creates the calendar
       event directly, and records the booking in service_requests only.

    Raises ValueError if no suitable agent/slot is available.
    """
    # 1. Enforce that the service requested is in the services catalog
    fields = get_service_required_fields(service_type)
    if not fields:
        raise ValueError(f"Service '{service_type}' is not found in our catalog. Please choose a valid service from the catalog.")
    
    # 2. Enforce customer and vehicle mandatory checks
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # Check customer name
        cursor.execute("SELECT name, phone FROM customers WHERE id = ?;", (customer_id,))
        cust = cursor.fetchone()
        if not cust:
            raise ValueError("Customer record not found.")
        if not cust["name"] or cust["name"] == "Unknown Customer" or cust["name"].strip() == "":
            raise ValueError("Customer name is required. Please collect the customer's name before booking.")
        if not cust["phone"] or cust["phone"] == "Unknown" or len(cust["phone"].strip()) < 10:
            raise ValueError("Customer phone number is required and must be a valid 10-digit number.")
            
        # Check vehicle details
        cursor.execute("SELECT make, model, year FROM vehicles WHERE customer_id = ? ORDER BY id DESC LIMIT 1;", (customer_id,))
        vehicle = cursor.fetchone()
        if not vehicle or not vehicle["make"] or vehicle["make"] == "Unknown" or vehicle["make"].strip() == "" or not vehicle["model"] or vehicle["model"] == "Unknown" or vehicle["model"].strip() == "":
            raise ValueError("Vehicle year, make, and model are required. Please collect the vehicle details before booking.")

    if not validate_booking_time(appointment_datetime):
        raise ValueError(f"Booking time {appointment_datetime} is outside company workhours (Monday to Friday, 7:00 AM to 6:00 PM).")

    from serviceBot.services.google_calendar import is_agent_free, create_agent_calendar_event

    duration_minutes = fields.get("duration_minutes") or 60

    with get_db_connection() as conn:
        conn.execute("BEGIN IMMEDIATE;")
        cursor = conn.cursor()

        # --- Try mock-slot mode first ---
        cursor.execute(
            "SELECT id, staff_agent_id FROM mock_calendar_slots WHERE slot_datetime = ? AND is_booked = 0;",
            (appointment_datetime,)
        )
        candidate_rows = cursor.fetchall()

        chosen_slot = None
        chosen_agent_id = None

        if candidate_rows:
            # Mock-slot mode: find a free agent from the mock slots
            for row in candidate_rows:
                if is_agent_free(row["staff_agent_id"], appointment_datetime, duration_minutes):
                    chosen_slot = row
                    chosen_agent_id = row["staff_agent_id"]
                    break

            if not chosen_slot:
                raise ValueError(f"Slot {appointment_datetime} is already booked or all agents are busy on Google Calendar.")

            # Mark mock slot as booked
            cursor.execute(
                "UPDATE mock_calendar_slots SET is_booked = 1 WHERE id = ?;",
                (chosen_slot["id"],)
            )
        else:
            # --- Live/dynamic mode: no mock slot row, use connected Google Calendar agents ---
            cursor.execute("SELECT agent_id FROM user_google_accounts WHERE refresh_token IS NOT NULL;")
            connected_ids = [r["agent_id"] for r in cursor.fetchall()]

            if not connected_ids:
                raise ValueError(
                    f"No available slot at {appointment_datetime} and no agents have Google Calendar connected. "
                    "Please seed mock calendar data or connect an agent's Google Calendar."
                )

            # Pick first agent who is free at the requested time
            for aid in connected_ids:
                if is_agent_free(aid, appointment_datetime, duration_minutes):
                    chosen_agent_id = aid
                    break

            if not chosen_agent_id:
                raise ValueError(f"All connected agents are busy at {appointment_datetime} on Google Calendar.")

            print(f"[book_appointment] Live mode: booking with agent {chosen_agent_id} at {appointment_datetime} (no mock slot row).")

        # --- Resolve / create service_request ---
        if not service_request_id:
            cursor.execute(
                "SELECT id FROM service_requests WHERE customer_id = ? AND status = 'pending' AND booking_type IS NULL ORDER BY id DESC LIMIT 1;",
                (customer_id,)
            )
            sr_row = cursor.fetchone()
            if sr_row:
                service_request_id = sr_row["id"]
            else:
                cursor.execute("SELECT id FROM vehicles WHERE customer_id = ? ORDER BY id DESC LIMIT 1;", (customer_id,))
                v_row = cursor.fetchone()
                vehicle_id = v_row["id"] if v_row else None
                if not vehicle_id:
                    cursor.execute("INSERT INTO vehicles (customer_id, make, model, year) VALUES (?, 'Unknown', 'Unknown', 2000);", (customer_id,))
                    vehicle_id = cursor.lastrowid

                cursor.execute(
                    "INSERT INTO service_requests (customer_id, vehicle_id, service_type, issue_description, status) VALUES (?, ?, ?, 'Appointment booking.', 'pending');",
                    (customer_id, vehicle_id, service_type)
                )
                service_request_id = cursor.lastrowid

        cursor.execute(
            "UPDATE service_requests SET booking_type = 'appointment', booking_time = ?, service_type = ?, staff_agent_id = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?;",
            (appointment_datetime, service_type, chosen_agent_id, service_request_id)
        )

        # Get customer info and issue details for Google Calendar event
        cursor.execute("SELECT name FROM customers WHERE id = ?;", (customer_id,))
        cust_row = cursor.fetchone()
        customer_name = cust_row["name"] if cust_row else "Unknown Customer"

        cursor.execute("SELECT issue_description FROM service_requests WHERE id = ?;", (service_request_id,))
        sr_desc_row = cursor.fetchone()
        issue_desc = sr_desc_row["issue_description"] if sr_desc_row else ""

        # Create Google Calendar event for the assigned agent (works in both modes)
        create_agent_calendar_event(
            agent_id=chosen_agent_id,
            customer_name=customer_name,
            service_type=service_type,
            issue_description=issue_desc,
            slot_datetime_str=appointment_datetime,
            duration_minutes=duration_minutes
        )

        return service_request_id


def get_service_required_fields(service_name: str) -> dict:
    """
    Looks up a service by name (case-insensitive) in the services table
    and returns its details along with the required fields mapping.
    """
    query = """
    SELECT name, description, price_range, duration_minutes,
           req_customer_name, req_phone_number, req_vehicle_details, req_issue_description, req_location
    FROM services
    WHERE LOWER(name) = ?;
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, (service_name.lower().strip(),))
        row = cursor.fetchone()
        if not row:
            return None
        return dict(row)

def create_crm_note(call_id: str, customer_id: int, summary: str, transcript: str) -> int:
    """
    Inserts a new CRM note (call summary and transcript) for a customer call.
    """
    query = """
    INSERT INTO crm_notes (call_id, customer_id, summary, transcript)
    VALUES (?, ?, ?, ?);
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, (call_id, customer_id, summary, transcript))
        conn.commit()
        return cursor.lastrowid


def create_callback_request(customer_id: int, service_request_id: int = None, preferred_time: str = None) -> int:
    """
    Inserts a callback request by updating the service_requests table.
    """
    # Enforce customer name, phone, and vehicle checks on the database/CRM request level
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # Check customer name
        cursor.execute("SELECT name, phone FROM customers WHERE id = ?;", (customer_id,))
        cust = cursor.fetchone()
        if not cust:
            raise ValueError("Customer record not found.")
        if not cust["name"] or cust["name"] == "Unknown Customer" or cust["name"].strip() == "":
            raise ValueError("Customer name is required. Please collect the customer's name before arranging a callback.")
        if not cust["phone"] or cust["phone"] == "Unknown" or len(cust["phone"].strip()) < 10:
            raise ValueError("Customer phone number is required and must be a valid 10-digit number.")
            
        # Check vehicle details
        cursor.execute("SELECT make, model, year FROM vehicles WHERE customer_id = ? ORDER BY id DESC LIMIT 1;", (customer_id,))
        vehicle = cursor.fetchone()
        if not vehicle or not vehicle["make"] or vehicle["make"] == "Unknown" or vehicle["make"].strip() == "" or not vehicle["model"] or vehicle["model"] == "Unknown" or vehicle["model"].strip() == "":
            raise ValueError("Vehicle year, make, and model are required. Please collect the vehicle details before arranging a callback.")

    if preferred_time and not validate_booking_time(preferred_time):
        raise ValueError(f"Callback preferred time {preferred_time} is outside company workhours (Monday to Friday, 7:00 AM to 6:00 PM).")
        
    cleaned_time = preferred_time
    if preferred_time:
        pref_lower = preferred_time.strip().lower()
        if "asap" in pref_lower or "as soon as possible" in pref_lower or "immediately" in pref_lower:
            cleaned_time = "ASAP"
            
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # If no service_request_id, find the last open raw intake one or create a new one
        if not service_request_id:
            cursor.execute(
                "SELECT id FROM service_requests WHERE customer_id = ? AND status = 'pending' AND booking_type IS NULL ORDER BY id DESC LIMIT 1;",
                (customer_id,)
            )
            sr_row = cursor.fetchone()
            if sr_row:
                service_request_id = sr_row["id"]
            else:
                cursor.execute("SELECT id FROM vehicles WHERE customer_id = ? ORDER BY id DESC LIMIT 1;", (customer_id,))
                v_row = cursor.fetchone()
                vehicle_id = v_row["id"] if v_row else None
                if not vehicle_id:
                    cursor.execute("INSERT INTO vehicles (customer_id, make, model, year) VALUES (?, 'Unknown', 'Unknown', 2000);", (customer_id,))
                    vehicle_id = cursor.lastrowid
                
                cursor.execute(
                    "INSERT INTO service_requests (customer_id, vehicle_id, service_type, issue_description, status) VALUES (?, ?, 'Repair', 'Callback requested.', 'pending');",
                    (customer_id, vehicle_id)
                )
                service_request_id = cursor.lastrowid
                
        # Select a staff agent to assign the callback to (default to John Doe/ID 1 or the first agent)
        cursor.execute("SELECT id FROM staff_agents ORDER BY id ASC LIMIT 1;")
        agent_row = cursor.fetchone()
        staff_agent_id = agent_row["id"] if agent_row else None

        cursor.execute(
            "UPDATE service_requests SET booking_type = 'callback', booking_time = ?, staff_agent_id = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?;",
            (cleaned_time, staff_agent_id, service_request_id)
        )
        conn.commit()
        return service_request_id


def get_customer_appointments(phone: str) -> list:
    """
    Looks up all scheduled/rescheduled appointments for a customer by phone number.
    """
    import re
    cleaned_phone = re.sub(r"\D", "", phone) if phone else ""
    if len(cleaned_phone) == 11 and cleaned_phone.startswith("1"):
        cleaned_phone = cleaned_phone[1:]

    query = """
    SELECT sr.id, sr.booking_time AS appointment_datetime, sr.service_type, sr.status 
    FROM service_requests sr
    JOIN customers c ON sr.customer_id = c.id
    WHERE (c.phone = ? OR REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(c.phone, '-', ''), ' ', ''), '(', ''), ')', ''), '+1', '') = ?)
      AND sr.booking_type = 'appointment'
      AND sr.status IN ('pending', 'in_progress')
    ORDER BY sr.booking_time DESC;
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, (phone, cleaned_phone))
        rows = cursor.fetchall()
        return [dict(row) for row in rows]


def reschedule_appointment(appointment_id: int, new_datetime: str) -> bool:
    """
    Reschedules an appointment: frees the old slot, books the new slot, and updates the appointment.
    All inside a single transaction. Checks Google Calendar availability of candidate agents.
    """
    if not validate_booking_time(new_datetime):
        raise ValueError(f"New booking time {new_datetime} is outside company workhours (Monday to Friday, 7:00 AM to 6:00 PM).")
        
    with get_db_connection() as conn:
        conn.execute("BEGIN IMMEDIATE;")
        cursor = conn.cursor()

        # 1. Get old appointment details
        cursor.execute(
            "SELECT booking_time, staff_agent_id, service_type, customer_id FROM service_requests WHERE id = ? AND booking_type = 'appointment';",
            (appointment_id,)
        )
        row = cursor.fetchone()
        if not row:
            raise ValueError(f"Appointment (Service Request) with ID {appointment_id} not found.")
        old_datetime = row["booking_time"]
        old_agent_id = row["staff_agent_id"]
        service_type = row["service_type"]
        customer_id = row["customer_id"]

        # 2. Free old slot
        if old_agent_id:
            cursor.execute(
                "UPDATE mock_calendar_slots SET is_booked = 0 WHERE slot_datetime = ? AND staff_agent_id = ?;",
                (old_datetime, old_agent_id)
            )
        else:
            cursor.execute(
                "UPDATE mock_calendar_slots SET is_booked = 0 WHERE slot_datetime = ?;",
                (old_datetime,)
            )

        # 3. Check availability for the slot datetime across all candidate slots
        cursor.execute(
            "SELECT id, staff_agent_id FROM mock_calendar_slots WHERE slot_datetime = ? AND is_booked = 0;",
            (new_datetime,)
        )
        candidate_rows = cursor.fetchall()
        
        from serviceBot.services.google_calendar import is_agent_free, create_agent_calendar_event
        
        duration_minutes = 60
        if service_type:
            fields = get_service_required_fields(service_type)
            if fields and fields.get("duration_minutes"):
                duration_minutes = fields["duration_minutes"]

        chosen_slot = None
        chosen_agent_id = None

        if candidate_rows:
            for r in candidate_rows:
                if is_agent_free(r["staff_agent_id"], new_datetime, duration_minutes):
                    chosen_slot = r
                    chosen_agent_id = r["staff_agent_id"]
                    break
        else:
            # Live/dynamic mode
            cursor.execute("SELECT agent_id FROM user_google_accounts WHERE refresh_token IS NOT NULL;")
            connected_ids = [r["agent_id"] for r in cursor.fetchall()]
            for aid in connected_ids:
                if is_agent_free(aid, new_datetime, duration_minutes):
                    chosen_agent_id = aid
                    break
                
        if not chosen_slot and not chosen_agent_id:
            raise ValueError(f"New slot {new_datetime} is not available or the agents are busy on Google Calendar.")
            
        if chosen_slot:
            cursor.execute(
                "UPDATE mock_calendar_slots SET is_booked = 1 WHERE id = ?;",
                (chosen_slot["id"],)
            )

        # 4. Update service request
        cursor.execute(
            "UPDATE service_requests SET booking_time = ?, staff_agent_id = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?;",
            (new_datetime, chosen_agent_id, appointment_id)
        )
        
        # Get customer details for calendar event
        cursor.execute("SELECT name FROM customers WHERE id = ?;", (customer_id,))
        cust_row = cursor.fetchone()
        customer_name = cust_row["name"] if cust_row else "Unknown Customer"
        
        cursor.execute("SELECT issue_description FROM service_requests WHERE id = ?;", (appointment_id,))
        sr_desc_row = cursor.fetchone()
        issue_desc = sr_desc_row["issue_description"] if sr_desc_row else ""
        
        # Insert event into the new agent's Google Calendar if connected
        create_agent_calendar_event(
            agent_id=chosen_agent_id,
            customer_name=customer_name,
            service_type=service_type,
            issue_description=issue_desc,
            slot_datetime_str=new_datetime,
            duration_minutes=duration_minutes
        )
        
        return True
