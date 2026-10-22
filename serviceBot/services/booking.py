"""Transactional local-authority booking and rescheduling service.

Reservations in PostgreSQL are the source of truth. Provider calendar work is
queued in the outbox after the reservation commits, so an unavailable or slow
provider cannot create a double booking or leave a partially updated request.
"""

from __future__ import annotations

import datetime as dt_mod
import json
import uuid
import itertools
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Optional

from serviceBot.db.connection import dict_cursor, get_db_connection


SLOT_MINUTES = 15
# Database adapters return base datetime objects even when the business clock
# module is replaced by a deterministic datetime subclass in tests.
_DATETIME_TYPE = dt_mod.datetime

from serviceBot.services import timezone_service


def _validated_components(request):
    """Validate a persisted snapshot without guessing names from a label."""
    components = request.get("service_components")
    if not isinstance(components, list) or not components:
        raise BookingValidationError("Appointment service components are unavailable or malformed.")
    names = []
    total = 0
    for component in components:
        if (not isinstance(component, dict) or set(component) != {"name", "duration_minutes"}
                or not isinstance(component["name"], str) or not component["name"].strip()
                or component["name"] != component["name"].strip()
                or type(component["duration_minutes"]) is not int
                or component["duration_minutes"] <= 0 or component["duration_minutes"] % SLOT_MINUTES):
            raise BookingValidationError("Appointment service components are unavailable or malformed.")
        names.append(component["name"])
        total += component["duration_minutes"]
    if (len(set(names)) != len(names) or ", ".join(names) != request.get("service_type")
            or total != request.get("duration_minutes")):
        raise BookingValidationError("Appointment service components do not match the booked appointment.")
    return components


def _appointment_blocks(items, plan):
    """Group appointments by agent while keeping callbacks independent."""
    blocks = []
    grouped = {}
    for item, agent_id in zip(items, plan, strict=True):
        if item["booking_type"] == "appointment" and agent_id in grouped:
            block = grouped[agent_id]
            block["name"] += ", " + item["name"]
            block["issue"] += "; " + item["issue"]
            block["duration"] += item["duration"]
            block["service_components"].append({"name": item["name"], "duration_minutes": item["duration"]})
        else:
            block = dict(item, agent_id=agent_id, service_components=[{
                "name": item["name"], "duration_minutes": item["duration"],
            }] if item["booking_type"] == "appointment" else None)
            blocks.append(block)
            if item["booking_type"] == "appointment":
                grouped[agent_id] = block
    return blocks


class _DynamicBusinessTZ(dt_mod.tzinfo):
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
        res = wrapped.fromutc(dt)
        return res.replace(tzinfo=self)

    @property
    def key(self):
        return timezone_service.get_business_timezone_str()

    def __repr__(self):
        return repr(self._tz)


BUSINESS_TZ = _DynamicBusinessTZ()


class BookingError(ValueError):
    """Base class for booking failures that are safe to surface to a caller."""


class BookingConflictError(BookingError):
    """Raised when the requested time is already reserved or blocked."""


class BookingValidationError(BookingError):
    """Raised when a booking request is incomplete or outside operating hours."""


class BookingHorizonError(BookingError):
    """Raised when an appointment is requested with insufficient advance lead time."""

    def __init__(
        self,
        message: str,
        min_buffer_hours: float = 4.0,
        earliest_allowed: Optional[dt_mod.datetime] = None,
        suggested_slots: Optional[list[str]] = None,
    ):
        super().__init__(message)
        self.min_buffer_hours = min_buffer_hours
        self.earliest_allowed = earliest_allowed
        self.suggested_slots = suggested_slots or []


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


def validate_appointment_lead_time(
    requested_datetime: str | dt_mod.datetime,
    current_time: Optional[dt_mod.datetime] = None,
    min_buffer_hours: Optional[float] = None,
    booking_type: str = "appointment",
) -> tuple[bool, dt_mod.datetime, list[str]]:
    """
    Validates whether an appointment or callback meets the required minimum planning lead time.
    Returns (is_valid, earliest_allowed_datetime, suggested_slots).
    """
    if current_time is None:
        current_time = timezone_service.now_in_business_tz().replace(tzinfo=None)

    is_callback = (booking_type == "callback")
    if min_buffer_hours is None:
        try:
            from serviceBot.api.portal import load_config
            cfg = load_config()
            if is_callback:
                min_buffer_hours = float(cfg.get("min_callback_buffer_hours", 2.0))
            else:
                min_buffer_hours = float(cfg.get("min_booking_buffer_hours", 4.0))
        except Exception:
            min_buffer_hours = 2.0 if is_callback else 4.0

    earliest_allowed = current_time + dt_mod.timedelta(hours=float(min_buffer_hours))

    req_dt = None
    if hasattr(requested_datetime, "strftime") and hasattr(requested_datetime, "year"):
        req_dt = requested_datetime
    elif isinstance(requested_datetime, str):
        for fmt in (
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y-%m-%dT%H:%M",
            "%Y-%m-%d",
            "%I:%M %p",
        ):
            try:
                req_dt = dt_mod.datetime.strptime(requested_datetime.strip().replace("Z", ""), fmt)
                if req_dt.year == 1900:
                    req_dt = req_dt.replace(year=current_time.year, month=current_time.month, day=current_time.day)
                break
            except ValueError:
                pass
        if req_dt is None:
            try:
                candidate = requested_datetime.strip().replace("Z", "")
                req_dt = dt_mod.datetime.fromisoformat(candidate)
            except Exception:
                pass

        if req_dt is None:
            try:
                from serviceBot.db.queries import parse_preferred_date_and_time
                _, _, start_ts = parse_preferred_date_and_time(str(requested_datetime))
                if start_ts and start_ts != "1970-01-01 00:00:00":
                    req_dt = dt_mod.datetime.strptime(start_ts, "%Y-%m-%d %H:%M:%S")
            except Exception:
                pass

    if req_dt is None:
        return True, earliest_allowed, []

    if req_dt.tzinfo is not None:
        req_dt = req_dt.astimezone(BUSINESS_TZ).replace(tzinfo=None)

    if req_dt < earliest_allowed:
        suggested_slots = []
        try:
            from serviceBot.db.queries import check_availability
            pref_date_str = earliest_allowed.strftime("%Y-%m-%d %H:%M:%S")
            suggested_slots = check_availability(preferred_date=pref_date_str, booking_type=booking_type)
        except Exception:
            # The lead-time boundary is known; provider-free capacity is not.
            suggested_slots = []
        return False, earliest_allowed, suggested_slots

    return True, earliest_allowed, []


