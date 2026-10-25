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
    timezone_str: Optional[str] = None,
    business_hours: Optional[List[int]] = None,
) -> Dict[str, Any]:
    """
    Computes all schedule display strings, closing boundary calculations,
    and duration latest start times for prompt formatting. Supports split schedules.
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

    # Hours & Split Interval handling
    if business_hours is not None and len(business_hours) > 0:
        sorted_h = sorted(set(int(h) for h in business_hours))
        intervals = []
        start = sorted_h[0]
        prev = sorted_h[0]
        for h in sorted_h[1:]:
            if h == prev + 1:
                prev = h
            else:
                intervals.append((start, prev + 1))
                start = h
                prev = h
        intervals.append((start, prev + 1))

        parts = []
        for s, e in intervals:
            s_dt = dt_mod.datetime(2000, 1, 1, s, 0)
            e_dt = dt_mod.datetime(2000, 1, 1, e, 0)
            parts.append(f"{s_dt.strftime('%I:%M %p').lstrip('0')} - {e_dt.strftime('%I:%M %p').lstrip('0')}")

        if len(parts) == 1:
            hours_desc = parts[0]
        elif len(parts) == 2:
            hours_desc = f"{parts[0]} and {parts[1]}"
        else:
            hours_desc = ", ".join(parts[:-1]) + f", and {parts[-1]}"

        eff_start_h = intervals[0][0]
        eff_end_h = intervals[-1][1]
    else:
        eff_start_h = start_hour
        eff_end_h = end_hour
        start_dt = dt_mod.datetime(2000, 1, 1, start_hour, 0)
        end_dt = dt_mod.datetime(2000, 1, 1, end_hour, 0)
        hours_desc = f"{start_dt.strftime('%I:%M %p').lstrip('0')} - {end_dt.strftime('%I:%M %p').lstrip('0')}"

    start_dt = dt_mod.datetime(2000, 1, 1, eff_start_h, 0)
    end_dt = dt_mod.datetime(2000, 1, 1, eff_end_h, 0)
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
        "hours_desc": hours_desc,
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
    hours_desc = sched["hours_desc"]
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
        f"{indent}   - Business hours are strictly {days_hyphen}, {hours_desc} {tz_code} ({closed_desc}). All appointments must fully conclude by {end_str}. Agents and business operations finish promptly at {end_str}.\n"
        f"{indent}   - Calculate the **Latest Possible Start Time**: `Latest Start Time = {end_str} - Total Service Duration`.\n"
        f"{indent}     - 60-minute service: Latest possible start is {start_60} (concludes at {end_str}).\n"
        f"{indent}     - 90-minute (1.5-hour) service: Latest possible start is {start_90} (concludes at {end_str}).\n"
        f"{indent}     - 120-minute (2-hour) service: Latest possible start is {start_120} (concludes at {end_str}).\n"
        f"{indent}   - **STRICT PROHIBITION:** You must NEVER offer, suggest, or accept an appointment start time where `start_time + duration` extends past {end_str} (for example, a 90-minute service at {example_bad_start} would extend until {example_bad_end}, which is after hours and strictly prohibited).\n"
        f"{indent}   - **Proactive Boundary Enforcement:** If the customer asks for a time that would run past {end_str} (e.g. asking for {example_bad_start} for a 90-minute service), immediately catch it and explain politely:\n"
        f"{indent}     *\"Our service center closes at {end_str}, and since this service takes about 1.5 hours, the latest appointment we can begin is {start_90}. Would you like to book for {start_90}, or would an earlier time or another day work better for you?\"*\n"
        f"{indent}     Never wait for the customer to remind you of our business hours!"
    )


INTERVAL_PATTERN = r"\b\d{1,2}(?::\d{2})?\s*(?:am|pm)?\s*(?:[-–—to]+|\s+to\s+)\s*\d{1,2}(?::\d{2})?\s*(?:am|pm)?\b"
INTERVAL_SEP = r"(?:[,\s]+and\s+|[,\s]*&[,\s]*|[,\s]*\/[,\s]*|,\s*|\s+and\s+)"
CLOSED_PATTERN = r"(?:\([ \t]*(?:we\s+are\s+)?closed[^\)]*\)|[,\s]*(?:we\s+are\s+)?closed\s+(?:on\s+)?[a-z0-9,\s]+(?:\sand\s+[a-z0-9]+)?)"

RECOGNIZED_SCHEDULE_RE = re.compile(
    rf"""^
    [ \t]*
    (?:
        (?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|Mon|Tue|Wed|Thu|Fri|Sat|Sun|Weekdays|Daily)
        (?:\s*(?:[-–—to]|and|through)\s*(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|Mon|Tue|Wed|Thu|Fri|Sat|Sun))?
        [,\s]*
    )*
    (?:
        {INTERVAL_PATTERN}
        (?:
            {INTERVAL_SEP}
            {INTERVAL_PATTERN}
        )*
    )
    (?:[ \t]+(?:ET|EST|EDT|CT|CST|CDT|MT|MST|MDT|PT|PST|PDT|UTC|GMT))?
    (?:[,\s]*{CLOSED_PATTERN})?
    [.\s]*
    """,
    re.VERBOSE | re.IGNORECASE
)


def update_prompt_business_hours(
    prompt_text: str,
    start_hour: int,
    end_hour: int,
    business_days: Optional[List[int]] = None,
    timezone_str: Optional[str] = "America/New_York",
    business_hours: Optional[List[int]] = None,
) -> str:
    """
    Substitutes operational business hours, operating days, timezone,
    closing boundaries, and calculated latest start durations into prompt_text.
    Preserves all other instructions, sections, and custom additions.
    """
    if not prompt_text or not isinstance(prompt_text, str):
        return prompt_text

    sched = format_business_schedule(start_hour, end_hour, business_days, timezone_str, business_hours)
    unsynchronized_schedules = []

    def replace_business_hours_line(m):
        prefix = m.group(1)
        remainder = m.group(2)

        custom_suffix = ""
        trimmed = remainder.strip()
        sep = " " if not prefix.endswith(" ") else ""
        if trimmed:
            match = RECOGNIZED_SCHEDULE_RE.match(remainder)
            if match:
                tail = remainder[match.end():].strip()
                if tail:
                    if tail.startswith(";"):
                        custom_trimmed = tail.lstrip(";").strip()
                        custom_suffix = f"; {custom_trimmed}"
                        if custom_trimmed:
                            unsynchronized_schedules.append(custom_trimmed)
                            logger.warning(f"Preserving custom instructions following schedule: {custom_trimmed}")
                    elif tail.startswith("|"):
                        custom_trimmed = tail.lstrip("|").strip()
                        custom_suffix = f" | {custom_trimmed}"
                        if custom_trimmed:
                            unsynchronized_schedules.append(custom_trimmed)
                            logger.warning(f"Preserving custom instructions following schedule: {custom_trimmed}")
                    elif tail.startswith("- "):
                        custom_trimmed = tail[2:].strip()
                        custom_suffix = f" - {custom_trimmed}"
                        if custom_trimmed:
                            unsynchronized_schedules.append(custom_trimmed)
                            logger.warning(f"Preserving custom instructions following schedule: {custom_trimmed}")
                    else:
                        clean_tail = tail.lstrip(". ").strip()
                        if clean_tail:
                            custom_suffix = f". {clean_tail}"
                            unsynchronized_schedules.append(clean_tail)
                            logger.warning(f"Preserving custom instructions following schedule: {clean_tail}")
            elif ";" in remainder:
                sched_part, custom_part = remainder.split(";", 1)
                custom_trimmed = custom_part.strip()
                custom_suffix = f"; {custom_trimmed}"
                if custom_trimmed:
                    unsynchronized_schedules.append(custom_trimmed)
                    logger.warning(f"Preserving custom instructions following schedule: {custom_trimmed}")
            elif " | " in remainder:
                sched_part, custom_part = remainder.split(" | ", 1)
                custom_trimmed = custom_part.strip()
                custom_suffix = f" | {custom_trimmed}"
                if custom_trimmed:
                    unsynchronized_schedules.append(custom_trimmed)
                    logger.warning(f"Preserving custom instructions following schedule: {custom_trimmed}")
            else:
                unsynchronized_schedules.append(trimmed)
                logger.warning(f"Schedule text could not be synchronized safely: {trimmed}")
                return f"{prefix}{sep}{sched['days_hyphen']} {sched['hours_desc']} {sched['tz_code']}. Note: {trimmed}"

        if custom_suffix:
            if (
                custom_suffix.startswith(".")
                or custom_suffix.startswith(";")
                or custom_suffix.startswith(" |")
                or custom_suffix.startswith(" -")
            ):
                return f"{prefix}{sep}{sched['days_hyphen']} {sched['hours_desc']} {sched['tz_code']}{custom_suffix}"
            return f"{prefix}{sep}{sched['days_hyphen']} {sched['hours_desc']} {sched['tz_code']}. {custom_suffix.lstrip()}"
        return f"{prefix}{sep}{sched['days_hyphen']} {sched['hours_desc']} {sched['tz_code']}."

    updated = re.sub(
        r"(?m)^([ \t]*(?:[-*][ \t]*)?Business hours:[ \t]*)([^\r\n]*)$",
        replace_business_hours_line,
        prompt_text
    )
    update_prompt_business_hours.unsynchronized_schedules = unsynchronized_schedules

    # 1. FAQ & General Knowledge bullet
    # Example: - **FAQ & General Knowledge:** The caller has questions about business hours (Monday-Friday 7:00 AM - 6:00 PM, closed weekends), location...
    faq_hours_str = f"{sched['days_hyphen']} {sched['hours_desc']}, {sched['closed_desc']}"
    faq_pattern = re.compile(
        r"(-\s*\*\*FAQ\s*&\s*General Knowledge:\*\*.*?questions about business hours\s*\()[^)]+(\))",
        re.IGNORECASE
    )
    updated = faq_pattern.sub(rf"\g<1>{faq_hours_str}\2", updated)

    # 2. If Callback bullet
    # Example: - **If Callback:** Callback calls are made during business hours (Monday–Friday 7:00 AM – 6:00 PM ET).
    callback_hours_str = f"{sched['days_hyphen']} {sched['hours_desc']} {sched['tz_code']}"
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
                f"Business hours are strictly {sched['days_hyphen']}, {sched['hours_desc']} {sched['tz_code']} ({sched['closed_desc']}). "
                f"All appointments must conclude strictly by {sched['end_str']}. "
                f"Calculate Latest Start Time = {sched['end_str']} minus service duration "
                f"(e.g., 60m -> {sched['start_60']} max; 90m -> {sched['start_90']} max; 120m -> {sched['start_120']} max). "
                f"NEVER offer or accept any appointment extending past {sched['end_str']}. "
                f"If a caller asks for a time that would run past {sched['end_str']} (e.g. {sched['example_bad_start']} for 90m), "
                f"immediately inform them that the business closes at {sched['end_str']}, explain the latest start time is {sched['start_90']}, "
                f"and offer {sched['start_90']} or an earlier slot."
            )
            updated = single_bullet_pattern.sub(single_block, updated)

    # 4. Human Handoff hours (in comments or active sections)
    # Example: AND ONLY during business hours (Monday-Friday 7:00 AM - 6:00 PM ET).
    handoff_pattern1 = re.compile(
        r"(AND ONLY during business hours\s*\()[^)]+(\))",
        re.IGNORECASE
    )
    updated = handoff_pattern1.sub(rf"\g<1>{sched['days_hyphen']} {sched['hours_desc']} {sched['tz_code']}\2", updated)

    # Example: (business hours are Monday to Friday, 7:00 AM to 6:00 PM ET)
    handoff_pattern2 = re.compile(
        r"(\(business hours are\s+)[^)]+(\))",
        re.IGNORECASE
    )
    updated = handoff_pattern2.sub(rf"\g<1>{sched['days_spoken']}, {sched['hours_desc']} {sched['tz_code']}\2", updated)

    return updated


def update_prompt_lead_time_buffers(
    prompt_text: str,
    appointment_buffer_hours: float = 4.0,
    callback_buffer_hours: float = 2.0
) -> str:
    """
    Substitutes appointment and callback advance lead time buffers into prompt_text.
    Maintains prompt consistency when shop policies or configuration are updated.
    """
    if not prompt_text or not isinstance(prompt_text, str):
        return prompt_text

    appt_val = float(appointment_buffer_hours)
    cb_val = float(callback_buffer_hours)
    appt_disp = int(appt_val) if appt_val.is_integer() else appt_val
    cb_disp = int(cb_val) if cb_val.is_integer() else cb_val

    updated = re.sub(r"Appointments require at least \d+(?:\.\d+)? hours advance notice; callbacks require \d+(?:\.\d+)? hours\.",
        f"Appointments require at least {appt_disp} hours advance notice; callbacks require {cb_disp} hours.", prompt_text)

    # 1. Update Appointment Horizon header (e.g., 4-Hour Minimum Planning Horizon Restriction)
    updated = re.sub(
        r"(\d+(?:\.\d+)?)-Hour Minimum Planning Horizon Restriction",
        f"{appt_disp}-Hour Minimum Planning Horizon Restriction",
        updated
    )

    # 2. Update Appointment notice sentences
    updated = re.sub(
        r"our shop requires at least \d+(?:\.\d+)? hours advance notice for all in-shop appointments",
        f"our shop requires at least {appt_disp} hours advance notice for all in-shop appointments",
        updated,
        flags=re.IGNORECASE
    )

    updated = re.sub(
        r"earlier than \d+(?:\.\d+)? hours from the current time \(`now \+ \d+(?:\.\d+)? hours`\)",
        f"earlier than {appt_disp} hours from the current time (`now + {appt_disp} hours`)",
        updated
    )

    updated = re.sub(
        r"our shop requires at least \d+(?:\.\d+)? hours advance notice\.",
        f"our shop requires at least {appt_disp} hours advance notice.",
        updated,
        flags=re.IGNORECASE
    )

    updated = re.sub(
        r"now \+ \d+(?:\.\d+)?h",
        f"now + {appt_disp}h",
        updated
    )

    # 3. Update callback references in appointment fallback
    updated = re.sub(
        r"\(callbacks have no \d+(?:\.\d+)?-hour buffer\)",
        f"(advisor callbacks require at least {cb_disp} hours advance notice)",
        updated,
        flags=re.IGNORECASE
    )
    updated = re.sub(
        r"\(advisor callbacks require at least \d+(?:\.\d+)? hours advance notice\)",
        f"(advisor callbacks require at least {cb_disp} hours advance notice)",
        updated,
        flags=re.IGNORECASE
    )

    # 4. Update callback section with lead time requirement
    cb_notice_pattern = re.compile(
        r"(?<!advisor )Callbacks require at least \d+(?:\.\d+)? hours advance notice[^.]*\.",
        re.IGNORECASE
    )
    cb_statement = f"Callbacks require at least {cb_disp} hours advance notice during business hours so an agent can review their service request."

    if cb_notice_pattern.search(updated):
        updated = cb_notice_pattern.sub(cb_statement, updated)
    else:
        # Inject right after "Callback calls are made during business hours (...)."
        updated = re.sub(
            r"((?:If Callback:|\- If they prefer a callback:)\s*Callback calls are made during business hours\s*\([^)]+\)\.)",
            rf"\g<1> {cb_statement}",
            updated,
            flags=re.IGNORECASE
        )

    return updated
