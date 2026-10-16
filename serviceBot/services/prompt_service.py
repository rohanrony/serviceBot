"""
prompt_service.py
=================
Handles dynamic prompt templating, formatting, and synchronization of
operational business hours, operating workdays, and closing boundaries
in the voice assistant system prompt.
"""

import datetime as dt_mod
import re
from typing import List, Optional, Dict, Any

from serviceBot.logger import get_logger

logger = get_logger("services.prompt_service")

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

TIMEZONE_ABBR_MAP = {
    "America/New_York": "ET",
    "America/Detroit": "ET",
    "America/Indiana/Indianapolis": "ET",
    "America/Chicago": "CT",
    "America/Denver": "MT",
    "America/Phoenix": "MST",
    "America/Los_Angeles": "PT",
    "America/Anchorage": "AKST",
    "Pacific/Honolulu": "HST",
}


def get_timezone_abbr(timezone_str: str) -> str:
    """Return common 2-4 letter timezone code (e.g. ET, CT, PT)."""
    clean_tz = (timezone_str or "").strip()
    if clean_tz in TIMEZONE_ABBR_MAP:
        return TIMEZONE_ABBR_MAP[clean_tz]
    try:
        import zoneinfo
        zi = zoneinfo.ZoneInfo(clean_tz)
        now_dt = dt_mod.datetime.now(zi)
        tz_abbr = now_dt.strftime("%Z")
        if tz_abbr:
            if tz_abbr in ("EST", "EDT"):
                return "ET"
            if tz_abbr in ("CST", "CDT"):
                return "CT"
            if tz_abbr in ("MST", "MDT"):
                return "MT"
            if tz_abbr in ("PST", "PDT"):
                return "PT"
            return tz_abbr
    except Exception:
        pass
    return "ET"


def format_business_schedule(
    start_hour: int,
    end_hour: int,
    business_days: Optional[List[int]] = None,
    timezone_str: Optional[str] = None
) -> Dict[str, Any]:
    """
    Computes all schedule display strings, closing boundary calculations,
    and duration latest start times for prompt formatting.
    """
    days = [int(d) for d in business_days] if business_days is not None else [0, 1, 2, 3, 4]
    days = sorted(set(days))
    if not days:
        days = [0, 1, 2, 3, 4]

    # Contiguous vs non-contiguous day display
    is_contiguous = (days == list(range(min(days), max(days) + 1)))
    if is_contiguous:
        days_hyphen = f"{DAY_NAMES[min(days)]}–{DAY_NAMES[max(days)]}"
        days_spoken = f"{DAY_NAMES[min(days)]} to {DAY_NAMES[max(days)]}"
    else:
        days_hyphen = ", ".join(DAY_NAMES[d] for d in days)
        days_spoken = days_hyphen

    # Closed days description
    closed_days = [d for d in range(7) if d not in days]
    if closed_days == [5, 6]:
        closed_desc = "closed weekends"
    elif closed_days == [6]:
        closed_desc = "closed Sundays"
    elif closed_days == [0, 6]:
        closed_desc = "closed Sunday and Monday"
    elif len(closed_days) == 0:
        closed_desc = "open 7 days a week"
    else:
        closed_desc = f"closed {', '.join(DAY_NAMES[d] + 's' for d in closed_days)}"

    # Hours
    start_dt = dt_mod.datetime(2000, 1, 1, start_hour, 0)
    end_dt = dt_mod.datetime(2000, 1, 1, end_hour, 0)
    start_str = start_dt.strftime("%I:%M %p").lstrip("0")
    end_str = end_dt.strftime("%I:%M %p").lstrip("0")

    tz_code = get_timezone_abbr(timezone_str or "America/New_York")

    # Latest start times by service duration
    # 60m: end - 60m
    dt_60 = end_dt - dt_mod.timedelta(minutes=60)
    start_60 = dt_60.strftime("%I:%M %p").lstrip("0")

    # 90m: end - 90m
    dt_90 = end_dt - dt_mod.timedelta(minutes=90)
    start_90 = dt_90.strftime("%I:%M %p").lstrip("0")

    # 120m: end - 120m
    dt_120 = end_dt - dt_mod.timedelta(minutes=120)
    start_120 = dt_120.strftime("%I:%M %p").lstrip("0")

    # Example violation (e.g. asking for 1 hour before closing for 90m service)
    bad_start_dt = end_dt - dt_mod.timedelta(minutes=60)
    bad_end_dt = bad_start_dt + dt_mod.timedelta(minutes=90)
    example_bad_start = bad_start_dt.strftime("%I:%M %p").lstrip("0")
    example_bad_end = bad_end_dt.strftime("%I:%M %p").lstrip("0")

    return {
        "days_hyphen": days_hyphen,
        "days_spoken": days_spoken,
        "closed_desc": closed_desc,
        "start_str": start_str,
        "end_str": end_str,
        "tz_code": tz_code,
        "start_60": start_60,
        "start_90": start_90,
        "start_120": start_120,
        "example_bad_start": example_bad_start,
        "example_bad_end": example_bad_end,
    }


