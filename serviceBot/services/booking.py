"""Transactional local-authority booking and rescheduling service.

Reservations in PostgreSQL are the source of truth. Provider calendar work is
queued in the outbox after the reservation commits, so an unavailable or slow
provider cannot create a double booking or leave a partially updated request.
"""

from __future__ import annotations

import datetime as dt_mod
import json
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Optional

from serviceBot.db.connection import dict_cursor, get_db_connection


SLOT_MINUTES = 15

try:
    from zoneinfo import ZoneInfo

    BUSINESS_TZ = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover - only for restricted Python builds
    BUSINESS_TZ = dt_mod.timezone(dt_mod.timedelta(hours=-4))


class BookingError(ValueError):
    """Base class for booking failures that are safe to surface to a caller."""


class BookingConflictError(BookingError):
    """Raised when the requested time is already reserved or blocked."""


class BookingValidationError(BookingError):
    """Raised when a booking request is incomplete or outside operating hours."""


@dataclass(frozen=True)
class BookingReceipt:
    request_id: int
    reservation_id: int
    staff_agent_id: int
    starts_at: dt_mod.datetime
    ends_at: dt_mod.datetime

    def as_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "reservation_id": self.reservation_id,
            "staff_agent_id": self.staff_agent_id,
            "booking_start_at": self.starts_at.strftime("%Y-%m-%d %H:%M:%S"),
            "booking_end_at": self.ends_at.strftime("%Y-%m-%d %H:%M:%S"),
        }


def parse_reservation_start(value: str | dt_mod.datetime) -> dt_mod.datetime:
    """Parse an exact, quarter-hour Eastern local booking start time."""
    if isinstance(value, dt_mod.datetime):
        parsed = value
    elif isinstance(value, str):
        candidate = value.strip().replace("Z", "+00:00")
        try:
            parsed = dt_mod.datetime.fromisoformat(candidate)
        except ValueError as exc:
            raise BookingValidationError(
                "booking_time must be an ISO-8601 date and time on a 15-minute boundary."
            ) from exc
    else:
        raise BookingValidationError(
            "booking_time must be an ISO-8601 date and time on a 15-minute boundary."
        )

    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(BUSINESS_TZ).replace(tzinfo=None)
    if parsed.second or parsed.microsecond or parsed.minute % SLOT_MINUTES:
        raise BookingValidationError("booking_time must begin on a 15-minute boundary.")
    return parsed


