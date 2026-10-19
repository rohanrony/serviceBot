from contextlib import contextmanager
from copy import deepcopy
from datetime import timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from serviceBot.api import telephony
from serviceBot.main import app
from serviceBot.services import booking

client = TestClient(app)

@pytest.fixture(autouse=True)
def cleanup_sessions(monkeypatch):
    # Session tracking is process-global; isolate the actual dictionary, including phone_ keys.
    monkeypatch.setattr(booking, "_IN_FLIGHT_BOOKING_SESSIONS", {})
    yield
    assert len(booking._IN_FLIGHT_BOOKING_SESSIONS) == 1


@pytest.fixture
def owned_booking(monkeypatch):
    """Native-shaped owned readbacks; the real session/ownership/capacity guards run."""
    def arrange(identifier, phone, service_type, vehicle):
        rows = []
        capacity_reads = []
        owned_reads = []
        connection = object()
        def insert(**kwargs):
            assert rows == []
            start = kwargs.get("booking_time") or kwargs["appointment_datetime"]
            rows.append({"id": identifier, "booking_type": "appointment", "appointment_datetime": start,
                         "duration_minutes": 60, "status": "pending", "service_type": service_type,
                         "service_components": None, "visit_group_id": None, "visit_member_ids": [],
                         **vehicle})
            return identifier
        def move(**kwargs):
            assert kwargs["appointment_id"] == identifier
            rows[0]["appointment_datetime"] = kwargs["new_datetime"]
            return True
        def appointments(number):
            assert number == phone
            owned_reads.append(number)
            return deepcopy(rows)
        @contextmanager
        def connect():
            yield connection
        @contextmanager
        def cursor(conn):
            assert conn is connection
            class Cursor:
                def execute(self, sql, params=None):
                    statement = " ".join(sql.split())
                    assert statement.startswith("SELECT ")
                    if statement == "SELECT name FROM services;":
                        assert params is None
                        self.result = [{"name": service_type}]
                        return
                    if "FROM services WHERE" in statement:
                        assert params == (service_type,)
                        self.result = [{"name": service_type}]
                        return
                    assert "FROM service_requests sr" in statement
                    assert "JOIN customers c ON c.id=sr.customer_id" in statement
                    assert "LEFT JOIN appointment_reservations ar ON ar.service_request_id=sr.id" in statement
                    assert "FROM appointment_reservation_segments seg" in statement
                    assert "WHERE sr.id=ANY(%s)" in statement
                    assert params == ([identifier],)
                    assert len(rows) == 1
                    capacity_reads.append((statement, deepcopy(params)))
                    start = booking.parse_reservation_start(rows[0]["appointment_datetime"])
                    reservation = identifier + 1000
                    self.result = [{"id": identifier, "request_staff": 7, "duration_minutes": 60,
                        "booking_time": rows[0]["appointment_datetime"], "request_status": "pending", "phone": phone,
                        "reservation_id": reservation, "service_request_id": identifier, "staff_agent_id": 7,
                        "starts_at": start, "ends_at": start + timedelta(minutes=60), "status": "ACTIVE",
                        "segments": [{"reservation_id": reservation, "staff_agent_id": 7, "segment_start": segment}
                                     for segment in booking.reservation_segments(start, 60)]}]
                def fetchall(self):
                    return deepcopy(self.result)
            yield Cursor()
        monkeypatch.setattr(telephony, "get_customer_appointments", appointments)
        monkeypatch.setattr(telephony, "get_db_connection", connect)
        monkeypatch.setattr(telephony, "dict_cursor", cursor)
        return insert, move, rows, capacity_reads, owned_reads
    return arrange


