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
try:
    import zoneinfo
    TZ = zoneinfo.ZoneInfo("America/New_York")
except Exception:
    TZ = datetime.timezone(datetime.timedelta(hours=-4))
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


def _generate_slot_strings(days: int = DEFAULT_DAYS, hours: List[int] = None) -> List[str]:
    """Return a list of 'YYYY-MM-DD HH:MM:SS' strings for business-hour slots."""
    if hours is None:
        hours = get_configured_business_hours()
    valid_days = get_configured_business_days()
    today = datetime.date.today()
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