def normalize_reservation_duration(duration_minutes: int) -> int:
    """Round a positive service duration up to the local 15-minute capacity grid."""
    try:
        requested_duration = int(duration_minutes)
    except (TypeError, ValueError) as exc:
        raise BookingValidationError("duration_minutes must be positive.") from exc
    if requested_duration <= 0:
        raise BookingValidationError("duration_minutes must be positive.")
    return ((requested_duration + SLOT_MINUTES - 1) // SLOT_MINUTES) * SLOT_MINUTES


def reservation_segments(starts_at: dt_mod.datetime, duration_minutes: int) -> list[dt_mod.datetime]:
    """Return every 15-minute segment occupied by a reservation."""
    normalized_duration = normalize_reservation_duration(duration_minutes)
    return [
        starts_at + dt_mod.timedelta(minutes=offset)
        for offset in range(0, normalized_duration, SLOT_MINUTES)
    ]


def validate_bookable_window(starts_at: dt_mod.datetime, duration_minutes: int) -> list[dt_mod.datetime]:
    """Reject windows that extend outside configured business days or hours."""
    from serviceBot.services.calendar_sync import (
        get_configured_business_days,
        get_configured_business_hours,
    )

    segments = reservation_segments(starts_at, duration_minutes)
    business_days = set(get_configured_business_days())
    business_hours = set(get_configured_business_hours())
    now = dt_mod.datetime.now(BUSINESS_TZ).replace(tzinfo=None)
    if starts_at <= now:
        raise BookingValidationError(
            "Booking time must be in the future. Ask the customer to select another available slot."
        )
    if not segments or not business_hours:
        raise BookingValidationError("No operating hours are configured for bookings.")
    for segment in segments:
        if segment.weekday() not in business_days or segment.hour not in business_hours:
            raise BookingValidationError(
                "Booking time is outside company workhours (Monday to Friday, 7:00 AM to 6:00 PM)."
            )
    return segments


def _as_datetime(value: Any) -> Optional[dt_mod.datetime]:
    if isinstance(value, dt_mod.datetime):
        return value.replace(tzinfo=None)
    if isinstance(value, str):
        try:
            return dt_mod.datetime.fromisoformat(value[:19])
        except ValueError:
            return None
    return None


class BookingService:
    """Owns durable capacity reservations and their transactional side effects."""

    def __init__(
        self,
        connection_factory: Callable = get_db_connection,
        cursor_factory: Callable = dict_cursor,
    ):
        self._connection_factory = connection_factory
        self._cursor_factory = cursor_factory

    def create_portal_request(
        self,
        *,
        customer_name: str,
        phone: str,
        vehicle_details: dict[str, Any],
        request_details: dict[str, Any],
    ) -> BookingReceipt | dict[str, int]:
        """Create a portal request and any requested reservation in one transaction."""
        service_type = request_details.get("service_type") or "General Service"
        issue_description = request_details.get("issue_description") or ""
        booking_type = request_details.get("booking_type") or "appointment"
        booking_time = request_details.get("booking_time")
        duration_minutes = normalize_reservation_duration(
            request_details.get("duration_minutes")
            or (SLOT_MINUTES if booking_type == "callback" else 60)
        )
        requested_agent_id = request_details.get("staff_agent_id")

        with self._connection_factory() as conn:
            with self._cursor_factory(conn) as cursor:
                cursor.execute(
                    """
                    INSERT INTO customers (name, phone)
                    VALUES (%s, %s)
                    ON CONFLICT (phone) DO UPDATE
                    SET name = CASE
                        WHEN customers.name IN ('', 'Unknown Customer', 'Unknown')
                        THEN EXCLUDED.name
                        ELSE customers.name
                    END
                    RETURNING id, name, phone;
                    """,
                    (customer_name or "Valued Customer", phone),
                )
                customer = cursor.fetchone()
                cursor.execute(
                    """
                    INSERT INTO vehicles (customer_id, make, model, year, vin)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id;
                    """,
                    (
                        customer["id"],
                        vehicle_details.get("make") or "Vehicle",
                        vehicle_details.get("model") or "Standard",
                        int(vehicle_details.get("year") or 2020),
                        vehicle_details.get("vin"),
                    ),
                )
                vehicle_id = cursor.fetchone()["id"]
                cursor.execute(
                    """
                    INSERT INTO service_requests (
                        customer_id, vehicle_id, service_type, issue_description, status,
                        booking_type, duration_minutes, staff_agent_id
                    )
                    VALUES (%s, %s, %s, %s, 'pending', %s, %s, %s)
                    RETURNING id;
                    """,
                    (
                        customer["id"],
                        vehicle_id,
                        service_type,
                        issue_description,
                        booking_type,
                        duration_minutes,
                        requested_agent_id,
                    ),
                )
                request_id = cursor.fetchone()["id"]
                cursor.execute(
                    """
                    INSERT INTO service_request_audit_log
                    (request_id, triggered_by, from_status, to_status, notes)
                    VALUES (%s, 'portal_staff', NULL, 'pending', 'Manual request created from portal');
                    """,
                    (request_id,),
                )
                if not booking_time:
                    return {"request_id": request_id}
                return self._reserve_request(
                    cursor,
                    request_id=request_id,
                    starts_at=parse_reservation_start(booking_time),
                    duration_minutes=duration_minutes,
                    booking_type=booking_type,
                    service_type=service_type,
                    requested_agent_id=requested_agent_id,
                    allow_replace=False,
                    triggered_by="portal_staff",
                )

    def reserve_or_create(
        self,
        *,
        customer_id: int,
        service_request_id: Optional[int],
        appointment_datetime: str | dt_mod.datetime,
        service_type: str,
        vehicle_details: Optional[dict[str, Any]] = None,
        issue_description: Optional[str] = None,
        booking_type: str = "appointment",
        duration_minutes: int = 60,
        requested_agent_id: Optional[int] = None,
        is_uncataloged: bool = False,
        linked_appointment_id: Optional[int] = None,
        callback_priority: str = "medium",
        callback_number: Optional[str] = None,
    ) -> BookingReceipt:
        """Reserve capacity for an existing request or create the request atomically."""
        starts_at = parse_reservation_start(appointment_datetime)
        duration_minutes = normalize_reservation_duration(duration_minutes)
        with self._connection_factory() as conn:
            with self._cursor_factory(conn) as cursor:
                customer = self._load_customer(cursor, customer_id)
                vehicle_id = self._resolve_vehicle(cursor, customer_id, vehicle_details)
                duplicate = self._find_duplicate_request(
                    cursor,
                    customer_id=customer_id,
                    vehicle_id=vehicle_id,
                    booking_type=booking_type,
                    starts_at=starts_at,
                )
                if duplicate:
                    self._merge_service_type(cursor, duplicate["id"], duplicate.get("service_type"), service_type)
                    return BookingReceipt(
                        request_id=duplicate["id"],
                        reservation_id=duplicate["reservation_id"],
                        staff_agent_id=duplicate["staff_agent_id"],
                        starts_at=_as_datetime(duplicate["starts_at"]) or starts_at,
                        ends_at=_as_datetime(duplicate["ends_at"])
                        or starts_at + dt_mod.timedelta(minutes=duration_minutes),
                    )
                request_id = self._find_or_create_request(
                    cursor,
                    customer_id=customer_id,
                    vehicle_id=vehicle_id,
                    service_request_id=service_request_id,
                    service_type=service_type,
                    duration_minutes=duration_minutes,
                    issue_description=issue_description,
                    booking_type=booking_type,
                    is_uncataloged=is_uncataloged,
                    linked_appointment_id=linked_appointment_id,
                    callback_priority=callback_priority,
                    callback_number=callback_number,
                )
                return self._reserve_request(
                    cursor,
                    request_id=request_id,
                    starts_at=starts_at,
                    duration_minutes=duration_minutes,
                    booking_type=booking_type,
                    service_type=service_type,
                    requested_agent_id=requested_agent_id,
                    allow_replace=False,
                    triggered_by="voice_tool",
                    customer=customer,
                )

    def reserve_existing(
        self,
        *,
        request_id: int,
        appointment_datetime: str | dt_mod.datetime,
        duration_minutes: Optional[int] = None,
        booking_type: Optional[str] = None,
        requested_agent_id: Optional[int] = None,
        allow_replace: bool = False,
        customer_consent_obtained: bool = True,
        triggered_by: str = "system",
    ) -> BookingReceipt:
        """Reserve or move a persisted request without invoking provider APIs."""
        starts_at = parse_reservation_start(appointment_datetime)
        with self._connection_factory() as conn:
            with self._cursor_factory(conn) as cursor:
                cursor.execute(
                    """
                    SELECT sr.id, sr.service_type, sr.booking_type, sr.duration_minutes,
                           sr.staff_agent_id, sr.status, c.name AS customer_name, c.phone
                    FROM service_requests sr
                    JOIN customers c ON c.id = sr.customer_id
                    WHERE sr.id = %s
                    FOR UPDATE OF sr;
                    """,
                    (request_id,),
                )
                row = cursor.fetchone()
                if not row:
                    raise BookingValidationError(f"Service request {request_id} was not found.")
                if str(row.get("status") or "pending").lower() in {
                    "completed",
                    "done",
                    "cancelled",
                    "cancelled_by_customer",
                }:
                    raise BookingValidationError(
                        f"Cannot reschedule appointment #{request_id} because its status is '{row.get('status')}'."
                    )
                existing = self._active_reservation(cursor, request_id)
                if existing and not allow_replace:
                    existing_start = _as_datetime(existing["starts_at"])
                    effective_duration = normalize_reservation_duration(duration_minutes or row.get("duration_minutes") or 60)
                    existing_end = _as_datetime(existing["ends_at"])
                    if existing_start == starts_at and existing_end == starts_at + dt_mod.timedelta(minutes=effective_duration):
                        return BookingReceipt(
                            request_id=request_id,
                            reservation_id=existing["id"],
                            staff_agent_id=existing["staff_agent_id"],
                            starts_at=starts_at,
                            ends_at=starts_at + dt_mod.timedelta(minutes=effective_duration),
                        )
                    raise BookingConflictError("This service request already has an active reservation.")
                if allow_replace and not customer_consent_obtained:
                    raise BookingValidationError("Customer consent is required when rescheduling an appointment.")
                return self._reserve_request(
                    cursor,
                    request_id=request_id,
                    starts_at=starts_at,
                    duration_minutes=normalize_reservation_duration(duration_minutes or row.get("duration_minutes") or 60),
                    booking_type=booking_type or row.get("booking_type") or "appointment",
                    service_type=row.get("service_type") or "Repair",
                    requested_agent_id=requested_agent_id,
                    allow_replace=allow_replace,
                    triggered_by=triggered_by,
                    customer={"name": row.get("customer_name"), "phone": row.get("phone")},
                )

    def reschedule(
        self,
        *,
        request_id: int,
        new_datetime: str | dt_mod.datetime,
        customer_consent_obtained: bool,
        triggered_by: str,
    ) -> BookingReceipt:
        return self.reserve_existing(
            request_id=request_id,
            appointment_datetime=new_datetime,
            allow_replace=True,
            customer_consent_obtained=customer_consent_obtained,
            triggered_by=triggered_by,
        )

    def apply_portal_edit(
        self,
        *,
        request_id: int,
        issue_description: str,
        vehicle_details: dict[str, Any],
        booking_time: Optional[str],
        booking_type: Optional[str],
        duration_minutes: Optional[int],
        customer_consent_obtained: bool,
    ) -> BookingReceipt | dict[str, int]:
        """Atomically apply a portal edit and any capacity-affecting reschedule."""
        with self._connection_factory() as conn:
            with self._cursor_factory(conn) as cursor:
                cursor.execute(
                    """
                    SELECT sr.id, sr.customer_id, sr.vehicle_id, sr.issue_description, sr.status,
                           sr.service_type, sr.booking_type, sr.booking_time, sr.duration_minutes,
                           sr.staff_agent_id
                    FROM service_requests sr
                    WHERE sr.id = %s
                    FOR UPDATE;
                    """,
                    (request_id,),
                )
                request = cursor.fetchone()
                if not request:
                    raise BookingValidationError("Service request not found")

                next_type = booking_type or request.get("booking_type") or "appointment"
                next_duration = normalize_reservation_duration(
                    duration_minutes or request.get("duration_minutes") or 60
                )
                current_duration = normalize_reservation_duration(
                    request.get("duration_minutes") or 60
                )
                next_time = booking_time or request.get("booking_time")
                capacity_change = bool(
                    next_time
                    and (
                        str(next_time) != str(request.get("booking_time") or "")
                        or next_duration != current_duration
                        or next_type != (request.get("booking_type") or "appointment")
                    )
                )
                if capacity_change and not customer_consent_obtained:
                    raise BookingValidationError("Customer consent is required when rescheduling an appointment.")

                cursor.execute(
                    """
                    UPDATE service_requests
                    SET issue_description = %s, booking_type = %s, duration_minutes = %s,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s;
                    """,
                    (issue_description, next_type, next_duration, request_id),
                )
                cursor.execute(
                    """
                    UPDATE vehicles
                    SET make = %s, model = %s, year = %s, vin = %s
                    WHERE id = %s;
                    """,
                    (
                        vehicle_details.get("make"),
                        vehicle_details.get("model"),
                        vehicle_details.get("year"),
                        vehicle_details.get("vin"),
                        request.get("vehicle_id"),
                    ),
                )
                if request.get("issue_description") != issue_description:
                    cursor.execute(
                        """
                        INSERT INTO service_request_audit_log
                        (request_id, triggered_by, from_status, to_status, notes)
                        VALUES (%s, 'portal_staff', NULL, %s, 'Manual issue description update');
                        """,
                        (request_id, request.get("status") or "pending"),
                    )
                if not capacity_change:
                    return {"request_id": request_id}

                return self._reserve_request(
                    cursor,
                    request_id=request_id,
                    starts_at=parse_reservation_start(next_time),
                    duration_minutes=next_duration,
                    booking_type=next_type,
                    service_type=request.get("service_type") or "Repair",
                    requested_agent_id=None,
                    allow_replace=True,
                    triggered_by="portal_staff",
                )

    @staticmethod
    def _load_customer(cursor, customer_id: int) -> dict[str, Any]:
        cursor.execute("SELECT id, name, phone FROM customers WHERE id = %s FOR UPDATE;", (customer_id,))
        customer = cursor.fetchone()
        if not customer:
            raise BookingValidationError("Customer record not found.")
        if not customer.get("phone") or str(customer["phone"]).strip().lower() == "unknown":
            raise BookingValidationError("Customer phone number is required and must be valid.")
        if not customer.get("name") or str(customer["name"]).strip() in {"", "Unknown Customer", "Unknown"}:
            cursor.execute("UPDATE customers SET name = 'Valued Customer' WHERE id = %s;", (customer_id,))
            customer = {**customer, "name": "Valued Customer"}
        return customer

    @staticmethod
    def _resolve_vehicle(cursor, customer_id: int, vehicle_details: Optional[dict[str, Any]]) -> int:
        details = vehicle_details or {}
        make = details.get("make")
        model = details.get("model")
        year = details.get("year")
        if make and model and year and make != "Unknown":
            cursor.execute(
                """
                SELECT id FROM vehicles
                WHERE customer_id = %s AND make = %s AND model = %s AND year = %s
                FOR UPDATE;
                """,
                (customer_id, make, model, year),
            )
            existing = cursor.fetchone()
            if existing:
                return existing["id"]
            cursor.execute(
                """
                INSERT INTO vehicles (customer_id, make, model, year)
                VALUES (%s, %s, %s, %s)
                RETURNING id;
                """,
                (customer_id, make, model, int(year)),
            )
            return cursor.fetchone()["id"]
        cursor.execute(
            "SELECT id FROM vehicles WHERE customer_id = %s ORDER BY id DESC LIMIT 1 FOR UPDATE;",
            (customer_id,),
        )
        existing = cursor.fetchone()
        if existing:
            return existing["id"]
        cursor.execute(
            """
            INSERT INTO vehicles (customer_id, make, model, year)
            VALUES (%s, 'Vehicle', 'Standard', 2020)
            RETURNING id;
            """,
            (customer_id,),
        )
        return cursor.fetchone()["id"]

    @staticmethod
    def _find_or_create_request(
        cursor,
        *,
        customer_id: int,
        vehicle_id: int,
        service_request_id: Optional[int],
        service_type: str,
        duration_minutes: int,
        issue_description: Optional[str],
        booking_type: str,
        is_uncataloged: bool,
        linked_appointment_id: Optional[int],
        callback_priority: str,
        callback_number: Optional[str],
    ) -> int:
        if service_request_id:
            cursor.execute(
                """
                SELECT id, booking_type FROM service_requests
                WHERE id = %s AND customer_id = %s
                FOR UPDATE;
                """,
                (service_request_id, customer_id),
            )
            existing = cursor.fetchone()
            if existing and existing.get("booking_type") in (None, ""):
                return existing["id"]
        cursor.execute(
            """
            SELECT id FROM service_requests
            WHERE customer_id = %s AND vehicle_id = %s AND status = 'pending'
              AND booking_type IS NULL
            ORDER BY id DESC LIMIT 1
            FOR UPDATE;
            """,
            (customer_id, vehicle_id),
        )
        existing = cursor.fetchone()
        if existing:
            return existing["id"]
        cursor.execute(
            """
            INSERT INTO service_requests
            (customer_id, vehicle_id, service_type, issue_description, status, duration_minutes,
             is_uncataloged, linked_appointment_id, callback_priority, callback_number)
            VALUES (%s, %s, %s, %s, 'pending', %s, %s, %s, %s, %s)
            RETURNING id;
            """,
            (
                customer_id,
                vehicle_id,
                service_type or "Repair",
                issue_description or service_type or "Appointment booked",
                duration_minutes,
                bool(is_uncataloged),
                linked_appointment_id,
                callback_priority,
                callback_number,
            ),
        )
        return cursor.fetchone()["id"]

    @staticmethod
    def _find_duplicate_request(cursor, *, customer_id: int, vehicle_id: int, booking_type: str, starts_at: dt_mod.datetime):
        cursor.execute(
            """
            SELECT sr.id, sr.service_type, ar.id AS reservation_id, ar.staff_agent_id,
                   ar.starts_at, ar.ends_at
            FROM service_requests sr
            JOIN appointment_reservations ar
              ON ar.service_request_id = sr.id AND ar.status = 'ACTIVE'
            WHERE sr.customer_id = %s AND sr.vehicle_id = %s
              AND sr.booking_type = %s AND ar.starts_at = %s
              AND sr.status IN ('pending', 'in_progress')
            FOR UPDATE OF sr, ar;
            """,
            (customer_id, vehicle_id, booking_type, starts_at),
        )
        return cursor.fetchone()

    @staticmethod
    def _merge_service_type(cursor, request_id: int, current_service_type: Optional[str], service_type: str) -> None:
        current = current_service_type or ""
        if service_type and service_type not in current:
            cursor.execute(
                "UPDATE service_requests SET service_type = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s;",
                (f"{current}, {service_type}".strip(", "), request_id),
            )

    @staticmethod
    def _active_reservation(cursor, request_id: int):
        cursor.execute(
            """
            SELECT id, staff_agent_id, starts_at, ends_at
            FROM appointment_reservations
            WHERE service_request_id = %s AND status = 'ACTIVE'
            FOR UPDATE;
            """,
            (request_id,),
        )
        return cursor.fetchone()

    def _reserve_request(
        self,
        cursor,
        *,
        request_id: int,
        starts_at: dt_mod.datetime,
        duration_minutes: int,
        booking_type: str,
        service_type: str,
        requested_agent_id: Optional[int],
        allow_replace: bool,
        triggered_by: str,
        customer: Optional[dict[str, Any]] = None,
    ) -> BookingReceipt:
        duration_minutes = normalize_reservation_duration(duration_minutes)
        segments = validate_bookable_window(starts_at, duration_minutes)
        ends_at = starts_at + dt_mod.timedelta(minutes=duration_minutes)
        cursor.execute(
            """
            SELECT sr.id, sr.customer_id, sr.staff_agent_id, sr.status,
                   c.name AS customer_name, c.phone
            FROM service_requests sr
            JOIN customers c ON c.id = sr.customer_id
            WHERE sr.id = %s
            FOR UPDATE OF sr;
            """,
            (request_id,),
        )
        request = cursor.fetchone()
        if not request:
            raise BookingValidationError(f"Service request {request_id} was not found.")
        if not customer:
            customer = {"name": request.get("customer_name"), "phone": request.get("phone")}

        existing = self._active_reservation(cursor, request_id)
        old_segments: list[dt_mod.datetime] = []
        old_agent_id: Optional[int] = None
        old_starts_at: Optional[dt_mod.datetime] = None
        if existing:
            existing_start = _as_datetime(existing["starts_at"])
            existing_end = _as_datetime(existing["ends_at"])
            old_starts_at = existing_start
            if not allow_replace:
                if existing_start == starts_at and existing_end == ends_at:
                    return BookingReceipt(
                        request_id=request_id,
                        reservation_id=existing["id"],
                        staff_agent_id=existing["staff_agent_id"],
                        starts_at=starts_at,
                        ends_at=ends_at,
                    )
                raise BookingConflictError("This service request already has an active reservation.")
            old_agent_id = existing["staff_agent_id"]
            cursor.execute(
                "SELECT segment_start FROM appointment_reservation_segments WHERE reservation_id = %s FOR UPDATE;",
                (existing["id"],),
            )
            old_segments = [_as_datetime(row["segment_start"]) for row in cursor.fetchall()]
            old_segments = [segment for segment in old_segments if segment is not None]
            cursor.execute("DELETE FROM appointment_reservation_segments WHERE reservation_id = %s;", (existing["id"],))

        candidate_ids = self._candidate_agent_ids(
            cursor,
            requested_agent_id=requested_agent_id,
            fallback_agent_id=request.get("staff_agent_id"),
        )
        if not candidate_ids:
            raise BookingConflictError("No staff agents are available to accept this booking.")

        reservation_id: Optional[int] = None
        chosen_agent_id: Optional[int] = None
        for agent_id in candidate_ids:
            saved_reservation_id = existing["id"] if existing else None
            candidate_reservation = self._try_reserve_candidate(
                cursor,
                request_id=request_id,
                existing_reservation_id=saved_reservation_id,
                agent_id=agent_id,
                starts_at=starts_at,
                ends_at=ends_at,
                segments=segments,
            )
            if candidate_reservation is not None:
                reservation_id = candidate_reservation
                chosen_agent_id = agent_id
                break
        if reservation_id is None or chosen_agent_id is None:
            raise BookingConflictError("The requested time is no longer available for any staff agent.")

        self._release_old_slots(cursor, request_id, old_agent_id, old_segments, chosen_agent_id, segments)
        self._mark_reserved_slots(cursor, request_id, chosen_agent_id, segments)
        cursor.execute(
            """
            UPDATE service_requests
            SET booking_type = %s,
                booking_time = %s,
                booking_start_at = %s,
                booking_end_at = %s,
                duration_minutes = %s,
                staff_agent_id = %s,
                service_type = %s,
                calendar_integration_status = 'PENDING_CALENDAR',
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s;
            """,
            (
                booking_type,
                starts_at.strftime("%Y-%m-%d %H:%M:%S"),
                starts_at,
                ends_at,
                duration_minutes,
                chosen_agent_id,
                service_type,
                request_id,
            ),
        )
        if existing:
            cursor.execute(
                """
                INSERT INTO service_request_audit_log
                (request_id, triggered_by, from_status, to_status, notes)
                VALUES (%s, %s, %s, 'pending', %s);
                """,
                (
                    request_id,
                    triggered_by,
                    request.get("status") or "pending",
                    "Rescheduled slot with recorded customer consent.",
                ),
            )
        self._enqueue_projection_events(
            cursor,
            request_id=request_id,
            reservation_id=reservation_id,
            staff_agent_id=chosen_agent_id,
            old_staff_agent_id=old_agent_id,
            old_starts_at=old_starts_at,
            booking_type=booking_type,
            starts_at=starts_at,
            duration_minutes=duration_minutes,
            customer=customer,
            service_type=service_type,
        )
        return BookingReceipt(
            request_id=request_id,
            reservation_id=reservation_id,
            staff_agent_id=chosen_agent_id,
            starts_at=starts_at,
            ends_at=ends_at,
        )

    @staticmethod
    def _candidate_agent_ids(
        cursor,
        requested_agent_id: Optional[int],
        fallback_agent_id: Optional[int] = None,
    ) -> list[int]:
        """Keep an explicit staff selection strict, otherwise prefer then fall back."""
        if requested_agent_id is not None:
            cursor.execute("SELECT id FROM staff_agents WHERE id = %s;", (requested_agent_id,))
            return [row["id"] for row in cursor.fetchall()]

        cursor.execute("SELECT id FROM staff_agents ORDER BY id ASC;")
        agent_ids = [row["id"] for row in cursor.fetchall()]
        if fallback_agent_id is None or fallback_agent_id not in agent_ids:
            return agent_ids
        return [fallback_agent_id, *[
            agent_id for agent_id in agent_ids if agent_id != fallback_agent_id
        ]]

    @staticmethod
    def _try_reserve_candidate(
        cursor,
        *,
        request_id: int,
        existing_reservation_id: Optional[int],
        agent_id: int,
        starts_at: dt_mod.datetime,
        ends_at: dt_mod.datetime,
        segments: Iterable[dt_mod.datetime],
    ) -> Optional[int]:
        savepoint = f"booking_agent_{int(agent_id)}"
        segment_list = list(segments)
        cursor.execute(f"SAVEPOINT {savepoint};")
        try:
            cursor.execute(
                """
                SELECT 1
                FROM mock_calendar_slots
                WHERE staff_agent_id = %s
                  AND slot_datetime = ANY(%s)
                  AND (reservation_status IN ('RESERVED', 'BLOCKED') OR is_booked = TRUE)
                  AND service_request_id IS DISTINCT FROM %s
                FOR UPDATE;
                """,
                (agent_id, segment_list, request_id),
            )
            if cursor.fetchone():
                raise BookingConflictError("The requested time is blocked on this agent's local calendar.")
            if existing_reservation_id:
                cursor.execute(
                    """
                    UPDATE appointment_reservations
                    SET staff_agent_id = %s, starts_at = %s, ends_at = %s,
                        status = 'ACTIVE', calendar_integration_status = 'PENDING_CALENDAR',
                        calendar_event_id = NULL, updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                    RETURNING id;
                    """,
                    (agent_id, starts_at, ends_at, existing_reservation_id),
                )
                reservation_id = cursor.fetchone()["id"]
            else:
                cursor.execute(
                    """
                    INSERT INTO appointment_reservations
                    (service_request_id, staff_agent_id, starts_at, ends_at, status, calendar_integration_status)
                    VALUES (%s, %s, %s, %s, 'ACTIVE', 'PENDING_CALENDAR')
                    RETURNING id;
                    """,
                    (request_id, agent_id, starts_at, ends_at),
                )
                reservation_id = cursor.fetchone()["id"]
            for segment in segment_list:
                cursor.execute(
                    """
                    INSERT INTO appointment_reservation_segments
                    (reservation_id, staff_agent_id, segment_start)
                    VALUES (%s, %s, %s);
                    """,
                    (reservation_id, agent_id, segment),
                )
            cursor.execute(f"RELEASE SAVEPOINT {savepoint};")
            return reservation_id
        except BookingConflictError:
            cursor.execute(f"ROLLBACK TO SAVEPOINT {savepoint};")
            cursor.execute(f"RELEASE SAVEPOINT {savepoint};")
            return None
        except Exception as exc:
            cursor.execute(f"ROLLBACK TO SAVEPOINT {savepoint};")
            cursor.execute(f"RELEASE SAVEPOINT {savepoint};")
            if getattr(exc, "pgcode", None) == "23505":
                return None
            raise

    @staticmethod
    def _release_old_slots(
        cursor,
        request_id: int,
        old_agent_id: Optional[int],
        old_segments: Iterable[dt_mod.datetime],
        new_agent_id: int,
        new_segments: Iterable[dt_mod.datetime],
    ) -> None:
        if old_agent_id is None:
            return
        new_set = set(new_segments) if old_agent_id == new_agent_id else set()
        releasable = [segment for segment in old_segments if segment not in new_set]
        if not releasable:
            return
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
              AND service_request_id = %s
              AND slot_datetime = ANY(%s);
            """,
            (old_agent_id, request_id, releasable),
        )

    @staticmethod
    def _mark_reserved_slots(cursor, request_id: int, agent_id: int, segments: Iterable[dt_mod.datetime]) -> None:
        for segment in segments:
            cursor.execute(
                """
                INSERT INTO mock_calendar_slots
                (slot_datetime, is_booked, staff_agent_id, reservation_status,
                 service_request_id, calendar_integration_status)
                VALUES (%s, TRUE, %s, 'RESERVED', %s, 'PENDING_CALENDAR')
                ON CONFLICT (slot_datetime, staff_agent_id) DO UPDATE
                SET is_booked = TRUE,
                    reservation_status = 'RESERVED',
                    service_request_id = EXCLUDED.service_request_id,
                    calendar_integration_status = 'PENDING_CALENDAR',
                    calendar_event_id = NULL,
                    updated_at = CURRENT_TIMESTAMP;
                """,
                (segment, agent_id, request_id),
            )

    @staticmethod
    def _enqueue_projection_events(
        cursor,
        *,
        request_id: int,
        reservation_id: int,
        staff_agent_id: int,
        old_staff_agent_id: Optional[int],
        old_starts_at: Optional[dt_mod.datetime],
        booking_type: str,
        starts_at: dt_mod.datetime,
        duration_minutes: int,
        customer: dict[str, Any],
        service_type: str,
    ) -> None:
        cursor.execute(
            """
            SELECT sa.name, sa.phone_number, COALESCE(uga.email, sa.email) AS email
            FROM staff_agents sa
            LEFT JOIN user_google_accounts uga ON uga.agent_id = sa.id
            WHERE sa.id = %s;
            """,
            (staff_agent_id,),
        )
        assigned_agent = cursor.fetchone() or {}
        previous_agent: dict[str, Any] = {}
        if old_staff_agent_id is not None and old_staff_agent_id != staff_agent_id:
            cursor.execute(
                """
                SELECT sa.name, sa.phone_number, COALESCE(uga.email, sa.email) AS email
                FROM staff_agents sa
                LEFT JOIN user_google_accounts uga ON uga.agent_id = sa.id
                WHERE sa.id = %s;
                """,
                (old_staff_agent_id,),
            )
            previous_agent = cursor.fetchone() or {}

        notification_event = "BOOKING"
        if old_starts_at is not None:
            notification_event = (
                "RESCHEDULED_REASSIGNED"
                if previous_agent
                else "RESCHEDULED"
            )
        calendar_event_id = f"servicebot{reservation_id}{starts_at.strftime('%Y%m%d%H%M')}"
        payload = {
            "reservation_id": reservation_id,
            "agent_id": staff_agent_id,
            "old_agent_id": old_staff_agent_id,
            "old_booking_time_str": old_starts_at.strftime("%Y-%m-%d %H:%M:%S") if old_starts_at else None,
            "calendar_event_id": calendar_event_id,
            "booking_type": booking_type,
            "booking_time_str": starts_at.strftime("%Y-%m-%d %H:%M:%S"),
            "duration_minutes": duration_minutes,
            "notification_event": notification_event,
            "agent_name": assigned_agent.get("name"),
            "agent_email": assigned_agent.get("email"),
            "agent_phone": assigned_agent.get("phone_number"),
            "previous_agent_name": previous_agent.get("name"),
            "previous_agent_phone": previous_agent.get("phone_number"),
            "details": {
                "customer_name": customer.get("name") or "Customer",
                "phone": customer.get("phone"),
                "service_type": service_type,
                "issue": service_type,
                "duration_minutes": duration_minutes,
                "agent_name": assigned_agent.get("name"),
                "new_agent_name": assigned_agent.get("name"),
                "previous_agent_name": previous_agent.get("name"),
            },
        }
        for event_type in ("calendar_projection", "booking_notification"):
            cursor.execute(
                """
                INSERT INTO outbox_notifications (event_type, request_id, payload, status, next_retry_at)
                VALUES (%s, %s, %s, 'PENDING', CURRENT_TIMESTAMP);
                """,
                (event_type, request_id, json.dumps(payload)),
            )
