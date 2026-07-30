from serviceBot.db.connection import get_db_connection, dict_cursor
from serviceBot.logger import get_logger, log_execution
import datetime as dt_mod
from datetime import timedelta

logger = get_logger("db.queries")


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
    WHERE c.phone = %s 
       OR c.phone = %s 
       OR REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(c.phone, '-', ''), ' ', ''), '(', ''), ')', ''), '+1', '') = %s
    ORDER BY sr.id DESC LIMIT 1;
    """
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(query, (phone, cleaned_phone, cleaned_phone))
            row = cursor.fetchone()
            if row is None or row['customer_id'] is None:
                return None
            return dict(row)


def update_customer_name(customer_id: int, new_name: str) -> bool:
    """Updates customer's name if a valid new name is provided."""
    if not customer_id or not new_name or new_name in ("Unknown Customer", "Unknown"):
        return False
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("UPDATE customers SET name = %s WHERE id = %s;", (new_name, customer_id))
            conn.commit()
            return cursor.rowcount > 0


def create_service_request(
    customer_id: int,
    vehicle_details: dict,
    issue: str,
    service_type: str = "Repair",
    time_slot: str = None,
    booking_type: str = None,
    booking_time: str = None,
    staff_agent_id: int = None
) -> int:
    """
    Creates a vehicle if it does not exist, and inserts a service request for the customer and vehicle.
    Supports booking_type ('appointment' or 'callback') and booking_time.
    If booking_type is 'appointment' and a matching mock_calendar_slot exists, marks the slot as booked.
    """
    # Try fuzzy catalog matching for service type
    fields = get_service_required_fields(service_type)
    matched_service_name = fields["name"] if fields else service_type

    if not booking_time and time_slot:
        booking_time = time_slot

    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            # Check if vehicle exists
            cursor.execute(
                "SELECT id FROM vehicles WHERE customer_id = %s AND make = %s AND model = %s AND year = %s;",
                (customer_id, vehicle_details.get("make"), vehicle_details.get("model"), vehicle_details.get("year"))
            )
            row = cursor.fetchone()
            if row:
                vehicle_id = row['id']
            else:
                cursor.execute(
                    "INSERT INTO vehicles (customer_id, make, model, year) VALUES (%s, %s, %s, %s) RETURNING id;",
                    (customer_id, vehicle_details.get("make"), vehicle_details.get("model"), vehicle_details.get("year"))
                )
                vehicle_id = cursor.fetchone()['id']
            
            # If staff_agent_id is not specified, assign default staff agent if available
            if not staff_agent_id:
                cursor.execute("SELECT id FROM staff_agents ORDER BY id ASC LIMIT 1;")
                sa_row = cursor.fetchone()
                if sa_row:
                    staff_agent_id = sa_row["id"]

            # Insert service request with booking_type and booking_time
            cursor.execute(
                """
                INSERT INTO service_requests 
                (customer_id, vehicle_id, service_type, issue_description, status, time_slot, booking_type, booking_time, staff_agent_id) 
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id;
                """,
                (customer_id, vehicle_id, matched_service_name, issue, "pending", time_slot, booking_type, booking_time, staff_agent_id)
            )
            sr_id = cursor.fetchone()['id']

            # If booked as appointment, attempt to mark mock calendar slots as booked for full duration
            if booking_type == "appointment" and booking_time:
                try:
                    duration_minutes = fields.get("duration_minutes") or 60 if fields else 60
                    b_start = dt_mod.datetime.strptime(booking_time, "%Y-%m-%d %H:%M:%S") if isinstance(booking_time, str) else booking_time
                    b_end = b_start + dt_mod.timedelta(minutes=duration_minutes)
                    cursor.execute(
                        """
                        UPDATE mock_calendar_slots 
                        SET is_booked = TRUE 
                        WHERE slot_datetime >= CAST(%s AS TIMESTAMP) 
                          AND slot_datetime < CAST(%s AS TIMESTAMP);
                        """,
                        (b_start.strftime("%Y-%m-%d %H:%M:%S"), b_end.strftime("%Y-%m-%d %H:%M:%S"))
                    )
                except Exception as slot_err:
                    logger.warning(f"Could not update mock_calendar_slots: {slot_err}")

            return sr_id


