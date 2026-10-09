"""
Centralized Business Time Zone Service.
Provides single source of truth for business operational timezone resolution,
DST-aware zoneinfo instances, and standardized datetime conversions.
"""

import datetime as dt_mod
import json
import os
import zoneinfo
from typing import Optional


def _get_config_path() -> str:
    current_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.abspath(os.path.join(current_dir, "..", "config.json"))


def load_config() -> dict:
    """Helper to read config.json dynamically."""
    try:
        config_path = _get_config_path()
        if os.path.exists(config_path):
            with open(config_path, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


DEFAULT_BUSINESS_TIMEZONE = "America/New_York"


def validate_timezone(tz_name: Optional[str]) -> bool:
    """Validate whether tz_name is a valid IANA timezone identifier."""
    if not tz_name or not isinstance(tz_name, str):
        return False
    clean_name = tz_name.strip()
    if not clean_name:
        return False
    try:
        zoneinfo.ZoneInfo(clean_name)
        return True
    except Exception:
        return False


def get_business_timezone_str() -> str:
    """Return the configured business timezone string or default to America/New_York."""
    cfg = load_config()
    tz_val = cfg.get("business_timezone")
    if tz_val and isinstance(tz_val, str) and validate_timezone(tz_val.strip()):
        return tz_val.strip()
    return DEFAULT_BUSINESS_TIMEZONE


def get_business_zoneinfo() -> zoneinfo.ZoneInfo:
    """Return the active ZoneInfo object for the configured business timezone."""
    tz_str = get_business_timezone_str()
    try:
        return zoneinfo.ZoneInfo(tz_str)
    except Exception:
        return zoneinfo.ZoneInfo(DEFAULT_BUSINESS_TIMEZONE)


def now_in_business_tz() -> dt_mod.datetime:
    """Return current timezone-aware datetime in the business operational timezone."""
    return dt_mod.datetime.now(get_business_zoneinfo())


def to_business_tz(dt: dt_mod.datetime) -> dt_mod.datetime:
    """
    Convert a datetime to the business operational timezone.
    If naive, attaches the business timezone.
    If timezone-aware, converts using astimezone().
    """
    if dt is None:
        return None
    biz_tz = get_business_zoneinfo()
    if dt.tzinfo is None:
        return dt.replace(tzinfo=biz_tz)
    return dt.astimezone(biz_tz)


def to_utc(dt: dt_mod.datetime) -> dt_mod.datetime:
    """
    Convert a datetime to UTC.
    If naive, assumes it is wall-clock time in the business operational timezone.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=get_business_zoneinfo())
    return dt.astimezone(dt_mod.timezone.utc)


def get_utc_offset_str(dt: Optional[dt_mod.datetime] = None) -> str:
    """
    Return the UTC offset string (e.g. "-04:00" or "-05:00") for the given datetime
    or current time in the configured business timezone.
    """
    target = dt or now_in_business_tz()
    target_in_tz = to_business_tz(target)
    offset = target_in_tz.utcoffset()
    if offset is None:
        return "+00:00"
    total_seconds = int(offset.total_seconds())
    sign = "+" if total_seconds >= 0 else "-"
    total_seconds = abs(total_seconds)
    hours, remainder = divmod(total_seconds, 3600)
    minutes = remainder // 60
    return f"{sign}{hours:02d}:{minutes:02d}"


def format_business_datetime(dt: dt_mod.datetime, fmt: str = "%Y-%m-%d %I:%M %p") -> str:
    """Format datetime in the business timezone."""
    if not dt:
        return ""
    biz_dt = to_business_tz(dt)
    return biz_dt.strftime(fmt)
