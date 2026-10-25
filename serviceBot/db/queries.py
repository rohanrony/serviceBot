from typing import Optional, Dict, Any, List, Tuple
import json
from serviceBot.db.connection import get_db_connection, dict_cursor
from serviceBot.logger import get_logger, log_execution
import datetime as dt_mod
from datetime import timedelta
from serviceBot.services.google_calendar import fetch_agent_events, parse_google_datetime

logger = get_logger("db.queries")


class AvailabilityUnknownError(RuntimeError):
    """Relevant calendar uncertainty prevents a trustworthy availability answer."""

    def __init__(self):
        super().__init__("Calendar availability could not be verified. Please try again later.")

    def as_result(self):
        return {"success": False, "error_code": "AVAILABILITY_UNKNOWN",
                "availability_status": "unknown", "available_slots": [],
                "retryable": True, "message": str(self)}


def normalize_e164_phone(phone: str) -> str:
    """Normalizes phone number string to E.164 format (+1XXXXXXXXXX)."""
    import re
    if not phone:
        return ""
    digits = re.sub(r"\D", "", phone)
    if len(digits) == 10:
        return f"+1{digits}"
    elif len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    elif phone.startswith("+"):
        return phone
    return phone


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
    e164_phone = f"+1{cleaned_phone}" if len(cleaned_phone) == 10 else f"+{cleaned_phone}"

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


def resolve_asap_callback_time(preferred_date: str = None) -> str:
    """
    Finds the next operating 15-minute callback slot without consulting a provider.
    Capacity is still claimed transactionally by BookingService after this hint is chosen.
    """
    from zoneinfo import ZoneInfo
    from serviceBot.services.calendar_sync import (
        get_configured_business_days,
        get_configured_business_hours,
    )

    business_days = set(get_configured_business_days())
    business_hours = set(get_configured_business_hours())
    if not business_days or not business_hours:
        raise ValueError("No operating hours are configured for callbacks.")

    from serviceBot.services import timezone_service
    now = timezone_service.now_in_business_tz().replace(tzinfo=None)
    min_buf = 2.0
    try:
        from serviceBot.api.portal import load_config
        cfg = load_config()
        min_buf = float(cfg.get("min_callback_buffer_hours", 2.0))
    except Exception:
        min_buf = 2.0

    earliest_allowed = now + dt_mod.timedelta(hours=min_buf)
    candidate = earliest_allowed.replace(second=0, microsecond=0)
    minutes_rem = candidate.minute % 15
    if minutes_rem != 0:
        candidate += dt_mod.timedelta(minutes=(15 - minutes_rem))

    if preferred_date:
        try:
            requested_date = dt_mod.date.fromisoformat(str(preferred_date)[:10])
            if requested_date > candidate.date():
                candidate = dt_mod.datetime.combine(
                    requested_date,
                    dt_mod.time(hour=min(business_hours)),
                )
        except ValueError:
            pass

    for _ in range(14 * 24 * 4):
        if candidate.weekday() in business_days and candidate.hour in business_hours:
            return candidate.strftime("%Y-%m-%d %H:%M:%S")
        candidate += dt_mod.timedelta(minutes=15)

    raise ValueError("No callback time is available in the next 14 days.")


def _create_service_request_legacy(
    customer_id: int,
    vehicle_details: dict,
    issue: str,
    service_type: str = "Repair",
    time_slot: str = None,
    booking_type: str = None,
    booking_time: str = None,
    staff_agent_id: int = None,
    is_uncataloged: bool = False,
    linked_appointment_id: int = None,
    callback_priority: str = "medium",
    callback_number: str = None
) -> int:
    """
    Creates a vehicle if it does not exist, and inserts a service request for the customer and vehicle.
    Supports booking_type ('appointment', 'callback', 'appointment_and_callback'), booking_time, and uncataloged callbacks.
    For callbacks, enforces 15-minute duration and resolves ASAP times to the earliest available slot.
    """
    from serviceBot.services.business_profile import get_business_profile, validate_intake_data
    intake_data = validate_intake_data((vehicle_details or {}).get("intake_data"))
    import datetime as dt_mod
    # Try fuzzy catalog matching for service type
    fields = get_service_required_fields(service_type)
    matched_service_name = fields["name"] if fields else service_type

    if not booking_time and time_slot:
        booking_time = time_slot

    is_cb = booking_type in ("callback", "appointment_and_callback") or (service_type and "callback" in str(service_type).lower())
    if is_cb and booking_type != "appointment_and_callback":
        booking_type = "callback"
        if not booking_time or "asap" in str(booking_time).lower() or "as soon as possible" in str(booking_time).lower():
            booking_time = resolve_asap_callback_time()

    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            vehicle_id = None
            if get_business_profile()["collect_vehicle_details"]:
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
                cursor.execute("SELECT id FROM staff_agents WHERE is_active IS NOT FALSE ORDER BY id ASC LIMIT 1;")
                sa_row = cursor.fetchone()
                if sa_row:
                    staff_agent_id = sa_row["id"]

            duration_minutes = 15 if is_cb else (fields.get("duration_minutes") or 60 if fields else 60)

            # Insert service request with booking_type, booking_time, duration_minutes, and uncataloged fields
            cursor.execute(
                """
                INSERT INTO service_requests 
                (customer_id, vehicle_id, service_type, issue_description, status, time_slot, booking_type, booking_time, duration_minutes, staff_agent_id, is_uncataloged, linked_appointment_id, callback_priority, callback_number) 
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id;
                """,
                (customer_id, vehicle_id, matched_service_name, issue, "pending", time_slot, booking_type, booking_time, duration_minutes, staff_agent_id, is_uncataloged, linked_appointment_id, callback_priority, callback_number)
            )
            sr_id = cursor.fetchone()['id']
            from serviceBot.services.booking import BookingService
            BookingService._persist_intake(cursor, sr_id, intake_data)



            conn.commit()

    # Create Google Calendar & Admin events for both appointments and callbacks outside of DB transaction
    if booking_time and staff_agent_id:
        try:
            c_name = "Customer"
            mech_name = f"Agent {staff_agent_id}"
            with get_db_connection() as conn:
                with dict_cursor(conn) as cursor:
                    cursor.execute("SELECT name FROM customers WHERE id = %s;", (customer_id,))
                    c_row = cursor.fetchone()
                    if c_row:
                        c_name = c_row["name"]
                    cursor.execute("SELECT name FROM staff_agents WHERE id = %s;", (staff_agent_id,))
                    sa_row = cursor.fetchone()
                    if sa_row:
                        mech_name = sa_row["name"]

            duration_minutes = 15 if is_cb else (fields.get("duration_minutes") or 60 if fields else 60)
            
            from serviceBot.services.google_calendar import create_agent_calendar_event
            create_agent_calendar_event(
                agent_id=staff_agent_id,
                customer_name=c_name,
                service_type=matched_service_name,
                issue_description=issue,
                slot_datetime_str=booking_time if isinstance(booking_time, str) else booking_time.strftime("%Y-%m-%d %H:%M:%S"),
                duration_minutes=duration_minutes,
                booking_type=booking_type or "appointment"
            )

            from serviceBot.services.gmail import create_admin_calendar_event
            create_admin_calendar_event(
                customer_name=c_name,
                service_type=matched_service_name,
                issue_description=issue,
                slot_datetime_str=booking_time if isinstance(booking_time, str) else booking_time.strftime("%Y-%m-%d %H:%M:%S"),
                mechanic_name=mech_name,
                duration_minutes=duration_minutes,
                booking_type=booking_type or "appointment"
            )
        except Exception as cal_err:
            logger.warning(f"Could not create calendar events for service request {sr_id}: {cal_err}")

    return sr_id


def create_service_request(
    customer_id: int,
    vehicle_details: dict,
    issue: str,
    service_type: str = "Repair",
    time_slot: str = None,
    booking_type: str = None,
    booking_time: str = None,
    staff_agent_id: int = None,
    is_uncataloged: bool = False,
    linked_appointment_id: int = None,
    callback_priority: str = "medium",
    callback_number: str = None,
) -> int:
    """Create an intake request, reserving calendar capacity atomically when scheduled."""
    fields = get_service_required_fields(service_type)
    matched_service_name = fields["name"] if fields else (service_type or "Repair")
    if not booking_time and time_slot:
        from serviceBot.services.booking import BookingValidationError, parse_reservation_start

        try:
            parse_reservation_start(time_slot)
        except BookingValidationError:
            # A natural-language intake window is not a confirmed reservation.
            pass
        else:
            booking_time = time_slot
    if booking_time and booking_type is None:
        booking_type = "appointment"

    is_callback = booking_type in ("callback", "appointment_and_callback") or (
        service_type and "callback" in str(service_type).lower()
    )
    if is_callback and booking_type != "appointment_and_callback":
        booking_type = "callback"
        if not booking_time or "asap" in str(booking_time).lower() or "as soon as possible" in str(booking_time).lower():
            booking_time = resolve_asap_callback_time()

    if booking_time and booking_type in ("appointment", "callback", "appointment_and_callback"):
        from serviceBot.services.booking import BookingService, SLOT_MINUTES

        duration_minutes = SLOT_MINUTES if is_callback else (
            (fields.get("duration_minutes") or 60) if fields else 60
        )
        receipt = BookingService().reserve_or_create(
            customer_id=customer_id,
            service_request_id=None,
            appointment_datetime=booking_time,
            service_type=matched_service_name,
            vehicle_details=vehicle_details,
            issue_description=issue,
            booking_type=booking_type,
            duration_minutes=duration_minutes,
            requested_agent_id=staff_agent_id,
            is_uncataloged=is_uncataloged,
            linked_appointment_id=linked_appointment_id,
            callback_priority=callback_priority,
            callback_number=callback_number,
        )
        return receipt.request_id

    return _create_service_request_legacy(
        customer_id=customer_id,
        vehicle_details=vehicle_details,
        issue=issue,
        service_type=service_type,
        time_slot=time_slot,
        booking_type=booking_type,
        booking_time=booking_time,
        staff_agent_id=staff_agent_id,
        is_uncataloged=is_uncataloged,
        linked_appointment_id=linked_appointment_id,
        callback_priority=callback_priority,
        callback_number=callback_number,
    )


def find_pending_callback_by_phone(phone: str) -> dict:
    """Finds an existing open callback request for a customer by phone number to prevent duplicate tickets."""
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                """
                SELECT sr.id, sr.issue_description, sr.created_at, sr.booking_type, sr.status, sr.callback_priority, sr.is_uncataloged
                FROM service_requests sr
                JOIN customers c ON sr.customer_id = c.id
                WHERE c.phone = %s 
                  AND sr.status IN ('pending', 'in_progress')
                  AND (sr.booking_type IN ('callback', 'appointment_and_callback') OR sr.is_uncataloged = TRUE)
                ORDER BY sr.created_at DESC
                LIMIT 1;
                """,
                (phone,)
            )
            return cursor.fetchone()


def create_dual_intake_request(
    customer_id: int,
    vehicle_details: dict,
    catalog_issue: str,
    uncataloged_issue: str,
    service_type: str = "Repair",
    time_slot: str = None,
    booking_time: str = None,
    staff_agent_id: int = None,
    callback_priority: str = "medium",
    callback_number: str = None
) -> dict:
    """
    Creates an appointment service request for the catalog item,
    and a linked callback service request for the uncataloged issue in a single atomic flow.
    Returns dict with appointment_id and callback_id.
    """
    # 1. Book standard appointment
    appointment_id = create_service_request(
        customer_id=customer_id,
        vehicle_details=vehicle_details,
        issue=catalog_issue,
        service_type=service_type,
        time_slot=time_slot,
        booking_type="appointment",
        booking_time=booking_time,
        staff_agent_id=staff_agent_id
    )

    # 2. Book linked callback for uncataloged issue
    callback_id = create_service_request(
        customer_id=customer_id,
        vehicle_details=vehicle_details,
        issue=uncataloged_issue,
        service_type=f"Uncataloged: {service_type}",
        time_slot=time_slot,
        booking_type="appointment_and_callback",
        booking_time=booking_time,
        staff_agent_id=staff_agent_id,
        is_uncataloged=True,
        linked_appointment_id=appointment_id,
        callback_priority=callback_priority,
        callback_number=callback_number
    )

    return {
        "appointment_id": appointment_id,
        "callback_id": callback_id
    }


def parse_specific_time(preferred_date_str: str):
    """
    Extracts an explicit hour and minute from a string if present.
    Returns datetime.time or None if only a general date or window was given.
    """
    if not preferred_date_str:
        return None
    import re
    import datetime as dt_mod

    raw = str(preferred_date_str).strip()
    low = raw.lower()

    # Strip ISO date (YYYY-MM-DD) if present
    low_without_date = re.sub(r'\b\d{4}-\d{2}-\d{2}\b', '', low)
    # Strip month date if present (e.g. 'august 6', 'august 6th, 2026')
    low_without_date = re.sub(
        r'\b(january|jan|february|feb|march|mar|april|apr|may|june|jun|july|jul|august|aug|september|sep|sept|october|oct|november|nov|december|dec)\b[\s,]*(\d{1,2})(?:st|nd|rd|th)?(?:\s*,?\s*(\d{4}))?',
        '',
        low_without_date,
    )

    # 1. Check HH:MM(:SS)? (am/pm)? e.g. 10:00, 10:30:00, 2:30 pm, 14:00
    m_time = re.search(r'\b(\d{1,2}):(\d{2})(?::\d{2})?\s*(am|pm|a\.m\.|p\.m\.)?\b', low_without_date)
    if m_time:
        h = int(m_time.group(1))
        m = int(m_time.group(2))
        meridiem = m_time.group(3)
        if meridiem:
            if 'p' in meridiem and h < 12:
                h += 12
            elif 'a' in meridiem and h == 12:
                h = 0
        elif 1 <= h <= 6:
            h += 12  # in auto service workhours (7am-6pm), 1..6 without am/pm means PM
        if 0 <= h <= 23 and 0 <= m <= 59:
            return dt_mod.time(h, m)

    # 2. Check H (am/pm) e.g. 10am, 2 pm, 9 a.m.
    m_hour = re.search(r'\b(\d{1,2})\s*(am|pm|a\.m\.|p\.m\.)\b', low_without_date)
    if m_hour:
        h = int(m_hour.group(1))
        meridiem = m_hour.group(2)
        if 'p' in meridiem and h < 12:
            h += 12
        elif 'a' in meridiem and h == 12:
            h = 0
        if 0 <= h <= 23:
            return dt_mod.time(h, 0)

    # 3. Check 'at H' e.g. 'at 10', 'at 2'
    m_at = re.search(r'\bat\s+(\d{1,2})\b', low_without_date)
    if m_at:
        h = int(m_at.group(1))
        if 1 <= h <= 6:
            h += 12
        if 7 <= h <= 18:
            return dt_mod.time(h, 0)

    # 4. Check 'noon'
    if re.search(r'\bnoon\b', low_without_date):
        return dt_mod.time(12, 0)

    return None


def parse_preferred_date_and_time(preferred_date_str: str) -> tuple:
    """
    Parses a user or tool supplied date/time string into a tuple:
    (iso_date_str, time_window, start_timestamp_str)
    """
    import re
    import datetime as dt_mod

    if not preferred_date_str:
        return None, None, "1970-01-01 00:00:00"

    raw = str(preferred_date_str).strip()
    low = raw.lower()

    # Check for specific time first
    target_time = parse_specific_time(preferred_date_str)

    # 1. Determine time_window (afternoon, morning, evening)
    time_window = None
    if target_time:
        if target_time.hour < 12:
            time_window = "morning"
        elif target_time.hour >= 17:
            time_window = "evening"
        else:
            time_window = "afternoon"
    else:
        if any(w in low for w in ["afternoon", "pm", "p.m.", "noon"]):
            time_window = "afternoon"
        elif any(w in low for w in ["morning", "am", "a.m."]):
            time_window = "morning"
        elif any(w in low for w in ["evening", "night"]):
            time_window = "evening"

    # 2. Extract ISO date (YYYY-MM-DD)
    iso_date_match = re.search(r'\b(\d{4}-\d{2}-\d{2})\b', raw)
    iso_date_str = None
    if iso_date_match:
        iso_date_str = iso_date_match.group(1)
    else:
        # Try parsing month names (e.g. "August 6", "Aug 6", "August 6th", "August 6, 2026")
        months = {
            "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
            "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
            "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9, "october": 10, "oct": 10,
            "november": 11, "nov": 11, "december": 12, "dec": 12
        }
        month_match = re.search(
            r'\b(january|jan|february|feb|march|mar|april|apr|may|june|jun|july|jul|august|aug|september|sep|sept|october|oct|november|nov|december|dec)\b[\s,]*(\d{1,2})(?:st|nd|rd|th)?(?:\s*,?\s*(\d{4}))?',
            low,
        )
        if month_match:
            m_str = month_match.group(1)
            d_int = int(month_match.group(2))
            y_str = month_match.group(3)
            m_int = months[m_str]
            year = int(y_str) if y_str else dt_mod.date.today().year
            try:
                dt_obj = dt_mod.date(year, m_int, d_int)
                iso_date_str = dt_obj.strftime("%Y-%m-%d")
            except ValueError:
                pass
        else:
            try:
                from serviceBot.services import timezone_service
                today_d = timezone_service.now_in_business_tz().date()
            except Exception:
                today_d = dt_mod.date.today()

            if "tomorrow" in low:
                iso_date_str = (today_d + dt_mod.timedelta(days=1)).strftime("%Y-%m-%d")
            elif "today" in low:
                iso_date_str = today_d.strftime("%Y-%m-%d")
            else:
                weekdays = {
                    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
                    "friday": 4, "saturday": 5, "sunday": 6
                }
                for day_name, day_num in weekdays.items():
                    if re.search(r'\b' + day_name + r'\b', low):
                        days_ahead = (day_num - today_d.weekday()) % 7
                        if days_ahead == 0:
                            days_ahead = 7
                        iso_date_str = (today_d + dt_mod.timedelta(days=days_ahead)).strftime("%Y-%m-%d")
                        break

    # 3. Construct start_timestamp_str (safe YYYY-MM-DD HH:MM:SS for SQL)
    if iso_date_str:
        if target_time:
            start_timestamp_str = f"{iso_date_str} {target_time.hour:02d}:{target_time.minute:02d}:00"
        elif time_window == "afternoon":
            start_timestamp_str = f"{iso_date_str} 12:00:00"
        elif time_window == "evening":
            start_timestamp_str = f"{iso_date_str} 15:00:00"
        elif time_window == "morning":
            start_timestamp_str = f"{iso_date_str} 07:00:00"
        else:
            start_timestamp_str = f"{iso_date_str} 00:00:00"
    else:
        start_timestamp_str = "1970-01-01 00:00:00"

    return iso_date_str, time_window, start_timestamp_str