def _as_datetime(value: Any) -> Optional[dt_mod.datetime]:
    if isinstance(value, _DATETIME_TYPE):
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

    @staticmethod
    def _intake_details(vehicle_details):
        from serviceBot.services.business_profile import validate_intake_data, normalize_legacy_intake_args, get_business_profile
        details = vehicle_details or {}
        profile = get_business_profile()
        raw = details.get("intake_data")
        args_to_normalize = dict(details)
        if isinstance(raw, dict):
            args_to_normalize["intake_data"] = raw
        normalized = normalize_legacy_intake_args(args_to_normalize, profile)
        return validate_intake_data(normalized, profile)

    @staticmethod
    def _persist_intake(cursor, request_id, intake_data):
        from serviceBot.services.business_profile import get_business_profile
        cursor.execute(
            "UPDATE service_requests SET intake_data = (intake_data - %s::text[]) || %s::jsonb WHERE id = %s;",
            ([field["key"] for field in get_business_profile()["intake_fields"]], json.dumps(intake_data), request_id),
        )

    def create_portal_request(
        self,
        *,
        customer_name: str,
        phone: str,
        vehicle_details: dict[str, Any],
        request_details: dict[str, Any],
    ) -> BookingReceipt | dict[str, int]:
        """Create a portal request and any requested reservation in one transaction."""
        intake_data = self._intake_details(vehicle_details)
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
                from serviceBot.services.business_profile import get_business_profile
                vehicle_id = None
                has_vehicle_info = bool(
                    vehicle_details
                    and (vehicle_details.get("make") or vehicle_details.get("model"))
                    and vehicle_details.get("make") not in ("Vehicle", "Unknown")
                )
                if get_business_profile()["collect_vehicle_details"] and has_vehicle_info:
                    cursor.execute(
                        """
                        INSERT INTO vehicles (customer_id, make, model, year, vin)
                        VALUES (%s, %s, %s, %s, %s)
                        RETURNING id;
                        """,
                        (
                            customer["id"],
                            vehicle_details.get("make") or "Unknown",
                            vehicle_details.get("model") or "Unknown",
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
                self._persist_intake(cursor, request_id, intake_data)
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
        intake_data = self._intake_details(vehicle_details)
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
                    self._persist_intake(cursor, duplicate["id"], intake_data)
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
                self._persist_intake(cursor, request_id, intake_data)
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
                           sr.staff_agent_id, sr.status, sr.visit_group_id, sr.booking_time,
                           c.name AS customer_name, c.phone
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

                orig_btime = row.get("booking_time")
                time_delta = None
                if orig_btime:
                    orig_start = _as_datetime(orig_btime)
                    if orig_start:
                        time_delta = starts_at - orig_start

                receipt = self._reserve_request(
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

                if allow_replace and row.get("visit_group_id") and time_delta:
                    cursor.execute(
                        """
                        SELECT sr.id, sr.service_type, sr.booking_type, sr.duration_minutes,
                               sr.staff_agent_id, sr.status, sr.booking_time,
                               c.name AS customer_name, c.phone
                        FROM service_requests sr
                        JOIN customers c ON c.id = sr.customer_id
                        WHERE sr.visit_group_id = %s AND sr.id != %s
                          AND sr.status NOT IN ('cancelled', 'cancelled_by_customer')
                        ORDER BY sr.id ASC
                        FOR UPDATE OF sr;
                        """,
                        (row.get("visit_group_id"), request_id),
                    )
                    companions = cursor.fetchall()
                    for comp in companions:
                        comp_btime = comp.get("booking_time")
                        if comp_btime:
                            comp_orig = _as_datetime(comp_btime)
                            if comp_orig:
                                comp_new_start = comp_orig + time_delta
                                self._reserve_request(
                                    cursor,
                                    request_id=comp["id"],
                                    starts_at=comp_new_start,
                                    duration_minutes=normalize_reservation_duration(comp.get("duration_minutes") or 60),
                                    booking_type=comp.get("booking_type") or "appointment",
                                    service_type=comp.get("service_type") or "Repair",
                                    requested_agent_id=comp.get("staff_agent_id"),
                                    allow_replace=True,
                                    triggered_by=triggered_by,
                                    customer={"name": comp.get("customer_name"), "phone": comp.get("phone")},
                                )

                return receipt

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

    def reserve_multi_service_appointment(
        self,
        *,
        customer_id: int,
        services: list[str],
        appointment_datetime: str | dt_mod.datetime,
        vehicle_details: Optional[dict[str, Any]] = None,
        booking_type: str = "appointment",
        issue_descriptions: Optional[list[str]] = None,
    ) -> list[dict[str, Any]]:
        """Atomically schedule multiple services, preferring single agent at preferred time or contiguous back-to-back."""
        from serviceBot.db.queries import get_service_required_fields
        from serviceBot.services.calendar_sync import get_configured_business_hours, get_configured_business_days

        if not services:
            raise ValueError("At least one service must be specified.")

        intake_data = self._intake_details(vehicle_details)
        starts_at = parse_reservation_start(appointment_datetime)
        b_hours = get_configured_business_hours()
        b_days = get_configured_business_days()
        closing_hour = max(b_hours) + 1
        opening_hour = min(b_hours)

        if starts_at.weekday() not in b_days:
            raise ValueError(f"Appointments cannot be scheduled on non-operating business days (weekday {starts_at.weekday()}).")

        service_items = []
        for i, svc_name in enumerate(services):
            fields = get_service_required_fields(svc_name)
            matched_name = fields["name"] if fields else svc_name
            is_cb = (booking_type == "callback") or ("callback" in str(svc_name).lower())
            eff_btype = "callback" if is_cb else "appointment"
            dur = 15 if is_cb else int((fields.get("duration_minutes") if fields else None) or 60)
            dur = normalize_reservation_duration(dur)
            issue = issue_descriptions[i] if (issue_descriptions and i < len(issue_descriptions)) else f"{matched_name} requested"
            service_items.append({
                "name": matched_name,
                "duration": dur,
                "booking_type": eff_btype,
                "issue": issue,
            })

        appointment_names = [item["name"] for item in service_items if item["booking_type"] == "appointment"]
        if len(set(appointment_names)) != len(appointment_names):
            raise BookingValidationError("Select each canonical appointment service only once.")

        # Dynamic business hours closing boundary check
        if booking_type == "appointment":
            total_duration = sum(item["duration"] for item in service_items)
            ends_at = starts_at + dt_mod.timedelta(minutes=total_duration)
            closing_time = starts_at.replace(hour=closing_hour, minute=0, second=0, microsecond=0)
            if ends_at > closing_time:
                raise ValueError(
                    f"Multi-service appointment of {total_duration} minutes concluding at {ends_at.strftime('%I:%M %p')} "
                    f"exceeds business hours (closing time is {closing_time.strftime('%I:%M %p')})."
                )

            is_valid, earliest_allowed, _ = validate_appointment_lead_time(starts_at, booking_type="appointment")
            if not is_valid:
                raise BookingConflictError(f"Insufficient lead time. Earliest allowed time is {earliest_allowed}.")
        elif booking_type == "callback":
            is_valid, earliest_allowed, _ = validate_appointment_lead_time(starts_at, booking_type="callback")
            if not is_valid:
                raise BookingConflictError(f"Insufficient lead time for callback. Earliest allowed time is {earliest_allowed}.")

        # Fetch qualified staff agents for each service
        with self._connection_factory() as conn:
            with self._cursor_factory(conn) as cursor:
                cursor.execute("SELECT id FROM staff_agents WHERE is_active IS NOT FALSE ORDER BY id ASC;")
                all_agent_ids = [r["id"] for r in cursor.fetchall()]
                cursor.execute("""SELECT s.name, m.staff_agent_id FROM services s
                    JOIN service_staff_agents m ON m.service_id=s.id WHERE s.name=ANY(%s)""",
                    ([item["name"] for item in service_items],))
                mappings = {}
                for row in cursor.fetchall():
                    mappings.setdefault(row["name"], []).append(row["staff_agent_id"])

        qualified_per_item = []
        for item in service_items:
            q = mappings.get(item["name"])
            valid = [aid for aid in q if aid in all_agent_ids] if q is not None else list(all_agent_ids)
            qualified_per_item.append(valid)

        # Candidate plans
        # Priority 1: Single-agent plans if an agent is qualified for ALL requested services
        common_agents = sorted(list(set.intersection(*(set(q) for q in qualified_per_item))))
        candidate_plans = []
        for aid in common_agents:
            candidate_plans.append([aid] * len(service_items))

        # Priority 2: Distinct multi-agent plans across qualified agents using greedy grouping
        all_combos = list(itertools.product(*qualified_per_item))
        def plan_greedy_score(plan):
            distinct_count = len(set(plan))
            transitions = sum(1 for i in range(len(plan) - 1) if plan[i] != plan[i + 1])
            first_agent_run = 0
            for x in plan:
                if x == plan[0]:
                    first_agent_run += 1
                else:
                    break
            # Prefer: fewer distinct agents, fewer handoffs/transitions, longer first run
            return (-distinct_count, -transitions, first_agent_run)

        all_combos.sort(key=plan_greedy_score, reverse=True)
        for combo in all_combos:
            combo_list = list(combo)
            if combo_list not in candidate_plans:
                candidate_plans.append(combo_list)

        visit_group_id = str(uuid.uuid4())
        chosen_plan = None
        plan_reservations = []

        with self._connection_factory() as conn:
            with self._cursor_factory(conn) as cursor:
                customer = self._load_customer(cursor, customer_id)
                vehicle_id = self._resolve_vehicle(cursor, customer_id, vehicle_details)

                created_requests = []
                for plan in candidate_plans:
                    sp_plan = "plan_attempt"
                    cursor.execute(f"SAVEPOINT {sp_plan};")
                    requests_in_plan = []
                    success = True

                    block_start = starts_at
                    for item in _appointment_blocks(service_items, plan):
                        agent_id = item["agent_id"]
                        t_start = block_start
                        block_start += dt_mod.timedelta(minutes=max(30, item["duration"]) if item["booking_type"] == "callback" else item["duration"])
                        t_dur = item["duration"]
                        t_end = t_start + dt_mod.timedelta(minutes=t_dur)
                        segs = reservation_segments(t_start, t_dur)

                        # Create service request inside savepoint
                        cursor.execute(
                            """
                            INSERT INTO service_requests (
                                customer_id, vehicle_id, service_type, issue_description, status,
                                time_slot, booking_type, booking_time, duration_minutes,
                                staff_agent_id, visit_group_id, service_components, booking_start_at, booking_end_at
                            ) VALUES (%s, %s, %s, %s, 'pending', %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            RETURNING id;
                            """,
                            (
                                customer_id,
                                vehicle_id,
                                item["name"],
                                item["issue"],
                                t_start.strftime("%Y-%m-%d %H:%M:%S"),
                                item["booking_type"],
                                t_start.strftime("%Y-%m-%d %H:%M:%S"),
                                t_dur,
                                agent_id,
                                visit_group_id,
                                json.dumps(item["service_components"]) if item["service_components"] is not None else None,
                                t_start,
                                t_end,
                            ),
                        )
                        sr_id = cursor.fetchone()["id"]
                        self._persist_intake(cursor, sr_id, intake_data)

                        res_id = self._try_reserve_candidate(
                            cursor,
                            request_id=sr_id,
                            existing_reservation_id=None,
                            agent_id=agent_id,
                            starts_at=t_start,
                            ends_at=t_end,
                            segments=segs,
                        )
                        if res_id is None:
                            success = False
                            break

                        self._mark_reserved_slots(cursor, sr_id, agent_id, segs)

                        requests_in_plan.append({
                            "service_request_id": sr_id,
                            "reservation_id": res_id,
                            "staff_agent_id": agent_id,
                            "booking_time": t_start.strftime("%Y-%m-%d %H:%M:%S"),
                            "duration_minutes": t_dur,
                            "visit_group_id": visit_group_id,
                            "service_type": item["name"],
                            "booking_type": item["booking_type"],
                            "service_components": item["service_components"],
                        })

                    if success:
                        created_requests = requests_in_plan
                        cursor.execute(f"RELEASE SAVEPOINT {sp_plan};")
                        break
                    else:
                        cursor.execute(f"ROLLBACK TO SAVEPOINT {sp_plan};")
                        cursor.execute(f"RELEASE SAVEPOINT {sp_plan};")

                if not created_requests:
                    raise BookingConflictError("The requested time is no longer available for the requested services.")

                # Cross-link linked_appointment_id
                if len(created_requests) == 2:
                    sr0 = created_requests[0]["service_request_id"]
                    sr1 = created_requests[1]["service_request_id"]
                    cursor.execute("UPDATE service_requests SET linked_appointment_id = %s WHERE id = %s;", (sr1, sr0))
                    cursor.execute("UPDATE service_requests SET linked_appointment_id = %s WHERE id = %s;", (sr0, sr1))
                    created_requests[0]["linked_appointment_id"] = sr1
                    created_requests[1]["linked_appointment_id"] = sr0
                elif len(created_requests) > 2:
                    for i in range(len(created_requests)):
                        companion_id = created_requests[(i + 1) % len(created_requests)]["service_request_id"]
                        cursor.execute("UPDATE service_requests SET linked_appointment_id = %s WHERE id = %s;", (companion_id, created_requests[i]["service_request_id"]))
                        created_requests[i]["linked_appointment_id"] = companion_id

                cursor.execute("SELECT name, phone FROM customers WHERE id = %s;", (customer_id,))
                cust_row = cursor.fetchone() or {"name": "Valued Customer", "phone": None}
                from serviceBot.services.business_profile import format_service_details
                v_str = format_service_details({**(vehicle_details or {}), "intake_data": intake_data})

                for req in created_requests:
                    self._enqueue_projection_events(
                        cursor,
                        request_id=req["service_request_id"],
                        reservation_id=req["reservation_id"],
                        staff_agent_id=req["staff_agent_id"],
                        old_staff_agent_id=None,
                        old_starts_at=None,
                        booking_type=req["booking_type"],
                        starts_at=parse_reservation_start(req["booking_time"]),
                        duration_minutes=req["duration_minutes"],
                        customer=cust_row,
                        service_type=req["service_type"],
                        vehicle_str=v_str,
                        issue_description=req["service_type"],
                        triggered_by="customer",
                    )

                conn.commit()
                return created_requests

    def cancel_multi_service_visit(
        self,
        visit_group_id: str,
        customer_consent_obtained: bool = True,
        triggered_by: str = "customer_request",
        reason: Optional[str] = "Cancelled multi-service visit",
    ) -> dict[str, Any]:
        """
        Atomically cancels all linked service requests associated with a visit_group_id.
        Releases reserved calendar slots for each segment and marks status as cancelled.
        """
        if not visit_group_id:
            raise ValueError("visit_group_id is required")

        with self._connection_factory() as conn:
            with self._cursor_factory(conn) as cursor:
                cursor.execute(
                    """
                    SELECT id, status, staff_agent_id, booking_time, duration_minutes
                    FROM service_requests
                    WHERE visit_group_id = %s;
                    """,
                    (visit_group_id,)
                )
                rows = cursor.fetchall()
                if not rows:
                    return {
                        "success": False,
                        "visit_group_id": visit_group_id,
                        "cancelled_ids": [],
                        "cancelled_count": 0,
                        "message": f"No service requests found for visit_group_id {visit_group_id}",
                    }

                cancelled_ids = []
                for row in rows:
                    req_id = row["id"]
                    aid = row.get("staff_agent_id")
                    btime = row.get("booking_time")

                    cursor.execute(
                        """
                        UPDATE service_requests
                        SET status = 'cancelled', updated_at = NOW()
                        WHERE id = %s;
                        """,
                        (req_id,)
                    )

                    if aid and btime:
                        b_dt = btime if isinstance(btime, dt_mod.datetime) else dt_mod.datetime.strptime(str(btime)[:19], "%Y-%m-%d %H:%M:%S")
                        cursor.execute(
                            """
                            UPDATE mock_calendar_slots
                            SET is_booked = FALSE, reservation_status = 'AVAILABLE'
                            WHERE staff_agent_id = %s AND slot_datetime = %s;
                            """,
                            (aid, b_dt)
                        )

                    cursor.execute(
                        """
                        DELETE FROM appointment_reservation_segments
                        WHERE reservation_id IN (
                            SELECT id FROM appointment_reservations WHERE service_request_id = %s
                        );
                        UPDATE appointment_reservations
                        SET status = 'CANCELLED', updated_at = NOW()
                        WHERE service_request_id = %s AND status = 'ACTIVE';
                        """,
                        (req_id, req_id)
                    )

                    cancelled_ids.append(req_id)

                conn.commit()

        return {
            "success": True,
            "visit_group_id": visit_group_id,
            "cancelled_ids": cancelled_ids,
            "cancelled_count": len(cancelled_ids),
            "message": f"Successfully cancelled all {len(cancelled_ids)} segments for visit {visit_group_id}.",
        }

    def revise_multi_service_visit(
        self,
        request_id_to_cancel: int,
        reason: Optional[str] = "Customer dropped single service from multi-service visit",
    ) -> dict[str, Any]:
        """
        Revises a multi-service visit by cancelling one specific service request
        while preserving all companion requests at their original start times.
        """
        with self._connection_factory() as conn:
            with self._cursor_factory(conn) as cursor:
                cursor.execute(
                    """
                    SELECT id, visit_group_id, staff_agent_id, booking_time, duration_minutes, status, service_type
                    FROM service_requests
                    WHERE id = %s
                    FOR UPDATE OF service_requests;
                    """,
                    (request_id_to_cancel,)
                )
                target = cursor.fetchone()
                if not target:
                    raise ValueError(f"Service request {request_id_to_cancel} was not found.")

                v_group = target.get("visit_group_id")
                aid = target.get("staff_agent_id")
                btime = target.get("booking_time")

                cursor.execute(
                    """
                    UPDATE service_requests
                    SET status = 'cancelled', updated_at = NOW()
                    WHERE id = %s;
                    """,
                    (request_id_to_cancel,)
                )

                if aid and btime:
                    b_dt = btime if isinstance(btime, dt_mod.datetime) else dt_mod.datetime.strptime(str(btime)[:19], "%Y-%m-%d %H:%M:%S")
                    cursor.execute(
                        """
                        UPDATE mock_calendar_slots
                        SET is_booked = FALSE, reservation_status = 'AVAILABLE'
                        WHERE staff_agent_id = %s AND slot_datetime = %s;
                        """,
                        (aid, b_dt)
                    )

                cursor.execute(
                    """
                    DELETE FROM appointment_reservation_segments
                    WHERE reservation_id IN (
                        SELECT id FROM appointment_reservations WHERE service_request_id = %s
                    );
                    UPDATE appointment_reservations
                    SET status = 'CANCELLED', updated_at = NOW()
                    WHERE service_request_id = %s AND status = 'ACTIVE';
                    """,
                    (request_id_to_cancel, request_id_to_cancel)
                )

                preserved_ids = []
                if v_group:
                    cursor.execute(
                        """
                        SELECT id, service_type, booking_time, duration_minutes, staff_agent_id
                        FROM service_requests
                        WHERE visit_group_id = %s AND id != %s AND status NOT IN ('cancelled', 'cancelled_by_customer');
                        """,
                        (v_group, request_id_to_cancel)
                    )
                    preserved = cursor.fetchall()
                    preserved_ids = [p["id"] for p in preserved]

                conn.commit()

        return {
            "success": True,
            "cancelled_id": request_id_to_cancel,
            "preserved_ids": preserved_ids,
            "visit_group_id": v_group,
            "message": f"Successfully cancelled service #{request_id_to_cancel}; preserved {len(preserved_ids)} companion service(s).",
        }

    def reassign_declined_technician_segment(
        self,
        request_id: int,
        reason: str = "Agent declined appointment via SMS",
    ) -> dict[str, Any]:
        """
        Attempts to automatically reassign a declined appointment segment to another qualified agent
        free at that exact time slot. If no other qualified agent is free, escalates to supervisor.
        """
        from serviceBot.db.queries import get_qualified_agent_ids

        with self._connection_factory() as conn:
            with self._cursor_factory(conn) as cursor:
                cursor.execute(
                    """
                    SELECT sr.id, sr.service_type, sr.booking_time, sr.duration_minutes, sr.staff_agent_id,
                           sr.visit_group_id, sr.customer_id
                    FROM service_requests sr
                    WHERE sr.id = %s
                    FOR UPDATE OF sr;
                    """,
                    (request_id,)
                )
                sr = cursor.fetchone()
                if not sr:
                    raise ValueError(f"Service request {request_id} was not found.")

                curr_agent_id = sr.get("staff_agent_id")
                svc_type = sr.get("service_type")
                btime = sr.get("booking_time")
                dur = sr.get("duration_minutes") or 60

                if not btime:
                    return {"success": False, "reassigned": False, "message": "No booking time found"}

                b_dt = btime if isinstance(btime, dt_mod.datetime) else dt_mod.datetime.strptime(str(btime)[:19], "%Y-%m-%d %H:%M:%S")

                qualified_ids = get_qualified_agent_ids(svc_type)
                if qualified_ids:
                    cursor.execute(
                        "SELECT id FROM staff_agents WHERE is_active IS NOT FALSE AND id = ANY(%s) AND id != %s ORDER BY id ASC;",
                        (qualified_ids, curr_agent_id or -1)
                    )
                    candidate_ids = [r["id"] for r in cursor.fetchall()]
                else:
                    cursor.execute(
                        "SELECT id FROM staff_agents WHERE is_active IS NOT FALSE AND id != %s ORDER BY id ASC;",
                        (curr_agent_id or -1,)
                    )
                    candidate_ids = [r["id"] for r in cursor.fetchall()]

                new_agent_id = None
                segments = [b_dt + dt_mod.timedelta(minutes=30 * i) for i in range(max(1, (dur + 29) // 30))]
                for cand_id in candidate_ids:
                    cursor.execute(
                        """
                        SELECT slot_datetime, is_booked, reservation_status
                        FROM mock_calendar_slots
                        WHERE staff_agent_id = %s AND slot_datetime = ANY(%s)
                        FOR UPDATE;
                        """,
                        (cand_id, segments)
                    )
                    slot_rows = cursor.fetchall()
                    has_conflict = False
                    for s_row in slot_rows:
                        if s_row.get("is_booked") is True or s_row.get("reservation_status") in ("RESERVED", "BLOCKED", "BOOKED"):
                            has_conflict = True
                            break
                    if not has_conflict:
                        new_agent_id = cand_id
                        break

                if new_agent_id:
                    if curr_agent_id:
                        cursor.execute(
                            """
                            UPDATE mock_calendar_slots
                            SET is_booked = FALSE, reservation_status = 'AVAILABLE', service_request_id = NULL
                            WHERE staff_agent_id = %s AND (service_request_id = %s OR slot_datetime = ANY(%s));
                            """,
                            (curr_agent_id, request_id, segments)
                        )

                    for seg in segments:
                        cursor.execute(
                            """
                            INSERT INTO mock_calendar_slots (staff_agent_id, slot_datetime, is_booked, reservation_status, service_request_id)
                            VALUES (%s, %s, TRUE, 'RESERVED', %s)
                            ON CONFLICT (slot_datetime, staff_agent_id) DO UPDATE
                            SET is_booked = TRUE, reservation_status = 'RESERVED', service_request_id = EXCLUDED.service_request_id;
                            """,
                            (new_agent_id, seg, request_id)
                        )

                    cursor.execute(
                        """
                        UPDATE appointment_reservations
                        SET staff_agent_id = %s, updated_at = NOW()
                        WHERE service_request_id = %s;
                        """,
                        (new_agent_id, request_id)
                    )

                    cursor.execute(
                        """
                        UPDATE appointment_reservation_segments
                        SET staff_agent_id = %s
                        WHERE reservation_id IN (
                            SELECT id FROM appointment_reservations WHERE service_request_id = %s
                        );
                        """,
                        (new_agent_id, request_id)
                    )

                    cursor.execute(
                        """
                        UPDATE service_requests
                        SET staff_agent_id = %s, escalation_status = 'reassigned',
                            confirmation_status = 'pending_agent_confirmation', updated_at = NOW()
                        WHERE id = %s;
                        """,
                        (new_agent_id, request_id)
                    )

                    conn.commit()
                    return {
                        "success": True,
                        "reassigned": True,
                        "new_agent_id": new_agent_id,
                        "previous_agent_id": curr_agent_id,
                        "message": f"Successfully auto-reassigned segment #{request_id} to staff agent {new_agent_id}."
                    }
                else:
                    cursor.execute(
                        """
                        UPDATE service_requests
                        SET escalation_status = 'escalated',
                            escalation_reason = 'AGENT_DECLINED',
                            updated_at = NOW()
                        WHERE id = %s;
                        """,
                        (request_id,)
                    )
                    conn.commit()
                    return {
                        "success": True,
                        "reassigned": False,
                        "escalated": True,
                        "message": f"No alternative agent available for #{request_id} at {b_dt}. Escalated to supervisor."
                    }

    def remove_appointment_service(
        self, *, request_id: int, service_name: str, customer_consent_obtained: bool,
        triggered_by: str, reason: str | None = None,
    ) -> dict[str, Any]:
        """Shrink only the selected agent block, under its existing row lock."""
        if customer_consent_obtained is not True:
            raise BookingValidationError("Customer consent is required to remove a service.")
        if (type(request_id) is not int or request_id <= 0 or not isinstance(service_name, str)
                or not service_name.strip() or service_name != service_name.strip()):
            raise BookingValidationError("Select an exact appointment and canonical service name.")
        with self._connection_factory() as conn, self._cursor_factory(conn) as cursor:
            cursor.execute("""SELECT sr.*, c.name AS customer_name, c.phone, v.year, v.make, v.model
                FROM service_requests sr JOIN customers c ON c.id=sr.customer_id
                LEFT JOIN vehicles v ON v.id=sr.vehicle_id WHERE sr.id=%s FOR UPDATE OF sr""", (request_id,))
            request = cursor.fetchone()
            if (not request or request.get("booking_type") != "appointment"
                    or request.get("status") not in ("pending", "confirmed", "in_progress")):
                raise BookingValidationError("Select an active appointment; callbacks cannot remove services.")
            if request.get("service_components") is None:
                # Never split a historical label heuristically. A canonical exact
                # catalog row can prove that this legacy row held one service.
                cursor.execute("SELECT name FROM services WHERE name=%s", (request.get("service_type"),))
                canonical = cursor.fetchall()
                if len(canonical) != 1 or canonical[0]["name"] != service_name:
                    raise BookingValidationError("Legacy composite appointment has no safe component snapshot.")
                snapshot = [{"name": canonical[0]["name"], "duration_minutes": request.get("duration_minutes")}]
                components = _validated_components(dict(request, service_components=snapshot))
            else:
                components = _validated_components(request)
            matches = [component for component in components if component["name"] == service_name]
            if len(matches) != 1:
                raise BookingValidationError("Select one exact booked canonical service name.")
            remaining = [component for component in components if component["name"] != service_name]
            existing = self._active_reservation(cursor, request_id)
            start = _as_datetime(request.get("booking_time"))
            if (not existing or not start or _as_datetime(existing["starts_at"]) != start
                    or existing["staff_agent_id"] != request.get("staff_agent_id")
                    or _as_datetime(existing["ends_at"]) != start + dt_mod.timedelta(minutes=request["duration_minutes"])):
                raise BookingValidationError("Appointment reservation does not match its service snapshot.")
            cursor.execute("SELECT staff_agent_id,segment_start FROM appointment_reservation_segments WHERE reservation_id=%s FOR UPDATE", (existing["id"],))
            segment_rows = cursor.fetchall()
            actual_segments = {_as_datetime(row["segment_start"]) for row in segment_rows}
            if (actual_segments != set(reservation_segments(start, request["duration_minutes"]))
                    or any(row["staff_agent_id"] != existing["staff_agent_id"] for row in segment_rows)):
                raise BookingValidationError("Appointment reservation segments do not match its service snapshot.")
            if not remaining:
                self._cancel_locked(cursor, request_id=request_id, triggered_by=triggered_by,
                                    reason=reason or f"Removed final service: {service_name}", selected_only=True)
                duration, end, label, status = 0, None, "", "cancelled"
            else:
                duration = sum(component["duration_minutes"] for component in remaining)
                end = start + dt_mod.timedelta(minutes=duration)
                label = ", ".join(component["name"] for component in remaining)
                cursor.execute("DELETE FROM appointment_reservation_segments WHERE reservation_id=%s AND segment_start >= %s", (existing["id"], end))
                cursor.execute("""UPDATE mock_calendar_slots SET is_booked=FALSE, reservation_status='AVAILABLE',
                    service_request_id=NULL, calendar_event_id=NULL, calendar_integration_status='PENDING_CALENDAR',
                    updated_at=CURRENT_TIMESTAMP WHERE service_request_id=%s AND staff_agent_id=%s
                    AND slot_datetime >= %s AND slot_datetime < %s""",
                    (request_id, existing["staff_agent_id"], end, existing["ends_at"]))
                cursor.execute("""UPDATE appointment_reservations SET ends_at=%s,
                    calendar_integration_status='PENDING_CALENDAR',updated_at=CURRENT_TIMESTAMP WHERE id=%s""", (end, existing["id"]))
                cursor.execute("""UPDATE service_requests SET service_type=%s,issue_description=%s,
                    service_components=%s,duration_minutes=%s,booking_end_at=%s,
                    calendar_integration_status='PENDING_CALENDAR',updated_at=CURRENT_TIMESTAMP WHERE id=%s""",
                    (label, label, json.dumps(remaining), duration, end, request_id))
                cursor.execute("""INSERT INTO service_request_audit_log
                    (request_id,triggered_by,from_status,to_status,notes) VALUES (%s,%s,%s,%s,%s)""",
                    (request_id, triggered_by, request["status"], request["status"],
                     f"Removed service {service_name}; unchanged appointment start; {reason or 'customer consent'}"))
                vehicle = " ".join(str(request[key]) for key in ("year", "make", "model") if request.get(key))
                self._enqueue_projection_events(cursor, request_id=request_id, reservation_id=existing["id"],
                    staff_agent_id=existing["staff_agent_id"], old_staff_agent_id=existing["staff_agent_id"],
                    old_starts_at=start, booking_type="appointment", starts_at=start, duration_minutes=duration,
                    customer={"name": request["customer_name"], "phone": request["phone"]},
                    service_type=label, vehicle_str=vehicle, issue_description=label, triggered_by=triggered_by,
                    old_calendar_event_id=existing.get("calendar_event_id"))
                status = request["status"]
            return {"success": True, "request_id": request_id, "appointment_id": request_id,
                    "status": status, "cancelled": not remaining, "removed_service": service_name,
                    "service_components": remaining, "service_type": label, "duration_minutes": duration,
                    "booking_time": start.strftime("%Y-%m-%d %H:%M:%S"),
                    "booking_end_at": end.strftime("%Y-%m-%d %H:%M:%S") if end else None,
                    "calendar_sync_status": "PENDING_CALENDAR", "notification_status": "queued"}

    def cancel(
        self,
        *,
        request_id: int,
        customer_consent_obtained: bool,
        triggered_by: str,
        reason: Optional[str] = None,
    ) -> dict[str, Any]:
        """Atomically cancel a service request and its capacity reservation."""
        if not customer_consent_obtained:
            raise BookingValidationError("Customer consent is required to cancel an appointment.")

        with self._connection_factory() as conn:
            with self._cursor_factory(conn) as cursor:
                return self._cancel_locked(cursor, request_id=request_id, triggered_by=triggered_by, reason=reason)

    def _cancel_locked(self, cursor, *, request_id, triggered_by, reason, selected_only=False):
        """Shared cancellation owner; caller owns the transaction and consent."""
        cursor.execute(
            """
            SELECT sr.id, sr.customer_id, sr.staff_agent_id, sr.status,
                   sr.booking_type, sr.booking_time, sr.service_type, sr.duration_minutes,
                   sr.visit_group_id,
                   c.name AS customer_name, c.phone,
                   v.year, v.make, v.model
            FROM service_requests sr
            JOIN customers c ON c.id = sr.customer_id
            LEFT JOIN vehicles v ON v.id = sr.vehicle_id
            WHERE sr.id = %s
            FOR UPDATE OF sr;
            """,
            (request_id,),
        )
        request = cursor.fetchone()
        if not request:
            raise BookingValidationError(f"Service request {request_id} was not found.")

        if request.get("status") in ("cancelled", "cancelled_by_customer", "cancelled_by_admin"):
            return {
                "request_id": request_id,
                "status": request.get("status"),
                "already_cancelled": True,
            }

        visit_group_id = request.get("visit_group_id")
        if visit_group_id and not selected_only:
            cursor.execute(
                """
                SELECT sr.id, sr.customer_id, sr.staff_agent_id, sr.status,
                       sr.booking_type, sr.booking_time, sr.service_type, sr.duration_minutes,
                       sr.visit_group_id,
                       c.name AS customer_name, c.phone,
                       v.year, v.make, v.model
                FROM service_requests sr
                JOIN customers c ON c.id = sr.customer_id
                LEFT JOIN vehicles v ON v.id = sr.vehicle_id
                WHERE sr.visit_group_id = %s
                FOR UPDATE OF sr;
                """,
                (visit_group_id,),
            )
            targets = cursor.fetchall()
        else:
            targets = [request]

        for target_req in targets:
            tid = target_req["id"]
            if target_req.get("status") in ("cancelled", "cancelled_by_customer", "cancelled_by_admin"):
                continue

            existing = self._active_reservation(cursor, tid)
            old_segments: list[dt_mod.datetime] = []
            old_agent_id: Optional[int] = target_req.get("staff_agent_id")
            old_starts_at: Optional[dt_mod.datetime] = None
            reservation_id: Optional[int] = None

            if existing:
                reservation_id = existing["id"]
                old_agent_id = existing["staff_agent_id"]
                old_starts_at = _as_datetime(existing["starts_at"])
                cursor.execute(
                    "SELECT segment_start FROM appointment_reservation_segments WHERE reservation_id = %s FOR UPDATE;",
                    (existing["id"],),
                )
                old_segments = [_as_datetime(row["segment_start"]) for row in cursor.fetchall()]
                old_segments = [seg for seg in old_segments if seg is not None]

                cursor.execute("DELETE FROM appointment_reservation_segments WHERE reservation_id = %s;", (existing["id"],))
                cursor.execute(
                    "UPDATE appointment_reservations SET status = 'CANCELLED', updated_at = CURRENT_TIMESTAMP WHERE id = %s;",
                    (existing["id"],),
                )

            # Release mock_calendar_slots
            if old_agent_id is not None and old_segments:
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
                      AND (service_request_id = %s OR slot_datetime = ANY(%s));
                    """,
                    (old_agent_id, tid, old_segments),
                )
            else:
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
                    (tid,),
                )

            # Update service_request status
            cursor.execute(
                """
                UPDATE service_requests
                SET status = 'cancelled',
                    confirmation_status = 'cancelled',
                    escalation_status = 'none',
                    escalation_reason = NULL,
                    calendar_integration_status = 'PENDING_CALENDAR',
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s;
                """,
                (tid,),
            )

            # Reminder invalidation must commit with the cancellation.
            cursor.execute(
                "UPDATE sms_reminders SET status = 'CANCELLED' WHERE appointment_id = %s AND status = 'PENDING';",
                (tid,),
            )

            # Audit log
            cursor.execute(
                """
                INSERT INTO service_request_audit_log
                (request_id, triggered_by, from_status, to_status, notes)
                VALUES (%s, %s, %s, 'cancelled', %s);
                """,
                (
                    tid,
                    triggered_by,
                    target_req.get("status") or "pending",
                    f"Appointment cancelled: {reason or 'No reason provided'}",
                ),
            )

            # Outbox notification
            v_parts = [target_req.get("year"), target_req.get("make"), target_req.get("model")]
            veh_str = " ".join([str(p).strip() for p in v_parts if p and str(p).strip().upper() not in ("NONE", "NULL", "N/A")]).strip() or "N/A"
            c_name = target_req.get("customer_name") or "Valued Customer"
            c_phone = target_req.get("phone")
            s_type = target_req.get("service_type") or "Repair"
            cancel_payload = {
                "action": "delete",
                "reservation_id": reservation_id,
                "agent_id": old_agent_id,
                "calendar_event_id": (
                    existing.get("calendar_event_id") if existing else None
                ) or (
                    f"servicebot{reservation_id}{old_starts_at:%Y%m%d%H%M}"
                    if reservation_id and old_starts_at else None
                ),
                "duration_minutes": target_req.get("duration_minutes") or 60,
                "booking_type": target_req.get("booking_type") or "appointment",
                "booking_time_str": str(target_req.get("booking_time"))[:19] if target_req.get("booking_time") else None,
                "notification_event": "CANCELLED_BY_CUSTOMER",
                "triggered_by": triggered_by,
                "bypass_quiet_hours": True,
                "vehicle": veh_str,
                "issue": s_type,
                "details": {
                    "customer_name": c_name,
                    "phone": c_phone,
                    "service_type": s_type,
                    "vehicle": veh_str,
                    "issue": s_type,
                    "duration_minutes": target_req.get("duration_minutes") or 60,
                    "triggered_by": triggered_by,
                    "bypass_quiet_hours": True,
                },
            }
            for event_type in ("calendar_projection", "booking_notification"):
                cursor.execute(
                    """
                    INSERT INTO outbox_notifications (event_type, request_id, payload, status, next_retry_at)
                    VALUES (%s, %s, %s, 'PENDING', CURRENT_TIMESTAMP);
                    """,
                    (event_type, tid, json.dumps(cancel_payload)),
                )

        return {
            "request_id": request_id,
            "status": "cancelled",
            "cancelled": True,
            "already_cancelled": False,
        }

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
        intake_data = self._intake_details(vehicle_details) if "intake_data" in vehicle_details else None
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
                if intake_data is not None:
                    self._persist_intake(cursor, request_id, intake_data)
                if vehicle_details.get("make") and request.get("vehicle_id"):
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
        from serviceBot.services.business_profile import get_business_profile
        if not get_business_profile()["collect_vehicle_details"]:
            return None
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
        return None

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
            WHERE customer_id = %s AND vehicle_id IS NOT DISTINCT FROM %s AND status = 'pending'
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
            WHERE sr.customer_id = %s AND sr.vehicle_id IS NOT DISTINCT FROM %s
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
            SELECT id, staff_agent_id, starts_at, ends_at, calendar_event_id
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
                   sr.service_type, sr.issue_description, sr.service_components, sr.duration_minutes,
                   sr.escalation_status, sr.intake_data,
                   c.name AS customer_name, c.phone,
                   v.year, v.make, v.model
            FROM service_requests sr
            JOIN customers c ON c.id = sr.customer_id
            LEFT JOIN vehicles v ON v.id = sr.vehicle_id
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

        from serviceBot.services.business_profile import format_service_details
        vehicle_str = format_service_details(request)
        issue_str = request.get("issue_description") or service_type

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

        if request.get("service_components") is not None:
            if duration_minutes != request["duration_minutes"] or service_type != request["service_type"]:
                raise BookingValidationError("Use selected-service removal to change a grouped appointment duration.")
        qualified_agent_ids = self._qualified_agent_ids(cursor, request)

        candidate_ids = self._candidate_agent_ids(
            cursor,
            requested_agent_id=requested_agent_id,
            fallback_agent_id=request.get("staff_agent_id"),
            qualified_agent_ids=qualified_agent_ids,
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
        staff_reassignment = (
            triggered_by == "portal_staff_reassignment"
            and request.get("staff_agent_id") != chosen_agent_id
        )
        escalation_status = "none"
        reassignment_cutoff = None
        if staff_reassignment:
            from serviceBot.api.portal import load_config

            window = int(load_config().get("reassignment_confirmation_window_minutes", 15))
            reassignment_cutoff = timezone_service.now_in_business_tz().replace(tzinfo=None) + dt_mod.timedelta(minutes=window)
            escalation_status = "reassigned"
            cursor.execute(
                "UPDATE sms_reminders SET status = 'CANCELLED' "
                "WHERE appointment_id = %s AND recipient_type = 'agent' AND status = 'PENDING';",
                (request_id,),
            )
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
                status = 'pending',
                calendar_integration_status = 'PENDING_CALENDAR',
                confirmation_status = 'pending_agent_confirmation',
                escalation_status = %s,
                escalation_reason = NULL,
                confirmation_cutoff_at = CASE WHEN %s THEN %s ELSE confirmation_cutoff_at END,
                confirmed_at = NULL,
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
                escalation_status,
                staff_reassignment,
                reassignment_cutoff,
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
            vehicle_str=vehicle_str,
            issue_description=issue_str,
            triggered_by=triggered_by,
            old_calendar_event_id=existing.get("calendar_event_id") if existing else None,
        )
        return BookingReceipt(
            request_id=request_id,
            reservation_id=reservation_id,
            staff_agent_id=chosen_agent_id,
            starts_at=starts_at,
            ends_at=ends_at,
        )

    @staticmethod
    def _qualified_agent_ids(cursor, request) -> Optional[list[int]]:
        """Share service eligibility between candidate listing and reservation writes."""
        if request.get("service_components") is not None:
            components = _validated_components(request)
            cursor.execute("SELECT id FROM staff_agents WHERE is_active IS NOT FALSE ORDER BY id")
            eligible = {row["id"] for row in cursor.fetchall()}
            for component in components:
                cursor.execute(
                    "SELECT m.staff_agent_id FROM service_staff_agents m JOIN services s ON s.id=m.service_id WHERE s.name=%s",
                    (component["name"],),
                )
                mapped = {row["staff_agent_id"] for row in cursor.fetchall()}
                if mapped:
                    eligible &= mapped
            return sorted(eligible)
        if request.get("service_type"):
            from serviceBot.db.queries import get_qualified_agent_ids

            return get_qualified_agent_ids(request["service_type"]) or None
        return None

    @staticmethod
    def _candidate_agent_ids(
        cursor,
        requested_agent_id: Optional[int],
        fallback_agent_id: Optional[int] = None,
        qualified_agent_ids: Optional[list[int]] = None,
    ) -> list[int]:
        """Keep an explicit staff selection strict, otherwise prefer then fall back."""
        if requested_agent_id is not None:
            cursor.execute("SELECT id FROM staff_agents WHERE id = %s AND is_active IS NOT FALSE;", (requested_agent_id,))
            return [row["id"] for row in cursor.fetchall()
                    if qualified_agent_ids is None or row["id"] in qualified_agent_ids]

        cursor.execute("SELECT id FROM staff_agents WHERE is_active IS NOT FALSE ORDER BY id ASC;")
        agent_ids = [row["id"] for row in cursor.fetchall()]

        if qualified_agent_ids is not None:
            agent_ids = [aid for aid in agent_ids if aid in qualified_agent_ids]

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

            # Check Google Calendar for busy intervals that overlap [starts_at, ends_at]
            try:
                from serviceBot.services.google_calendar import fetch_agent_events
                from serviceBot.services.calendar_availability import _provider_datetime
                start_iso = (starts_at.replace(tzinfo=BUSINESS_TZ) - dt_mod.timedelta(minutes=5)).isoformat()
                end_iso = (ends_at.replace(tzinfo=BUSINESS_TZ) + dt_mod.timedelta(minutes=5)).isoformat()
                g_events = fetch_agent_events(agent_id, start_iso, end_iso)
                if g_events is None:
                    raise BookingConflictError("Calendar provider unavailable or returned unknown state.")
                s_naive = starts_at.replace(tzinfo=None)
                e_naive = ends_at.replace(tzinfo=None)
                for ev in g_events:
                    if ev.get("status") == "cancelled":
                        continue
                    ev_start = _provider_datetime(ev.get("start") or {})
                    ev_end = _provider_datetime(ev.get("end") or {})
                    if ev_start and ev_end:
                        if s_naive < ev_end and e_naive > ev_start:
                            raise BookingConflictError("The requested time overlaps an existing Google Calendar event.")
            except BookingConflictError:
                raise
            except Exception as exc:
                raise BookingConflictError(f"Calendar provider error: {exc}") from exc
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
        vehicle_str: Optional[str] = None,
        issue_description: Optional[str] = None,
        triggered_by: str = "system",
        old_calendar_event_id: Optional[str] = None,
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
            time_changed = (old_starts_at != starts_at)
            agent_changed = bool(previous_agent)
            if time_changed and agent_changed:
                notification_event = "RESCHEDULED_REASSIGNED"
            elif agent_changed:
                notification_event = "REASSIGNED"
            elif time_changed:
                notification_event = "RESCHEDULED"
            else:
                notification_event = "BOOKING"
        if triggered_by == "portal_staff_reassignment":
            # Recovery of an unassigned request must not reuse BOOKING's dedup key
            # or replace the reassignment deadline with a new-booking SLA.
            notification_event = "REASSIGNED"
        calendar_event_id = f"servicebot{reservation_id}{starts_at.strftime('%Y%m%d%H%M')}"
        bypass_qh = triggered_by in ("voice_agent", "telephony_voice_assistant", "voice_tool", "customer")
        payload = {
            "reservation_id": reservation_id,
            "agent_id": staff_agent_id,
            "old_agent_id": old_staff_agent_id,
            "old_booking_time_str": old_starts_at.strftime("%Y-%m-%d %H:%M:%S") if old_starts_at else None,
            "old_calendar_event_id": old_calendar_event_id,
            "calendar_event_id": calendar_event_id,
            "booking_type": booking_type,
            "booking_time_str": starts_at.strftime("%Y-%m-%d %H:%M:%S"),
            "duration_minutes": duration_minutes,
            "notification_event": notification_event,
            "triggered_by": triggered_by,
            "bypass_quiet_hours": bypass_qh,
            "agent_name": assigned_agent.get("name"),
            "agent_email": assigned_agent.get("email"),
            "agent_phone": assigned_agent.get("phone_number"),
            "previous_agent_name": previous_agent.get("name"),
            "previous_agent_phone": previous_agent.get("phone_number"),
            "vehicle": vehicle_str or "N/A",
            "issue": issue_description or service_type,
            "details": {
                "customer_name": customer.get("name") or "Customer",
                "phone": customer.get("phone"),
                "service_type": service_type,
                "vehicle": vehicle_str or "N/A",
                "issue": issue_description or service_type,
                "duration_minutes": duration_minutes,
                "agent_name": assigned_agent.get("name"),
                "new_agent_name": assigned_agent.get("name"),
                "previous_agent_name": previous_agent.get("name"),
                "triggered_by": triggered_by,
                "bypass_quiet_hours": bypass_qh,
            },
        }
        from serviceBot.services.simulation_faults import bind_booking, has_booking_capability
        for event_type in ("calendar_projection", "booking_notification"):
            bind_fault = event_type == "calendar_projection" and has_booking_capability()
            cursor.execute(
                """
                INSERT INTO outbox_notifications (event_type, request_id, payload, status, next_retry_at)
                VALUES (%s, %s, %s, 'PENDING', CURRENT_TIMESTAMP)
                """ + (" RETURNING id;" if bind_fault else ";"),
                (event_type, request_id, json.dumps(payload)),
            )
            if bind_fault:
                bind_booking(cursor, request_id=request_id, reservation_id=reservation_id,
                    outbox_id=cursor.fetchone()["id"], staff_agent_id=staff_agent_id,
                    service_type=service_type, customer_phone=customer.get("phone"))


# In-flight booking session tracking for call deduplication
_IN_FLIGHT_BOOKING_SESSIONS: dict[str, dict[str, Any]] = {}


def track_session_booking(
    session_key: str,
    service_request_id: int,
    booking_time: str,
    duration_minutes: int = 60,
    phone: Optional[str] = None,
    vehicle: Optional[dict[str, Any]] = None,
) -> None:
    """Records an active in-flight booking within a call session."""
    if not session_key:
        return
    record = {
        "service_request_id": service_request_id,
        "booking_time": booking_time,
        "duration_minutes": duration_minutes,
        "phone": phone,
        "vehicle": vehicle or {},
        "created_at": dt_mod.datetime.now(),
    }
    _IN_FLIGHT_BOOKING_SESSIONS[session_key] = record


def get_session_booking(session_key: str, max_age_seconds: int = 900) -> Optional[dict[str, Any]]:
    """Retrieves an active in-flight booking for a session if not expired."""
    if not session_key:
        return None
    data = _IN_FLIGHT_BOOKING_SESSIONS.get(session_key)
    if not data:
        return None
    created = data.get("created_at")
    if created and (dt_mod.datetime.now() - created).total_seconds() > max_age_seconds:
        _IN_FLIGHT_BOOKING_SESSIONS.pop(session_key, None)
        return None
    return data


def clear_session_booking(session_key: str) -> None:
    """Removes a session booking record upon call completion."""
    if not session_key:
        return
    _IN_FLIGHT_BOOKING_SESSIONS.pop(session_key, None)


def reserve_multi_service_appointment(*args, **kwargs) -> list[dict[str, Any]]:
    """Module-level wrapper for BookingService().reserve_multi_service_appointment."""
    return BookingService().reserve_multi_service_appointment(*args, **kwargs)


def cancel_multi_service_visit(*args, **kwargs) -> dict[str, Any]:
    """Module-level wrapper for BookingService().cancel_multi_service_visit."""
    return BookingService().cancel_multi_service_visit(*args, **kwargs)


def revise_multi_service_visit(*args, **kwargs) -> dict[str, Any]:
    """Module-level wrapper for BookingService().revise_multi_service_visit."""
    return BookingService().revise_multi_service_visit(*args, **kwargs)


def reassign_declined_technician_segment(*args, **kwargs) -> dict[str, Any]:
    """Module-level wrapper for BookingService().reassign_declined_technician_segment."""
    return BookingService().reassign_declined_technician_segment(*args, **kwargs)


