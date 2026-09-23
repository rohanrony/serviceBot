"""Contract tests for the PostgreSQL reservation authority."""

import datetime as dt_mod
import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import serviceBot.db.queries as queries
from serviceBot.main import app
from serviceBot.services.booking import (
    BUSINESS_TZ,
    BookingConflictError,
    BookingReceipt,
    BookingService,
    BookingValidationError,
    normalize_reservation_duration,
    parse_reservation_start,
    reservation_segments,
    validate_bookable_window,
)


class RecordingCursor:
    def __init__(self, rows=()):
        self.rows = list(rows)
        self.executed = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, query, params=None):
        self.executed.append((" ".join(query.split()), params))

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None

    def fetchall(self):
        return self.rows.pop(0) if self.rows else []


class RecordingConnection:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def test_reservation_parser_and_segments_round_duration_up_to_a_quarter_hour():
    starts_at = parse_reservation_start("2026-10-15T09:30:00")
    assert reservation_segments(starts_at, 60) == [
        dt_mod.datetime(2026, 10, 15, 9, 30),
        dt_mod.datetime(2026, 10, 15, 9, 45),
        dt_mod.datetime(2026, 10, 15, 10, 0),
        dt_mod.datetime(2026, 10, 15, 10, 15),
    ]
    assert normalize_reservation_duration(20) == 30
    assert reservation_segments(starts_at, 20) == [
        dt_mod.datetime(2026, 10, 15, 9, 30),
        dt_mod.datetime(2026, 10, 15, 9, 45),
    ]

    with pytest.raises(BookingValidationError, match="15-minute boundary"):
        parse_reservation_start("2026-10-15T09:31:00")
    with pytest.raises(BookingValidationError, match="positive"):
        reservation_segments(starts_at, 0)

def test_window_validation_rejects_a_booking_that_runs_past_business_hours():
    with patch("serviceBot.services.calendar_sync.get_configured_business_days", return_value=[2]), patch(
        "serviceBot.services.calendar_sync.get_configured_business_hours", return_value=list(range(7, 18))
    ):
        with pytest.raises(BookingValidationError, match="outside company workhours"):
            validate_bookable_window(dt_mod.datetime(2026, 10, 15, 17, 45), 30)


def test_window_validation_rejects_past_bookings_before_availability_checks():
    past = dt_mod.datetime.now(BUSINESS_TZ).replace(tzinfo=None, second=0, microsecond=0) - dt_mod.timedelta(minutes=15)
    with pytest.raises(BookingValidationError, match="must be in the future"):
        validate_bookable_window(past, 15)


@patch("serviceBot.services.google_calendar.fetch_agent_events", side_effect=RuntimeError("provider unavailable"))
def test_check_availability_fails_closed_when_no_provider_state_can_be_loaded(_fetch_events):
    candidate = dt_mod.date.today() + dt_mod.timedelta(days=1)
    while candidate.weekday() > 4:
        candidate += dt_mod.timedelta(days=1)

    assert queries.check_availability(preferred_date=candidate.isoformat()) == []


def test_portal_edit_checks_consent_before_any_mutation():
    cursor = RecordingCursor(
        [
            {
                "id": 9,
                "customer_id": 2,
                "vehicle_id": 3,
                "issue_description": "Old issue",
                "status": "pending",
                "service_type": "Oil Change",
                "booking_type": "appointment",
                "booking_time": "2026-10-15 09:30:00",
                "duration_minutes": 60,
                "staff_agent_id": 1,
            }
        ]
    )
    service = BookingService(
        connection_factory=lambda: RecordingConnection(),
        cursor_factory=lambda _connection: cursor,
    )

    with pytest.raises(BookingValidationError, match="Customer consent"):
        service.apply_portal_edit(
            request_id=9,
            issue_description="New issue",
            vehicle_details={"make": "Honda", "model": "Civic", "year": 2020, "vin": None},
            booking_time="2026-10-15T10:30:00",
            booking_type="appointment",
            duration_minutes=60,
            customer_consent_obtained=False,
        )

    assert len(cursor.executed) == 1
    assert "FOR UPDATE" in cursor.executed[0][0]


def test_blocked_local_slot_never_attempts_reservation_insert():
    cursor = RecordingCursor([{"blocked": True}])

    result = BookingService._try_reserve_candidate(
        cursor,
        request_id=9,
        existing_reservation_id=None,
        agent_id=1,
        starts_at=dt_mod.datetime(2026, 10, 15, 9, 30),
        ends_at=dt_mod.datetime(2026, 10, 15, 10, 30),
        segments=reservation_segments(dt_mod.datetime(2026, 10, 15, 9, 30), 60),
    )

    assert result is None
    assert not any("INSERT INTO appointment_reservations" in query for query, _ in cursor.executed)


def test_public_booking_helper_delegates_to_the_reservation_authority():
    receipt = BookingReceipt(7, 11, 3, dt_mod.datetime(2026, 10, 15, 9, 30), dt_mod.datetime(2026, 10, 15, 10, 30))
    with patch("serviceBot.db.queries.get_service_required_fields", return_value={"name": "Oil Change", "duration_minutes": 60}), patch(
        "serviceBot.services.booking.BookingService"
    ) as booking_class:
        booking_class.return_value.reserve_or_create.return_value = receipt

        assert queries.book_appointment(1, 7, "2026-10-15T09:30:00", "Oil Change") == 7

    booking_class.return_value.reserve_or_create.assert_called_once()
    assert booking_class.return_value.reserve_or_create.call_args.kwargs["duration_minutes"] == 60


