"""PostgreSQL-backed calendar slot management for the portal and booking service."""

from __future__ import annotations

import datetime as dt_mod
from typing import Any, Callable, Iterable, Optional

from serviceBot.db.connection import dict_cursor, get_db_connection
from serviceBot.services.calendar_sync import _generate_slot_strings


def _default_fetch_events(agent_id: int, start_iso: str, end_iso: str):
    """Import the Google provider only when a sync operation needs it."""
    from serviceBot.services.google_calendar import fetch_agent_events

    return fetch_agent_events(agent_id, start_iso, end_iso)


class CalendarError(ValueError):
    """Base error for calendar slot operations."""


class CalendarConflictError(CalendarError):
    """Raised when an operation would overwrite a reservation."""


def parse_slot_datetime(value: str | dt_mod.datetime) -> dt_mod.datetime:
    """Parse a portal slot as a timezone-naive America/New_York wall time."""
    if isinstance(value, dt_mod.datetime):
        parsed = value
    elif isinstance(value, str):
        candidate = value.strip().replace("Z", "+00:00")
        try:
            parsed = dt_mod.datetime.fromisoformat(candidate)
        except ValueError as exc:
            raise CalendarError("slot_datetime must be an ISO-8601 datetime.") from exc
    else:
        raise CalendarError("slot_datetime must be an ISO-8601 datetime.")

    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(dt_mod.timezone(dt_mod.timedelta(hours=-4))).replace(tzinfo=None)
    if parsed.second or parsed.microsecond or parsed.minute not in (0, 15, 30, 45):
        raise CalendarError("slot_datetime must begin on a 15-minute boundary.")
    return parsed


def serialize_slot_datetime(value: str | dt_mod.datetime) -> str:
    """Return the stable database/API representation for a calendar slot."""
    return parse_slot_datetime(value).strftime("%Y-%m-%d %H:%M:%S")


def _provider_datetime(value: dict[str, Any]) -> Optional[dt_mod.datetime]:
    raw = value.get("dateTime") or value.get("date")
    if not raw:
        return None
    try:
        parsed = dt_mod.datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = dt_mod.datetime.strptime(str(raw), "%Y-%m-%d")
        except ValueError:
            return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(dt_mod.timezone(dt_mod.timedelta(hours=-4))).replace(tzinfo=None)
    return parsed


def provider_event_overlaps_slot(event: dict[str, Any], starts_at: dt_mod.datetime, duration_minutes: int = 15) -> bool:
    """Return whether a non-cancelled provider event overlaps a local slot."""
    if event.get("status") == "cancelled":
        return False
    event_start = _provider_datetime(event.get("start") or {})
    event_end = _provider_datetime(event.get("end") or {})
    if not event_start or not event_end:
        return False
    ends_at = starts_at + dt_mod.timedelta(minutes=duration_minutes)
    return starts_at < event_end and ends_at > event_start