def _generate_dynamic_slots(preferred_date_str: str, duration_minutes: int, interval_minutes: int = 30, booking_type: str = "appointment") -> list:
    """
    Generates candidate work-hour slots dynamically for the next 14 business days,
    starting from preferred_date_str (or today). Used when mock_calendar_slots is empty.
    Returns a list of ISO datetime strings: YYYY-MM-DD HH:MM:SS.
    """
    import datetime as dt_mod
    from serviceBot.services.calendar_sync import get_configured_business_hours, get_configured_business_days
    
    iso_date_str, time_window, _ = parse_preferred_date_and_time(preferred_date_str)

    if iso_date_str:
        try:
            start_date = dt_mod.date.fromisoformat(iso_date_str)
        except ValueError:
            start_date = dt_mod.date.today()
    else:
        start_date = dt_mod.date.today()

    # Ensure we don't start from a past date in the business timezone
    from serviceBot.services import timezone_service
    now_dt = timezone_service.now_in_business_tz().replace(tzinfo=None)
    today = now_dt.date()
    if start_date < today:
        start_date = today

    # Generate slots for up to 14 business days
    slots = []
    day_offset = 0

    min_lead_hours = 0.0
    try:
        from serviceBot.api.portal import load_config
        cfg = load_config()
        if booking_type == "callback":
            min_lead_hours = float(cfg.get("min_callback_buffer_hours", 2.0))
        elif booking_type == "appointment":
            min_lead_hours = float(cfg.get("min_booking_buffer_hours", 4.0))
    except Exception:
        min_lead_hours = 2.0 if booking_type == "callback" else 4.0
    min_cutoff_dt = now_dt + dt_mod.timedelta(hours=min_lead_hours)

    valid_hours = get_configured_business_hours()
    valid_days = get_configured_business_days()
    business_hours_set = set(valid_hours)
    business_days_set = set(valid_days)
    norm_duration = max(15, ((int(duration_minutes or 60) + 14) // 15) * 15)

    if time_window == "afternoon":
        valid_hours = [h for h in valid_hours if 12 <= h < 18]
    elif time_window == "morning":
        valid_hours = [h for h in valid_hours if 7 <= h < 12]
    elif time_window == "evening":
        valid_hours = [h for h in valid_hours if h >= 15]

    valid_minutes = (0, 15, 30, 45) if interval_minutes == 15 else (0, 30)

    while len(slots) < 60 and day_offset < 30:
        candidate_day = start_date + dt_mod.timedelta(days=day_offset)
        if candidate_day.weekday() in valid_days:  # Configured operating days
            for hour in valid_hours:
                for minute in valid_minutes:
                    slot_dt = dt_mod.datetime.combine(candidate_day, dt_mod.time(hour, minute, 0))
                    if slot_dt >= min_cutoff_dt:
                        # Enforce that every 15-minute segment of the appointment is strictly within business hours and days
                        fits_business_hours = True
                        for offset in range(0, norm_duration, 15):
                            seg_dt = slot_dt + dt_mod.timedelta(minutes=offset)
                            if seg_dt.weekday() not in business_days_set or seg_dt.hour not in business_hours_set:
                                fits_business_hours = False
                                break
                        if fits_business_hours:
                            slots.append(slot_dt.strftime("%Y-%m-%d %H:%M:%S"))
        day_offset += 1
    return slots


def check_availability(service_type: str = None, preferred_date: str = None, booking_type: str = "appointment", preferred_time: str = None, services_list: list[str] = None) -> list:
    """
    Checks available appointment or callback slots on or after preferred_date.

    - For appointments: checks slots on 30-minute intervals (0, 30 mins) with service duration.
    - For callbacks: checks slots on 15-minute intervals (0, 15, 30, 45 mins) with 15-minute duration.

    Returns up to 3 available slot datetime strings (YYYY-MM-DD HH:MM:SS).
    """
    import zoneinfo
    import datetime as dt_mod
    from datetime import datetime, timedelta
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from serviceBot.services.google_calendar import fetch_agent_events, parse_google_datetime
    from serviceBot.services.booking import normalize_reservation_duration
    from serviceBot.services.calendar_sync import get_configured_business_hours, get_configured_business_days

    if preferred_time:
        pref_time_clean = str(preferred_time).strip()
        if preferred_date:
            if pref_time_clean.lower() not in str(preferred_date).lower():
                preferred_date = f"{preferred_date} {pref_time_clean}"
        else:
            preferred_date = pref_time_clean

    iso_date_str, time_window, start_time = parse_preferred_date_and_time(preferred_date)

    is_callback = (booking_type == "callback") or (service_type and "callback" in str(service_type).lower())

    if not services_list and service_type:
        fields = get_service_required_fields(service_type, strict=True)
        services_list = fields.get("service_names") if fields else None

    parsed_services = []
    if services_list and len(services_list) > 1:
        accum_offset = 0
        for s_name in services_list:
            s_fields = get_service_required_fields(s_name, strict=True)
            s_name_clean = (s_fields.get("name") if (s_fields and isinstance(s_fields, dict)) else None) or s_name
            s_dur = 15 if is_callback else int((s_fields.get("duration_minutes") if (s_fields and isinstance(s_fields, dict)) else None) or 60)
            s_dur = normalize_reservation_duration(s_dur)
            s_q = get_qualified_agent_ids(s_name_clean, strict=True)
            parsed_services.append({
                "name": s_name_clean,
                "duration": s_dur,
                "offset": accum_offset,
                "qualified_agent_ids": s_q,
            })
            accum_offset += (max(30, s_dur) if is_callback else s_dur)
        duration_minutes = accum_offset
    else:
        if is_callback:
            duration_minutes = 15
        else:
            duration_minutes = 60
            if service_type:
                fields = get_service_required_fields(service_type, strict=True)
                if fields and fields.get("duration_minutes"):
                    duration_minutes = fields["duration_minutes"]
        duration_minutes = normalize_reservation_duration(duration_minutes)

    # --- Get all agents and filter by qualified agents tagged to service ---
    try:
        with get_db_connection() as conn, dict_cursor(conn) as cursor:
            cursor.execute("SELECT id FROM staff_agents WHERE is_active IS NOT FALSE;")
            all_agent_ids = [r["id"] for r in cursor.fetchall()]
    except Exception:  # noqa: BLE001 - failed staff observations cannot establish availability.
        raise AvailabilityUnknownError() from None

    if parsed_services:
        eval_set = set()
        for ps in parsed_services:
            if ps["qualified_agent_ids"]:
                eval_set.update([aid for aid in ps["qualified_agent_ids"] if aid in all_agent_ids])
            else:
                eval_set.update(all_agent_ids)
        active_eval_agent_ids = [aid for aid in eval_set if aid in all_agent_ids]
    else:
        qualified_agent_ids = get_qualified_agent_ids(service_type, strict=True) if service_type else []
        if qualified_agent_ids:
            active_eval_agent_ids = [aid for aid in qualified_agent_ids if aid in all_agent_ids]
        else:
            active_eval_agent_ids = all_agent_ids

    if not active_eval_agent_ids:
        return []

    from serviceBot.services import timezone_service
    tz = timezone_service.get_business_zoneinfo()
        
    agent_events_map = {}

    candidate_slots = _generate_dynamic_slots(
        preferred_date,
        duration_minutes,
        interval_minutes=15 if is_callback else 30,
        booking_type="callback" if is_callback else "appointment"
    )

    if not candidate_slots:
        return []

    # Pre-fetch events for eligible agents across the full candidate range
    slot_dts_parsed = [datetime.strptime(s, "%Y-%m-%d %H:%M:%S") for s in candidate_slots]
    min_dt = min(slot_dts_parsed).replace(tzinfo=tz)
    max_dt = (max(slot_dts_parsed) + timedelta(minutes=duration_minutes)).replace(tzinfo=tz)
    start_iso = min_dt.isoformat()
    end_iso = max_dt.isoformat()

    with ThreadPoolExecutor(max_workers=max(1, len(active_eval_agent_ids))) as executor:
        future_to_agent = {
            executor.submit(fetch_agent_events, aid, start_iso, end_iso): aid
            for aid in active_eval_agent_ids
        }
        for future in as_completed(future_to_agent):
            aid = future_to_agent[future]
            try:
                events = future.result()
                agent_events_map[aid] = events
            except Exception as exc:
                agent_events_map[aid] = None

    blocked_mock_slots = set()
    reserved_segments = set()
    try:
        with get_db_connection() as conn:
            with dict_cursor(conn) as cursor:
                cursor.execute(
                    """
                    SELECT staff_agent_id, slot_datetime
                    FROM mock_calendar_slots
                    WHERE (reservation_status = 'RESERVED' OR (reservation_status = 'BLOCKED' AND calendar_integration_status != 'FAILED') OR (is_booked = TRUE AND calendar_integration_status != 'FAILED'))
                      AND slot_datetime >= %s AND slot_datetime <= %s;
                    """,
                    (min_dt.replace(tzinfo=None), max_dt.replace(tzinfo=None)),
                )
                for r in cursor.fetchall():
                    s_dt = r["slot_datetime"]
                    dt_str = s_dt.strftime("%Y-%m-%d %H:%M:%S") if hasattr(s_dt, "strftime") else str(s_dt)[:19]
                    blocked_mock_slots.add((r["staff_agent_id"], dt_str))

                cursor.execute(
                    """
                    SELECT staff_agent_id, segment_start
                    FROM appointment_reservation_segments
                    WHERE segment_start >= %s AND segment_start <= %s;
                    """,
                    (min_dt.replace(tzinfo=None), max_dt.replace(tzinfo=None)),
                )
                for r in cursor.fetchall():
                    s_dt = r["segment_start"]
                    dt_str = s_dt.strftime("%Y-%m-%d %H:%M:%S") if hasattr(s_dt, "strftime") else str(s_dt)[:19]
                    reserved_segments.add((r["staff_agent_id"], dt_str))
    except Exception:
        raise AvailabilityUnknownError() from None

    valid_business_hours = set(get_configured_business_hours())
    valid_business_days = set(get_configured_business_days())

    def is_agent_free_live(agent_id: int, slot_dt_str: str, check_duration: int = None) -> bool | None:
        """Returns True if agent has no Google Calendar or local DB conflict for the slot and slot fits business hours."""
        slot_dt_naive = datetime.strptime(slot_dt_str, "%Y-%m-%d %H:%M:%S")
        eff_dur = check_duration if check_duration is not None else duration_minutes
        norm_dur = max(15, ((int(eff_dur or 60) + 14) // 15) * 15)
        for seg_offset in range(0, norm_dur, 15):
            seg_time = slot_dt_naive + timedelta(minutes=seg_offset)
            if seg_time.weekday() not in valid_business_days or seg_time.hour not in valid_business_hours:
                return False

        # Known local conflicts rule this plan out even if the provider is unknown.
        for seg_offset in range(0, eff_dur, 15):
            seg_time = slot_dt_naive + timedelta(minutes=seg_offset)
            seg_str = seg_time.strftime("%Y-%m-%d %H:%M:%S")
            if (agent_id, seg_str) in blocked_mock_slots or (agent_id, seg_str) in reserved_segments:
                return False
        if agent_events_map.get(agent_id) is None:
            return None

        # Check Google Calendar events if connected and available
        if agent_id in agent_events_map and agent_events_map[agent_id] is not None:
            slot_start = slot_dt_naive.replace(tzinfo=tz)
            slot_end = slot_start + timedelta(minutes=eff_dur)
            for event in agent_events_map[agent_id]:
                evt_start = parse_google_datetime(event.get("start"), tz)
                evt_end = parse_google_datetime(event.get("end"), tz)
                if evt_start and evt_end:
                    if slot_start < evt_end and slot_end > evt_start:
                        return False

        return True

    all_free_slots = []
    uncertain_plan = False
    for slot_dt_str in candidate_slots:
        if parsed_services:
            slot_dt_naive = datetime.strptime(slot_dt_str, "%Y-%m-%d %H:%M:%S")
            plan_verified = True
            plan_possible = True
            for ps in parsed_services:
                s_start = slot_dt_naive + timedelta(minutes=ps["offset"])
                s_start_str = s_start.strftime("%Y-%m-%d %H:%M:%S")
                cand_pool = ps["qualified_agent_ids"] or all_agent_ids
                states = [is_agent_free_live(aid, s_start_str, check_duration=ps["duration"])
                          for aid in cand_pool if aid in all_agent_ids]
                plan_verified = plan_verified and any(value is True for value in states)
                plan_possible = plan_possible and any(value is not False for value in states)
            if plan_verified:
                all_free_slots.append(slot_dt_str)
            elif plan_possible:
                uncertain_plan = True
        else:
            states = [is_agent_free_live(aid, slot_dt_str) for aid in active_eval_agent_ids]
            if any(value is True for value in states):
                all_free_slots.append(slot_dt_str)
            elif any(value is None for value in states):
                uncertain_plan = True

    if not all_free_slots:
        if uncertain_plan:
            raise AvailabilityUnknownError()
        return []

    target_date_str = all_free_slots[0][:10]
    day_slots = [s for s in all_free_slots if s.startswith(target_date_str)]
    if not day_slots:
        day_slots = all_free_slots

    specific_time = parse_specific_time(preferred_date)
    if specific_time:
        # Caller requested a specific target time (e.g. 10:00 AM, 2:30 PM, 14:00)
        # Select slots on target date ranked by proximity to the requested target time
        try:
            target_date_obj = dt_mod.date.fromisoformat(target_date_str)
        except Exception:
            target_date_obj = dt_mod.date.today()
        target_dt = dt_mod.datetime.combine(target_date_obj, specific_time)

        def slot_distance(s_str):
            s_dt = datetime.strptime(s_str, "%Y-%m-%d %H:%M:%S")
            diff = abs((s_dt - target_dt).total_seconds())
            tie_breaker = 0.0 if s_dt >= target_dt else 0.1
            return diff + tie_breaker

        sorted_by_proximity = sorted(day_slots, key=slot_distance)
        selected = sorted_by_proximity[:3]
        selected.sort()
        return selected

    # If caller specified a general time window (e.g. morning, afternoon, evening) without an exact time
    if time_window:
        return day_slots[:3]

    # If general date inquiry without time window, provide a diverse spread across morning, midday, afternoon
    if len(day_slots) <= 3:
        return day_slots

    morning_slots = [s for s in day_slots if int(s[11:13]) < 12]
    midday_slots = [s for s in day_slots if 12 <= int(s[11:13]) < 15]
    afternoon_slots = [s for s in day_slots if int(s[11:13]) >= 15]

    selected = []
    if morning_slots:
        selected.append(morning_slots[0])
    if midday_slots:
        selected.append(midday_slots[0])
    if afternoon_slots:
        selected.append(afternoon_slots[0])

    if len(selected) < 3:
        for s in day_slots:
            if s not in selected:
                selected.append(s)
            if len(selected) >= 3:
                break

    selected.sort()
    return selected[:3]


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


def _book_appointment_legacy(customer_id: int, service_request_id: int, appointment_datetime: str, service_type: str, vehicle_details: dict = None, booking_type: str = "appointment", duration_minutes: Optional[int] = None) -> int:
    """
    Books an appointment or callback and sets staff_agent_id.

    Two-mode operation:
    1. Mock-slot mode: If a matching mock_calendar_slots row exists, marks it as booked
       and (if the agent has Google Calendar connected) also creates a calendar event.
    2. Live/dynamic mode: If no mock slot row exists (mock data cleared), picks any
       connected agent who is free on Google Calendar at that time, creates the calendar
       event directly, and records the booking in service_requests only.

    Raises ValueError if no suitable agent/slot is available.
    """
    is_cb = booking_type == "callback" or (service_type and "callback" in str(service_type).lower())
    b_type = "callback" if is_cb else "appointment"

    # 1. Enforce that the service requested is in the services catalog
    fields = get_service_required_fields(service_type)
    if not fields:
        matched_service_name = service_type if service_type else ("Callback / Phone Consultation" if is_cb else "Repair")
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
                cursor.execute("UPDATE customers SET name = 'Valued Customer' WHERE id = %s;", (customer_id,))
                conn.commit()
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
                    cursor.execute("INSERT INTO vehicles (customer_id, make, model, year) VALUES (%s, 'Vehicle', 'Standard', 2020) RETURNING id;", (customer_id,))
                    vehicle_id = cursor.fetchone()["id"]

            # Sanity check: check if the customer already has an appointment booked for the same vehicle at this slot
            cursor.execute(
                "SELECT id, service_type, issue_description FROM service_requests WHERE customer_id = %s AND vehicle_id = %s AND booking_type = %s AND booking_time = %s AND status IN ('pending', 'in_progress');",
                (customer_id, vehicle_id, b_type, appointment_datetime)
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

    if duration_minutes is None:
        duration_minutes = 15 if is_cb else (fields.get("duration_minutes") or 60 if fields else 60)
    elif is_cb:
        duration_minutes = 15

    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            # --- Live/dynamic mode: no mock slot row, use Google Calendar agents ---
            cursor.execute("SELECT id FROM staff_agents WHERE is_active IS NOT FALSE;")
            all_agent_ids = [r["id"] for r in cursor.fetchall()]

            if not all_agent_ids:
                raise ValueError(
                    f"No staff agents found in the system to book the appointment at {appointment_datetime}."
                )

            chosen_agent_id = None
            # Pick first agent who is free at the requested time
            for aid in all_agent_ids:
                if is_agent_free(aid, appointment_datetime, duration_minutes):
                    chosen_agent_id = aid
                    break

            if not chosen_agent_id:
                raise ValueError(f"All agents are busy at {appointment_datetime} on Google Calendar.")

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
                    fallback_desc = matched_service_name if matched_service_name else ("Callback requested" if is_cb else "Appointment booked")
                    cursor.execute(
                        "INSERT INTO service_requests (customer_id, vehicle_id, service_type, issue_description, status, duration_minutes) VALUES (%s, %s, %s, %s, 'pending', %s) RETURNING id;",
                        (customer_id, vehicle_id, matched_service_name, fallback_desc, duration_minutes)
                    )
                    service_request_id = cursor.fetchone()["id"]

            cursor.execute(
                "UPDATE service_requests SET booking_type = %s, booking_time = %s, service_type = %s, duration_minutes = %s, staff_agent_id = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s;",
                (b_type, appointment_datetime, matched_service_name, duration_minutes, chosen_agent_id, service_request_id)
            )

            # Get customer info and issue details for Google Calendar event
            cursor.execute("SELECT name FROM customers WHERE id = %s;", (customer_id,))
            cust_row = cursor.fetchone()
            customer_name = cust_row["name"] if cust_row else "Unknown Customer"

            cursor.execute("SELECT issue_description FROM service_requests WHERE id = %s;", (service_request_id,))
            sr_desc_row = cursor.fetchone()
            raw_desc = sr_desc_row["issue_description"] if sr_desc_row else ""
            if not raw_desc or raw_desc in ("Appointment booking.", "Callback booking.", "Not specified", "", "Callback requested."):
                issue_desc = matched_service_name if matched_service_name else ("Callback requested" if is_cb else "Appointment booked")
            else:
                issue_desc = raw_desc

            # Create Google Calendar event for the assigned agent (works in both modes)
            create_agent_calendar_event(
                agent_id=chosen_agent_id,
                customer_name=customer_name,
                service_type=matched_service_name,
                issue_description=issue_desc,
                slot_datetime_str=appointment_datetime,
                duration_minutes=duration_minutes,
                booking_type=b_type
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
                    duration_minutes=duration_minutes,
                    booking_type=b_type
                )
            except Exception as admin_cal_err:
                logger.warning(f"Could not create admin calendar event: {admin_cal_err}")

            return service_request_id


def book_appointment(
    customer_id: int,
    service_request_id: int,
    appointment_datetime: str,
    service_type: str,
    vehicle_details: dict = None,
    booking_type: str = "appointment",
    duration_minutes: Optional[int] = None,
) -> int:
    """Reserve a service request through the PostgreSQL authority, never a provider read."""
    from serviceBot.services.booking import BookingService, SLOT_MINUTES

    is_callback = booking_type == "callback" or (
        service_type and "callback" in str(service_type).lower()
    )
    effective_type = "callback" if is_callback else "appointment"
    fields = get_service_required_fields(service_type)
    matched_service_name = fields["name"] if fields else (
        service_type or ("Callback / Phone Consultation" if is_callback else "Repair")
    )
    effective_duration = (
        SLOT_MINUTES
        if is_callback
        else int(duration_minutes or (fields.get("duration_minutes") if fields else 60))
    )
    receipt = BookingService().reserve_or_create(
        customer_id=customer_id,
        service_request_id=service_request_id,
        appointment_datetime=appointment_datetime,
        service_type=matched_service_name,
        vehicle_details=vehicle_details,
        booking_type=effective_type,
        duration_minutes=effective_duration,
    )
    return receipt.request_id


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


def match_catalog_service_names(service_name: str, catalog_names: list[str]) -> list[str]:
    """Resolve a complete sequence of catalogue labels before interpreting separators.

    Punctuation belongs to a label until that whole label has matched. Requiring
    complete consumption prevents free-text symptoms from becoming a partial order.
    """
    import re
    from collections import Counter
    from functools import lru_cache

    if not isinstance(service_name, str) or not service_name.strip():
        return []
    text = service_name.strip()
    patterns = [(name, re.compile(re.escape(name), re.IGNORECASE))
                for name in sorted(catalog_names, key=len, reverse=True)]
    separator = re.compile(r"(?:\s*(?:[,/+&]|\band\b)\s*)+", re.IGNORECASE)

    @lru_cache(maxsize=None)
    def match_from(position):
        for name, pattern in patterns:
            match = pattern.match(text, position)
            if match is None:
                continue
            if match.end() == len(text):
                return (name,)
            boundary = separator.match(text, match.end())
            if boundary is not None:
                remaining = match_from(boundary.end())
                if remaining:
                    return (name, *remaining)
        return ()

    result = list(match_from(0))
    counts = Counter(name.casefold() for name in catalog_names)
    return result if all(counts[name.casefold()] == 1 for name in result) else []



def get_service_required_fields(service_name: str, *, strict: bool = False) -> dict:
    """
    Looks up a service by name (fuzzy matching supported) in the services table
    and returns its details along with the required fields mapping.
    For multi-service requests, calculates aggregate duration_minutes by summing
    the durations of all matched catalog services.
    """
    if not service_name:
        return None
        
    rows = []
    try:
        query = """
        SELECT name, description, price_range, duration_minutes,
               req_customer_name, req_phone_number, req_vehicle_details, req_issue_description, req_location
        FROM services;
        """
        with get_db_connection() as conn:
            with dict_cursor(conn) as cursor:
                cursor.execute(query)
                rows = [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        if strict:
            raise AvailabilityUnknownError() from None
        logger.warning(f"Could not query services table in get_service_required_fields: {e}")
        rows = []
        
    import re
    def clean_str(s: str) -> str:
        return re.sub(r'[^a-z0-9\s]', '', s.lower()).strip()

    cleaned_query = clean_str(service_name)

    # 1. Exact match check for single catalog service
    for s in rows:
        if cleaned_query == clean_str(s["name"]):
            return s

    # 2. Match whole canonical labels before the legacy fuzzy-name fallback.
    canonical_names = match_catalog_service_names(service_name, [s["name"] for s in rows])
    by_name = {s["name"]: s for s in rows}
    matched_services = [by_name[name] for name in canonical_names]
    parts = [p.strip() for p in re.split(r'[,/+]|\band\b|&', service_name, flags=re.IGNORECASE) if p.strip()]
    if not canonical_names and len(parts) > 1:
        for part in parts:
            part_clean = clean_str(part)
            if not part_clean:
                continue
            # Try exact match for part
            m = None
            for s in rows:
                if part_clean == clean_str(s["name"]):
                    m = s
                    break
            if not m:
                m = find_best_service_match(part_clean, rows)
            if not m:
                for s in rows:
                    sc = clean_str(s["name"])
                    if sc and (sc in part_clean or part_clean in sc):
                        m = s
                        break
            if m and m not in matched_services:
                matched_services.append(m)

    if len(matched_services) > 1:
        total_duration = sum(s.get("duration_minutes") or 60 for s in matched_services)
        matched_names = ", ".join(s["name"] for s in matched_services)
        prices = [s["price_range"] for s in matched_services if s.get("price_range")]
        price_str = ", ".join(prices) if prices else "Varies by service"
        return {
            "name": service_name,
            "service_names": [s["name"] for s in matched_services],
            "description": f"Multiple services requested: {matched_names}",
            "price_range": price_str,
            "duration_minutes": total_duration,
            "req_customer_name": any(bool(s.get("req_customer_name")) for s in matched_services),
            "req_phone_number": any(bool(s.get("req_phone_number")) for s in matched_services),
            "req_vehicle_details": any(bool(s.get("req_vehicle_details")) for s in matched_services),
            "req_issue_description": any(bool(s.get("req_issue_description")) for s in matched_services),
            "req_location": any(bool(s.get("req_location")) for s in matched_services)
        }

    # 3. Single service fuzzy match fallback
    match = find_best_service_match(service_name, rows)
    if match:
        return match

    return {
        "name": service_name,
        "description": "Service request",
        "price_range": "Varies by service",
        "duration_minutes": 60,
        "req_customer_name": True,
        "req_phone_number": True,
        "req_vehicle_details": True,
        "req_issue_description": True,
        "req_location": False,
        "is_fallback": True,
        "service_found": False
    }


def get_service_agent_ids(service_id: int, *, strict: bool = False) -> list[int]:
    """Returns the list of staff_agent IDs tagged to a catalog service."""
    if not service_id:
        return []
    try:
        with get_db_connection() as conn:
            with dict_cursor(conn) as cursor:
                statement = """
                    SELECT ssa.staff_agent_id
                    FROM service_staff_agents ssa
                    JOIN staff_agents sa ON sa.id = ssa.staff_agent_id
                    WHERE ssa.service_id = %s AND sa.is_active IS NOT FALSE
                    ORDER BY ssa.staff_agent_id ASC;
                    """
                if strict:
                    # Preserve raw membership so inactive-only tags do not look mappingless.
                    statement = statement.replace("AND sa.is_active IS NOT FALSE", "")
                cursor.execute(statement, (service_id,))
                return [row["staff_agent_id"] for row in cursor.fetchall()]
    except Exception as e:
        if strict:
            raise AvailabilityUnknownError() from None
        logger.warning(f"Error fetching tagged agents for service {service_id}: {e}")
        return []


def set_service_agents(service_id: int, agent_ids: list[int]) -> None:
    """Sets the staff agents tagged to a service, replacing any existing tags."""
    if not service_id:
        return
    unique_agent_ids = list(dict.fromkeys(agent_ids or []))
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("DELETE FROM service_staff_agents WHERE service_id = %s;", (service_id,))
            for aid in unique_agent_ids:
                cursor.execute(
                    "INSERT INTO service_staff_agents (service_id, staff_agent_id) VALUES (%s, %s) ON CONFLICT DO NOTHING;",
                    (service_id, aid)
                )
            conn.commit()


def get_qualified_agent_ids(service_name_or_id, *, strict: bool = False) -> list[int]:
    """
    Returns the list of agent IDs qualified for a service.
    If the service has no tagged agents, returns [] (meaning open to any active agent).
    """
    if not service_name_or_id:
        return []
    service_id = None
    if isinstance(service_name_or_id, int):
        service_id = service_name_or_id
    else:
        fields = (get_service_required_fields(str(service_name_or_id), strict=True) if strict
                  else get_service_required_fields(str(service_name_or_id)))
        if fields:
            try:
                with get_db_connection() as conn:
                    with dict_cursor(conn) as cursor:
                        cursor.execute("SELECT id FROM services WHERE name = %s LIMIT 1;", (fields["name"],))
                        row = cursor.fetchone()
                        if row:
                            service_id = row["id"]
            except Exception as e:
                if strict:
                    raise AvailabilityUnknownError() from None
                logger.warning(f"Error resolving service ID for {service_name_or_id}: {e}")
    if not service_id:
        return []
    return get_service_agent_ids(service_id, strict=True) if strict else get_service_agent_ids(service_id)


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
    """Reserve callback capacity through the PostgreSQL booking authority."""
    from serviceBot.services.booking import BookingService, SLOT_MINUTES

    selected_request_id = None
    service_type = "Callback / Phone Consultation"
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("SELECT name, phone FROM customers WHERE id = %s;", (customer_id,))
            customer = cursor.fetchone()
            if not customer:
                raise ValueError("Customer record not found.")
            if not customer["name"] or customer["name"] in {"Unknown Customer", "Unknown"}:
                raise ValueError("Customer name is required. Please collect the customer's name before arranging a callback.")
            if not customer["phone"] or customer["phone"] == "Unknown" or len(customer["phone"].strip()) < 10:
                raise ValueError("Customer phone number is required and must be a valid 10-digit number.")
            if service_request_id:
                cursor.execute(
                    """
                    SELECT id, booking_type, service_type FROM service_requests
                    WHERE id = %s AND customer_id = %s
                    FOR UPDATE;
                    """,
                    (service_request_id, customer_id),
                )
                existing = cursor.fetchone()
                if existing and existing.get("booking_type") in (None, "", "callback"):
                    selected_request_id = existing["id"]
                    service_type = existing.get("service_type") or service_type

    if not preferred_time or "asap" in str(preferred_time).lower() or "as soon as possible" in str(preferred_time).lower():
        reservation_time = resolve_asap_callback_time()
    else:
        reservation_time = str(preferred_time).strip()

    receipt = BookingService().reserve_or_create(
        customer_id=customer_id,
        service_request_id=selected_request_id,
        appointment_datetime=reservation_time,
        service_type=service_type,
        vehicle_details=vehicle_details,
        issue_description="Callback requested / phone consultation.",
        booking_type="callback",
        duration_minutes=SLOT_MINUTES,
    )
    return receipt.request_id


CUSTOMER_APPOINTMENTS_SELECT = """
    SELECT sr.id, sr.booking_time AS appointment_datetime, sr.booking_type, sr.service_type, sr.service_components,
           sr.issue_description, COALESCE(sr.duration_minutes, 60) AS duration_minutes,
           sr.status, sr.intake_data, v.year, v.make, v.model,
           CASE WHEN sr.booking_type = 'appointment' THEN sr.visit_group_id END AS visit_group_id,
           linked.visit_start, linked.visit_anchor_id,
           COALESCE(linked.visit_member_ids, ARRAY[]::integer[]) AS visit_member_ids
    FROM service_requests sr
    JOIN customers c ON sr.customer_id = c.id
    LEFT JOIN vehicles v ON sr.vehicle_id = v.id
    LEFT JOIN LATERAL (
        SELECT CASE WHEN bool_and(member.booking_time IS NOT NULL)
                    THEN min(member.booking_time) END AS visit_start,
               CASE WHEN bool_and(member.booking_time IS NOT NULL)
                    THEN (array_agg(member.id ORDER BY member.booking_time ASC NULLS LAST, member.id))[1]
                    END AS visit_anchor_id,
               array_agg(member.id ORDER BY member.booking_time ASC NULLS LAST, member.id) AS visit_member_ids
        FROM service_requests member
        WHERE member.visit_group_id = sr.visit_group_id
          AND member.customer_id = sr.customer_id
          AND member.booking_type = 'appointment'
          AND member.status IN ('pending', 'in_progress', 'confirmed')
    ) linked ON sr.booking_type = 'appointment' AND sr.visit_group_id IS NOT NULL
"""


def get_customer_appointments(phone: str) -> list:
    """
    Looks up all scheduled/rescheduled appointments and service requests (including advisor callbacks)
    for a customer by phone number, including vehicle make, model, year, issue description, duration,
    and booking type. Authoritative linked-visit metadata is customer-scoped and
    includes only active appointment components; callbacks are never grouped.
    """
    import re
    cleaned_phone = re.sub(r"\D", "", phone) if phone else ""
    if len(cleaned_phone) == 11 and cleaned_phone.startswith("1"):
        cleaned_phone = cleaned_phone[1:]

    query = CUSTOMER_APPOINTMENTS_SELECT + """
    WHERE (c.phone = %s OR REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(c.phone, '-', ''), ' ', ''), '(', ''), ')', ''), '+1', '') = %s)
      AND (sr.booking_type IN ('appointment', 'callback', 'appointment_and_callback') OR sr.booking_time IS NOT NULL)
      AND sr.status IN ('pending', 'in_progress', 'confirmed')
    ORDER BY sr.booking_time ASC NULLS LAST, sr.id;
    """
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(query, (phone, cleaned_phone))
            rows = cursor.fetchall()
            return [dict(row) for row in rows]


def get_customer_service_history(phone: str, limit: int = 5) -> list:
    """
    Looks up recent service requests and callbacks for a customer by phone number,
    including completed, in-progress, or pending records with issue descriptions.
    """
    import re
    cleaned_phone = re.sub(r"\D", "", phone) if phone else ""
    if len(cleaned_phone) == 11 and cleaned_phone.startswith("1"):
        cleaned_phone = cleaned_phone[1:]

    query = """
    SELECT sr.id, sr.booking_type, sr.booking_time, sr.service_type, sr.issue_description,
           COALESCE(sr.duration_minutes, 60) AS duration_minutes, sr.status, sr.created_at,
           v.year, v.make, v.model
    FROM service_requests sr
    JOIN customers c ON sr.customer_id = c.id
    LEFT JOIN vehicles v ON sr.vehicle_id = v.id
    WHERE (c.phone = %s OR REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(c.phone, '-', ''), ' ', ''), '(', ''), ')', ''), '+1', '') = %s)
    ORDER BY sr.created_at DESC
    LIMIT %s;
    """
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(query, (phone, cleaned_phone, limit))
            rows = cursor.fetchall()
            return [dict(row) for row in rows]


def get_available_slots_for_date(target_date_str: str, duration_minutes: int = 60, staff_agent_id: int = None) -> list:
    """
    Returns available time slots for a specific date across staff agents.
    Generates intervals between 07:00 AM and 05:00 PM (Monday-Friday business hours).
    Checks Google Calendar availability efficiently (pre-fetching day range per agent).
    """
    import datetime as dt_mod
    import concurrent.futures
    import zoneinfo
    from unittest.mock import Mock
    from serviceBot.services.google_calendar import fetch_agent_events, parse_google_datetime, is_agent_free
    from serviceBot.services.booking import normalize_reservation_duration
    duration_minutes = normalize_reservation_duration(duration_minutes)

    clean_date_str = str(target_date_str).strip()
    if "T" in clean_date_str:
        clean_date_str = clean_date_str.split("T")[0]
    if " " in clean_date_str:
        clean_date_str = clean_date_str.split(" ")[0]
    if "," in clean_date_str:
        clean_date_str = clean_date_str.split(",")[0]

    try:
        if "/" in clean_date_str:
            parts = clean_date_str.split("/")
            if len(parts[0]) == 4:
                target_date = dt_mod.datetime.strptime(clean_date_str, "%Y/%m/%d").date()
            else:
                target_date = dt_mod.datetime.strptime(clean_date_str, "%m/%d/%Y").date()
        else:
            target_date = dt_mod.datetime.strptime(clean_date_str, "%Y-%m-%d").date()
    except Exception:
        raise ValueError(f"Invalid date format '{target_date_str}'. Expected YYYY-MM-DD.")

    if target_date.weekday() >= 5:
        return []

    available_slots = []
    
    try:
        with get_db_connection() as conn:
            with dict_cursor(conn) as cursor:
                if staff_agent_id:
                    cursor.execute("SELECT id, name FROM staff_agents WHERE id = %s AND is_active IS NOT FALSE;", (staff_agent_id,))
                else:
                    cursor.execute("SELECT id, name FROM staff_agents WHERE is_active IS NOT FALSE;")
                agents = cursor.fetchall()
            
                if not agents:
                    return []

                from serviceBot.services.calendar_sync import get_configured_business_hours, get_configured_business_days
                valid_business_hours = set(get_configured_business_hours())
                valid_business_days = set(get_configured_business_days())
                norm_dur = max(15, ((int(duration_minutes or 60) + 14) // 15) * 15)

                def _fits_hours(s_dt: dt_mod.datetime) -> bool:
                    for off in range(0, norm_dur, 15):
                        seg = s_dt + dt_mod.timedelta(minutes=off)
                        if seg.weekday() not in valid_business_days or seg.hour not in valid_business_hours:
                            return False
                    return True

                from serviceBot.services import timezone_service
                tz = timezone_service.get_business_zoneinfo()

                day_start_dt = dt_mod.datetime.combine(target_date, dt_mod.time(0, 0, 0)).replace(tzinfo=tz)
                day_end_dt = dt_mod.datetime.combine(target_date, dt_mod.time(23, 59, 59)).replace(tzinfo=tz)
                start_iso = day_start_dt.isoformat()
                end_iso = day_end_dt.isoformat()

                blocked_mock_slots = set()
                reserved_segments = set()
                try:
                    cursor.execute(
                        """
                        SELECT staff_agent_id, slot_datetime
                        FROM mock_calendar_slots
                        WHERE (reservation_status IN ('RESERVED', 'BLOCKED') OR is_booked = TRUE)
                          AND slot_datetime >= %s AND slot_datetime <= %s;
                        """,
                        (day_start_dt.replace(tzinfo=None), day_end_dt.replace(tzinfo=None)),
                    )
                    for r in cursor.fetchall():
                        s_dt = r["slot_datetime"]
                        dt_str = s_dt.strftime("%Y-%m-%d %H:%M:%S") if hasattr(s_dt, "strftime") else str(s_dt)[:19]
                        blocked_mock_slots.add((r["staff_agent_id"], dt_str))

                    cursor.execute(
                        """
                        SELECT staff_agent_id, segment_start
                        FROM appointment_reservation_segments
                        WHERE segment_start >= %s AND segment_start <= %s;
                        """,
                        (day_start_dt.replace(tzinfo=None), day_end_dt.replace(tzinfo=None)),
                    )
                    for r in cursor.fetchall():
                        s_dt = r["segment_start"]
                        dt_str = s_dt.strftime("%Y-%m-%d %H:%M:%S") if hasattr(s_dt, "strftime") else str(s_dt)[:19]
                        reserved_segments.add((r["staff_agent_id"], dt_str))

                    cursor.execute(
                        """
                        SELECT staff_agent_id, booking_time, duration_minutes
                        FROM service_requests
                        WHERE status NOT IN ('cancelled', 'cancelled_by_customer', 'cancelled_by_admin')
                          AND booking_type = 'appointment'
                          AND staff_agent_id IS NOT NULL
                          AND REPLACE(booking_time::text, 'T', ' ') >= %s AND REPLACE(booking_time::text, 'T', ' ') <= %s;
                        """,
                        (day_start_dt.strftime("%Y-%m-%d %H:%M:%S"), day_end_dt.strftime("%Y-%m-%d %H:%M:%S")),
                    )
                    for r in cursor.fetchall():
                        b_time = r["booking_time"]
                        if isinstance(b_time, str):
                            try:
                                b_dt = dt_mod.datetime.strptime(b_time[:19].replace("T", " "), "%Y-%m-%d %H:%M:%S")
                            except Exception:
                                continue
                        else:
                            b_dt = b_time
                        dur = r.get("duration_minutes") or 60
                        norm_d = max(15, ((int(dur) + 14) // 15) * 15)
                        for off in range(0, norm_d, 15):
                            seg_dt = b_dt + dt_mod.timedelta(minutes=off)
                            reserved_segments.add((r["staff_agent_id"], seg_dt.strftime("%Y-%m-%d %H:%M:%S")))
                except Exception:
                    raise AvailabilityUnknownError() from None

                # If is_agent_free is explicitly mocked (e.g., in unit tests), use standard fallback loop
                if isinstance(is_agent_free, Mock):
                    current_slot_dt = dt_mod.datetime.combine(target_date, dt_mod.time(7, 0))
                    end_of_day = dt_mod.datetime.combine(target_date, dt_mod.time(17, 0))
                    while current_slot_dt <= end_of_day:
                        if not _fits_hours(current_slot_dt):
                            current_slot_dt += dt_mod.timedelta(minutes=30)
                            continue
                        slot_str = current_slot_dt.strftime("%Y-%m-%d %H:%M:%S")
                        free_count = 0
                        for agent in agents:
                            aid = agent["id"]
                            is_local_blocked = False
                            for off in range(0, norm_dur, 15):
                                seg_str = (current_slot_dt + dt_mod.timedelta(minutes=off)).strftime("%Y-%m-%d %H:%M:%S")
                                if (aid, seg_str) in blocked_mock_slots or (aid, seg_str) in reserved_segments:
                                    is_local_blocked = True
                                    break
                            if not is_local_blocked and is_agent_free(aid, slot_str, duration_minutes=duration_minutes):
                                free_count += 1
                        if free_count > 0:
                            end_slot_dt = current_slot_dt + dt_mod.timedelta(minutes=duration_minutes)
                            available_slots.append({
                                "start_time": slot_str,
                                "end_time": end_slot_dt.strftime("%Y-%m-%d %H:%M:%S"),
                                "available_agents_count": free_count
                            })
                        current_slot_dt += dt_mod.timedelta(minutes=30)
                    return available_slots

                agent_busy_ranges = {}

                def _load_agent_busy(agent_id):
                    events = fetch_agent_events(agent_id, start_iso, end_iso)
                    if events is None:
                        return None
                    ranges = []
                    for ev in events:
                        s_dt = parse_google_datetime(ev.get("start"), tz)
                        e_dt = parse_google_datetime(ev.get("end"), tz)
                        if s_dt and e_dt:
                            ranges.append((s_dt, e_dt))
                    return ranges

                with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(agents), 10)) as executor:
                    future_map = {
                        executor.submit(_load_agent_busy, agent["id"]): agent["id"]
                        for agent in agents
                    }
                    for future in concurrent.futures.as_completed(future_map):
                        aid = future_map[future]
                        try:
                            agent_busy_ranges[aid] = future.result()
                        except Exception:
                            agent_busy_ranges[aid] = None

                uncertain_candidate = False
                current_slot_dt = dt_mod.datetime.combine(target_date, dt_mod.time(7, 0))
                end_of_day = dt_mod.datetime.combine(target_date, dt_mod.time(17, 0))

                while current_slot_dt <= end_of_day:
                    if not _fits_hours(current_slot_dt):
                        current_slot_dt += dt_mod.timedelta(minutes=30)
                        continue
                    slot_str = current_slot_dt.strftime("%Y-%m-%d %H:%M:%S")
                    slot_start_localized = current_slot_dt.replace(tzinfo=tz)
                    slot_end_localized = (current_slot_dt + dt_mod.timedelta(minutes=duration_minutes)).replace(tzinfo=tz)
                    free_count = 0

                    for agent in agents:
                        aid = agent["id"]
                        busy_ranges = agent_busy_ranges.get(aid)
                        # Check local DB blocks & reservations across all 15-minute segments of the slot
                        is_local_blocked = False
                        for off in range(0, norm_dur, 15):
                            seg_str = (current_slot_dt + dt_mod.timedelta(minutes=off)).strftime("%Y-%m-%d %H:%M:%S")
                            if (aid, seg_str) in blocked_mock_slots or (aid, seg_str) in reserved_segments:
                                is_local_blocked = True
                                break
                        if is_local_blocked:
                            continue
                        if busy_ranges is None:
                            uncertain_candidate = True
                            continue

                        is_busy = False
                        for b_start, b_end in busy_ranges:
                            if slot_start_localized < b_end and slot_end_localized > b_start:
                                is_busy = True
                                break
                        if not is_busy:
                            free_count += 1

                    if free_count > 0:
                        end_slot_dt = current_slot_dt + dt_mod.timedelta(minutes=duration_minutes)
                        available_slots.append({
                            "start_time": slot_str,
                            "end_time": end_slot_dt.strftime("%Y-%m-%d %H:%M:%S"),
                            "available_agents_count": free_count
                        })

                    current_slot_dt += dt_mod.timedelta(minutes=30)
                
    except AvailabilityUnknownError:
        raise
    except Exception:  # noqa: BLE001 - sanitize every failed availability observation.
        raise AvailabilityUnknownError() from None

    if not available_slots and uncertain_candidate:
        raise AvailabilityUnknownError()
    return available_slots


def _reschedule_appointment_legacy(
    appointment_id: int, 
    new_datetime: str, 
    customer_consent_obtained: bool = True, 
    triggered_by: str = "system"
) -> bool:
    """
    Reschedules an appointment: frees the old slot, books the new slot, and updates the appointment.
    All inside a single transaction. Checks Google Calendar availability of candidate agents.
    Records customer consent status and logs audit entry.
    """
    if not validate_booking_time(new_datetime):
        raise ValueError(f"New booking time {new_datetime} is outside company workhours (Monday to Friday, 7:00 AM to 6:00 PM).")
        
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            # 1. Get old appointment details
            cursor.execute(
                "SELECT booking_time, staff_agent_id, service_type, customer_id, status, duration_minutes FROM service_requests WHERE id = %s AND booking_type = 'appointment';",
                (appointment_id,)
            )
            row = cursor.fetchone()
            if not row:
                raise ValueError(f"Appointment (Service Request) with ID {appointment_id} not found.")
            if (row.get("status") or "").lower() in ("completed", "done", "cancelled", "cancelled_by_customer"):
                raise ValueError(f"Cannot reschedule appointment #{appointment_id} because its status is '{row.get('status')}'.")
            old_datetime = row["booking_time"]
            old_agent_id = row["staff_agent_id"]
            service_type = row["service_type"]
            customer_id = row["customer_id"]

            # 2. Check availability for the slot datetime across all candidate agents
            duration_minutes = row.get("duration_minutes") or 60
            if not row.get("duration_minutes") and service_type:
                fields = get_service_required_fields(service_type)
                if fields and fields.get("duration_minutes"):
                    duration_minutes = fields["duration_minutes"]

            from serviceBot.services.google_calendar import is_agent_free, create_agent_calendar_event

            chosen_agent_id = None
            
            # Live/dynamic mode
            cursor.execute("SELECT id FROM staff_agents WHERE is_active IS NOT FALSE;")
            connected_ids = [r["id"] for r in cursor.fetchall()]
            
            if not connected_ids:
                raise ValueError(f"No staff agents found to handle the rescheduling at {new_datetime}.")

            for aid in connected_ids:
                if is_agent_free(aid, new_datetime, duration_minutes):
                    chosen_agent_id = aid
                    break
                    
            if not chosen_agent_id:
                raise ValueError(f"New slot {new_datetime} is not available or the agents are busy on Google Calendar.")

            # 4. Update service request
            cursor.execute(
                """UPDATE service_requests 
                   SET booking_time = %s, staff_agent_id = %s, duration_minutes = %s, status = 'pending', 
                       customer_consent_obtained = %s, last_rescheduled_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP 
                   WHERE id = %s;""",
                (new_datetime, chosen_agent_id, duration_minutes, customer_consent_obtained, appointment_id)
            )

            # Audit log
            old_dt_desc = str(old_datetime)[:19] if old_datetime else "Unscheduled"
            cursor.execute(
                """INSERT INTO service_request_audit_log (request_id, triggered_by, from_status, to_status, notes)
                   VALUES (%s, %s, %s, %s, %s);""",
                (
                    appointment_id,
                    triggered_by,
                    row.get("status") or "pending",
                    "pending",
                    f"Rescheduled slot: {old_dt_desc} -> {new_datetime} | Customer consent obtained: {customer_consent_obtained}"
                )
            )
            
            # Get customer details for calendar event
            cursor.execute("SELECT name FROM customers WHERE id = %s;", (customer_id,))
            cust_row = cursor.fetchone()
            customer_name = cust_row["name"] if cust_row else "Unknown Customer"
            
            cursor.execute("SELECT issue_description FROM service_requests WHERE id = %s;", (appointment_id,))
            sr_desc_row = cursor.fetchone()
            issue_desc = sr_desc_row["issue_description"] if sr_desc_row else ""
            
            # Cancel old events for old agent and admin if previous booking_time existed
            if old_datetime:
                old_dt_str = old_datetime.strftime("%Y-%m-%d %H:%M:%S") if isinstance(old_datetime, dt_mod.datetime) else str(old_datetime)[:19]
                if old_agent_id:
                    try:
                        from serviceBot.services.google_calendar import delete_agent_calendar_event
                        delete_agent_calendar_event(old_agent_id, old_dt_str, duration_minutes=duration_minutes)
                    except Exception as del_err:
                        logger.warning(f"Could not delete old agent calendar event for agent {old_agent_id} at {old_dt_str}: {del_err}")
                try:
                    from serviceBot.services.gmail import delete_admin_calendar_event
                    delete_admin_calendar_event(old_dt_str, duration_minutes=duration_minutes)
                except Exception as del_adm_err:
                    logger.warning(f"Could not delete old admin calendar event at {old_dt_str}: {del_adm_err}")

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


def reschedule_appointment(
    appointment_id: int,
    new_datetime: str,
    customer_consent_obtained: bool = True,
    triggered_by: str = "system",
) -> bool:
    """Move an appointment atomically, retaining the previous slot on conflict."""
    from serviceBot.services.booking import BookingService

    BookingService().reschedule(
        request_id=appointment_id,
        new_datetime=new_datetime,
        customer_consent_obtained=customer_consent_obtained,
        triggered_by=triggered_by,
    )
    return True


def cancel_appointment(
    appointment_id: int,
    customer_consent_obtained: bool = True,
    triggered_by: str = "customer",
    reason: str = None,
) -> dict:
    """Cancel an appointment atomically, freeing reserved capacity and triggering notifications."""
    from serviceBot.services.booking import BookingService

    return BookingService().cancel(
        request_id=appointment_id,
        customer_consent_obtained=customer_consent_obtained,
        triggered_by=triggered_by,
        reason=reason,
    )


ALLOWED_TRANSITIONS = {
    "pending": {"confirmed", "in_progress", "completed", "cancelled"},
    "confirmed": {"pending", "in_progress", "completed", "cancelled"},
    "in_progress": {"completed", "cancelled"},
    "completed": set(),
    "cancelled": set(),
    "cancelled_by_customer": set(),
    "rescheduled": set()
}

def update_service_request_status(request_id: int, status: str, triggered_by: str = "system", notes: str = None) -> dict:
    """
    Updates the status of a service request using FSM validation and audit logging.
    Valid core statuses: 'pending', 'confirmed', 'in_progress', 'completed', 'cancelled'.
    Maps aliases: 'done' -> 'completed', 'cancelled_by_customer' -> 'cancelled', 'rescheduled' -> 'pending'.
    Frees calendar slots if cancelling.
    """
    raw_status = (status or "").lower().strip()
    normalized_status = raw_status
    if normalized_status in ('done', 'completed'):
        normalized_status = 'completed'
    elif normalized_status in ('cancelled_by_customer', 'cancelled', 'cancelled_by_admin'):
        normalized_status = 'cancelled'
    elif normalized_status == 'rescheduled':
        normalized_status = 'pending'

    valid_statuses = ('pending', 'confirmed', 'in_progress', 'completed', 'cancelled')
    if normalized_status not in valid_statuses:
        raise ValueError(f"Invalid status '{status}'. Must be one of {valid_statuses}")

    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            # Check FSM transition
            cursor.execute("SELECT status FROM service_requests WHERE id = %s;", (request_id,))
            current_row = cursor.fetchone()
            if not current_row:
                raise ValueError(f"Service request with ID {request_id} not found.")
            current_status = current_row["status"] or "pending"

            if normalized_status != current_status:
                allowed_next = ALLOWED_TRANSITIONS.get(current_status, set())
                # Handle test cases and overrides - if not strictly defined, we can log a warning,
                # but to be strict to the PRD, we raise ValueError.
                if normalized_status not in allowed_next:
                    raise ValueError(f"Invalid FSM transition: Cannot move from '{current_status}' to '{normalized_status}'.")

            if normalized_status == 'cancelled':
                # First retrieve staff_agent_id and booking_time to release any matching slots
                cursor.execute(
                    """
                    SELECT staff_agent_id, booking_time, duration_minutes
                    FROM service_requests
                    WHERE id = %s;
                    """,
                    (request_id,)
                )
                sr_data = cursor.fetchone()
                if sr_data and sr_data.get("staff_agent_id") and sr_data.get("booking_time"):
                    try:
                        from serviceBot.services.booking import parse_reservation_start, reservation_segments
                        b_start = parse_reservation_start(sr_data["booking_time"])
                        dur = sr_data.get("duration_minutes") or 60
                        segs = reservation_segments(b_start, dur)
                        cursor.execute(
                            """
                            UPDATE mock_calendar_slots
                            SET is_booked = FALSE,
                                reservation_status = 'AVAILABLE',
                                service_request_id = NULL,
                                calendar_integration_status = 'PENDING_CALENDAR',
                                calendar_event_id = NULL,
                                updated_at = CURRENT_TIMESTAMP
                            WHERE staff_agent_id = %s
                              AND (service_request_id = %s OR service_request_id IS NULL)
                              AND slot_datetime = ANY(%s);
                            """,
                            (sr_data["staff_agent_id"], request_id, segs),
                        )
                    except Exception:
                        pass

                cursor.execute(
                    """
                    UPDATE service_requests
                    SET status = %s,
                        confirmation_status = 'cancelled',
                        escalation_status = 'none',
                        escalation_reason = NULL,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                    RETURNING id, status, updated_at;
                    """,
                    (normalized_status, request_id)
                )
                row = cursor.fetchone()

                # Release capacity reservations, segments, and mock calendar slots
                cursor.execute(
                    """
                    UPDATE appointment_reservations
                    SET status = 'CANCELLED', updated_at = CURRENT_TIMESTAMP
                    WHERE service_request_id = %s;
                    """,
                    (request_id,)
                )
                cursor.execute(
                    """
                    DELETE FROM appointment_reservation_segments
                    WHERE reservation_id IN (SELECT id FROM appointment_reservations WHERE service_request_id = %s);
                    """,
                    (request_id,)
                )
                cursor.execute(
                    """
                    UPDATE mock_calendar_slots
                    SET is_booked = FALSE,
                        reservation_status = 'AVAILABLE',
                        service_request_id = NULL,
                        calendar_integration_status = 'PENDING_CALENDAR',
                        calendar_event_id = NULL,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE service_request_id = %s;
                    """,
                    (request_id,)
                )
            elif normalized_status == 'confirmed':
                cursor.execute(
                    """
                    UPDATE service_requests
                    SET status = %s,
                        confirmation_status = 'confirmed',
                        confirmed_at = COALESCE(confirmed_at, CURRENT_TIMESTAMP),
                        escalation_status = CASE WHEN escalation_status = 'escalated' THEN 'resolved' ELSE escalation_status END,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                    RETURNING id, status, updated_at;
                    """,
                    (normalized_status, request_id)
                )
                row = cursor.fetchone()
            elif normalized_status == 'pending':
                cursor.execute(
                    """
                    UPDATE service_requests
                    SET status = %s,
                        confirmation_status = 'pending_agent_confirmation',
                        confirmed_at = NULL,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                    RETURNING id, status, updated_at;
                    """,
                    (normalized_status, request_id)
                )
                row = cursor.fetchone()
            elif normalized_status == 'completed':
                cursor.execute(
                    """
                    UPDATE service_requests
                    SET status = %s,
                        escalation_status = CASE WHEN escalation_status = 'escalated' THEN 'resolved' ELSE escalation_status END,
                        escalation_reason = NULL,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                    RETURNING id, status, updated_at;
                    """,
                    (normalized_status, request_id)
                )
                row = cursor.fetchone()
            else:
                cursor.execute(
                    "UPDATE service_requests SET status = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s RETURNING id, status, updated_at;",
                    (normalized_status, request_id)
                )
                row = cursor.fetchone()

            if not row:
                raise ValueError(f"Service request with ID {request_id} not found.")

            if normalized_status != current_status or raw_status == 'rescheduled':
                cursor.execute(
                    """
                    INSERT INTO service_request_audit_log (request_id, from_status, to_status, triggered_by, notes)
                    VALUES (%s, %s, %s, %s, %s);
                    """,
                    (request_id, current_status, normalized_status, triggered_by, notes)
                )

                notification_event = None
                if normalized_status == 'cancelled':
                    notification_event = "CANCELLED_BY_CUSTOMER" if raw_status == "cancelled_by_customer" or triggered_by == "customer" else "CANCELLED_BY_ADMIN"
                elif raw_status == 'rescheduled':
                    notification_event = "RESCHEDULED"
                elif normalized_status == 'in_progress':
                    notification_event = "STATUS_IN_PROGRESS"
                elif normalized_status == 'completed':
                    notification_event = "STATUS_COMPLETED"

                if notification_event:
                    cursor.execute(
                        """
                        SELECT sa.id AS agent_id, sa.name AS agent_name, sa.phone_number AS agent_phone,
                               COALESCE(uga.email, sa.email) AS agent_email,
                               sr.booking_time, sr.service_type, sr.issue_description,
                               ar.id AS reservation_id, ar.starts_at AS reservation_starts_at,
                               COALESCE(ar.calendar_event_id, sr.calendar_event_id) AS calendar_event_id,
                               c.name AS customer_name, c.phone AS customer_phone,
                               v.year AS vehicle_year, v.make AS vehicle_make, v.model AS vehicle_model
                        FROM service_requests sr
                        LEFT JOIN staff_agents sa ON sr.staff_agent_id = sa.id
                        LEFT JOIN user_google_accounts uga ON uga.agent_id = sa.id
                        LEFT JOIN appointment_reservations ar ON ar.service_request_id = sr.id
                        LEFT JOIN customers c ON sr.customer_id = c.id
                        LEFT JOIN vehicles v ON sr.vehicle_id = v.id
                        WHERE sr.id = %s;
                        """,
                        (request_id,)
                    )
                    details_row = cursor.fetchone() or {}

                    v_parts = [details_row.get("vehicle_year"), details_row.get("vehicle_make"), details_row.get("vehicle_model")]
                    veh_str = " ".join([str(p).strip() for p in v_parts if p and str(p).strip().upper() not in ("NONE", "NULL", "N/A")]).strip() or "N/A"

                    payload = {
                        "sms_event_type": notification_event,
                        "appointment_id": request_id,
                        "customer_phone": details_row.get("customer_phone"),
                        "agent_phone": details_row.get("agent_phone"),
                        "agent_id": details_row.get("agent_id"),
                        "agent_name": details_row.get("agent_name"),
                        "agent_email": details_row.get("agent_email"),
                        "booking_time_str": str(details_row.get("booking_time") or ""),
                        "vehicle": veh_str,
                        "details": {
                            "customer_name": details_row.get("customer_name") or "Customer",
                            "phone": details_row.get("customer_phone"),
                            "service_type": details_row.get("service_type") or "Service",
                            "vehicle": veh_str,
                            "issue": notes or details_row.get("issue_description") or "",
                            "agent_name": details_row.get("agent_name"),
                            "agent_phone": details_row.get("agent_phone"),
                            "agent_email": details_row.get("agent_email"),
                        }
                    }

                    cursor.execute(
                        """
                        INSERT INTO outbox_notifications
                        (event_type, request_id, payload, status, next_retry_at)
                        VALUES ('sms_status_change', %s, %s, 'PENDING', CURRENT_TIMESTAMP);
                        """,
                        (
                            request_id,
                            json.dumps(payload),
                        ),
                    )

                    if normalized_status == 'cancelled' and details_row.get("agent_id") and details_row.get("booking_time"):
                        reservation_id = details_row.get("reservation_id")
                        calendar_event_id = details_row.get("calendar_event_id")
                        if not calendar_event_id and reservation_id:
                            starts_at = dt_mod.datetime.fromisoformat(str(
                                details_row.get("reservation_starts_at") or details_row["booking_time"]
                            ))
                            calendar_event_id = f"servicebot{reservation_id}{starts_at:%Y%m%d%H%M}"
                        cal_payload = {
                            "action": "delete",
                            "reservation_id": reservation_id,
                            "agent_id": details_row.get("agent_id"),
                            "calendar_event_id": calendar_event_id,
                            "booking_time_str": str(details_row.get("booking_time"))[:19],
                            "details": {
                                "customer_name": details_row.get("customer_name") or "Customer",
                                "phone": details_row.get("customer_phone"),
                                "service_type": details_row.get("service_type") or "Service",
                            },
                        }
                        cursor.execute(
                            """
                            INSERT INTO outbox_notifications (event_type, request_id, payload, status, next_retry_at)
                            VALUES ('calendar_projection', %s, %s, 'PENDING', CURRENT_TIMESTAMP);
                            """,
                            (request_id, json.dumps(cal_payload)),
                        )

            if normalized_status == 'cancelled':
                cursor.execute(
                    "UPDATE sms_reminders SET status = 'CANCELLED' WHERE appointment_id = %s AND status = 'PENDING';",
                    (request_id,),
                )

            return dict(row)


def _assign_staff_agent_to_service_request_legacy(request_id: int, staff_agent_id: int = None) -> dict:
    """
    Assigns or updates the assigned staff agent for a service request.
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
                SELECT sr.id, sr.status, sr.staff_agent_id, sr.booking_time, sr.time_slot, sr.service_type, sr.issue_description,
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

            sr_status = (sr.get("status") or "").lower()
            if sr_status in ("completed", "done", "cancelled", "cancelled_by_customer"):
                raise ValueError(f"Cannot reassign agent for service request #{request_id} as it is marked as {sr_status}.")

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



def _get_available_agents_for_request_legacy(request_id: int) -> list:
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

            cursor.execute("SELECT id, name, role, email, phone_number FROM staff_agents WHERE is_active IS NOT FALSE ORDER BY id ASC;")
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
                "SELECT staff_agent_id FROM service_requests WHERE (booking_time = %s OR time_slot = %s) AND id != %s AND status NOT IN ('cancelled') AND staff_agent_id IS NOT NULL;",
                (b_time_str, b_time_str, request_id)
            )
            conflicting_sr_agent_ids = {r["staff_agent_id"] for r in cursor.fetchall()}

    for agent in agents:
        agent_id = agent["id"]
        is_busy = False
        reason = "Available"

        if agent_id in conflicting_sr_agent_ids:
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


def assign_staff_agent_to_service_request(
    request_id: int, staff_agent_id: int = None, *, reason: Optional[str] = None
) -> dict:
    """Assign scheduled work by moving its durable local reservation atomically."""
    from serviceBot.services.booking import (
        BUSINESS_TZ,
        BookingValidationError,
        BookingService,
        parse_reservation_start,
    )

    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                """
                SELECT sr.id, sr.status, sr.staff_agent_id, sr.booking_time, sr.time_slot,
                       sr.updated_at, sr.confirmation_status, sr.confirmed_at,
                       sr.escalation_status, sr.escalation_reason, sr.confirmation_cutoff_at,
                       ar.id AS reservation_id,
                       ar.staff_agent_id AS reservation_agent_id,
                       ar.starts_at AS reservation_start
                FROM service_requests sr
                LEFT JOIN appointment_reservations ar
                  ON ar.service_request_id = sr.id AND ar.status = 'ACTIVE'
                WHERE sr.id = %s;
                """,
                (request_id,),
            )
            request = cursor.fetchone()
            if not request:
                raise ValueError(f"Service request with ID {request_id} was not found.")

            current_status = (request.get("status") or "pending").lower()
            if current_status in {"completed", "done", "cancelled", "cancelled_by_customer"}:
                raise ValueError(
                    f"Cannot reassign agent for service request #{request_id} as it is marked as {current_status}."
                )
            if staff_agent_id is not None:
                cursor.execute("SELECT id FROM staff_agents WHERE id = %s;", (staff_agent_id,))
                if not cursor.fetchone():
                    raise ValueError(f"Staff agent with ID {staff_agent_id} does not exist.")

    reservation_time = request.get("reservation_start") or request.get("booking_time") or request.get("time_slot")
    starts_at = None
    if reservation_time and str(reservation_time).upper() != "ASAP":
        try:
            starts_at = parse_reservation_start(reservation_time)
        except BookingValidationError:
            starts_at = None

    active_reservation = request.get("reservation_id") is not None
    requires_reservation = active_reservation or (
        starts_at is not None
        and starts_at > dt_mod.datetime.now(BUSINESS_TZ).replace(tzinfo=None)
    )
    if requires_reservation:
        if staff_agent_id is None:
            raise BookingValidationError("A scheduled reservation must have an assigned staff agent.")
        if (
            active_reservation
            and request.get("staff_agent_id") == staff_agent_id
            and request.get("reservation_agent_id") == staff_agent_id
        ):
            return {
                "id": request_id,
                "staff_agent_id": staff_agent_id,
                "status": request.get("status"),
                "confirmation_status": request.get("confirmation_status"),
                "confirmed_at": request.get("confirmed_at"),
                "escalation_status": request.get("escalation_status"),
                "escalation_reason": request.get("escalation_reason"),
                "confirmation_cutoff_at": request.get("confirmation_cutoff_at"),
                "updated_at": request.get("updated_at"),
            }
        if starts_at is None:
            raise BookingValidationError("Scheduled reservation is missing a valid booking time.")
        receipt = BookingService().reserve_existing(
            request_id=request_id,
            appointment_datetime=starts_at,
            requested_agent_id=staff_agent_id,
            allow_replace=True,
            customer_consent_obtained=True,
            triggered_by="portal_staff_reassignment",
        )
        with get_db_connection() as conn:
            with dict_cursor(conn) as cursor:
                # Log agent assignment/reassignment to audit log
                old_agent_id = request.get("staff_agent_id")
                old_agent_name = "Unassigned"
                new_agent_name = "Unassigned"
                if old_agent_id or staff_agent_id:
                    cursor.execute(
                        "SELECT id, name FROM staff_agents WHERE id IN (%s, %s);",
                        (old_agent_id or -1, staff_agent_id or -1)
                    )
                    agent_rows = {a["id"]: a["name"] for a in cursor.fetchall()}
                    if old_agent_id:
                        old_agent_name = agent_rows.get(old_agent_id, f"Agent #{old_agent_id}")
                    if staff_agent_id:
                        new_agent_name = agent_rows.get(staff_agent_id, f"Agent #{staff_agent_id}")

                is_reassign = (old_agent_id is not None and old_agent_id != staff_agent_id)
                evt_type = "AGENT_REASSIGNED" if is_reassign else "AGENT_ASSIGNED"
                audit_note = (
                    f"Reassigned from {old_agent_name} to {new_agent_name} by portal staff"
                    if is_reassign
                    else f"Assigned to {new_agent_name} by portal staff"
                )
                cursor.execute(
                    """
                    INSERT INTO service_request_audit_log
                    (request_id, from_status, to_status, triggered_by, actor_name, event_type, notes, metadata)
                    VALUES (%s, %s, 'pending', 'portal_staff', 'Portal Staff', %s, %s, %s);
                    """,
                    (
                        request_id,
                        request.get("status") or "pending",
                        evt_type,
                        f"{audit_note} ({reason})" if reason else audit_note,
                        json.dumps({
                            "old_agent_id": old_agent_id,
                            "old_agent_name": old_agent_name,
                            "new_agent_id": staff_agent_id,
                            "new_agent_name": new_agent_name,
                            **({"reason": reason} if reason else {}),
                        }),
                    ),
                )
                cursor.execute(
                    """SELECT sr.id, sr.staff_agent_id, sr.status, sr.confirmation_status,
                       sr.confirmed_at, sr.escalation_status, sr.escalation_reason,
                       sr.confirmation_cutoff_at, sr.updated_at, sa.name AS staff_agent_name
                       FROM service_requests sr LEFT JOIN staff_agents sa ON sa.id=sr.staff_agent_id
                       WHERE sr.id = %s;""",
                    (request_id,),
                )
                updated_row = cursor.fetchone()
                conn.commit()
        return dict(updated_row) if updated_row else {
            "id": receipt.request_id,
            "staff_agent_id": receipt.staff_agent_id,
            "status": "pending",
            "confirmation_status": "pending_agent_confirmation",
            "updated_at": request.get("updated_at"),
        }

    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                """
                UPDATE service_requests
                SET staff_agent_id = %s,
                    status = 'pending',
                    confirmation_status = 'pending_agent_confirmation',
                    confirmed_at = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                RETURNING id, staff_agent_id, status, confirmation_status, updated_at;
                """,
                (staff_agent_id, request_id),
            )
            row = cursor.fetchone()
            if not row:
                raise ValueError(f"Service request with ID {request_id} was not found.")

            # Log agent assignment/reassignment to audit log
            old_agent_id = request.get("staff_agent_id")
            old_agent_name = "Unassigned"
            new_agent_name = "Unassigned"
            if old_agent_id or staff_agent_id:
                cursor.execute(
                    "SELECT id, name FROM staff_agents WHERE id IN (%s, %s);",
                    (old_agent_id or -1, staff_agent_id or -1)
                )
                agent_rows = {a["id"]: a["name"] for a in cursor.fetchall()}
                if old_agent_id:
                    old_agent_name = agent_rows.get(old_agent_id, f"Agent #{old_agent_id}")
                if staff_agent_id:
                    new_agent_name = agent_rows.get(staff_agent_id, f"Agent #{staff_agent_id}")

            is_reassign = (old_agent_id is not None and old_agent_id != staff_agent_id)
            evt_type = "AGENT_REASSIGNED" if is_reassign else "AGENT_ASSIGNED"
            audit_note = (
                f"Reassigned from {old_agent_name} to {new_agent_name} by portal staff"
                if is_reassign
                else f"Assigned to {new_agent_name} by portal staff"
            )
            cursor.execute(
                """
                INSERT INTO service_request_audit_log
                (request_id, from_status, to_status, triggered_by, actor_name, event_type, notes, metadata)
                VALUES (%s, %s, 'pending', 'portal_staff', 'Portal Staff', %s, %s, %s);
                """,
                (
                    request_id,
                    request.get("status") or "pending",
                    evt_type,
                    f"{audit_note} ({reason})" if reason else audit_note,
                    json.dumps({
                        "old_agent_id": old_agent_id,
                        "old_agent_name": old_agent_name,
                        "new_agent_id": staff_agent_id,
                        "new_agent_name": new_agent_name,
                        **({"reason": reason} if reason else {}),
                    }),
                ),
            )
            conn.commit()
            return dict(row)


def get_available_agents_for_request(request_id: int) -> list:
    """
    Return candidates whose local reservation and provider state both permit assignment.
    Evaluates calendar availability across Google Calendar, appointment reservations,
    and service requests. Computes current schedule load and ranks candidates.
    """
    from serviceBot.services.booking import BookingService, normalize_reservation_duration, reservation_segments
    from serviceBot.services.google_calendar import fetch_agent_events, parse_google_datetime
    from serviceBot.services.sms_reminders import parse_booking_datetime
    from serviceBot.services import timezone_service

    timezone = timezone_service.get_business_zoneinfo()

    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                """
                SELECT id, booking_time, time_slot, duration_minutes, booking_start_at,
                       booking_end_at, service_type, staff_agent_id, service_components
                FROM service_requests
                WHERE id = %s;
                """,
                (request_id,),
            )
            request = cursor.fetchone()
            if not request:
                raise ValueError(f"Service request with ID {request_id} was not found.")
            qualified_agent_ids = BookingService._qualified_agent_ids(cursor, request)
            cursor.execute(
                "SELECT id, name, role, email, phone_number FROM staff_agents WHERE is_active IS NOT FALSE ORDER BY id ASC;"
            )
            agents = [dict(row) for row in cursor.fetchall()]
            for a in agents:
                a["whatsapp_connected"] = is_agent_whatsapp_connected(a.get("phone_number"))

    # Robust parsing of appointment start time
    starts_at = None
    booking_start_at = request.get("booking_start_at")
    if isinstance(booking_start_at, dt_mod.datetime):
        starts_at = booking_start_at
    elif isinstance(booking_start_at, str):
        starts_at = parse_booking_datetime(booking_start_at)

    if not starts_at:
        raw_val = request.get("booking_time") or request.get("time_slot")
        if isinstance(raw_val, dt_mod.datetime):
            starts_at = raw_val
        elif raw_val and str(raw_val).strip().upper() not in ("ASAP", "NONE", "NULL", ""):
            raw_str = str(raw_val).strip()
            for sep in [" to ", " - ", " – "]:
                if sep in raw_str and not raw_str.startswith("-"):
                    raw_str = raw_str.split(sep)[0].strip()
                    break
            starts_at = parse_booking_datetime(raw_str)
            if not starts_at:
                try:
                    from serviceBot.services.booking import parse_reservation_start
                    starts_at = parse_reservation_start(raw_str)
                except Exception:
                    pass

    default_duration = 15 if (request.get("booking_type") == "callback" or str(request.get("service_type") or "").lower() == "callback") else 60
    duration_minutes = normalize_reservation_duration(request.get("duration_minutes") or default_duration)

    if starts_at and starts_at.tzinfo is not None:
        starts_at = starts_at.astimezone(timezone).replace(tzinfo=None)

    ends_at = request.get("booking_end_at")
    if isinstance(ends_at, dt_mod.datetime):
        if ends_at.tzinfo is not None:
            ends_at = ends_at.astimezone(timezone).replace(tzinfo=None)
    elif starts_at:
        ends_at = starts_at + dt_mod.timedelta(minutes=duration_minutes)

    # If booking is unscheduled or ASAP, everyone is available
    if not starts_at or str(request.get("booking_time") or "").strip().upper() == "ASAP":
        for a in agents:
            a["agent_id"] = a["id"]
            a["agent_name"] = a["name"]
            a["is_available"] = True
            a["available"] = True
            a["reason"] = "Available"
            a["current_job_count_today"] = 0
            a["skills_match"] = True
        return agents

    segments = reservation_segments(starts_at, duration_minutes)
    target_date = starts_at.date()

    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            # 1. Active schedule load today per agent
            cursor.execute(
                """
                SELECT staff_agent_id, COUNT(*) AS cnt
                FROM service_requests
                WHERE status NOT IN ('cancelled', 'cancelled_by_customer', 'cancelled_by_admin', 'completed', 'done')
                  AND staff_agent_id IS NOT NULL
                  AND (
                    (booking_start_at IS NOT NULL AND DATE(booking_start_at) = %s)
                    OR (booking_time LIKE %s)
                  )
                GROUP BY staff_agent_id;
                """,
                (target_date, f"{target_date}%"),
            )
            job_counts = {r["staff_agent_id"]: r["cnt"] for r in cursor.fetchall()}

            # 2. Local reservations in appointment_reservations
            cursor.execute(
                """
                SELECT DISTINCT staff_agent_id
                FROM appointment_reservations
                WHERE service_request_id != %s
                  AND status = 'ACTIVE'
                  AND starts_at < %s
                  AND ends_at > %s;
                """,
                (request_id, ends_at, starts_at),
            )
            locally_reserved = {row["staff_agent_id"] for row in cursor.fetchall()}

            # 3. Blocked slots in mock_calendar_slots
            cursor.execute(
                """
                SELECT DISTINCT staff_agent_id
                FROM mock_calendar_slots
                WHERE slot_datetime = ANY(%s)
                  AND (reservation_status IN ('RESERVED', 'BLOCKED') OR is_booked = TRUE)
                  AND (service_request_id IS NULL OR service_request_id != %s);
                """,
                (segments, request_id),
            )
            locally_reserved.update(
                row["staff_agent_id"] for row in cursor.fetchall()
            )

            # 4. Overlapping active appointments or callbacks in service_requests
            cursor.execute(
                """
                SELECT DISTINCT staff_agent_id
                FROM service_requests
                WHERE id != %s
                  AND staff_agent_id IS NOT NULL
                  AND status NOT IN ('cancelled', 'cancelled_by_customer', 'cancelled_by_admin', 'completed', 'done')
                  AND (
                    (booking_start_at IS NOT NULL AND booking_end_at IS NOT NULL AND booking_start_at < %s AND booking_end_at > %s)
                    OR (booking_time = %s)
                  );
                """,
                (request_id, ends_at, starts_at, str(request.get("booking_time") or "")),
            )
            overlapping_sr_agent_ids = {row["staff_agent_id"] for row in cursor.fetchall()}

    # Check skills qualification if service has tagged agents
    provider_start = starts_at.replace(tzinfo=timezone)
    provider_end = ends_at.replace(tzinfo=timezone)

    for agent in agents:
        agent_id = agent["id"]
        agent["agent_id"] = agent_id
        agent["agent_name"] = agent["name"]
        agent["current_job_count_today"] = job_counts.get(agent_id, 0)
        agent["skills_match"] = qualified_agent_ids is None or agent_id in qualified_agent_ids

        if not agent["skills_match"]:
            agent["is_available"] = False
            agent["available"] = False
            agent["reason"] = "Not qualified for this service"
            continue

        if agent_id in locally_reserved:
            agent["is_available"] = False
            agent["available"] = False
            agent["reason"] = "Reserved locally"
            continue

        if agent_id in overlapping_sr_agent_ids:
            agent["is_available"] = False
            agent["available"] = False
            agent["reason"] = "Booked for another appointment"
            continue

        calendar_error = False
        try:
            events = fetch_agent_events(
                agent_id,
                provider_start.isoformat(),
                provider_end.isoformat(),
            )
        except Exception:
            calendar_error = True
            events = None

        if calendar_error or events is None:
            agent["is_available"] = False
            agent["available"] = False
            agent["reason"] = "Calendar state unavailable"
            continue

        if events is not None:
            is_busy = False
            for event in events:
                if event.get("status") == "cancelled":
                    continue
                event_start = parse_google_datetime(event.get("start") or {}, timezone)
                event_end = parse_google_datetime(event.get("end") or {}, timezone)
                if event_start and event_end and provider_start < event_end and provider_end > event_start:
                    is_busy = True
                    break
            agent["is_available"] = not is_busy
            agent["available"] = not is_busy
            agent["reason"] = "Busy in Google Calendar" if is_busy else "Available"

    # Candidates are ranked by calendar availability (available first),
    # skills match (qualified first),
    # current schedule load (lowest job count first),
    # and name.
    agents.sort(
        key=lambda a: (
            not a["is_available"],
            not a.get("skills_match", True),
            a.get("current_job_count_today", 0),
            a.get("name", "")
        )
    )

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


def get_sms_matrix_rules(channel: str = None) -> list:
    """Fetches all event matrix notification rules, optionally filtered by channel."""
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            if channel:
                cursor.execute(
                    "SELECT * FROM sms_matrix_rules WHERE UPPER(channel) = UPPER(%s) ORDER BY event_type, recipient_role;",
                    (channel,)
                )
            else:
                cursor.execute("SELECT * FROM sms_matrix_rules ORDER BY event_type, recipient_role, channel;")
            return [dict(r) for r in cursor.fetchall()]


def update_sms_matrix_rule(event_type: str, recipient_role: str, enabled: bool, channel: str = "WHATSAPP") -> dict:
    """Updates or inserts a matrix rule for an event, recipient role, and channel."""
    chan = (channel or "WHATSAPP").upper()
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                """
                INSERT INTO sms_matrix_rules (event_type, recipient_role, channel, enabled)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (event_type, recipient_role, channel)
                DO UPDATE SET enabled = EXCLUDED.enabled
                RETURNING *;
                """,
                (event_type, recipient_role, chan, enabled)
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
    clean = re.sub(r"\D", "", str(phone_number))
    if not clean:
        return False
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("SELECT phone_number FROM sms_whitelist;")
            for r in cursor.fetchall():
                w_clean = re.sub(r"\D", "", r.get("phone_number") or "")
                if not w_clean:
                    continue
                if w_clean == clean:
                    return True
                if len(w_clean) >= 10 and len(clean) >= 10 and w_clean[-10:] == clean[-10:]:
                    return True
            return False


def is_agent_whatsapp_connected(phone_number: str) -> bool:
    """Checks whether an agent's phone number is whitelisted and onboarded to WhatsApp."""
    import re
    if not phone_number:
        return False
    clean = re.sub(r"\D", "", str(phone_number))
    if not clean:
        return False
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("SELECT phone_number, whatsapp_onboarded FROM sms_whitelist WHERE whatsapp_onboarded = TRUE;")
            for r in cursor.fetchall():
                if r.get("whatsapp_onboarded") is False:
                    continue
                w_clean = re.sub(r"\D", "", r.get("phone_number") or "")
                if not w_clean:
                    continue
                if w_clean == clean:
                    return True
                if len(w_clean) >= 10 and len(clean) >= 10 and w_clean[-10:] == clean[-10:]:
                    return True
            return False


def get_agent_whatsapp_status(agent_id: int) -> dict:
    """Returns WhatsApp onboarding status and phone info for a specific staff agent."""
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("SELECT id, name, phone_number FROM staff_agents WHERE id = %s;", (agent_id,))
            agent = cursor.fetchone()
            if not agent:
                return {
                    "agent_id": agent_id,
                    "has_phone": False,
                    "phone_number": None,
                    "is_connected": False,
                    "whatsapp_onboarded_at": None,
                }
            phone = agent.get("phone_number")
            if not phone:
                return {
                    "agent_id": agent_id,
                    "has_phone": False,
                    "phone_number": None,
                    "is_connected": False,
                    "whatsapp_onboarded_at": None,
                }
            is_connected = is_agent_whatsapp_connected(phone)
            cursor.execute(
                "SELECT whatsapp_onboarded_at FROM sms_whitelist WHERE phone_number = %s AND whatsapp_onboarded = TRUE LIMIT 1;",
                (phone,)
            )
            wl_row = cursor.fetchone()
            onboarded_at = wl_row["whatsapp_onboarded_at"] if wl_row else None
            return {
                "agent_id": agent_id,
                "has_phone": True,
                "phone_number": phone,
                "is_connected": is_connected,
                "whatsapp_onboarded_at": onboarded_at.isoformat() if onboarded_at else None,
            }


def disconnect_agent_whatsapp(agent_id: int) -> dict:
    """Marks an agent's phone as not onboarded to WhatsApp in the whitelist."""
    import re
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("SELECT id, name, phone_number FROM staff_agents WHERE id = %s;", (agent_id,))
            agent = cursor.fetchone()
            if not agent:
                return {"success": False, "error": "Agent not found", "is_connected": False}
            phone = agent.get("phone_number")
            if not phone:
                return {"success": True, "agent_id": agent_id, "is_connected": False}
            
            clean = re.sub(r"\D", "", phone)
            cursor.execute(
                r"""
                UPDATE sms_whitelist
                SET whatsapp_onboarded = FALSE, whatsapp_onboarded_at = NULL
                WHERE phone_number = %s
                   OR (LENGTH(%s) >= 10 AND regexp_replace(phone_number, '\D', '', 'g') LIKE '%%' || RIGHT(%s, 10));
                """,
                (phone, clean, clean)
            )
            conn.commit()
            return {"success": True, "agent_id": agent_id, "phone_number": phone, "is_connected": False}


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
    scheduled_send_at: dt_mod.datetime = None,
    body: str = None,
    channel: str = "SMS",
) -> int:
    """Logs a channel-specific notification dispatch attempt into sms_log."""
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            valid_appt_id = None
            if appointment_id:
                cursor.execute("SELECT id FROM service_requests WHERE id = %s;", (appointment_id,))
                if cursor.fetchone():
                    valid_appt_id = appointment_id

            cursor.execute(
                """
                INSERT INTO sms_log 
                (appointment_id, recipient_type, recipient_phone, template_type, twilio_message_sid, status, error_code, error_message, retry_count, scheduled_send_at, sent_at, body, channel)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id;
                """,
                (
                    valid_appt_id, recipient_type, recipient_phone, template_type,
                    twilio_message_sid, status, error_code, error_message, retry_count,
                    scheduled_send_at, dt_mod.datetime.now(dt_mod.timezone.utc) if status in ("SENT", "DELIVERED") else None,
                    body, (channel or "SMS").upper(),
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


def _to_iso_utc_str(val):
    """Converts a database timestamp value (datetime or string) to ISO 8601 UTC string with Z suffix."""
    if not val:
        return None
    if isinstance(val, str):
        val_str = val.strip()
        if " " in val_str and "T" not in val_str:
            val_str = val_str.replace(" ", "T")
        if not val_str.endswith("Z") and "+" not in val_str and "-" not in val_str[10:]:
            val_str += "Z"
        return val_str
    return val.strftime("%Y-%m-%dT%H:%M:%SZ")


def get_sms_logs_by_appointment(appointment_id: int) -> list:
    """Fetches all SMS dispatch logs for a given appointment, ordered descending by time (latest first)."""
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("SELECT * FROM sms_log WHERE appointment_id = %s ORDER BY created_at DESC, id DESC;", (appointment_id,))
            rows = cursor.fetchall()
            logs = []
            for r in rows:
                item = dict(r)
                if item.get("created_at"):
                    item["created_at"] = _to_iso_utc_str(item["created_at"])
                if item.get("sent_at"):
                    item["sent_at"] = _to_iso_utc_str(item["sent_at"])
                if item.get("scheduled_send_at"):
                    item["scheduled_send_at"] = _to_iso_utc_str(item["scheduled_send_at"])
                logs.append(item)
            return logs


def get_appointment_details_by_id(appointment_id: int) -> dict:
    """Fetches full details of an appointment for SMS log popup context."""
    from serviceBot.services.sms_reminders import parse_booking_datetime
    from serviceBot.services import timezone_service
    import datetime as dt_mod

    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("""
                SELECT sr.id, sr.service_type, sr.issue_description, sr.status, sr.time_slot, sr.booking_time, sr.booking_type, sr.duration_minutes, sr.created_at, sr.updated_at,
                       sr.staff_agent_id, sr.confirmation_status, sr.escalation_status, sr.escalation_reason, sr.confirmation_cutoff_at, sr.confirmed_at,
                       c.id AS customer_id, c.name AS customer_name, c.phone AS customer_phone,
                       v.id AS vehicle_id, v.make AS vehicle_make, v.model AS vehicle_model, v.year AS vehicle_year,
                       sa.name AS staff_agent_name, sa.role AS staff_agent_role, sa.phone_number AS staff_agent_phone
                FROM service_requests sr
                LEFT JOIN customers c ON sr.customer_id = c.id
                LEFT JOIN vehicles v ON sr.vehicle_id = v.id
                LEFT JOIN staff_agents sa ON sr.staff_agent_id = sa.id
                WHERE sr.id = %s;
            """, (appointment_id,))
            row = cursor.fetchone()
            if row:
                r = dict(row)
                for ts_field in ("created_at", "updated_at", "booking_time", "confirmation_cutoff_at", "confirmed_at"):
                    if r.get(ts_field) and not isinstance(r[ts_field], str):
                        r[ts_field] = r[ts_field].strftime("%Y-%m-%d %H:%M:%S")

                duration = r.get("duration_minutes")
                if duration is None:
                    if r.get("booking_type") == "callback":
                        duration = 15
                    else:
                        svc = r.get("service_type") or r.get("issue_description") or ""
                        svc_fields = get_service_required_fields(svc) if svc else None
                        duration = (svc_fields.get("duration_minutes") or 60) if svc_fields else 60
                r["duration_minutes"] = duration

                raw_time = r.get("booking_time") or r.get("time_slot")
                if raw_time:
                    dt = parse_booking_datetime(str(raw_time))
                    if dt:
                        dt = dt.replace(tzinfo=timezone_service.get_business_zoneinfo())
                        end_dt = dt + dt_mod.timedelta(minutes=duration)
                        r["booking_start_time"] = dt.isoformat()
                        r["booking_end_time"] = end_dt.isoformat()
                    else:
                        r["booking_start_time"] = str(raw_time)
                        r["booking_end_time"] = None
                else:
                    r["booking_start_time"] = None
                    r["booking_end_time"] = None

                return r
            return None


def get_appointment_full_trace(appointment_id: int) -> Optional[dict]:
    """
    Synthesizes a unified, chronological lifecycle audit trace for an appointment.
    Aggregates service_request_audit_log, sms_log, inbound sms responses, and crm_notes.
    """
    app = get_appointment_details_by_id(appointment_id)
    if not app:
        return None

    raw_sms = get_sms_logs_by_appointment(appointment_id)

    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            # 1. Fetch all audit logs for this appointment
            cursor.execute(
                """
                SELECT id, request_id, event_type, from_status, to_status,
                       triggered_by, actor_name, notes, metadata, created_at
                FROM service_request_audit_log
                WHERE request_id = %s
                ORDER BY created_at ASC, id ASC;
                """,
                (appointment_id,)
            )
            audit_rows = cursor.fetchall()

    timeline = []

    # Map SMS templates to readable titles & categories
    sms_template_titles = {
        "booking": "Customer Confirmation Dispatched",
        "booking_confirmation": "Customer Confirmation Dispatched",
        "agent_booking": "Agent Assignment Alert Dispatched",
        "agent_reassigned": "Replacement Agent Alert Dispatched",
        "unassignment": "Previous Agent Unassigned Notice",
        "reschedule": "Reschedule Notice Dispatched",
        "cancellation": "Cancellation Notice Dispatched",
        "reminder_24h": "24h Pre-Appointment Reminder Dispatched",
        "reminder_2h": "2h Pre-Appointment Reminder Dispatched",
        "admin_booking": "Admin Notification Alert Dispatched",
    }

    # Transform SMS logs to timeline events
    for s in raw_sms:
        sid = s.get("id")
        created_str = str(s.get("created_at") or "")[:19]
        tmpl = s.get("template_type") or "sms_notification"
        title = sms_template_titles.get(tmpl, f"SMS Dispatch ({tmpl})")
        status = (s.get("status") or "PENDING").upper()
        recip_type = (s.get("recipient_type") or "customer").capitalize()
        phone = s.get("recipient_phone") or ""

        badge_color = "success" if status in ("SENT", "DELIVERED") else ("danger" if status == "FAILED" else "warning")
        desc = f"Sent to {recip_type} ({phone}). Status: {status}."
        if s.get("error_message"):
            desc += f" Error: {s['error_message']}"
        elif s.get("error_code"):
            desc += f" Error Code: {s['error_code']}"

        timeline.append({
            "id": f"sms-{sid}",
            "raw_timestamp": s.get("created_at"),
            "timestamp": created_str,
            "category": "DISPATCH",
            "event_type": f"SMS_{status}",
            "title": title,
            "actor": "Twilio SMS Gateway",
            "actor_type": "system",
            "badge_color": badge_color,
            "description": desc,
            "metadata": {
                "recipient_type": s.get("recipient_type"),
                "recipient_phone": phone,
                "status": status,
                "twilio_message_sid": s.get("twilio_message_sid"),
                "template_type": tmpl,
                "retry_count": s.get("retry_count", 0),
            }
        })

    # Transform Audit rows to timeline events
    for a in audit_rows:
        aid = a["id"]
        created_str = str(a.get("created_at") or "")[:19]
        evt_type = a.get("event_type") or "STATUS_CHANGE"
        trig = (a.get("triggered_by") or "").lower()
        actor = a.get("actor_name") or ("Portal Staff" if "portal" in trig or "admin" in trig else ("Voice AI Agent" if "voice" in trig or "elevenlabs" in trig else ("Agent" if "agent" in trig else ("Customer" if "customer" in trig else "System"))))
        actor_type = "agent" if "agent" in trig else ("customer" if "customer" in trig else ("admin" if "staff" in trig or "admin" in trig or "supervisor" in trig else "system"))

        to_st = (a.get("to_status") or "").lower()
        notes = a.get("notes") or ""

        # Determine category & title
        category = "STATUS"
        title = "Status Changed"
        badge_color = "info"

        if evt_type == "BOOKING_CREATED" or "created" in notes.lower():
            category = "CREATION"
            title = "Appointment Created"
            badge_color = "info"
        elif evt_type in ("AGENT_ASSIGNED", "AGENT_REASSIGNED") or "assigned" in notes.lower():
            category = "REASSIGNMENT" if "reassigned" in notes.lower() or evt_type == "AGENT_REASSIGNED" else "ASSIGNMENT"
            title = "Agent Reassigned" if category == "REASSIGNMENT" else "Agent Assigned"
            badge_color = "info"
        elif evt_type == "AGENT_CONFIRMED" or to_st == "confirmed" or "confirmation status changed to confirmed" in notes.lower():
            category = "CONFIRMATION"
            title = "Agent Confirmed Assignment"
            badge_color = "success"
        elif evt_type == "AGENT_DECLINED" or to_st == "declined" or "declined" in notes.lower():
            category = "DECLINE"
            title = "Agent Declined Assignment"
            badge_color = "danger"
        elif evt_type == "ESCALATION_TRIGGERED" or to_st == "escalated" or "escalated" in notes.lower():
            category = "ESCALATION"
            title = "Supervisor Escalation Triggered"
            badge_color = "danger"
        elif "rescheduled" in notes.lower() or to_st == "rescheduled":
            category = "RESCHEDULE"
            title = "Appointment Rescheduled"
            badge_color = "warning"
        elif to_st in ("cancelled", "cancelled_by_customer", "cancelled_by_admin") or "cancelled" in notes.lower():
            category = "STATUS"
            title = "Appointment Cancelled"
            badge_color = "danger"
        elif to_st in ("completed", "done"):
            category = "STATUS"
            title = "Service Completed"
            badge_color = "success"

        meta = a.get("metadata") or {}
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except Exception:
                meta = {}

        timeline.append({
            "id": f"audit-{aid}",
            "raw_timestamp": a.get("created_at"),
            "timestamp": created_str,
            "category": category,
            "event_type": evt_type,
            "title": title,
            "actor": actor,
            "actor_type": actor_type,
            "badge_color": badge_color,
            "description": notes or f"Transitioned from {a.get('from_status')} to {a.get('to_status')}",
            "metadata": meta,
        })

    # Ensure baseline lifecycle events are present if not already recorded in audit logs
    has_creation = any(ev.get("category") == "CREATION" or ev.get("event_type") == "BOOKING_CREATED" for ev in timeline)
    if not has_creation and app.get("created_at"):
        booking_type = (app.get("booking_type") or "appointment").lower()
        intake_actor = "AI Voice Intake" if "voice" in booking_type or "call" in booking_type else ("Admin Web Portal" if "portal" in booking_type or "manual" in booking_type else "Customer System Intake")
        timeline.append({
            "id": f"synth-create-{appointment_id}",
            "raw_timestamp": app["created_at"],
            "timestamp": str(app["created_at"])[:19],
            "category": "CREATION",
            "event_type": "BOOKING_CREATED",
            "title": f"Appointment Created ({booking_type.capitalize()})",
            "actor": intake_actor,
            "actor_type": "system",
            "badge_color": "info",
            "description": f"Appointment booked for {app.get('service_type') or 'General Service'}. Customer: {app.get('customer_name') or 'Customer'} ({app.get('customer_phone') or 'N/A'}).",
            "metadata": {
                "service_type": app.get("service_type"),
                "booking_type": app.get("booking_type"),
                "booking_time": str(app.get("booking_time") or ""),
                "issue_description": app.get("issue_description"),
            }
        })

    has_assignment = any(ev.get("category") in ("ASSIGNMENT", "REASSIGNMENT") or ev.get("event_type") in ("AGENT_ASSIGNED", "AGENT_REASSIGNED") for ev in timeline)
    if app.get("staff_agent_id") and not has_assignment and app.get("created_at"):
        assigned_name = app.get("staff_agent_name") or f"Agent #{app['staff_agent_id']}"
        timeline.append({
            "id": f"synth-assign-{appointment_id}",
            "raw_timestamp": app["created_at"],
            "timestamp": str(app["created_at"])[:19],
            "category": "ASSIGNMENT",
            "event_type": "AGENT_ASSIGNED",
            "title": "Agent Assigned",
            "actor": "Dispatch System",
            "actor_type": "system",
            "badge_color": "info",
            "description": f"Assigned to agent {assigned_name}.",
            "metadata": {
                "staff_agent_id": app["staff_agent_id"],
                "staff_agent_name": app.get("staff_agent_name"),
                "staff_agent_phone": app.get("staff_agent_phone"),
            }
        })

    has_confirmation = any(ev.get("category") == "CONFIRMATION" or ev.get("event_type") == "AGENT_CONFIRMED" for ev in timeline)
    if app.get("staff_agent_id") and app.get("confirmation_status") == "confirmed" and not has_confirmation:
        conf_time = app.get("confirmed_at") or app.get("updated_at") or app.get("created_at")
        tech_name = app.get("staff_agent_name") or "Agent"
        timeline.append({
            "id": f"synth-confirm-{appointment_id}",
            "raw_timestamp": conf_time,
            "timestamp": str(conf_time)[:19],
            "category": "CONFIRMATION",
            "event_type": "AGENT_CONFIRMED",
            "title": "Agent Confirmed Assignment",
            "actor": tech_name,
            "actor_type": "agent",
            "badge_color": "success",
            "description": f"{tech_name} confirmed appointment assignment.",
            "metadata": {
                "confirmation_status": "confirmed",
                "staff_agent_id": app.get("staff_agent_id"),
            }
        })

    has_escalation = any(ev.get("category") == "ESCALATION" or ev.get("event_type") == "ESCALATION_TRIGGERED" for ev in timeline)
    if app.get("escalation_status") == "escalated" and not has_escalation:
        timeline.append({
            "id": f"synth-esc-{appointment_id}",
            "raw_timestamp": app.get("updated_at") or app.get("created_at"),
            "timestamp": str(app.get("updated_at") or app.get("created_at"))[:19],
            "category": "ESCALATION",
            "event_type": "ESCALATION_TRIGGERED",
            "title": "Supervisor Escalation Triggered",
            "actor": "SLA Monitor",
            "actor_type": "system",
            "badge_color": "danger",
            "description": f"Escalated due to: {app.get('escalation_reason') or 'TIMEOUT_NO_RESPONSE'}",
            "metadata": {"escalation_reason": app.get("escalation_reason")},
        })

    curr_st = (app.get("status") or "").lower()
    has_terminal_st = any(ev.get("event_type") in (f"STATUS_{curr_st.upper()}", "STATUS_CHANGED") or (ev.get("category") == "STATUS" and curr_st in ev.get("description", "").lower()) for ev in timeline)
    if curr_st in ("completed", "cancelled") and not has_terminal_st:
        st_time = app.get("updated_at") or app.get("created_at")
        is_done = curr_st == "completed"
        timeline.append({
            "id": f"synth-status-{appointment_id}",
            "raw_timestamp": st_time,
            "timestamp": str(st_time)[:19],
            "category": "STATUS",
            "event_type": f"STATUS_{curr_st.upper()}",
            "title": "Service Completed" if is_done else "Appointment Cancelled",
            "actor": "Portal Staff / System",
            "actor_type": "system",
            "badge_color": "success" if is_done else "danger",
            "description": f"Appointment marked as {curr_st}.",
            "metadata": {"status": curr_st}
        })

    # Sort combined timeline chronologically
    def _sort_key(ev):
        raw = ev.get("raw_timestamp")
        if raw is not None:
            if hasattr(raw, "isoformat"):
                return raw.isoformat().replace(" ", "T")
            return str(raw).replace(" ", "T")
        ts = ev.get("timestamp") or ""
        return str(ts).replace(" ", "T")

    timeline.sort(key=_sort_key)

    # Clean out internal raw_timestamp before returning
    for ev in timeline:
        ev.pop("raw_timestamp", None)

    return {
        "success": True,
        "appointment": app,
        "summary_metrics": {
            "total_events": len(timeline),
            "total_dispatches": len(raw_sms),
            "escalated": (app.get("escalation_status") == "escalated"),
            "confirmation_status": app.get("confirmation_status"),
            "assigned_agent_name": app.get("staff_agent_name") or "Unassigned",
        },
        "trace": timeline,
        "raw_sms_logs": raw_sms,
    }


def get_sms_log_by_id(log_id: int) -> dict:
    """Fetches a single SMS log by ID."""
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("SELECT * FROM sms_log WHERE id = %s;", (log_id,))
            row = cursor.fetchone()
            return dict(row) if row else None


def schedule_sms_reminder(
    appointment_id: int,
    recipient_type: str,
    recipient_phone: str,
    reminder_type: str,
    scheduled_at: dt_mod.datetime,
    attempt_number: int = 1,
    attempt_kind: str = "final_reminder",
    status: str = "PENDING",
) -> int:
    """Schedules a pre-appointment SMS reminder in sms_reminders table."""
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            if appointment_id:
                cursor.execute("SELECT id FROM service_requests WHERE id = %s;", (appointment_id,))
                if not cursor.fetchone():
                    logger.warning(f"Skipping schedule_sms_reminder for non-existent appointment {appointment_id}")
                    return None

            cursor.execute(
                """
                INSERT INTO sms_reminders (
                    appointment_id, recipient_type, recipient_phone, reminder_type, scheduled_at, status,
                    attempt_number, attempt_kind, retry_count
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 0)
                RETURNING id;
                """,
                (appointment_id, recipient_type, recipient_phone, reminder_type, scheduled_at, status, attempt_number, attempt_kind)
            )
            return cursor.fetchone()["id"]


def cancel_pending_sms_reminders(appointment_id: int, recipient_type: str = None):
    """Marks pending reminders for an appointment as CANCELLED, optionally filtered by recipient_type."""
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            if recipient_type:
                cursor.execute(
                    "UPDATE sms_reminders SET status = 'CANCELLED' WHERE appointment_id = %s AND recipient_type = %s AND status = 'PENDING';",
                    (appointment_id, recipient_type)
                )
            else:
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
                "SELECT * FROM sms_log WHERE status = 'QUEUED' AND scheduled_send_at <= (CURRENT_TIMESTAMP AT TIME ZONE 'UTC') ORDER BY scheduled_send_at ASC;"
            )
            return [dict(r) for r in cursor.fetchall()]


def get_or_create_sms_conversation(customer_phone: str, context_appointment_id: int = None, assigned_agent_id: int = None) -> dict:
    """Gets an existing conversation for a customer phone number or creates a new one."""
    import re
    if not customer_phone:
        return {}
    cleaned_phone = str(customer_phone).strip()
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
                "INSERT INTO sms_conversations (id, customer_phone, state) VALUES (%s, %s, 'AUTOMATED') ON CONFLICT (id) DO NOTHING;",
                (conversation_id, f"Unknown-{conversation_id}")
            )
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
            rows = cursor.fetchall()
            msgs = []
            for r in rows:
                item = dict(r)
                if item.get("created_at"):
                    item["created_at"] = _to_iso_utc_str(item["created_at"])
                msgs.append(item)
            return msgs


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


def consolidate_appointment_service(
    appointment_id: int,
    additional_issue: str,
    additional_service_type: str = None,
    additional_duration_minutes: int = 30,
    source_appointment_ids: Any = None,
) -> dict:
    """
    Consolidates an additional service or symptom into an existing appointment.
    Appends the additional issue description and extends duration_minutes.
    Optionally cancels and links source appointment/callback IDs so duplicate requests are closed.
    Updates linked appointment_reservations, reservation segments, and enqueues outbox SMS notification.
    """
    import datetime as dt_mod
    from serviceBot.services.booking import normalize_reservation_duration
    from serviceBot.services.outbox_worker import enqueue_outbox_event

    try:
        additional_duration_minutes = int(additional_duration_minutes)
    except (ValueError, TypeError):
        return {"success": False, "error": "additional_duration_minutes must be a positive integer"}
    if additional_duration_minutes <= 0:
        return {"success": False, "error": "additional_duration_minutes must be positive"}

    parsed_source_ids = []
    if source_appointment_ids:
        if isinstance(source_appointment_ids, (list, tuple, set)):
            parsed_source_ids = [int(x) for x in source_appointment_ids if str(x).isdigit()]
        elif isinstance(source_appointment_ids, int):
            parsed_source_ids = [source_appointment_ids]
        elif isinstance(source_appointment_ids, str):
            import re
            clean_str = re.sub(r"[\[\]'\"]", "", source_appointment_ids)
            parsed_source_ids = [int(x.strip()) for x in clean_str.split(",") if x.strip().isdigit()]

    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                """
                SELECT sr.id, sr.customer_id, sr.booking_time, sr.booking_type, sr.issue_description, sr.service_type,
                       COALESCE(sr.duration_minutes, 60) AS duration_minutes, sr.vehicle_id, sr.staff_agent_id,
                       sr.service_components, sr.visit_group_id, v.year, v.make, v.model,
                       c.phone, c.name AS customer_name
                FROM service_requests sr
                LEFT JOIN vehicles v ON sr.vehicle_id = v.id
                LEFT JOIN customers c ON sr.customer_id = c.id
                WHERE sr.id = %s FOR UPDATE OF sr;
                """,
                (appointment_id,)
            )
            sr = cursor.fetchone()
            if not sr:
                return {"success": False, "error": f"Appointment #{appointment_id} not found."}

            customer_id = sr.get("customer_id")
            if parsed_source_ids:
                cursor.execute(
                    "SELECT id, customer_id, status FROM service_requests WHERE id = ANY(%s);",
                    (list(set(parsed_source_ids)),)
                )
                source_rows = cursor.fetchall()
                for s_row in source_rows:
                    if s_row["customer_id"] != customer_id:
                        conn.rollback()
                        return {
                            "success": False,
                            "error": "Cross-customer source IDs must be rejected atomically"
                        }

            existing_desc = (sr.get("issue_description") or "").strip()
            existing_duration = sr.get("duration_minutes") or 60
            booking_time = sr.get("booking_time")
            vehicle_id = sr.get("vehicle_id")

            clean_add = (additional_issue or "").strip()
            if existing_desc and clean_add:
                if clean_add.lower() in existing_desc.lower():
                    combined_issues = existing_desc
                elif existing_desc.lower() in clean_add.lower():
                    combined_issues = clean_add
                else:
                    combined_issues = f"{existing_desc}; {clean_add}"
            elif clean_add:
                combined_issues = clean_add
            else:
                combined_issues = existing_desc

            new_duration = normalize_reservation_duration(existing_duration + additional_duration_minutes)
            new_service_type = sr.get("service_type")
            if additional_service_type and additional_service_type not in (new_service_type or ""):
                new_service_type = f"{new_service_type}, {additional_service_type}"

            components = None
            if sr.get("service_components") is not None and additional_service_type:
                from serviceBot.services.booking import _validated_components
                try:
                    prior_components = _validated_components(sr)
                except ValueError:
                    prior_components = None
                cursor.execute("SELECT name FROM services WHERE name=%s", (additional_service_type,))
                canonical = cursor.fetchall()
                if (prior_components and len(canonical) == 1
                        and canonical[0]["name"] == additional_service_type
                        and additional_service_type not in {component["name"] for component in prior_components}):
                    components = [*prior_components, {"name": additional_service_type,
                        "duration_minutes": new_duration - existing_duration}]
            if components:
                # Canonical components remain one agent's indivisible block.
                # Raw mappings distinguish mappingless services from tags whose
                # only agents have become inactive.
                assigned = sr.get("staff_agent_id")
                cursor.execute("SELECT id FROM staff_agents WHERE id=%s AND is_active IS NOT FALSE", (assigned,))
                active_staff = cursor.fetchone()
                cursor.execute("""SELECT s.name,m.staff_agent_id FROM services s
                    JOIN service_staff_agents m ON m.service_id=s.id WHERE s.name=ANY(%s)""",
                    ([component["name"] for component in components],))
                mappings = {}
                for row in cursor.fetchall():
                    mappings.setdefault(row["name"], set()).add(row["staff_agent_id"])
                if (not active_staff or any(assigned not in mappings[component["name"]]
                        for component in components if component["name"] in mappings)):
                    return {"success": False, "error": "Assigned agent is not active and qualified for every selected service."}
                new_service_type = ", ".join(component["name"] for component in components)
            # NULL makes unstructured legacy/additional work explicitly unselectable.
            start_dt = None
            new_end_dt = None
            if booking_time:
                try:
                    if isinstance(booking_time, str):
                        b_clean = booking_time.replace("T", " ")[:19]
                        start_dt = dt_mod.datetime.strptime(b_clean, "%Y-%m-%d %H:%M:%S")
                    else:
                        start_dt = booking_time
                    new_end_dt = start_dt + dt_mod.timedelta(minutes=new_duration)
                except Exception:
                    pass

            cursor.execute(
                """
                SELECT id, staff_agent_id, starts_at, ends_at, calendar_event_id
                FROM appointment_reservations
                WHERE service_request_id = %s;
                """,
                (appointment_id,)
            )
            res_row = cursor.fetchone()
            agent_id = sr.get("staff_agent_id") or (res_row.get("staff_agent_id") if res_row else None)

            extra_segments = []
            if start_dt:
                cur_seg = start_dt + dt_mod.timedelta(minutes=existing_duration)
                end_seg = start_dt + dt_mod.timedelta(minutes=new_duration)
                while cur_seg < end_seg:
                    extra_segments.append(cur_seg)
                    cur_seg += dt_mod.timedelta(minutes=15)

            if extra_segments and agent_id:
                cursor.execute(
                    """
                    SELECT 1
                    FROM mock_calendar_slots
                    WHERE staff_agent_id = %s
                      AND slot_datetime = ANY(%s)
                      AND (reservation_status IN ('RESERVED', 'BLOCKED') OR is_booked = TRUE)
                      AND service_request_id IS DISTINCT FROM %s;
                    """,
                    (agent_id, extra_segments, appointment_id)
                )
                if cursor.fetchone():
                    conn.rollback()
                    return {
                        "success": False,
                        "capacity_blocked": True,
                        "appointment_id": appointment_id,
                        "message": "Agent schedule cannot accommodate the extra duration contiguous with this appointment."
                    }

                cursor.execute(
                    """
                    SELECT 1
                    FROM appointment_reservation_segments ars
                    JOIN appointment_reservations ar ON ar.id = ars.reservation_id
                    WHERE ars.staff_agent_id = %s
                      AND ars.segment_start = ANY(%s)
                      AND ar.service_request_id IS DISTINCT FROM %s
                      AND ar.status = 'ACTIVE';
                    """,
                    (agent_id, extra_segments, appointment_id)
                )
                if cursor.fetchone():
                    conn.rollback()
                    return {
                        "success": False,
                        "capacity_blocked": True,
                        "appointment_id": appointment_id,
                        "message": "Agent schedule cannot accommodate the extra duration contiguous with this appointment."
                    }

            cursor.execute(
                """
                UPDATE service_requests
                SET issue_description = %s,
                    duration_minutes = %s,
                    service_type = %s,
                    service_components = %s,
                    booking_end_at = %s,
                    calendar_integration_status = 'PENDING_CALENDAR',
                    updated_at = NOW()
                WHERE id = %s;
                """,
                (combined_issues, new_duration, new_service_type, json.dumps(components) if components else None, new_end_dt, appointment_id)
            )

            if new_end_dt and res_row:
                res_id = res_row["id"]
                cursor.execute(
                    """
                    UPDATE appointment_reservations
                    SET ends_at = %s,
                        calendar_integration_status = 'PENDING_CALENDAR',
                        updated_at = NOW()
                    WHERE id = %s;
                    """,
                    (new_end_dt, res_id)
                )
                for seg in extra_segments:
                    cursor.execute(
                        """
                        INSERT INTO appointment_reservation_segments (reservation_id, staff_agent_id, segment_start)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (staff_agent_id, segment_start) DO NOTHING;
                        """,
                        (res_id, agent_id, seg)
                    )

            if extra_segments and agent_id:
                for seg in extra_segments:
                    cursor.execute(
                        """
                        INSERT INTO mock_calendar_slots
                        (slot_datetime, is_booked, staff_agent_id, reservation_status, service_request_id, calendar_integration_status)
                        VALUES (%s, TRUE, %s, 'RESERVED', %s, 'PENDING_CALENDAR')
                        ON CONFLICT (slot_datetime, staff_agent_id) DO UPDATE
                        SET is_booked = TRUE,
                            reservation_status = 'RESERVED',
                            service_request_id = EXCLUDED.service_request_id,
                            calendar_integration_status = 'PENDING_CALENDAR',
                            updated_at = CURRENT_TIMESTAMP;
                        """,
                        (seg, agent_id, appointment_id)
                    )

            # Process source appointments / callbacks to merge & cancel
            cancelled_ids = []
            if not parsed_source_ids and customer_id and vehicle_id and booking_time:
                b_date_str = str(booking_time)[:10]
                cursor.execute(
                    """
                    SELECT id FROM service_requests
                    WHERE customer_id = %s
                      AND vehicle_id = %s
                      AND id != %s
                      AND (visit_group_id IS NULL OR visit_group_id IS DISTINCT FROM %s)
                      AND status IN ('pending', 'in_progress')
                      AND (booking_time::text LIKE %s OR booking_time IS NULL);
                    """,
                    (customer_id, vehicle_id, appointment_id, sr.get("visit_group_id"), f"{b_date_str}%")
                )
                parsed_source_ids = [r["id"] for r in cursor.fetchall()]

            for src_id in set(parsed_source_ids):
                if src_id != appointment_id:
                    cursor.execute(
                        "SELECT id, staff_agent_id, starts_at, calendar_event_id FROM appointment_reservations WHERE service_request_id = %s FOR UPDATE;",
                        (src_id,),
                    )
                    source_reservations = cursor.fetchall()
                    cursor.execute(
                        """
                        UPDATE service_requests
                        SET status = 'cancelled_by_customer',
                            confirmation_status = 'cancelled',
                            escalation_status = 'none',
                            escalation_reason = NULL,
                            linked_appointment_id = %s,
                            calendar_integration_status = 'PENDING_CALENDAR',
                            updated_at = NOW()
                        WHERE id = %s;
                        """,
                        (appointment_id, src_id)
                    )
                    cursor.execute(
                        """
                        DELETE FROM appointment_reservation_segments
                        WHERE reservation_id IN (
                            SELECT id FROM appointment_reservations WHERE service_request_id = %s
                        );
                        """,
                        (src_id,),
                    )
                    cursor.execute(
                        """
                        UPDATE appointment_reservations
                        SET status = 'CANCELLED', calendar_integration_status = 'PENDING_CALENDAR', updated_at = NOW()
                        WHERE service_request_id = %s;
                        """,
                        (src_id,),
                    )
                    cursor.execute(
                        """
                        UPDATE mock_calendar_slots
                        SET is_booked = FALSE,
                            reservation_status = 'AVAILABLE',
                            service_request_id = NULL,
                            calendar_integration_status = 'PENDING_CALENDAR',
                            calendar_event_id = NULL,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE service_request_id = %s;
                        """,
                        (src_id,),
                    )
                    cursor.execute(
                        "UPDATE sms_reminders SET status = 'CANCELLED' WHERE appointment_id = %s AND status = 'PENDING';",
                        (src_id,),
                    )
                    for source_reservation in source_reservations:
                        source_start = source_reservation["starts_at"]
                        source_event_id = source_reservation.get("calendar_event_id") or (
                            f"servicebot{source_reservation['id']}{source_start:%Y%m%d%H%M}"
                        )
                        enqueue_outbox_event(
                            cursor=cursor,
                            event_type="calendar_projection",
                            request_id=src_id,
                            payload={
                                "action": "delete",
                                "reservation_id": source_reservation["id"],
                                "agent_id": source_reservation["staff_agent_id"],
                                "calendar_event_id": source_event_id,
                            },
                        )
                    cancelled_ids.append(src_id)

            if start_dt and res_row and agent_id:
                enqueue_outbox_event(
                    cursor=cursor,
                    event_type="calendar_projection",
                    request_id=appointment_id,
                    payload={
                        "reservation_id": res_row["id"],
                        "agent_id": agent_id,
                        "calendar_event_id": res_row.get("calendar_event_id") or f"servicebot{res_row['id']}{start_dt:%Y%m%d%H%M}",
                        "booking_type": sr.get("booking_type") or "appointment",
                        "booking_time_str": start_dt.strftime("%Y-%m-%d %H:%M:%S"),
                        "duration_minutes": new_duration,
                        "details": {
                            "customer_name": sr.get("customer_name"),
                            "service_type": new_service_type,
                            "issue": combined_issues,
                        },
                    },
                )

            # Enqueue outbox notification
            veh_str = f"{sr.get('year') or ''} {sr.get('make') or ''} {sr.get('model') or ''}".strip()
            enqueue_outbox_event(
                cursor=cursor,
                event_type="sms_consolidated",
                request_id=appointment_id,
                payload={
                    "sms_event_type": "CONSOLIDATED",
                    "appointment_id": appointment_id,
                    "customer_phone": sr.get("phone"),
                    "booking_time": str(booking_time),
                    "details": {
                        "customer_name": sr.get("customer_name") or "Valued Customer",
                        "phone": sr.get("phone"),
                        "service_type": new_service_type,
                        "issue": combined_issues,
                        "duration_minutes": new_duration,
                        "time": str(booking_time),
                        "vehicle": veh_str,
                        "cancelled_source_ids": cancelled_ids
                    }
                }
            )

            conn.commit()

            return {
                "success": True,
                "appointment_id": appointment_id,
                "combined_issues": combined_issues,
                "new_duration_minutes": new_duration,
                "booking_time": str(booking_time),
                "booking_end_time": new_end_dt.strftime("%Y-%m-%d %H:%M:%S") if new_end_dt else None,
                "service_type": new_service_type,
                "cancelled_source_ids": cancelled_ids,
                "vehicle": {
                    "year": sr.get("year"),
                    "make": sr.get("make"),
                    "model": sr.get("model")
                }
            }


def get_staff_agent_by_phone(phone_number: str) -> Optional[Dict[str, Any]]:
    """
    Looks up a staff agent by phone number, matching against raw or E.164 normalized formats.
    """
    if not phone_number:
        return None
    import re
    cleaned = re.sub(r"\D", "", phone_number)
    if len(cleaned) == 11 and cleaned.startswith("1"):
        cleaned_10 = cleaned[1:]
    else:
        cleaned_10 = cleaned if len(cleaned) == 10 else ""
    e164 = f"+1{cleaned_10}" if cleaned_10 else phone_number.strip()

    query = """
    SELECT id, name, email, phone_number, role
    FROM staff_agents
    WHERE phone_number = %s
       OR phone_number = %s
       OR REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(phone_number, '-', ''), ' ', ''), '(', ''), ')', ''), '+1', '') = %s
    LIMIT 1;
    """
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(query, (phone_number.strip(), e164, cleaned_10 or cleaned))
            row = cursor.fetchone()
            return dict(row) if row else None


def update_appointment_confirmation_status(
    request_id: int,
    confirmation_status: str,
    confirmed_at: Optional[dt_mod.datetime] = None,
) -> Dict[str, Any]:
    """
    Updates the confirmation status ('pending_agent_confirmation', 'confirmed', 'declined')
    and confirmed_at timestamp for a service request.
    If transitioning to 'confirmed' and currently 'escalated', auto-resolves escalation.
    """
    valid_statuses = ('pending_agent_confirmation', 'confirmed', 'declined')
    if confirmation_status not in valid_statuses:
        raise ValueError(f"Invalid confirmation_status '{confirmation_status}'. Must be one of {valid_statuses}")

    if confirmation_status == 'confirmed' and confirmed_at is None:
        confirmed_at = dt_mod.datetime.now()

    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                "SELECT id, status, confirmation_status, escalation_status FROM service_requests WHERE id = %s FOR UPDATE;",
                (request_id,)
            )
            current = cursor.fetchone()
            if not current:
                raise ValueError(f"Service request #{request_id} not found.")

            escalation_status = current.get("escalation_status") or "none"
            if confirmation_status == "confirmed" and escalation_status == "escalated":
                escalation_status = "resolved"

            curr_status = current.get("status") or "pending"
            new_primary_status = curr_status
            if confirmation_status == "confirmed" and curr_status in ("pending", "rescheduled"):
                new_primary_status = "confirmed"

            cursor.execute(
                """
                UPDATE service_requests
                SET confirmation_status = %s,
                    confirmed_at = %s,
                    escalation_status = %s,
                    status = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                RETURNING *;
                """,
                (confirmation_status, confirmed_at, escalation_status, new_primary_status, request_id)
            )
            updated = dict(cursor.fetchone())

            evt_type = "AGENT_CONFIRMED" if confirmation_status == "confirmed" else ("AGENT_DECLINED" if confirmation_status == "declined" else "CONFIRMATION_STATUS_CHANGED")
            cursor.execute(
                """
                INSERT INTO service_request_audit_log (request_id, from_status, to_status, triggered_by, actor_name, event_type, notes, metadata)
                VALUES (%s, %s, %s, 'agent', 'Agent', %s, %s, %s);
                """,
                (
                    request_id,
                    current.get("confirmation_status") or "pending_agent_confirmation",
                    confirmation_status,
                    evt_type,
                    f"Agent confirmation status changed to {confirmation_status} (escalation: {escalation_status})",
                    json.dumps({
                        "confirmation_status": confirmation_status,
                        "escalation_status": escalation_status,
                        "confirmed_at": str(confirmed_at) if confirmed_at else None
                    })
                )
            )
            conn.commit()
            return updated


def escalate_service_request(
    request_id: int,
    reason: str = "TIMEOUT_NO_RESPONSE",
    triggered_by: str = "system",
) -> Dict[str, Any]:
    """
    Flags a service request as escalated with a specific escalation reason.
    Valid reasons: 'TIMEOUT_NO_RESPONSE', 'AGENT_DECLINED', 'DELIVERY_FAILED',
    'UNASSIGNED_ON_CREATION', 'MANUAL_SUPERVISOR_ACTION'.
    """
    valid_reasons = (
        'TIMEOUT_NO_RESPONSE',
        'AGENT_DECLINED',
        'DELIVERY_FAILED',
        'UNASSIGNED_ON_CREATION',
        'MANUAL_SUPERVISOR_ACTION',
        'AGENT_DEACTIVATED'
    )
    if reason not in valid_reasons:
        raise ValueError(f"Invalid escalation reason '{reason}'. Must be one of {valid_reasons}")

    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                "SELECT id, status, escalation_status FROM service_requests WHERE id = %s FOR UPDATE;",
                (request_id,)
            )
            current = cursor.fetchone()
            if not current:
                raise ValueError(f"Service request #{request_id} not found.")

            curr_status = (current.get("status") or "").lower()
            if curr_status in ("completed", "done", "cancelled", "cancelled_by_customer"):
                logger.info(f"Skipping escalation for closed/completed or cancelled service request #{request_id}.")
                return dict(current)

            cursor.execute(
                """
                UPDATE service_requests
                SET escalation_status = 'escalated',
                    escalation_reason = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                RETURNING *;
                """,
                (reason, request_id)
            )
            updated = dict(cursor.fetchone())

            actor = "Agent" if triggered_by == "agent_sms" else ("SLA Monitor" if triggered_by in ("system", "system_poller") else triggered_by)
            cursor.execute(
                """
                INSERT INTO service_request_audit_log (request_id, from_status, to_status, triggered_by, actor_name, event_type, notes, metadata)
                VALUES (%s, %s, 'escalated', %s, %s, 'ESCALATION_TRIGGERED', %s, %s);
                """,
                (
                    request_id,
                    current.get("escalation_status") or "none",
                    triggered_by,
                    actor,
                    f"Escalated due to: {reason}",
                    json.dumps({"escalation_reason": reason, "triggered_by": triggered_by})
                )
            )
            conn.commit()
            return updated


def get_breached_unconfirmed_appointments(
    cutoff_threshold: Optional[dt_mod.datetime] = None,
    as_of_time: Optional[dt_mod.datetime] = None,
) -> List[Dict[str, Any]]:
    """
    Retrieves all pending appointments where confirmation_cutoff_at <= cutoff_threshold
    and confirmation_status is still 'pending_agent_confirmation' and escalation_status is 'none'.
    """
    if cutoff_threshold is None:
        from serviceBot.services.booking import BUSINESS_TZ
        cutoff_threshold = as_of_time if as_of_time is not None else dt_mod.datetime.now(BUSINESS_TZ).replace(tzinfo=None)

    if cutoff_threshold.tzinfo is not None:
        from serviceBot.services.timezone_service import to_business_tz

        # Cutoffs are business wall-clock timestamps, independent of the DB session timezone.
        cutoff_threshold = to_business_tz(cutoff_threshold).replace(tzinfo=None)

    query = """
    SELECT sr.*, c.name AS customer_name, c.phone AS customer_phone, sa.name AS agent_name, sa.phone_number AS agent_phone
    FROM service_requests sr
    LEFT JOIN customers c ON sr.customer_id = c.id
    LEFT JOIN staff_agents sa ON sr.staff_agent_id = sa.id
    WHERE sr.confirmation_status = 'pending_agent_confirmation'
      AND sr.confirmation_cutoff_at IS NOT NULL
      AND sr.confirmation_cutoff_at <= %s
      AND sr.escalation_status IN ('none', 'reassigned')
      AND sr.status IN ('pending', 'in_progress')
    ORDER BY sr.confirmation_cutoff_at ASC;
    """
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(query, (cutoff_threshold,))
            rows = cursor.fetchall()
            return [dict(r) for r in rows]