def generate_closing_boundary_block(sched: Dict[str, Any], indent: str = "  ") -> str:
    """Generates the standardized Closing Boundary markdown section."""
    days_hyphen = sched["days_hyphen"]
    start_str = sched["start_str"]
    end_str = sched["end_str"]
    tz_code = sched["tz_code"]
    closed_desc = sched["closed_desc"]
    start_60 = sched["start_60"]
    start_90 = sched["start_90"]
    start_120 = sched["start_120"]
    example_bad_start = sched["example_bad_start"]
    example_bad_end = sched["example_bad_end"]

    return (
        f"{indent}4. **Business Hours Closing Boundary & Duration Constraints (MANDATORY):**\n"
        f"{indent}   - Business hours are strictly {days_hyphen}, {start_str} – {end_str} {tz_code} ({closed_desc}). All in-shop appointments must fully conclude by {end_str}. Technicians and shop operations finish promptly at {end_str}.\n"
        f"{indent}   - Calculate the **Latest Possible Start Time**: `Latest Start Time = {end_str} - Total Service Duration`.\n"
        f"{indent}     - 60-minute service: Latest possible start is {start_60} (concludes at {end_str}).\n"
        f"{indent}     - 90-minute (1.5-hour) service: Latest possible start is {start_90} (concludes at {end_str}).\n"
        f"{indent}     - 120-minute (2-hour) service: Latest possible start is {start_120} (concludes at {end_str}).\n"
        f"{indent}   - **STRICT PROHIBITION:** You must NEVER offer, suggest, or accept an appointment start time where `start_time + duration` extends past {end_str} (for example, a 90-minute service at {example_bad_start} would extend until {example_bad_end}, which is after hours and strictly prohibited).\n"
        f"{indent}   - **Proactive Boundary Enforcement:** If the customer asks for a time that would run past {end_str} (e.g. asking for {example_bad_start} for a 90-minute service), immediately catch it and explain politely:\n"
        f"{indent}     *\"Our service center closes at {end_str}, and since this service takes about 1.5 hours, the latest appointment we can begin is {start_90}. Would you like to book for {start_90}, or would an earlier time or another day work better for you?\"*\n"
        f"{indent}     Never wait for the customer to remind you of our business hours!"
    )