def _generate_dynamic_slots(preferred_date_str: str, duration_minutes: int) -> list:
    """
    Generates candidate work-hour slots dynamically for the next 14 business days,
    starting from preferred_date_str (or today). Used when mock_calendar_slots is empty.
    Returns a list of ISO datetime strings: YYYY-MM-DD HH:MM:SS.
    """
    import datetime as dt_mod
    from serviceBot.services.calendar_sync import get_configured_business_hours, get_configured_business_days
    
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
    now_dt = dt_mod.datetime.now()
    valid_hours = get_configured_business_hours()
    valid_days = get_configured_business_days()
    while len(slots) < 60 and day_offset < 30:
        candidate_day = start_date + dt_mod.timedelta(days=day_offset)
        if candidate_day.weekday() in valid_days:  # Configured operating days
            for hour in valid_hours:
                slot_dt = dt_mod.datetime.combine(candidate_day, dt_mod.time(hour, 0, 0))
                if slot_dt > now_dt:
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
    import datetime as dt_mod
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
    SELECT id, slot_datetime, staff_agent_id, is_booked 
    FROM mock_calendar_slots 
    WHERE slot_datetime >= CAST(%s AS TIMESTAMP)
    ORDER BY slot_datetime ASC;
    """
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(query, (start_time,))
            mock_rows = cursor.fetchall()

    # Filter out past slots relative to current system time
    now_dt = dt_mod.datetime.now()
    all_agent_slots = {}
    candidate_rows = []
    if mock_rows:
        for r in mock_rows:
            val = r["slot_datetime"]
            dt_val = dt_mod.datetime.strptime(val, "%Y-%m-%d %H:%M:%S") if isinstance(val, str) else val
            all_agent_slots[(r["staff_agent_id"], dt_val)] = r["is_booked"]
            if dt_val > now_dt and not r["is_booked"]:
                candidate_rows.append(r)


    # --- Get all Google Calendar connected agents ---
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("SELECT agent_id FROM user_google_accounts WHERE refresh_token IS NOT NULL;")
            connected_agent_ids = [r["agent_id"] for r in cursor.fetchall()]

    try:
        tz = zoneinfo.ZoneInfo("America/New_York")
    except Exception:
        from datetime import timezone, timedelta
        tz = timezone(timedelta(hours=-4))
    agent_events_map = {}

    # ===========================================================
    # MODE 1: Mock slot mode — slots exist in mock_calendar_slots
    # ===========================================================
    if mock_rows:
        limited_rows = candidate_rows[:100]

        if connected_agent_ids and limited_rows:
            slot_dts = []
            for r in limited_rows:
                val = r["slot_datetime"]
                if isinstance(val, str):
                    slot_dts.append(datetime.strptime(val, "%Y-%m-%d %H:%M:%S"))
                else:
                    slot_dts.append(val)

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

        def is_agent_free_locally(agent_id: int, slot_dt_val) -> bool:
            if isinstance(slot_dt_val, str):
                slot_start = datetime.strptime(slot_dt_val, "%Y-%m-%d %H:%M:%S").replace(tzinfo=tz)
            else:
                slot_start = slot_dt_val.replace(tzinfo=tz)
            slot_end = slot_start + timedelta(minutes=duration_minutes)
            
            # 1. Google Calendar event overlap check
            if agent_id in agent_events_map:
                for event in agent_events_map[agent_id]:
                    evt_start = parse_google_datetime(event.get("start"), tz)
                    evt_end = parse_google_datetime(event.get("end"), tz)
                    if evt_start and evt_end:
                        if slot_start < evt_end and slot_end > evt_start:
                            return False

            # 2. DB mock slots overlap check for aggregate duration [slot_start, slot_end)
            raw_start = slot_start.replace(tzinfo=None)
            raw_end = slot_end.replace(tzinfo=None)
            for (aid, dt_k), is_booked in all_agent_slots.items():
                if aid == agent_id and raw_start <= dt_k < raw_end:
                    if is_booked:
                        return False

            return True

        from collections import defaultdict
        slots_by_time = defaultdict(list)
        for row in limited_rows:
            dt_val = row["slot_datetime"]
            dt_obj = dt_mod.datetime.strptime(dt_val, "%Y-%m-%d %H:%M:%S") if isinstance(dt_val, str) else dt_val
            dt_str = dt_obj.strftime("%Y-%m-%d %H:%M:%S")
            slots_by_time[dt_str].append((row["staff_agent_id"], dt_obj))

        unique_datetimes = sorted(list(slots_by_time.keys()))
        available_datetimes = []
        for slot_dt_str in unique_datetimes:
            if len(available_datetimes) >= 3:
                break
            any_free = any(
                is_agent_free_locally(agent_id, dt_val)
                for agent_id, dt_val in slots_by_time[slot_dt_str]
            )
            if any_free:
                available_datetimes.append(slot_dt_str)

        return available_datetimes

    # =============================================================
    # MODE 2: Live/dynamic mode — no mock slots, use Google Calendar
    # =============================================================
    if not connected_agent_ids:
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
        any_free = any(is_agent_free_live(aid, slot_dt_str) for aid in connected_agent_ids)
        if any_free:
            available_datetimes.append(slot_dt_str)

    return available_datetimes


def validate_booking_time(booking_time: str) -> bool:
    """
    Validates that a booking datetime or time slot string is within configured business workhours.
    If booking_time is 'ASAP', it is always valid.
    """
    if not booking_time:
        return False
    
    cleaned = booking_time.strip()
    if cleaned.upper() == "ASAP":
        return True
        
    import re
    from datetime import datetime
    from serviceBot.services.calendar_sync import get_configured_business_hours, get_configured_business_days
    
    valid_hours = get_configured_business_hours()
    valid_days = get_configured_business_days()
    
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
                if hour not in valid_hours:
                    return False
                return True
        else:
            return True
            
    if dt:
        # Check weekday against configured operating business days (0=Mon, 6=Sun)
        if dt.weekday() not in valid_days:
            return False
        # Check hour against configured business hours
        if dt.hour not in valid_hours:
            return False
            
    return True


def book_appointment(customer_id: int, service_request_id: int, appointment_datetime: str, service_type: str, vehicle_details: dict = None) -> int:
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
        matched_service_name = service_type if service_type else "Repair"
    else:
        matched_service_name = fields["name"]
    
    # 2. Enforce customer and vehicle mandatory checks
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            # Check customer name
            cursor.execute("SELECT name, phone FROM customers WHERE id = %s;", (customer_id,))
            cust = cursor.fetchone()
            if not cust:
                raise ValueError("Customer record not found.")
            if not cust["name"] or cust["name"] == "Unknown Customer" or cust["name"].strip() == "":
                raise ValueError("Customer name is required. Please collect the customer's name before booking.")
            if not cust["phone"] or cust["phone"] == "Unknown" or len(cust["phone"].strip()) < 10:
                raise ValueError("Customer phone number is required and must be a valid 10-digit number.")
                
            # Resolve vehicle details
            vehicle_id = None
            if vehicle_details and vehicle_details.get("make") and vehicle_details.get("make") != "Unknown":
                cursor.execute(
                    "SELECT id, make, model FROM vehicles WHERE customer_id = %s AND make = %s AND model = %s AND year = %s;",
                    (customer_id, vehicle_details.get("make"), vehicle_details.get("model"), vehicle_details.get("year"))
                )
                v_row = cursor.fetchone()
                if v_row:
                    vehicle_id = v_row["id"]
                else:
                    cursor.execute(
                        "INSERT INTO vehicles (customer_id, make, model, year) VALUES (%s, %s, %s, %s) RETURNING id;",
                        (customer_id, vehicle_details.get("make"), vehicle_details.get("model"), vehicle_details.get("year"))
                    )
                    vehicle_id = cursor.fetchone()["id"]
            
            if not vehicle_id:
                cursor.execute("SELECT id FROM vehicles WHERE customer_id = %s ORDER BY id DESC LIMIT 1;", (customer_id,))
                v_row = cursor.fetchone()
                vehicle_id = v_row["id"] if v_row else None
                if not vehicle_id:
                    cursor.execute("INSERT INTO vehicles (customer_id, make, model, year) VALUES (%s, 'Unknown', 'Unknown', 2000) RETURNING id;", (customer_id,))
                    vehicle_id = cursor.fetchone()["id"]
                    
            # Fetch the resolved vehicle details for validation
            cursor.execute("SELECT make, model FROM vehicles WHERE id = %s;", (vehicle_id,))
            vehicle = cursor.fetchone()
            if not vehicle or not vehicle["make"] or vehicle["make"] == "Unknown" or vehicle["make"].strip() == "" or not vehicle["model"] or vehicle["model"] == "Unknown" or vehicle["model"].strip() == "":
                raise ValueError("Vehicle year, make, and model are required. Please collect the vehicle details before booking.")

            # Sanity check: check if the customer already has an appointment booked for the same vehicle at this slot
            cursor.execute(
                "SELECT id, service_type, issue_description FROM service_requests WHERE customer_id = %s AND vehicle_id = %s AND booking_type = 'appointment' AND booking_time = %s AND status IN ('pending', 'in_progress');",
                (customer_id, vehicle_id, appointment_datetime)
            )
            existing_appt = cursor.fetchone()
            if existing_appt:
                existing_id = existing_appt["id"]
                curr_service = existing_appt.get("service_type") or ""
                if matched_service_name and matched_service_name not in curr_service:
                    new_service_type = f"{curr_service}, {matched_service_name}".strip(", ")
                    cursor.execute(
                        "UPDATE service_requests SET service_type = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s;",
                        (new_service_type, existing_id)
                    )
                    conn.commit()
                return existing_id

    if not validate_booking_time(appointment_datetime):
        raise ValueError(f"Booking time {appointment_datetime} is outside company workhours (Monday to Friday, 7:00 AM to 6:00 PM).")

    from serviceBot.services.google_calendar import is_agent_free, create_agent_calendar_event

    duration_minutes = fields.get("duration_minutes") or 60

    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            # --- Try mock-slot mode first ---
            cursor.execute(
                "SELECT id, slot_datetime, staff_agent_id, is_booked FROM mock_calendar_slots WHERE slot_datetime >= CAST(%s AS TIMESTAMP);",
                (appointment_datetime,)
            )
            all_mock_rows = cursor.fetchall()

            all_agent_slots = {}
            candidate_rows = []
            for r in all_mock_rows:
                val = r["slot_datetime"]
                dt_val = dt_mod.datetime.strptime(val, "%Y-%m-%d %H:%M:%S") if isinstance(val, str) else val
                dt_str = dt_val.strftime("%Y-%m-%d %H:%M:%S")
                all_agent_slots[(r["staff_agent_id"], dt_val)] = r["is_booked"]
                if dt_str == appointment_datetime and not r["is_booked"]:
                    candidate_rows.append(r)

            chosen_slot = None
            chosen_agent_id = None

            if candidate_rows:
                start_dt = dt_mod.datetime.strptime(appointment_datetime, "%Y-%m-%d %H:%M:%S") if isinstance(appointment_datetime, str) else appointment_datetime
                end_dt = start_dt + timedelta(minutes=duration_minutes)

                for row in candidate_rows:
                    aid = row["staff_agent_id"]
                    if not is_agent_free(aid, appointment_datetime, duration_minutes):
                        continue
                    
                    is_free_in_db = True
                    for (slot_aid, dt_k), is_booked in all_agent_slots.items():
                        if slot_aid == aid and start_dt <= dt_k < end_dt:
                            if is_booked:
                                is_free_in_db = False
                                break
                    if is_free_in_db:
                        chosen_slot = row
                        chosen_agent_id = aid
                        break

                if not chosen_slot:
                    raise ValueError(f"Slot {appointment_datetime} is already booked or all agents are busy on Google Calendar.")

                # Mark all mock slots in the aggregate duration window as booked
                cursor.execute(
                    """
                    UPDATE mock_calendar_slots 
                    SET is_booked = TRUE 
                    WHERE staff_agent_id = %s 
                      AND slot_datetime >= CAST(%s AS TIMESTAMP) 
                      AND slot_datetime < CAST(%s AS TIMESTAMP);
                    """,
                    (chosen_agent_id, start_dt.strftime("%Y-%m-%d %H:%M:%S"), end_dt.strftime("%Y-%m-%d %H:%M:%S"))
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
            # If service_request_id is provided, verify it is not already booked
            if service_request_id:
                cursor.execute(
                    "SELECT id, booking_type FROM service_requests WHERE id = %s AND customer_id = %s;",
                    (service_request_id, customer_id)
                )
                sr_row = cursor.fetchone()
                if not sr_row or sr_row["booking_type"] is not None:
                    service_request_id = None

            if not service_request_id:
                cursor.execute(
                    "SELECT id FROM service_requests WHERE customer_id = %s AND vehicle_id = %s AND status = 'pending' AND booking_type IS NULL ORDER BY id DESC LIMIT 1;",
                    (customer_id, vehicle_id)
                )
                sr_row = cursor.fetchone()
                if sr_row:
                    service_request_id = sr_row["id"]
                else:
                    cursor.execute(
                        "INSERT INTO service_requests (customer_id, vehicle_id, service_type, issue_description, status) VALUES (%s, %s, %s, 'Appointment booking.', 'pending') RETURNING id;",
                        (customer_id, vehicle_id, matched_service_name)
                    )
                    service_request_id = cursor.fetchone()["id"]

            cursor.execute(
                "UPDATE service_requests SET booking_type = 'appointment', booking_time = %s, service_type = %s, staff_agent_id = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s;",
                (appointment_datetime, matched_service_name, chosen_agent_id, service_request_id)
            )

            # Get customer info and issue details for Google Calendar event
            cursor.execute("SELECT name FROM customers WHERE id = %s;", (customer_id,))
            cust_row = cursor.fetchone()
            customer_name = cust_row["name"] if cust_row else "Unknown Customer"

            cursor.execute("SELECT issue_description FROM service_requests WHERE id = %s;", (service_request_id,))
            sr_desc_row = cursor.fetchone()
            issue_desc = sr_desc_row["issue_description"] if sr_desc_row else ""

            # Create Google Calendar event for the assigned agent (works in both modes)
            create_agent_calendar_event(
                agent_id=chosen_agent_id,
                customer_name=customer_name,
                service_type=matched_service_name,
                issue_description=issue_desc,
                slot_datetime_str=appointment_datetime,
                duration_minutes=duration_minutes
            )

            # Create Admin Google Calendar event
            try:
                cursor.execute("SELECT name FROM staff_agents WHERE id = %s;", (chosen_agent_id,))
                sa_row = cursor.fetchone()
                mech_name = sa_row["name"] if sa_row else f"Agent {chosen_agent_id}"

                from serviceBot.services.gmail import create_admin_calendar_event
                create_admin_calendar_event(
                    customer_name=customer_name,
                    service_type=matched_service_name,
                    issue_description=issue_desc,
                    slot_datetime_str=appointment_datetime,
                    mechanic_name=mech_name,
                    duration_minutes=duration_minutes
                )
            except Exception as admin_cal_err:
                print(f"Error creating admin calendar event: {admin_cal_err}")

            return service_request_id


def find_best_service_match(query_name: str, services_list: list) -> dict:
    """
    Finds the best matching service from a list of services.
    Cleans strings, tokenizes, checks exact match, checks substrings,
    and calculates Jaccard similarity.
    """
    import re
    def clean_str(s: str) -> str:
        return re.sub(r'[^a-z0-9\s]', '', s.lower()).strip()

    cleaned_query = clean_str(query_name)
    if not cleaned_query:
        return None

    # First check for exact match
    for s in services_list:
        if cleaned_query == clean_str(s["name"]):
            return s

    # Check if the query matches MULTIPLE distinct services in the catalog
    matching_services = []
    for s in services_list:
        db_name_clean = clean_str(s["name"])
        if db_name_clean and (db_name_clean in cleaned_query or cleaned_query in db_name_clean):
            matching_services.append(s)

    # If the user input contains multiple distinct catalog services, return None to trigger multi-service fallback
    if len(matching_services) > 1:
        return None

    best_match = None
    best_score = 0.0

    for s in services_list:
        db_name = s["name"]
        cleaned_db = clean_str(db_name)
        db_tokens = set(cleaned_db.split())
        query_tokens = set(cleaned_query.split())

        # Substring match
        if cleaned_query in cleaned_db or cleaned_db in cleaned_query:
            score = 0.8 + (min(len(cleaned_query), len(cleaned_db)) / max(len(cleaned_query), len(cleaned_db))) * 0.19
        else:
            # Token overlap (Jaccard similarity)
            intersection = query_tokens.intersection(db_tokens)
            union = query_tokens.union(db_tokens)
            score = len(intersection) / len(union) if union else 0.0

        if score > best_score and score >= 0.25:
            best_score = score
            best_match = s

    return best_match


def get_service_required_fields(service_name: str) -> dict:
    """
    Looks up a service by name (fuzzy matching supported) in the services table
    and returns its details along with the required fields mapping.
    For multi-service requests, calculates aggregate duration_minutes by summing
    the durations of all matched catalog services.
    """
    if not service_name:
        return None
        
    query = """
    SELECT name, description, price_range, duration_minutes,
           req_customer_name, req_phone_number, req_vehicle_details, req_issue_description, req_location
    FROM services;
    """
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(query)
            rows = [dict(row) for row in cursor.fetchall()]
        
    import re
    def clean_str(s: str) -> str:
        return re.sub(r'[^a-z0-9\s]', '', s.lower()).strip()

    cleaned_query = clean_str(service_name)

    matched_services = []
    for s in rows:
        db_name_clean = clean_str(s["name"])
        if db_name_clean and (db_name_clean in cleaned_query or cleaned_query in db_name_clean):
            if s not in matched_services:
                matched_services.append(s)

    if len(matched_services) > 1:
        total_duration = sum(s.get("duration_minutes") or 60 for s in matched_services)
        matched_names = ", ".join(s["name"] for s in matched_services)
        prices = [s["price_range"] for s in matched_services if s.get("price_range")]
        price_str = ", ".join(prices) if prices else "Varies by service"
        return {
            "name": service_name,
            "description": f"Multiple services requested: {matched_names}",
            "price_range": price_str,
            "duration_minutes": total_duration,
            "req_customer_name": any(bool(s.get("req_customer_name")) for s in matched_services),
            "req_phone_number": any(bool(s.get("req_phone_number")) for s in matched_services),
            "req_vehicle_details": any(bool(s.get("req_vehicle_details")) for s in matched_services),
            "req_issue_description": any(bool(s.get("req_issue_description")) for s in matched_services),
            "req_location": any(bool(s.get("req_location")) for s in matched_services)
        }

    match = find_best_service_match(service_name, rows)
    if match:
        return match

    return {
        "name": service_name,
        "description": "Vehicle service and repair",
        "price_range": "Varies by service",
        "duration_minutes": 60,
        "req_customer_name": True,
        "req_phone_number": True,
        "req_vehicle_details": True,
        "req_issue_description": True,
        "req_location": False
    }

def create_crm_note(call_id: str, customer_id: int, summary: str, transcript: str) -> int:
    """
    Inserts a new CRM note (call summary and transcript) for a customer call.
    """
    query = """
    INSERT INTO crm_notes (call_id, customer_id, summary, transcript)
    VALUES (%s, %s, %s, %s) RETURNING id;
    """
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(query, (call_id, customer_id, summary, transcript))
            conn.commit()
            return cursor.fetchone()["id"]


def create_callback_request(customer_id: int, service_request_id: int = None, preferred_time: str = None, vehicle_details: dict = None) -> int:
    """
    Inserts a callback request by updating the service_requests table.
    """
    # Enforce customer name, phone, and vehicle checks on the database/CRM request level
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            # Check customer name
            cursor.execute("SELECT name, phone FROM customers WHERE id = %s;", (customer_id,))
            cust = cursor.fetchone()
            if not cust:
                raise ValueError("Customer record not found.")
            if not cust["name"] or cust["name"] == "Unknown Customer" or cust["name"].strip() == "":
                raise ValueError("Customer name is required. Please collect the customer's name before arranging a callback.")
            if not cust["phone"] or cust["phone"] == "Unknown" or len(cust["phone"].strip()) < 10:
                raise ValueError("Customer phone number is required and must be a valid 10-digit number.")
                
            # Resolve vehicle details
            vehicle_id = None
            if vehicle_details and vehicle_details.get("make") and vehicle_details.get("make") != "Unknown":
                cursor.execute(
                    "SELECT id FROM vehicles WHERE customer_id = %s AND make = %s AND model = %s AND year = %s;",
                    (customer_id, vehicle_details.get("make"), vehicle_details.get("model"), vehicle_details.get("year"))
                )
                v_row = cursor.fetchone()
                if v_row:
                    vehicle_id = v_row["id"]
                else:
                    cursor.execute(
                        "INSERT INTO vehicles (customer_id, make, model, year) VALUES (%s, %s, %s, %s) RETURNING id;",
                        (customer_id, vehicle_details.get("make"), vehicle_details.get("model"), vehicle_details.get("year"))
                    )
                    vehicle_id = cursor.fetchone()["id"]

            if not vehicle_id:
                cursor.execute("SELECT id FROM vehicles WHERE customer_id = %s ORDER BY id DESC LIMIT 1;", (customer_id,))
                v_row = cursor.fetchone()
                vehicle_id = v_row["id"] if v_row else None
                if not vehicle_id:
                    cursor.execute("INSERT INTO vehicles (customer_id, make, model, year) VALUES (%s, 'Unknown', 'Unknown', 2000) RETURNING id;", (customer_id,))
                    vehicle_id = cursor.fetchone()["id"]

    if preferred_time and not validate_booking_time(preferred_time):
        raise ValueError(f"Callback preferred time {preferred_time} is outside company workhours (Monday to Friday, 7:00 AM to 6:00 PM).")
        
    cleaned_time = preferred_time
    if preferred_time:
        pref_lower = preferred_time.strip().lower()
        if "asap" in pref_lower or "as soon as possible" in pref_lower or "immediately" in pref_lower:
            cleaned_time = "ASAP"
            
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            # If service_request_id is provided, verify it is not already booked
            if service_request_id:
                cursor.execute(
                    "SELECT id, booking_type FROM service_requests WHERE id = %s AND customer_id = %s;",
                    (service_request_id, customer_id)
                )
                sr_row = cursor.fetchone()
                if not sr_row or sr_row["booking_type"] is not None:
                    service_request_id = None
            
            # If no service_request_id, find the last open raw intake one or create a new one
            if not service_request_id:
                cursor.execute(
                    "SELECT id FROM service_requests WHERE customer_id = %s AND vehicle_id = %s AND status = 'pending' AND booking_type IS NULL ORDER BY id DESC LIMIT 1;",
                    (customer_id, vehicle_id)
                )
                sr_row = cursor.fetchone()
                if sr_row:
                    service_request_id = sr_row["id"]
                else:
                    cursor.execute(
                        "INSERT INTO service_requests (customer_id, vehicle_id, service_type, issue_description, status) VALUES (%s, %s, 'Repair', 'Callback requested.', 'pending') RETURNING id;",
                        (customer_id, vehicle_id)
                    )
                    service_request_id = cursor.fetchone()["id"]
                    
            # Select a staff agent to assign the callback to (default to John Doe/ID 1 or the first agent)
            cursor.execute("SELECT id FROM staff_agents ORDER BY id ASC LIMIT 1;")
            agent_row = cursor.fetchone()
            staff_agent_id = agent_row["id"] if agent_row else None

            cursor.execute(
                "UPDATE service_requests SET booking_type = 'callback', booking_time = %s, staff_agent_id = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s;",
                (cleaned_time, staff_agent_id, service_request_id)
            )
            conn.commit()
            return service_request_id


def get_customer_appointments(phone: str) -> list:
    """
    Looks up all scheduled/rescheduled appointments for a customer by phone number,
    including vehicle make, model, and year.
    """
    import re
    cleaned_phone = re.sub(r"\D", "", phone) if phone else ""
    if len(cleaned_phone) == 11 and cleaned_phone.startswith("1"):
        cleaned_phone = cleaned_phone[1:]

    query = """
    SELECT sr.id, sr.booking_time AS appointment_datetime, sr.service_type, sr.status,
           v.year, v.make, v.model
    FROM service_requests sr
    JOIN customers c ON sr.customer_id = c.id
    LEFT JOIN vehicles v ON sr.vehicle_id = v.id
    WHERE (c.phone = %s OR REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(c.phone, '-', ''), ' ', ''), '(', ''), ')', ''), '+1', '') = %s)
      AND sr.booking_type = 'appointment'
      AND sr.status IN ('pending', 'in_progress')
    ORDER BY sr.booking_time DESC;
    """
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
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
        with dict_cursor(conn) as cursor:
            # 1. Get old appointment details
            cursor.execute(
                "SELECT booking_time, staff_agent_id, service_type, customer_id FROM service_requests WHERE id = %s AND booking_type = 'appointment';",
                (appointment_id,)
            )
            row = cursor.fetchone()
            if not row:
                raise ValueError(f"Appointment (Service Request) with ID {appointment_id} not found.")
            old_datetime = row["booking_time"]
            old_agent_id = row["staff_agent_id"]
            service_type = row["service_type"]
            customer_id = row["customer_id"]

            # 2. Free old slot window
            old_fields = get_service_required_fields(service_type) if service_type else None
            old_duration = old_fields.get("duration_minutes") or 60 if old_fields else 60
            if old_datetime:
                old_start = dt_mod.datetime.strptime(old_datetime, "%Y-%m-%d %H:%M:%S") if isinstance(old_datetime, str) else old_datetime
                old_end = old_start + dt_mod.timedelta(minutes=old_duration)
                if old_agent_id:
                    cursor.execute(
                        """
                        UPDATE mock_calendar_slots 
                        SET is_booked = FALSE 
                        WHERE staff_agent_id = %s 
                          AND slot_datetime >= CAST(%s AS TIMESTAMP) 
                          AND slot_datetime < CAST(%s AS TIMESTAMP);
                        """,
                        (old_agent_id, old_start.strftime("%Y-%m-%d %H:%M:%S"), old_end.strftime("%Y-%m-%d %H:%M:%S"))
                    )
                else:
                    cursor.execute(
                        """
                        UPDATE mock_calendar_slots 
                        SET is_booked = FALSE 
                        WHERE slot_datetime >= CAST(%s AS TIMESTAMP) 
                          AND slot_datetime < CAST(%s AS TIMESTAMP);
                        """,
                        (old_start.strftime("%Y-%m-%d %H:%M:%S"), old_end.strftime("%Y-%m-%d %H:%M:%S"))
                    )

            # 3. Check availability for the slot datetime across all candidate slots
            duration_minutes = 60
            if service_type:
                fields = get_service_required_fields(service_type)
                if fields and fields.get("duration_minutes"):
                    duration_minutes = fields["duration_minutes"]

            cursor.execute(
                "SELECT id, slot_datetime, staff_agent_id, is_booked FROM mock_calendar_slots WHERE slot_datetime >= CAST(%s AS TIMESTAMP);",
                (new_datetime,)
            )
            all_mock_rows = cursor.fetchall()

            all_agent_slots = {}
            candidate_rows = []
            for r in all_mock_rows:
                val = r["slot_datetime"]
                dt_val = dt_mod.datetime.strptime(val, "%Y-%m-%d %H:%M:%S") if isinstance(val, str) else val
                dt_str = dt_val.strftime("%Y-%m-%d %H:%M:%S")
                all_agent_slots[(r["staff_agent_id"], dt_val)] = r["is_booked"]
                if dt_str == new_datetime and not r["is_booked"]:
                    candidate_rows.append(r)
            
            from serviceBot.services.google_calendar import is_agent_free, create_agent_calendar_event

            chosen_slot = None
            chosen_agent_id = None

            if candidate_rows:
                new_start = dt_mod.datetime.strptime(new_datetime, "%Y-%m-%d %H:%M:%S") if isinstance(new_datetime, str) else new_datetime
                new_end = new_start + dt_mod.timedelta(minutes=duration_minutes)

                for r in candidate_rows:
                    aid = r["staff_agent_id"]
                    if not is_agent_free(aid, new_datetime, duration_minutes):
                        continue
                    
                    is_free_in_db = True
                    for (slot_aid, dt_k), is_booked in all_agent_slots.items():
                        if slot_aid == aid and new_start <= dt_k < new_end:
                            if is_booked:
                                is_free_in_db = False
                                break
                    if is_free_in_db:
                        chosen_slot = r
                        chosen_agent_id = aid
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
                
            if chosen_slot and chosen_agent_id:
                new_start = dt_mod.datetime.strptime(new_datetime, "%Y-%m-%d %H:%M:%S") if isinstance(new_datetime, str) else new_datetime
                new_end = new_start + dt_mod.timedelta(minutes=duration_minutes)
                cursor.execute(
                    """
                    UPDATE mock_calendar_slots 
                    SET is_booked = TRUE 
                    WHERE staff_agent_id = %s 
                      AND slot_datetime >= CAST(%s AS TIMESTAMP) 
                      AND slot_datetime < CAST(%s AS TIMESTAMP);
                    """,
                    (chosen_agent_id, new_start.strftime("%Y-%m-%d %H:%M:%S"), new_end.strftime("%Y-%m-%d %H:%M:%S"))
                )

            # 4. Update service request
            cursor.execute(
                "UPDATE service_requests SET booking_time = %s, staff_agent_id = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s;",
                (new_datetime, chosen_agent_id, appointment_id)
            )
            
            # Get customer details for calendar event
            cursor.execute("SELECT name FROM customers WHERE id = %s;", (customer_id,))
            cust_row = cursor.fetchone()
            customer_name = cust_row["name"] if cust_row else "Unknown Customer"
            
            cursor.execute("SELECT issue_description FROM service_requests WHERE id = %s;", (appointment_id,))
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

            # Create Admin Google Calendar event
            try:
                cursor.execute("SELECT name FROM staff_agents WHERE id = %s;", (chosen_agent_id,))
                sa_row = cursor.fetchone()
                mech_name = sa_row["name"] if sa_row else f"Agent {chosen_agent_id}"

                from serviceBot.services.gmail import create_admin_calendar_event
                create_admin_calendar_event(
                    customer_name=customer_name,
                    service_type=service_type,
                    issue_description=issue_desc,
                    slot_datetime_str=new_datetime,
                    mechanic_name=mech_name,
                    duration_minutes=duration_minutes
                )
            except Exception as admin_cal_err:
                print(f"Error creating admin calendar event: {admin_cal_err}")

            return True


def update_service_request_status(request_id: int, status: str) -> dict:
    """
    Updates the status of a service request.
    Valid statuses: 'pending', 'in_progress', 'completed', 'cancelled', 'rescheduled'.
    Maps 'done' -> 'completed'.
    """
    normalized_status = status.lower().strip()
    if normalized_status == 'done':
        normalized_status = 'completed'

    valid_statuses = ('pending', 'confirmed', 'in_progress', 'completed', 'cancelled', 'cancelled_by_customer', 'rescheduled')
    if normalized_status not in valid_statuses:
        raise ValueError(f"Invalid status '{status}'. Must be one of {valid_statuses}")

    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                "UPDATE service_requests SET status = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s RETURNING id, status, updated_at;",
                (normalized_status, request_id)
            )
            row = cursor.fetchone()
            if not row:
                raise ValueError(f"Service request with ID {request_id} not found.")
            return dict(row)


def assign_staff_agent_to_service_request(request_id: int, staff_agent_id: int = None) -> dict:
    """
    Assigns or updates the assigned staff agent / technician for a service request.
    Triggers slot booking changes in mock_calendar_slots, cancels the old agent's Google Calendar invite,
    sends a new Google Calendar invite & email to the new agent, and updates the Admin via email and calendar.
    """
    import datetime as dt_mod
    from serviceBot.services.google_calendar import delete_agent_calendar_event, create_agent_calendar_event
    from serviceBot.services.gmail import send_booking_notification, send_admin_notification, create_admin_calendar_event


    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            # 1. Fetch current service request and related customer/vehicle details
            cursor.execute("""
                SELECT sr.id, sr.staff_agent_id, sr.booking_time, sr.time_slot, sr.service_type, sr.issue_description,
                       sr.customer_id, sr.vehicle_id,
                       c.name AS customer_name, c.phone AS customer_phone,
                       v.year AS vehicle_year, v.make AS vehicle_make, v.model AS vehicle_model
                FROM service_requests sr
                LEFT JOIN customers c ON sr.customer_id = c.id
                LEFT JOIN vehicles v ON sr.vehicle_id = v.id
                WHERE sr.id = %s;
            """, (request_id,))
            sr = cursor.fetchone()
            if not sr:
                raise ValueError(f"Service request with ID {request_id} not found.")

            old_agent_id = sr.get("staff_agent_id")
            old_agent_name = None
            old_agent_email = None
            old_agent_phone = None
            if old_agent_id:
                cursor.execute("SELECT name, email, phone_number FROM staff_agents WHERE id = %s;", (old_agent_id,))
                oa_row = cursor.fetchone()
                if oa_row:
                    old_agent_name = oa_row["name"]
                    old_agent_email = oa_row["email"]
                    old_agent_phone = oa_row.get("phone_number")

            new_agent_name = None
            new_agent_email = None
            new_agent_phone = None
            if staff_agent_id is not None:
                cursor.execute("SELECT id, name, email, phone_number FROM staff_agents WHERE id = %s;", (staff_agent_id,))
                na_row = cursor.fetchone()
                if not na_row:
                    raise ValueError(f"Staff agent with ID {staff_agent_id} does not exist.")
                new_agent_name = na_row["name"]
                new_agent_email = na_row["email"]
                new_agent_phone = na_row.get("phone_number")

            # 2. Check if agent is being switched/reassigned
            is_agent_changed = (old_agent_id != staff_agent_id)
            booking_time_str = sr.get("booking_time") or sr.get("time_slot")
            if isinstance(booking_time_str, dt_mod.datetime):
                booking_time_str = booking_time_str.strftime("%Y-%m-%d %H:%M:%S")

            if is_agent_changed and booking_time_str and str(booking_time_str).upper() != "ASAP":
                # --- A. Slot Booking Changes ---
                # Unbook slot for previous agent if present
                if old_agent_id:
                    cursor.execute(
                        "UPDATE mock_calendar_slots SET is_booked = FALSE WHERE staff_agent_id = %s AND slot_datetime = CAST(%s AS TIMESTAMP);",
                        (old_agent_id, str(booking_time_str)[:19])
                    )

                # Reserve slot for new agent if present
                if staff_agent_id is not None:
                    cursor.execute(
                        "SELECT id FROM mock_calendar_slots WHERE staff_agent_id = %s AND slot_datetime = CAST(%s AS TIMESTAMP);",
                        (staff_agent_id, str(booking_time_str)[:19])
                    )
                    existing_slot = cursor.fetchone()
                    if existing_slot:
                        cursor.execute(
                            "UPDATE mock_calendar_slots SET is_booked = TRUE WHERE id = %s;",
                            (existing_slot["id"],)
                        )
                    else:
                        cursor.execute(
                            "INSERT INTO mock_calendar_slots (slot_datetime, is_booked, staff_agent_id) VALUES (CAST(%s AS TIMESTAMP), TRUE, %s) ON CONFLICT (slot_datetime, staff_agent_id) DO UPDATE SET is_booked = TRUE;",
                            (str(booking_time_str)[:19], staff_agent_id)
                        )

                # Prepare details dictionary for email notifications
                v_parts = [sr.get("vehicle_year"), sr.get("vehicle_make"), sr.get("vehicle_model")]
                v_str = " ".join([str(p) for p in v_parts if p]).strip() or "N/A"
                details = {
                    "customer_name": sr.get("customer_name") or "Unknown Customer",
                    "phone": sr.get("customer_phone") or "N/A",
                    "vehicle": v_str,
                    "service_type": sr.get("service_type") or "N/A",
                    "time": str(booking_time_str)[:19],
                    "issue": sr.get("issue_description") or "",
                    "previous_agent_name": old_agent_name or "Unassigned",
                    "new_agent_name": new_agent_name or "Unassigned"
                }

                # Transactional Outbox Event: Atomically enqueue outbox record in same DB transaction
                from serviceBot.services.outbox_worker import enqueue_outbox_event
                outbox_payload = {
                    "old_agent_id": old_agent_id,
                    "old_agent_name": old_agent_name,
                    "new_agent_id": staff_agent_id,
                    "new_agent_name": new_agent_name,
                    "new_agent_email": new_agent_email,
                    "agent_phone": new_agent_phone,
                    "previous_agent_phone": old_agent_phone,
                    "booking_time_str": str(booking_time_str)[:19] if booking_time_str else None,
                    "details": details
                }
                enqueue_outbox_event(cursor, "agent_reassignment", request_id, outbox_payload)

            # 3. Update database record
            cursor.execute(
                "UPDATE service_requests SET staff_agent_id = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s RETURNING id, staff_agent_id, status, updated_at;",
                (staff_agent_id, request_id)
            )
            row = cursor.fetchone()
            if not row:
                raise ValueError(f"Service request with ID {request_id} not found.")
            return dict(row)



def get_available_agents_for_request(request_id: int) -> list:
    """
    Fetches all staff agents and checks their availability for the scheduled booking_time/time_slot
    of the given service request.
    """
    import datetime as dt_mod
    from serviceBot.services.google_calendar import fetch_agent_events, parse_google_datetime

    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                "SELECT id, booking_time, time_slot, service_type, staff_agent_id FROM service_requests WHERE id = %s;",
                (request_id,)
            )
            sr = cursor.fetchone()
            if not sr:
                raise ValueError(f"Service request with ID {request_id} not found.")

            cursor.execute("SELECT id, name, role, email, phone_number FROM staff_agents ORDER BY id ASC;")
            agents = [dict(row) for row in cursor.fetchall()]

    b_time_str = sr.get("booking_time") or sr.get("time_slot")
    if not b_time_str or str(b_time_str).upper() == "ASAP":
        for a in agents:
            a["is_available"] = True
            a["reason"] = "Available"
        return agents

    try:
        if len(str(b_time_str)) == 10:
            start_dt = dt_mod.datetime.strptime(str(b_time_str), "%Y-%m-%d")
        else:
            start_dt = dt_mod.datetime.strptime(str(b_time_str)[:19], "%Y-%m-%d %H:%M:%S")
    except Exception:
        for a in agents:
            a["is_available"] = True
            a["reason"] = "Available"
        return agents

    start_str = start_dt.strftime("%Y-%m-%d %H:%M:%S")

    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                "SELECT staff_agent_id FROM mock_calendar_slots WHERE slot_datetime = CAST(%s AS TIMESTAMP) AND is_booked = TRUE;",
                (start_str,)
            )
            booked_slot_agent_ids = {r["staff_agent_id"] for r in cursor.fetchall() if r["staff_agent_id"] is not None}

            cursor.execute(
                "SELECT staff_agent_id FROM service_requests WHERE (booking_time = %s OR time_slot = %s) AND id != %s AND status NOT IN ('cancelled') AND staff_agent_id IS NOT NULL;",
                (b_time_str, b_time_str, request_id)
            )
            conflicting_sr_agent_ids = {r["staff_agent_id"] for r in cursor.fetchall()}

    for agent in agents:
        agent_id = agent["id"]
        is_busy = False
        reason = "Available"

        if agent_id in booked_slot_agent_ids:
            is_busy = True
            reason = "Booked in calendar"
        elif agent_id in conflicting_sr_agent_ids:
            is_busy = True
            reason = "Assigned to another request at this time"
        else:
            try:
                events = fetch_agent_events(agent_id)
                if events:
                    end_dt = start_dt + dt_mod.timedelta(minutes=60)
                    for ev in events:
                        ev_start = parse_google_datetime(ev.get("start", {}).get("dateTime") or ev.get("start", {}).get("date"))
                        ev_end = parse_google_datetime(ev.get("end", {}).get("dateTime") or ev.get("end", {}).get("date"))
                        if ev_start and ev_end and not (end_dt <= ev_start or start_dt >= ev_end):
                            is_busy = True
                            reason = "Busy in Google Calendar"
                            break
            except Exception:
                pass

        agent["is_available"] = not is_busy
        agent["reason"] = reason

    return agents


# --- SMS Notification System & Two-Way Handoff Queries ---

def get_sms_config() -> dict:
    """Fetches the global SMS configuration."""
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("SELECT * FROM sms_config ORDER BY id ASC LIMIT 1;")
            row = cursor.fetchone()
            if not row:
                return {}
            d = dict(row)
            if isinstance(d.get("quiet_start_time"), (dt_mod.time, dt_mod.datetime)):
                d["quiet_start_time"] = str(d["quiet_start_time"])
            if isinstance(d.get("quiet_end_time"), (dt_mod.time, dt_mod.datetime)):
                d["quiet_end_time"] = str(d["quiet_end_time"])
            return d


def update_sms_config(data: dict) -> dict:
    """Updates SMS configuration settings."""
    allowed = {
        "quiet_hours_enabled", "quiet_start_time", "quiet_end_time",
        "urgent_threshold_hours", "support_phone_number", "admin_phone_number",
        "auto_responder_template", "auto_responder_debounce_seconds", "environment"
    }
    updates = []
    params = []
    for k, v in data.items():
        if k in allowed:
            updates.append(f"{k} = %s")
            params.append(v)
    if not updates:
        return get_sms_config()

    query = f"UPDATE sms_config SET {', '.join(updates)}, updated_at = CURRENT_TIMESTAMP WHERE id = (SELECT id FROM sms_config ORDER BY id ASC LIMIT 1) RETURNING *;"
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(query, params)
            row = cursor.fetchone()
            d = dict(row) if row else {}
            if isinstance(d.get("quiet_start_time"), (dt_mod.time, dt_mod.datetime)):
                d["quiet_start_time"] = str(d["quiet_start_time"])
            if isinstance(d.get("quiet_end_time"), (dt_mod.time, dt_mod.datetime)):
                d["quiet_end_time"] = str(d["quiet_end_time"])
            return d


def get_sms_matrix_rules() -> list:
    """Fetches all event matrix notification rules."""
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("SELECT * FROM sms_matrix_rules ORDER BY event_type, recipient_role;")
            return [dict(r) for r in cursor.fetchall()]


def update_sms_matrix_rule(event_type: str, recipient_role: str, enabled: bool) -> dict:
    """Updates or inserts a matrix rule for an event and recipient role."""
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                """
                INSERT INTO sms_matrix_rules (event_type, recipient_role, enabled)
                VALUES (%s, %s, %s)
                ON CONFLICT (event_type, recipient_role)
                DO UPDATE SET enabled = EXCLUDED.enabled
                RETURNING *;
                """,
                (event_type, recipient_role, enabled)
            )
            return dict(cursor.fetchone())


def get_sms_whitelist() -> list:
    """Fetches all whitelisted phone numbers for test environment."""
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("SELECT * FROM sms_whitelist ORDER BY created_at DESC;")
            return [dict(r) for r in cursor.fetchall()]


def add_sms_whitelist(
    phone_number: str,
    friendly_name: str = None,
    twilio_verified: bool = False,
    whatsapp_onboarded: bool = False,
    recipient_role: str = "CUSTOMER"
) -> dict:
    """Adds or updates a phone number in the SMS test whitelist."""
    from datetime import datetime
    whatsapp_onboarded_at = datetime.utcnow() if whatsapp_onboarded else None
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                """
                INSERT INTO sms_whitelist (phone_number, friendly_name, twilio_verified, whatsapp_onboarded, whatsapp_onboarded_at, recipient_role)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (phone_number) DO UPDATE SET
                    friendly_name = COALESCE(EXCLUDED.friendly_name, sms_whitelist.friendly_name),
                    twilio_verified = EXCLUDED.twilio_verified,
                    whatsapp_onboarded = CASE WHEN EXCLUDED.whatsapp_onboarded THEN TRUE ELSE sms_whitelist.whatsapp_onboarded END,
                    whatsapp_onboarded_at = CASE WHEN EXCLUDED.whatsapp_onboarded THEN EXCLUDED.whatsapp_onboarded_at ELSE sms_whitelist.whatsapp_onboarded_at END,
                    recipient_role = EXCLUDED.recipient_role
                RETURNING *;
                """,
                (phone_number, friendly_name, twilio_verified, whatsapp_onboarded, whatsapp_onboarded_at, recipient_role)
            )
            return dict(cursor.fetchone())


def update_whatsapp_onboarding_status(phone_number: str, whatsapp_onboarded: bool = True, recipient_role: str = "CUSTOMER") -> dict:
    """Updates the WhatsApp onboarding status for a whitelisted phone number."""
    from datetime import datetime
    whatsapp_onboarded_at = datetime.utcnow() if whatsapp_onboarded else None
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                """
                UPDATE sms_whitelist
                SET whatsapp_onboarded = %s,
                    whatsapp_onboarded_at = %s,
                    recipient_role = COALESCE(%s, recipient_role)
                WHERE phone_number = %s
                RETURNING *;
                """,
                (whatsapp_onboarded, whatsapp_onboarded_at, recipient_role, phone_number)
            )
            res = cursor.fetchone()
            if res:
                return dict(res)
            # If not yet in whitelist, insert it
            return add_sms_whitelist(phone_number, friendly_name=phone_number, twilio_verified=True, whatsapp_onboarded=whatsapp_onboarded, recipient_role=recipient_role)


def delete_sms_whitelist(whitelist_id: int) -> bool:
    """Deletes a phone number entry from the SMS test whitelist."""
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("DELETE FROM sms_whitelist WHERE id = %s;", (whitelist_id,))
            return cursor.rowcount > 0


def is_phone_whitelisted(phone_number: str) -> bool:
    """Checks whether a phone number is present in the SMS test whitelist."""
    import re
    if not phone_number:
        return False
    clean = re.sub(r"\D", "", phone_number)
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("SELECT phone_number FROM sms_whitelist;")
            for r in cursor.fetchall():
                w_clean = re.sub(r"\D", "", r["phone_number"])
                if w_clean == clean or (len(w_clean) == 10 and clean.endswith(w_clean)):
                    return True
            return False


def log_sms_dispatch(
    appointment_id: int,
    recipient_type: str,
    recipient_phone: str,
    template_type: str,
    status: str = "PENDING",
    twilio_message_sid: str = None,
    error_code: str = None,
    error_message: str = None,
    retry_count: int = 0,
    scheduled_send_at: dt_mod.datetime = None
) -> int:
    """Logs an SMS dispatch attempt into the sms_log table."""
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                """
                INSERT INTO sms_log 
                (appointment_id, recipient_type, recipient_phone, template_type, twilio_message_sid, status, error_code, error_message, retry_count, scheduled_send_at, sent_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id;
                """,
                (
                    appointment_id, recipient_type, recipient_phone, template_type,
                    twilio_message_sid, status, error_code, error_message, retry_count,
                    scheduled_send_at, dt_mod.datetime.utcnow() if status in ("SENT", "DELIVERED") else None
                )
            )
            return cursor.fetchone()["id"]


def update_sms_log_status(
    log_id: int,
    status: str,
    twilio_message_sid: str = None,
    error_code: str = None,
    error_message: str = None,
    increment_retry: bool = False
):
    """Updates an existing sms_log record status and details."""
    updates = ["status = %s"]
    params = [status]
    if twilio_message_sid:
        updates.append("twilio_message_sid = %s")
        params.append(twilio_message_sid)
    if error_code is not None:
        updates.append("error_code = %s")
        params.append(error_code)
    if error_message is not None:
        updates.append("error_message = %s")
        params.append(error_message)
    if increment_retry:
        updates.append("retry_count = retry_count + 1")
    if status in ("SENT", "DELIVERED"):
        updates.append("sent_at = CURRENT_TIMESTAMP")

    params.append(log_id)
    query = f"UPDATE sms_log SET {', '.join(updates)} WHERE id = %s RETURNING *;"
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(query, params)
            row = cursor.fetchone()
            return dict(row) if row else None


def get_sms_logs_by_appointment(appointment_id: int) -> list:
    """Fetches all SMS dispatch logs for a given appointment."""
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("SELECT * FROM sms_log WHERE appointment_id = %s ORDER BY created_at ASC;", (appointment_id,))
            rows = cursor.fetchall()
            logs = []
            for r in rows:
                item = dict(r)
                if item.get("created_at") and not isinstance(item["created_at"], str):
                    item["created_at"] = item["created_at"].strftime("%Y-%m-%d %H:%M:%S")
                if item.get("sent_at") and not isinstance(item["sent_at"], str):
                    item["sent_at"] = item["sent_at"].strftime("%Y-%m-%d %H:%M:%S")
                if item.get("scheduled_send_at") and not isinstance(item["scheduled_send_at"], str):
                    item["scheduled_send_at"] = item["scheduled_send_at"].strftime("%Y-%m-%d %H:%M:%S")
                logs.append(item)
            return logs


def get_appointment_details_by_id(appointment_id: int) -> dict:
    """Fetches full details of an appointment for SMS log popup context."""
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("""
                SELECT sr.id, sr.service_type, sr.issue_description, sr.status, sr.time_slot, sr.booking_time, sr.created_at,
                       c.name AS customer_name, c.phone AS customer_phone,
                       v.make AS vehicle_make, v.model AS vehicle_model, v.year AS vehicle_year,
                       sa.name AS staff_agent_name, sa.role AS staff_agent_role
                FROM service_requests sr
                LEFT JOIN customers c ON sr.customer_id = c.id
                LEFT JOIN vehicles v ON sr.vehicle_id = v.id
                LEFT JOIN staff_agents sa ON sr.staff_agent_id = sa.id
                WHERE sr.id = %s;
            """, (appointment_id,))
            row = cursor.fetchone()
            if row:
                r = dict(row)
                if r.get("created_at") and not isinstance(r["created_at"], str):
                    r["created_at"] = r["created_at"].strftime("%Y-%m-%d %H:%M:%S")
                if r.get("booking_time") and not isinstance(r["booking_time"], str):
                    r["booking_time"] = r["booking_time"].strftime("%Y-%m-%d %H:%M:%S")
                return r
            return None


def get_sms_log_by_id(log_id: int) -> dict:
    """Fetches a single SMS log by ID."""
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("SELECT * FROM sms_log WHERE id = %s;", (log_id,))
            row = cursor.fetchone()
            return dict(row) if row else None


def schedule_sms_reminder(appointment_id: int, recipient_type: str, recipient_phone: str, reminder_type: str, scheduled_at: dt_mod.datetime) -> int:
    """Schedules a pre-appointment SMS reminder in sms_reminders table."""
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                """
                INSERT INTO sms_reminders (appointment_id, recipient_type, recipient_phone, reminder_type, scheduled_at, status)
                VALUES (%s, %s, %s, %s, %s, 'PENDING')
                RETURNING id;
                """,
                (appointment_id, recipient_type, recipient_phone, reminder_type, scheduled_at)
            )
            return cursor.fetchone()["id"]


def cancel_pending_sms_reminders(appointment_id: int):
    """Marks all pending reminders for an appointment as CANCELLED."""
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                "UPDATE sms_reminders SET status = 'CANCELLED' WHERE appointment_id = %s AND status = 'PENDING';",
                (appointment_id,)
            )


def get_due_sms_reminders() -> list:
    """Fetches all pending SMS reminders that are scheduled at or before NOW."""
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                "SELECT * FROM sms_reminders WHERE status = 'PENDING' AND scheduled_at <= CURRENT_TIMESTAMP ORDER BY scheduled_at ASC;"
            )
            return [dict(r) for r in cursor.fetchall()]


def mark_sms_reminder_status(reminder_id: int, status: str):
    """Updates the status of an SMS reminder."""
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("UPDATE sms_reminders SET status = %s WHERE id = %s;", (status, reminder_id))


def get_due_queued_sms_logs() -> list:
    """Fetches SMS logs in QUEUED status whose scheduled_send_at is due."""
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                "SELECT * FROM sms_log WHERE status = 'QUEUED' AND scheduled_send_at <= CURRENT_TIMESTAMP ORDER BY scheduled_send_at ASC;"
            )
            return [dict(r) for r in cursor.fetchall()]


def get_or_create_sms_conversation(customer_phone: str, context_appointment_id: int = None, assigned_agent_id: int = None) -> dict:
    """Gets an existing conversation for a customer phone number or creates a new one."""
    import re
    cleaned_phone = customer_phone.strip()
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("SELECT * FROM sms_conversations WHERE customer_phone = %s;", (cleaned_phone,))
            row = cursor.fetchone()
            if row:
                if context_appointment_id or assigned_agent_id:
                    cursor.execute(
                        "UPDATE sms_conversations SET context_appointment_id = COALESCE(%s, context_appointment_id), assigned_agent_id = COALESCE(%s, assigned_agent_id), updated_at = CURRENT_TIMESTAMP WHERE id = %s RETURNING *;",
                        (context_appointment_id, assigned_agent_id, row["id"])
                    )
                    return dict(cursor.fetchone())
                return dict(row)
            
            cursor.execute(
                """
                INSERT INTO sms_conversations (customer_phone, state, context_appointment_id, assigned_agent_id)
                VALUES (%s, 'AUTOMATED', %s, %s)
                RETURNING *;
                """,
                (cleaned_phone, context_appointment_id, assigned_agent_id)
            )
            return dict(cursor.fetchone())


def update_sms_conversation_state(conversation_id: int, state: str, last_auto_responder_at: dt_mod.datetime = None) -> dict:
    """Updates the state of an SMS conversation."""
    updates = ["state = %s", "updated_at = CURRENT_TIMESTAMP"]
    params = [state]
    if last_auto_responder_at is not None:
        updates.append("last_auto_responder_at = %s")
        params.append(last_auto_responder_at)

    params.append(conversation_id)
    query = f"UPDATE sms_conversations SET {', '.join(updates)} WHERE id = %s RETURNING *;"
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(query, params)
            row = cursor.fetchone()
            return dict(row) if row else {}


def get_sms_conversations(state: str = None, assigned_agent_id: int = None) -> list:
    """Lists SMS conversations filtered optionally by state or assigned_agent_id."""
    where_clauses = []
    params = []
    if state:
        where_clauses.append("c.state = %s")
        params.append(state)
    if assigned_agent_id:
        where_clauses.append("c.assigned_agent_id = %s")
        params.append(assigned_agent_id)

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    query = f"""
    SELECT 
        c.*,
        cust.name AS customer_name,
        sa.name AS agent_name,
        sr.service_type AS appointment_service_type,
        sr.booking_time AS appointment_time
    FROM sms_conversations c
    LEFT JOIN customers cust ON REPLACE(REPLACE(REPLACE(cust.phone, '-', ''), ' ', ''), '+1', '') = REPLACE(REPLACE(REPLACE(c.customer_phone, '-', ''), ' ', ''), '+1', '')
    LEFT JOIN staff_agents sa ON c.assigned_agent_id = sa.id
    LEFT JOIN service_requests sr ON c.context_appointment_id = sr.id
    {where_sql}
    ORDER BY c.updated_at DESC;
    """
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(query, params)
            return [dict(r) for r in cursor.fetchall()]


def add_sms_message(conversation_id: int, direction: str, sender_type: str, sender_name: str, body: str, twilio_message_sid: str = None) -> dict:
    """Adds a message entry to a conversation history."""
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                """
                INSERT INTO sms_messages (conversation_id, direction, sender_type, sender_name, body, twilio_message_sid)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING *;
                """,
                (conversation_id, direction, sender_type, sender_name, body, twilio_message_sid)
            )
            msg = dict(cursor.fetchone())
            cursor.execute("UPDATE sms_conversations SET updated_at = CURRENT_TIMESTAMP WHERE id = %s;", (conversation_id,))
            return msg


def get_sms_messages(conversation_id: int) -> list:
    """Fetches all messages for a given conversation ordered chronologically."""
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("SELECT * FROM sms_messages WHERE conversation_id = %s ORDER BY created_at ASC;", (conversation_id,))
            return [dict(r) for r in cursor.fetchall()]


def update_customer_opt_in(phone: str, opt_in: bool) -> bool:
    """Updates or inserts customer.sms_opt_in status by phone number."""
    import re
    if not phone:
        return False
    cleaned = re.sub(r"\D", "", phone)
    if len(cleaned) == 11 and cleaned.startswith("1"):
        cleaned = cleaned[1:]

    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                """
                UPDATE customers 
                SET sms_opt_in = %s 
                WHERE phone = %s OR REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(phone, '-', ''), ' ', ''), '(', ''), ')', ''), '+1', '') = %s;
                """,
                (opt_in, phone, cleaned)
            )
            if cursor.rowcount == 0:
                cursor.execute(
                    """
                    INSERT INTO customers (name, phone, sms_opt_in)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (phone) DO UPDATE SET sms_opt_in = EXCLUDED.sms_opt_in;
                    """,
                    (f"Customer {cleaned}", phone, opt_in)
                )
            return True



def get_customer_opt_in(phone: str) -> bool:
    """Checks customer.sms_opt_in status for a phone number."""
    import re
    if not phone:
        return True
    cleaned = re.sub(r"\D", "", phone)
    if len(cleaned) == 11 and cleaned.startswith("1"):
        cleaned = cleaned[1:]
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                """
                SELECT sms_opt_in FROM customers 
                WHERE phone = %s OR REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(phone, '-', ''), ' ', ''), '(', ''), ')', ''), '+1', '') = %s;
                """,
                (phone, cleaned)
            )
            row = cursor.fetchone()
            if row and row["sms_opt_in"] is not None:
                return row["sms_opt_in"]
            return True