def test_booking_response_includes_start_end_and_extension_notice():
    """Verify booking response includes expected start/end times and extension notice."""
    with patch("serviceBot.api.telephony.lookup_customer_by_phone") as mock_lookup, \
         patch("serviceBot.api.telephony.update_customer_name") as _mock_upd_name, \
         patch("serviceBot.api.telephony.create_service_request") as mock_create, \
         patch("serviceBot.api.telephony.get_service_required_fields") as mock_fields:

        mock_lookup.return_value = {"customer_id": 1, "name": "John Doe", "make": "Honda", "model": "Civic", "year": 2020}
        mock_create.return_value = 101
        mock_fields.return_value = {"price_range": "$79-$119", "duration_minutes": 60}

        payload = {
            "name": "create_service_request",
            "arguments": {
                "customer_name": "John Doe",
                "phone": "5551234567",
                "make": "Honda",
                "model": "Civic",
                "year": 2020,
                "issue_description": "Oil Change",
                "booking_type": "appointment",
                "booking_time": "2026-10-05 10:00:00",
                "call_sid": "test_call_sid_123"
            }
        }
        resp = client.post("/api/v1/voice/tools", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        result = data.get("result", data)
        assert result["success"] is True
        # Check start and end time window or duration
        assert "expected_end_time" in result or "10:00 AM" in result.get("message", "")
        # Check extension notice
        assert "extend" in result.get("message", "").lower()


def test_single_booking_on_time_change_deduplication(owned_booking):
    """
    Verify that when create_service_request is called a second time in the same call session
    with a revised time (e.g. 10:00 AM then 10:30 AM), it updates the existing booking
    rather than creating a duplicate.
    """
    with patch("serviceBot.api.telephony.lookup_customer_by_phone") as mock_lookup, \
         patch("serviceBot.api.telephony.update_customer_name") as _mock_upd_name, \
         patch("serviceBot.api.telephony.create_service_request") as mock_create, \
         patch("serviceBot.api.telephony.reschedule_appointment") as mock_reschedule, \
         patch("serviceBot.api.telephony.get_service_required_fields") as mock_fields:

        mock_lookup.return_value = {"customer_id": 1, "name": "John Doe", "make": "Honda", "model": "Civic", "year": 2020}
        insert, move, rows, capacity_reads, owned_reads = owned_booking(
            101, "5551234567", "Oil Change", {"make": "Honda", "model": "Civic", "year": 2020})
        mock_create.side_effect = insert
        mock_reschedule.side_effect = move
        mock_fields.return_value = {"price_range": "$79-$119", "duration_minutes": 60}

        # Turn 1: 10:00 AM booking
        payload_1 = {
            "name": "create_service_request",
            "arguments": {
                "customer_name": "John Doe",
                "phone": "5551234567",
                "make": "Honda",
                "model": "Civic",
                "year": 2020,
                "issue_description": "Oil Change",
                "booking_type": "appointment",
                "booking_time": "2026-10-05 10:00:00",
                "call_sid": "test_call_sid_123"
            }
        }
        resp1 = client.post("/api/v1/voice/tools", json=payload_1)
        assert resp1.status_code == 200
        res1 = resp1.json().get("result", resp1.json())
        assert res1["success"] is True
        assert res1.get("service_request_id") == 101

        # Turn 2: Caller changes mind to 10:30 AM in same call session
        payload_2 = {
            "name": "create_service_request",
            "arguments": {
                "customer_name": "John Doe",
                "phone": "5551234567",
                "make": "Honda",
                "model": "Civic",
                "year": 2020,
                "issue_description": "Oil Change",
                "booking_type": "appointment",
                "booking_time": "2026-10-05 10:30:00",
                "call_sid": "test_call_sid_123"
            }
        }
        resp2 = client.post("/api/v1/voice/tools", json=payload_2)
        assert resp2.status_code == 200
        res2 = resp2.json().get("result", resp2.json())
        assert res2["success"] is True
        # Must be recognized as an update of the existing booking 101
        assert res2.get("is_update") is True
        assert res2.get("service_request_id") == 101
        # create_service_request was called once; reschedule was called for the change
        assert mock_create.call_count == 1
        assert mock_reschedule.call_count == 1
        mock_reschedule.assert_called_once_with(appointment_id=101, new_datetime="2026-10-05 10:30:00",
            customer_consent_obtained=True, triggered_by="telephony_voice_assistant")
        mock_create.assert_called_once_with(customer_id=1,
            vehicle_details={"make": "Honda", "model": "Civic", "year": 2020}, issue="Oil Change",
            service_type="Oil Change", time_slot=None, booking_type="appointment", booking_time="2026-10-05 10:00:00")
        assert mock_create.call_args.kwargs["booking_time"] == "2026-10-05 10:00:00"
        assert mock_create.call_args.kwargs["customer_id"] == 1
        assert rows[0]["appointment_datetime"] == "2026-10-05 10:30:00"
        assert res2["booking_time"] == booking.parse_reservation_start("2026-10-05 10:30:00").isoformat()
        assert res2["expected_end_time"] == "2026-10-05 11:30:00"
        assert res2["duration_minutes"] == 60
        cached = booking.get_session_booking("test_call_sid_123")
        assert cached["service_request_id"] == 101 and cached["phone"] == "5551234567"
        assert cached["booking_time"] == res2["booking_time"] and cached["duration_minutes"] == 60
        assert set(booking._IN_FLIGHT_BOOKING_SESSIONS) == {"test_call_sid_123"}
        assert len(capacity_reads) == 2 and owned_reads == ["5551234567"] * 3


def test_book_appointment_deduplication_on_time_change(owned_booking):
    """Verify that book_appointment tool also deduplicates within the same call session."""
    with patch("serviceBot.api.telephony.lookup_customer_by_phone") as mock_lookup, \
         patch("serviceBot.api.telephony.update_customer_name") as _mock_upd_name, \
         patch("serviceBot.api.telephony.book_appointment") as mock_book, \
         patch("serviceBot.api.telephony.reschedule_appointment") as mock_reschedule, \
         patch("serviceBot.api.telephony.get_service_required_fields") as mock_fields:

        mock_lookup.return_value = {"customer_id": 1, "name": "Alice Smith", "make": "Ford", "model": "Focus", "year": 2018}
        insert, move, rows, capacity_reads, owned_reads = owned_booking(
            202, "5559876543", "Brake Service", {"make": "Ford", "model": "Focus", "year": 2018})
        mock_book.side_effect = insert
        mock_reschedule.side_effect = move
        mock_fields.return_value = {"price_range": "$120-$200", "duration_minutes": 60}

        payload_1 = {
            "name": "book_appointment",
            "arguments": {
                "customer_name": "Alice Smith",
                "phone": "5559876543",
                "appointment_datetime": "2026-10-05 14:00:00",
                "service_type": "Brake Service",
                "call_sid": "call_alice_789"
            }
        }
        resp1 = client.post("/api/v1/voice/tools", json=payload_1)
        assert resp1.status_code == 200
        res1 = resp1.json().get("result", resp1.json())
        assert res1["success"] is True
        assert res1["appointment_id"] == 202

        # Caller shifts to 14:30:00
        payload_2 = {
            "name": "book_appointment",
            "arguments": {
                "customer_name": "Alice Smith",
                "phone": "5559876543",
                "appointment_datetime": "2026-10-05 14:30:00",
                "service_type": "Brake Service",
                "call_sid": "call_alice_789"
            }
        }
        resp2 = client.post("/api/v1/voice/tools", json=payload_2)
        assert resp2.status_code == 200
        res2 = resp2.json().get("result", resp2.json())
        assert res2["success"] is True
        assert res2.get("is_update") is True
        assert res2.get("appointment_id") == 202
        assert mock_book.call_count == 1
        assert mock_reschedule.call_count == 1
        mock_reschedule.assert_called_once_with(appointment_id=202, new_datetime="2026-10-05 14:30:00",
            customer_consent_obtained=True, triggered_by="telephony_voice_assistant")
        mock_book.assert_called_once_with(customer_id=1, service_request_id=None,
            appointment_datetime="2026-10-05 14:00:00", service_type="Brake Service",
            vehicle_details={"make": "Ford", "model": "Focus", "year": 2018})
        assert mock_book.call_args.kwargs["appointment_datetime"] == "2026-10-05 14:00:00"
        assert mock_book.call_args.kwargs["customer_id"] == 1
        assert rows[0]["appointment_datetime"] == "2026-10-05 14:30:00"
        assert res2["booking_time"] == booking.parse_reservation_start("2026-10-05 14:30:00").isoformat()
        assert res2["expected_end_time"] == "2026-10-05 15:30:00"
        assert res2["duration_minutes"] == 60
        cached = booking.get_session_booking("call_alice_789")
        assert cached["service_request_id"] == 202 and cached["phone"] == "5559876543"
        assert cached["booking_time"] == res2["booking_time"] and cached["duration_minutes"] == 60
        assert set(booking._IN_FLIGHT_BOOKING_SESSIONS) == {"call_alice_789"}
        assert len(capacity_reads) == 2 and owned_reads == ["5559876543"] * 3