def update_prompt_business_hours(
    prompt_text: str,
    start_hour: int,
    end_hour: int,
    business_days: Optional[List[int]] = None,
    timezone_str: Optional[str] = "America/New_York"
) -> str:
    """
    Substitutes operational business hours, operating days, timezone,
    closing boundaries, and calculated latest start durations into prompt_text.
    Preserves all other instructions, sections, and custom additions.
    """
    if not prompt_text or not isinstance(prompt_text, str):
        return prompt_text

    sched = format_business_schedule(start_hour, end_hour, business_days, timezone_str)
    updated = prompt_text

    # 1. FAQ & General Knowledge bullet
    # Example: - **FAQ & General Knowledge:** The caller has questions about business hours (Monday-Friday 7:00 AM - 6:00 PM, closed weekends), location...
    faq_hours_str = f"{sched['days_hyphen']} {sched['start_str']} - {sched['end_str']}, {sched['closed_desc']}"
    faq_pattern = re.compile(
        r"(-\s*\*\*FAQ\s*&\s*General Knowledge:\*\*.*?questions about business hours\s*\()[^)]+(\))",
        re.IGNORECASE
    )
    updated = faq_pattern.sub(rf"\g<1>{faq_hours_str}\2", updated)

    # 2. If Callback bullet
    # Example: - **If Callback:** Callback calls are made during business hours (Monday–Friday 7:00 AM – 6:00 PM ET).
    callback_hours_str = f"{sched['days_hyphen']} {sched['start_str']} – {sched['end_str']} {sched['tz_code']}"
    callback_pattern = re.compile(
        r"(-\s*\*\*If Callback:\*\*\s*Callback calls are made during business hours\s*\()[^)]+(\))",
        re.IGNORECASE
    )
    updated = callback_pattern.sub(rf"\g<1>{callback_hours_str}\2", updated)

    # Also handle shorter portal.py default:
    # Example: - If they prefer a callback: Callback calls are made during business hours (Monday–Friday 7:00 AM – 6:00 PM ET).
    callback_alt_pattern = re.compile(
        r"(-\s*If they prefer a callback:\s*Callback calls are made during business hours\s*\()[^)]+(\))",
        re.IGNORECASE
    )
    updated = callback_alt_pattern.sub(rf"\g<1>{callback_hours_str}\2", updated)

    # 3. Business Hours Closing Boundary & Duration Constraints section (multi-line block)
    boundary_block = generate_closing_boundary_block(sched)
    # Match from section header to next numbered list item (Quote...) or heading
    closing_boundary_pattern = re.compile(
        r"(\s*\d+\.\s+\*\*Business Hours Closing Boundary & Duration Constraints \(MANDATORY\):\*\*[\s\S]*?)(?=\n\s*(?:\d+\.\s+Quote|###|\Z))"
    )
    if closing_boundary_pattern.search(updated):
        updated = closing_boundary_pattern.sub(boundary_block, updated)
    else:
        # Check single-bullet variant in portal.py default:
        single_bullet_pattern = re.compile(
            r"(-\s*\*\*Business Hours Closing Boundary & Duration Constraints \(MANDATORY\):\*\*[\s\S]*?)(?=\n\s*-\s*\*\*|\n\s*###|\Z)"
        )
        if single_bullet_pattern.search(updated):
            single_block = (
                f"- **Business Hours Closing Boundary & Duration Constraints (MANDATORY):** "
                f"Business hours are strictly {sched['days_hyphen']}, {sched['start_str']} – {sched['end_str']} {sched['tz_code']} ({sched['closed_desc']}). "
                f"All appointments must conclude strictly by {sched['end_str']}. "
                f"Calculate Latest Start Time = {sched['end_str']} minus service duration "
                f"(e.g., 60m -> {sched['start_60']} max; 90m -> {sched['start_90']} max; 120m -> {sched['start_120']} max). "
                f"NEVER offer or accept any appointment extending past {sched['end_str']}. "
                f"If a caller asks for a time that would run past {sched['end_str']} (e.g. {sched['example_bad_start']} for 90m), "
                f"immediately inform them that the shop closes at {sched['end_str']}, explain the latest start time is {sched['start_90']}, "
                f"and offer {sched['start_90']} or an earlier slot."
            )
            updated = single_bullet_pattern.sub(single_block, updated)

    # 4. Human Handoff hours (in comments or active sections)
    # Example: AND ONLY during business hours (Monday-Friday 7:00 AM - 6:00 PM ET).
    handoff_pattern1 = re.compile(
        r"(AND ONLY during business hours\s*\()[^)]+(\))",
        re.IGNORECASE
    )
    updated = handoff_pattern1.sub(rf"\g<1>{sched['days_hyphen']} {sched['start_str']} - {sched['end_str']} {sched['tz_code']}\2", updated)

    # Example: (business hours are Monday to Friday, 7:00 AM to 6:00 PM ET)
    handoff_pattern2 = re.compile(
        r"(\(business hours are\s+)[^)]+(\))",
        re.IGNORECASE
    )
    updated = handoff_pattern2.sub(rf"\g<1>{sched['days_spoken']}, {sched['start_str']} to {sched['end_str']} {sched['tz_code']}\2", updated)

    return updated