class CalendarAvailabilityService:
    """Owns calendar slots while Google Calendar remains an asynchronous projection."""

    def __init__(
        self,
        connection_factory: Callable = get_db_connection,
        cursor_factory: Callable = dict_cursor,
        fetch_events: Optional[Callable] = None,
    ):
        self._connection_factory = connection_factory
        self._cursor_factory = cursor_factory
        self._fetch_events = fetch_events or _default_fetch_events

    @staticmethod
    def _slot_dict(row: dict[str, Any]) -> dict[str, Any]:
        result = dict(row)
        slot_datetime = result.get("slot_datetime")
        if isinstance(slot_datetime, dt_mod.datetime):
            result["slot_datetime"] = slot_datetime.strftime("%Y-%m-%d %H:%M:%S")
        result["is_booked"] = bool(result.get("is_booked"))
        return result

    @staticmethod
    def _assert_agent(cursor, agent_id: int) -> None:
        cursor.execute("SELECT id FROM staff_agents WHERE id = %s;", (agent_id,))
        if not cursor.fetchone():
            raise CalendarError(f"Staff agent {agent_id} was not found.")

    def list_slots(self, agent_id: int) -> list[dict[str, Any]]:
        with self._connection_factory() as conn:
            with self._cursor_factory(conn) as cursor:
                self._assert_agent(cursor, agent_id)
                cursor.execute(
                    """
                    SELECT id, slot_datetime, is_booked, staff_agent_id,
                           reservation_status, calendar_integration_status
                    FROM mock_calendar_slots
                    WHERE staff_agent_id = %s
                    ORDER BY slot_datetime ASC;
                    """,
                    (agent_id,),
                )
                return [self._slot_dict(row) for row in cursor.fetchall()]

    def create_slot(self, agent_id: int, slot_datetime: str, is_booked: bool = False) -> dict[str, Any]:
        normalized = serialize_slot_datetime(slot_datetime)
        reservation_status = "BLOCKED" if is_booked else "AVAILABLE"
        with self._connection_factory() as conn:
            with self._cursor_factory(conn) as cursor:
                self._assert_agent(cursor, agent_id)
                cursor.execute(
                    """
                    INSERT INTO mock_calendar_slots (
                        slot_datetime, is_booked, staff_agent_id, reservation_status
                    )
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (slot_datetime, staff_agent_id) DO UPDATE
                    SET updated_at = CURRENT_TIMESTAMP
                    RETURNING id, slot_datetime, is_booked, staff_agent_id,
                              reservation_status, calendar_integration_status;
                    """,
                    (normalized, is_booked, agent_id, reservation_status),
                )
                row = cursor.fetchone()
                conn.commit()
                return self._slot_dict(row)

    def update_slot(
        self,
        slot_id: int,
        is_booked: Optional[bool] = None,
        slot_datetime: Optional[str] = None,
    ) -> dict[str, Any]:
        normalized = serialize_slot_datetime(slot_datetime) if slot_datetime else None
        with self._connection_factory() as conn:
            with self._cursor_factory(conn) as cursor:
                cursor.execute(
                    """
                    SELECT id, slot_datetime, is_booked, staff_agent_id, reservation_status
                    FROM mock_calendar_slots
                    WHERE id = %s
                    FOR UPDATE;
                    """,
                    (slot_id,),
                )
                current = cursor.fetchone()
                if not current:
                    raise CalendarError(f"Calendar slot {slot_id} was not found.")
                if current["reservation_status"] == "RESERVED" and (
                    normalized is not None or is_booked is False
                ):
                    raise CalendarConflictError("A reserved slot cannot be moved, reopened, or deleted.")

                next_booked = current["is_booked"] if is_booked is None else is_booked
                next_status = current["reservation_status"]
                if next_status != "RESERVED":
                    next_status = "BLOCKED" if next_booked else "AVAILABLE"

                cursor.execute(
                    """
                    UPDATE mock_calendar_slots
                    SET slot_datetime = COALESCE(%s, slot_datetime),
                        is_booked = %s,
                        reservation_status = %s,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                    RETURNING id, slot_datetime, is_booked, staff_agent_id,
                              reservation_status, calendar_integration_status;
                    """,
                    (normalized, next_booked, next_status, slot_id),
                )
                row = cursor.fetchone()
                conn.commit()
                return self._slot_dict(row)

    def delete_slot(self, slot_id: int) -> None:
        with self._connection_factory() as conn:
            with self._cursor_factory(conn) as cursor:
                cursor.execute(
                    """
                    SELECT reservation_status
                    FROM mock_calendar_slots
                    WHERE id = %s
                    FOR UPDATE;
                    """,
                    (slot_id,),
                )
                current = cursor.fetchone()
                if not current:
                    raise CalendarError(f"Calendar slot {slot_id} was not found.")
                if current["reservation_status"] == "RESERVED":
                    raise CalendarConflictError("A reserved slot cannot be deleted.")
                cursor.execute("DELETE FROM mock_calendar_slots WHERE id = %s;", (slot_id,))
                conn.commit()

    def populate_agent(self, agent_id: int, days: int = 30, hours: Optional[Iterable[int]] = None) -> dict[str, Any]:
        if not 1 <= days <= 90:
            raise CalendarError("days must be between 1 and 90.")
        hours_list = list(hours) if hours is not None else None
        if hours_list is not None and any(hour < 0 or hour > 23 for hour in hours_list):
            raise CalendarError("hours must contain values from 0 through 23.")

        slot_strings = _generate_slot_strings(days=days, hours=hours_list)
        first = parse_slot_datetime(slot_strings[0]) if slot_strings else None
        last = parse_slot_datetime(slot_strings[-1]) if slot_strings else None
        events = None
        if first and last:
            try:
                events = self._fetch_events(
                    agent_id,
                    first.isoformat(),
                    (last + dt_mod.timedelta(minutes=15)).isoformat(),
                )
            except Exception:
                events = None

        created = 0
        blocked = 0
        provider_available = events is not None
        events = events or []
        with self._connection_factory() as conn:
            with self._cursor_factory(conn) as cursor:
                self._assert_agent(cursor, agent_id)
                for raw_slot in slot_strings:
                    starts_at = parse_slot_datetime(raw_slot)
                    is_blocked = not provider_available or any(
                        provider_event_overlaps_slot(event, starts_at) for event in events
                    )
                    reservation_status = "BLOCKED" if is_blocked else "AVAILABLE"
                    cursor.execute(
                        """
                        SELECT id FROM mock_calendar_slots
                        WHERE staff_agent_id = %s AND slot_datetime = %s
                        FOR UPDATE;
                        """,
                        (agent_id, raw_slot),
                    )
                    exists = cursor.fetchone()
                    if not exists:
                        created += 1
                    if is_blocked:
                        blocked += 1
                    cursor.execute(
                        """
                        INSERT INTO mock_calendar_slots (
                            slot_datetime, is_booked, staff_agent_id, reservation_status,
                            calendar_integration_status
                        )
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (slot_datetime, staff_agent_id) DO UPDATE
                        SET is_booked = CASE
                                WHEN mock_calendar_slots.reservation_status = 'RESERVED'
                                THEN mock_calendar_slots.is_booked
                                ELSE EXCLUDED.is_booked
                            END,
                            reservation_status = CASE
                                WHEN mock_calendar_slots.reservation_status = 'RESERVED'
                                THEN 'RESERVED'
                                ELSE EXCLUDED.reservation_status
                            END,
                            calendar_integration_status = CASE
                                WHEN mock_calendar_slots.reservation_status = 'RESERVED'
                                THEN mock_calendar_slots.calendar_integration_status
                                ELSE EXCLUDED.calendar_integration_status
                            END,
                            updated_at = CURRENT_TIMESTAMP;
                        """,
                        (
                            raw_slot,
                            is_blocked,
                            agent_id,
                            reservation_status,
                            "CREATED" if provider_available else "FAILED",
                        ),
                    )
                conn.commit()

        return {
            "agent_id": agent_id,
            "slots_created": created,
            "slots_blocked_by_calendar": blocked,
            "total_candidates": len(slot_strings),
            "free_estimate": 0 if not provider_available else len(slot_strings) - blocked,
            "provider_available": provider_available,
        }

    def sync_all(self, days: int = 30) -> dict[str, Any]:
        with self._connection_factory() as conn:
            with self._cursor_factory(conn) as cursor:
                cursor.execute(
                    """
                    SELECT DISTINCT sa.id, sa.name
                    FROM staff_agents sa
                    JOIN user_google_accounts uga ON uga.agent_id = sa.id
                    WHERE uga.provider = 'google';
                    """
                )
                agents = [dict(agent) for agent in cursor.fetchall()]

        details = {}
        for agent in agents:
            details[agent["name"]] = self.populate_agent(agent["id"], days=days)

        return {
            "agents_synced": [agent["name"] for agent in agents],
            "total_new_slots": sum(item["slots_created"] for item in details.values()),
            "details": details,
        }

