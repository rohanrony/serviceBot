"""
calendar_sync.py
================
Syncs connected agents' real Google Calendar free/busy data into mock_calendar_slots.

Called:
  - On server startup (for all connected agents)
  - After an OAuth connection is completed
  - Via the portal API endpoint POST /agents/{id}/calendar/populate
  - During check_availability when an agent has 0 DB slots

Business hours: Mon–Fri, 7 AM – 6 PM (America/New_York)
Slots already booked (by the system) are preserved. Only UNBOOKED slots are
re-evaluated against live Google Calendar to flip them booked/available.
"""

import datetime
import traceback
from typing import List, Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from serviceBot.services import timezone_service

class _DynamicCalendarSyncTZ(datetime.tzinfo):
    @property
    def _tz(self):
        return timezone_service.get_business_zoneinfo()

    def utcoffset(self, dt):
        return self._tz.utcoffset(dt)

    def dst(self, dt):
        return self._tz.dst(dt)

    def tzname(self, dt):
        return self._tz.tzname(dt)

    def fromutc(self, dt):
        wrapped = self._tz
        if dt.tzinfo is self:
            dt = dt.replace(tzinfo=wrapped)
        return wrapped.fromutc(dt)

TZ = _DynamicCalendarSyncTZ()
from serviceBot.logger import get_logger

logger = get_logger("services.calendar_sync")
DEFAULT_DAYS  = 30


def get_configured_business_hours() -> List[int]:
    """
    Returns the list of integer hours for business hours based on portal configuration.
    Reads 'business_hours_start', 'business_hours_end', or 'business_hours' from config.json.
    Defaults to 7 AM – 6 PM (hours 7 through 17).
    """
    try:
        from serviceBot.api.portal import load_config
        cfg = load_config()
        if cfg.get("business_hours") and isinstance(cfg["business_hours"], list) and len(cfg["business_hours"]) > 0:
            return [int(h) for h in cfg["business_hours"]]
        start = int(cfg.get("business_hours_start", 7))
        end = int(cfg.get("business_hours_end", 18))
        if start < end:
            return list(range(start, end))
    except Exception as e:
        logger.warning(f"Error loading configured business hours: {e}")
    return list(range(7, 18))


def get_configured_business_days() -> List[int]:
    """
    Returns the list of integer business days of week (0=Monday, 6=Sunday).
    Reads 'business_days' from config.json. Defaults to [0, 1, 2, 3, 4] (Mon-Fri).
    """
    try:
        from serviceBot.api.portal import load_config
        cfg = load_config()
        if cfg.get("business_days") and isinstance(cfg["business_days"], list) and len(cfg["business_days"]) > 0:
            return [int(d) for d in cfg["business_days"]]
    except Exception as e:
        logger.warning(f"Error loading configured business days: {e}")
    return [0, 1, 2, 3, 4]


def get_business_hours_display() -> tuple[str, str]:
    """
    Returns (schedule_description, closing_time_str) based on portal configuration.
    Example: ("Monday to Friday, 7:00 AM to 6:00 PM", "6:00 PM")
    """
    b_hours = get_configured_business_hours()
    b_days = get_configured_business_days()
    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    if b_days:
        if b_days == list(range(min(b_days), max(b_days) + 1)):
            days_str = f"{day_names[min(b_days)]} to {day_names[max(b_days)]}"
        else:
            days_str = ", ".join(day_names[d] for d in b_days)
    else:
        days_str = "Monday to Friday"

    start_h = min(b_hours) if b_hours else 7
    end_h = (max(b_hours) + 1) if b_hours else 18
    s_dt = datetime.datetime(2000, 1, 1, start_h, 0)
    e_dt = datetime.datetime(2000, 1, 1, end_h, 0)
    s_str = s_dt.strftime("%I:%M %p").lstrip("0")
    e_str = e_dt.strftime("%I:%M %p").lstrip("0")
    return f"{days_str}, {s_str} to {e_str}", e_str


def _generate_slot_strings(days: int = DEFAULT_DAYS, hours: List[int] = None) -> List[str]:
    """Return a list of 'YYYY-MM-DD HH:MM:SS' strings for business-hour slots."""
    if hours is None:
        hours = get_configured_business_hours()
    valid_days = get_configured_business_days()
    today = timezone_service.now_in_business_tz().date()
    slots = []
    for offset in range(days):
        day = today + datetime.timedelta(days=offset)
        if day.weekday() not in valid_days:          # Skip non-operating business days
            continue
        for hour in hours:
            for minute in (0, 15, 30, 45):
                dt = datetime.datetime.combine(day, datetime.time(hour, minute, 0))
                slots.append(dt.strftime("%Y-%m-%d %H:%M:%S"))
    return slots
