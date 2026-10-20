"""A boolean domain result never substitutes for persisted reschedule evidence."""

import asyncio
from copy import deepcopy
from datetime import timedelta
from unittest.mock import Mock

import pytest

from serviceBot.api import telephony
from serviceBot.services.booking import parse_reservation_start, reservation_segments


@pytest.fixture(scope="session", autouse=True)
def setup_and_cleanup_test_db():
    yield


@pytest.fixture
def persisted_move(monkeypatch):
    rows = [{"id": 17, "booking_type": "appointment", "status": "pending",
             "appointment_datetime": "2026-11-20 10:00:00", "duration_minutes": 90,
             "service_type": "Brake Repair & Pad Replacement", "service_components": None,
             "visit_group_id": None, "visit_member_ids": []}]
    monkeypatch.setattr(telephony, "get_customer_appointments", lambda _: deepcopy(rows))
    def capacity(ids):
        return [{"id": row["id"], "request_staff": 7, "service_request_id": row["id"],
                 "reservation_id": 101, "staff_agent_id": 7, "status": "ACTIVE",
                 "request_status": "pending", "phone": "5550100001",
                 "duration_minutes": row["duration_minutes"], "booking_time": row["appointment_datetime"],
                 "starts_at": row["appointment_datetime"],
                 "ends_at": parse_reservation_start(row["appointment_datetime"]) + timedelta(minutes=row["duration_minutes"]),
                 "segments": [{"reservation_id": 101, "staff_agent_id": 7, "segment_start": start}
                              for start in reservation_segments(parse_reservation_start(row["appointment_datetime"]), row["duration_minutes"])]}
                for row in rows]
    monkeypatch.setattr(telephony, "_session_capacity_evidence", capacity)
    def invoke():
        return asyncio.run(telephony.voice_tools({"name": "reschedule_appointment", "arguments": {
            "phone": "5550100001", "appointment_id": 17,
            "new_appointment_datetime": "2026-11-20 12:00:00"}}))["result"]
    return rows, invoke


@pytest.mark.parametrize("outcome", [False, None, 1, {"success": True}, True])
def test_unmoved_or_ambiguous_domain_outcome_cannot_report_success(persisted_move, monkeypatch, outcome):
    _, invoke = persisted_move
    monkeypatch.setattr(telephony, "reschedule_appointment", Mock(return_value=outcome))
    result = invoke()
    assert result["success"] is False
    assert result["error_code"] == "RESCHEDULE_UNVERIFIED"
    assert result["booking_confirmation_status"] == "unconfirmed"


@pytest.mark.parametrize("defect", ["none", "missing", "wrong_end", "missing_segment", "wrong_staff", "read_error", "duration_changed"])
def test_saved_duration_and_native_capacity_must_agree(persisted_move, monkeypatch, defect):
    rows, invoke = persisted_move
    capacity = telephony._session_capacity_evidence
    def update(**_):
        rows[0]["appointment_datetime"] = "2026-11-20 12:00:00"
        if defect == "duration_changed": rows[0]["duration_minutes"] = 60
        def read(ids):
            if defect == "read_error": raise RuntimeError("private-provider-secret")
            data = capacity(ids)
            if defect == "missing": return []
            if defect == "wrong_end": data[0]["ends_at"] += timedelta(minutes=15)
            if defect == "missing_segment": data[0]["segments"].pop()
            if defect == "wrong_staff": data[0]["segments"][0]["staff_agent_id"] = 8
            return data
        monkeypatch.setattr(telephony, "_session_capacity_evidence", read)
        return True
    monkeypatch.setattr(telephony, "reschedule_appointment", update)
    result = invoke()
    assert result["success"] is (defect == "none"), result
    assert "private-provider-secret" not in str(result)
    if defect == "none":
        assert result["duration_minutes"] == 90
        assert result["expected_end_time"] == "2026-11-20 13:30:00"
        assert result["appointments"][0]["reservation_id"] == 101


def test_same_saved_time_is_verified_without_another_mutation(persisted_move, monkeypatch):
    rows, invoke = persisted_move
    rows[0]["appointment_datetime"] = "2026-11-20 12:00:00"
    mutation = Mock()
    monkeypatch.setattr(telephony, "reschedule_appointment", mutation)
    result = invoke()
    assert result["success"] is True and result["is_update"] is False
    assert result["duration_minutes"] == 90
    mutation.assert_not_called()


def test_unknown_native_capacity_prevents_mutation(persisted_move, monkeypatch):
    _, invoke = persisted_move
    monkeypatch.setattr(telephony, "_session_capacity_evidence", Mock(return_value=[]))
    mutation = Mock()
    monkeypatch.setattr(telephony, "reschedule_appointment", mutation)
    result = invoke()
    assert result["success"] is False
    mutation.assert_not_called()


def test_prompt_requires_admitting_recorded_duration_mismatch():
    from pathlib import Path

    prompt = (Path(__file__).resolve().parents[1] / "serviceBot/system_prompt.txt").read_text()
    assert "A catalogue estimate is not a saved reservation" in prompt
    assert "acknowledge the discrepancy" in prompt
    assert 'Never invent an "initial check-in slot"' in prompt