def test_reschedule_outbox_preserves_notification_event_and_recipient_context():
    cursor = RecordingCursor(
        [
            {"name": "New Agent", "phone_number": "+15550100002", "email": "new@example.test"},
            {"name": "Previous Agent", "phone_number": "+15550100001", "email": "old@example.test"},
        ]
    )

    BookingService._enqueue_projection_events(
        cursor,
        request_id=9,
        reservation_id=12,
        staff_agent_id=2,
        old_staff_agent_id=1,
        old_starts_at=dt_mod.datetime(2026, 10, 15, 9, 30),
        booking_type="appointment",
        starts_at=dt_mod.datetime(2026, 10, 15, 10, 30),
        duration_minutes=60,
        customer={"name": "Ada Lovelace", "phone": "+15550100000"},
        service_type="Oil Change",
    )

    payloads = [
        json.loads(params[2])
        for query, params in cursor.executed
        if "INSERT INTO outbox_notifications" in query
    ]
    assert len(payloads) == 2
    for payload in payloads:
        assert payload["notification_event"] == "RESCHEDULED_REASSIGNED"
        assert payload["agent_phone"] == "+15550100002"
        assert payload["previous_agent_phone"] == "+15550100001"
        assert payload["details"]["new_agent_name"] == "New Agent"


def test_scheduled_create_service_request_cannot_bypass_the_reservation_authority():
    receipt = BookingReceipt(12, 14, 3, dt_mod.datetime(2026, 10, 15, 9, 30), dt_mod.datetime(2026, 10, 15, 10, 30))
    with patch("serviceBot.db.queries.get_service_required_fields", return_value={"name": "Oil Change", "duration_minutes": 60}), patch(
        "serviceBot.services.booking.BookingService"
    ) as booking_class:
        booking_class.return_value.reserve_or_create.return_value = receipt

        assert queries.create_service_request(
            customer_id=1,
            vehicle_details={"make": "Honda", "model": "Civic", "year": 2020},
            issue="Routine service",
            service_type="Oil Change",
            booking_type="appointment",
            booking_time="2026-10-15T09:30:00",
        ) == 12

    booking_class.return_value.reserve_or_create.assert_called_once()


def test_scheduled_create_service_request_forwards_uncataloged_metadata():
    receipt = BookingReceipt(14, 15, 3, dt_mod.datetime(2026, 10, 15, 9, 30), dt_mod.datetime(2026, 10, 15, 9, 45))
    with patch("serviceBot.db.queries.get_service_required_fields", return_value={"name": "Custom Tuning", "duration_minutes": 60}), patch(
        "serviceBot.services.booking.BookingService"
    ) as booking_class:
        booking_class.return_value.reserve_or_create.return_value = receipt

        assert queries.create_service_request(
            customer_id=1,
            vehicle_details={"make": "Ford", "model": "Mustang", "year": 1968},
            issue="Custom carburetor tuning",
            service_type="Custom Tuning",
            booking_type="appointment_and_callback",
            booking_time="2026-10-15T09:30:00",
            is_uncataloged=True,
            linked_appointment_id=9,
            callback_priority="high",
            callback_number="+15550123456",
        ) == 14

    forwarded = booking_class.return_value.reserve_or_create.call_args.kwargs
    assert forwarded["is_uncataloged"] is True
    assert forwarded["linked_appointment_id"] == 9
    assert forwarded["callback_priority"] == "high"
    assert forwarded["callback_number"] == "+15550123456"


def test_portal_routes_delegate_to_one_transactional_gateway():
    client = TestClient(app)
    receipt = BookingReceipt(22, 25, 2, dt_mod.datetime(2026, 10, 15, 9, 30), dt_mod.datetime(2026, 10, 15, 10, 30))
    payload = {
        "customer": {"name": "Ada", "phone": "424-270-4893"},
        "vehicle": {"make": "Honda", "model": "Civic", "year": 2020, "vin": None},
        "service_request": {"service_type": "Oil Change", "booking_time": "2026-10-15T09:30:00"},
    }
    with patch("serviceBot.services.booking.BookingService") as booking_class:
        booking_class.return_value.create_portal_request.return_value = receipt
        created = client.post("/api/v1/portal/service-requests", json=payload)

    assert created.status_code == 201
    assert created.json() == {"success": True, "request_id": 22}
    booking_class.return_value.create_portal_request.assert_called_once()

    with patch("serviceBot.services.booking.BookingService") as booking_class:
        edited = client.put(
            "/api/v1/portal/service-requests/22",
            json={
                "issue_description": "Routine service",
                "vehicle_details": {"make": "Honda", "model": "Civic", "year": 2020, "vin": None},
                "booking_time": "2026-10-15T10:30:00",
                "customer_consent_obtained": True,
            },
        )

    assert edited.status_code == 200
    booking_class.return_value.apply_portal_edit.assert_called_once()


def test_portal_returns_conflict_when_the_transactional_gateway_rejects_capacity():
    client = TestClient(app)
    payload = {
        "customer": {"name": "Ada", "phone": "424-270-4893"},
        "vehicle": {"make": "Honda", "model": "Civic", "year": 2020, "vin": None},
        "service_request": {"service_type": "Oil Change", "booking_time": "2026-10-15T09:30:00"},
    }
    with patch("serviceBot.services.booking.BookingService") as booking_class:
        booking_class.return_value.create_portal_request.side_effect = BookingConflictError("The requested time is no longer available.")
        response = client.post("/api/v1/portal/service-requests", json=payload)

    assert response.status_code == 409
    assert "no longer available" in response.json()["detail"]

