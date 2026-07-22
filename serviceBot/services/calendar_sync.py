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
        print(f"[calendar_sync] Error loading configured business hours: {e}")
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
        print(f"[calendar_sync] Error loading configured business days: {e}")
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
            dt = datetime.datetime.combine(day, datetime.time(hour, 0, 0))
            slots.append(dt.strftime("%Y-%m-%d %H:%M:%S"))
    return slots


def _check_busy_via_calendar(agent_id: int, slot_strs: List[str], duration_minutes: int = 60) -> dict:
    """
    For a list of slot strings, fetch the agent's Google Calendar events once
    for the whole range, then determine which slots are busy.

    Returns: {slot_str: True}  for every slot that is BUSY.
    """
    if not slot_strs:
        return {}

    from serviceBot.services.google_calendar import (
        get_user_google_credentials,
        parse_google_datetime,
        GoogleAuthException,
        fetch_agent_events,
    )

    # Determine the full query window (first slot start → last slot end)
    slot_dts = [
        datetime.datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=TZ)
        for s in slot_strs
    ]
    window_start = min(slot_dts)
    window_end   = max(slot_dts) + datetime.timedelta(minutes=duration_minutes)

    try:
        events = fetch_agent_events(
            agent_id,
            window_start.isoformat(),
            window_end.isoformat(),
        )
    except Exception as exc:
        print(f"[calendar_sync] Could not fetch events for agent {agent_id}: {exc}")
        return {}

    if events is None:
        # Agent not connected / insufficient scope — treat all as free
        return {}

    busy = {}
    for slot_str in slot_strs:
        slot_start = datetime.datetime.strptime(slot_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=TZ)
        slot_end   = slot_start + datetime.timedelta(minutes=duration_minutes)
        for event in events:
            evt_start = parse_google_datetime(event.get("start"), TZ)
            evt_end   = parse_google_datetime(event.get("end"), TZ)
            if evt_start and evt_end:
                # Overlap: slot_start < evt_end  AND  slot_end > evt_start
                if slot_start < evt_end and slot_end > evt_start:
                    busy[slot_str] = True
                    break
    return busy


def sync_agent_slots(
    agent_id: int,
    days: int = DEFAULT_DAYS,
    hours: List[int] = None,
    duration_minutes: int = 60,
) -> dict:
    """
    Upsert availability slots for a connected agent and mark them free/busy
    according to their live Google Calendar.

    Returns a summary dict with counts.
    """
    from serviceBot.db.connection import get_db_connection, dict_cursor

    slot_strs = _generate_slot_strings(days, hours)
    if not slot_strs:
        return {"created": 0, "freed": 0, "blocked": 0, "total": 0}

    # 1. Check live calendar
    busy_map = _check_busy_via_calendar(agent_id, slot_strs, duration_minutes)

    created  = 0
    freed    = 0
    blocked  = 0

    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            for slot_str in slot_strs:
                is_busy = slot_str in busy_map

                # Try to insert (ON CONFLICT DO NOTHING preserves system-booked entries)
                cursor.execute(
                    "SELECT id, is_booked FROM mock_calendar_slots "
                    "WHERE slot_datetime = CAST(%s AS TIMESTAMP) AND staff_agent_id = %s",
                    (slot_str, agent_id),
                )
                row = cursor.fetchone()

                if row is None:
                    # New slot — insert with live calendar status
                    cursor.execute(
                        "INSERT INTO mock_calendar_slots "
                        "(slot_datetime, is_booked, staff_agent_id) VALUES (%s, %s, %s) "
                        "ON CONFLICT (slot_datetime, staff_agent_id) DO NOTHING",
                        (slot_str, bool(is_busy), agent_id),
                    )
                    if cursor.rowcount:
                        created += 1
                        if is_busy:
                            blocked += 1
                else:
                    # Existing slot: only update is_booked if it was NOT booked by the system
                    existing_booked = bool(row["is_booked"])
                    if not existing_booked and is_busy:
                        # Calendar says busy → mark blocked
                        cursor.execute(
                            "UPDATE mock_calendar_slots SET is_booked = TRUE "
                            "WHERE id = %s", (row["id"],)
                        )
                        blocked += 1
                    elif existing_booked and not is_busy:
                        # Was blocked by calendar, now free → restore
                        freed += 1  # logged but we don't auto-unblock — could be a real booking

            conn.commit()

    total_free = len(slot_strs) - len(busy_map)
    print(
        f"[calendar_sync] Agent {agent_id}: created={created}, "
        f"blocked_by_calendar={blocked}, free_slots≈{total_free}"
    )
    return {
        "created": created,
        "freed": freed,
        "blocked": blocked,
        "total": len(slot_strs),
        "free_estimate": total_free,
    }


def sync_all_connected_agents(days: int = DEFAULT_DAYS) -> dict:
    """
    Runs sync_agent_slots for every agent that has a connected Google Calendar
    with calendar.events scope. Run in parallel for speed.
    """
    from serviceBot.db.connection import get_db_connection, dict_cursor

    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                "SELECT agent_id FROM user_google_accounts WHERE access_token IS NOT NULL AND access_token != '';"
            )
            agent_ids = [r["agent_id"] for r in cursor.fetchall()]

    if not agent_ids:
        print("[calendar_sync] No connected agents found — skipping sync.")
        return {}

    results = {}
    print(f"[calendar_sync] Syncing {len(agent_ids)} connected agent(s): {agent_ids}")

    with ThreadPoolExecutor(max_workers=max(1, len(agent_ids))) as executor:
        future_to_agent = {
            executor.submit(sync_agent_slots, aid, days): aid
            for aid in agent_ids
        }
        for future in as_completed(future_to_agent):
            aid = future_to_agent[future]
            try:
                results[aid] = future.result()
            except Exception as exc:
                print(f"[calendar_sync] Sync failed for agent {aid}: {exc}")
                traceback.print_exc()
                results[aid] = {"error": str(exc)}

    return results

