"""Voice intake preserves an exact catalog identity supplied as the issue."""

from datetime import timedelta

import pytest

from e2e.test_voice_and_reporting import voice


@pytest.mark.parametrize("case", ["exact", "case_and_space", "explicit", "uncataloged", "nonmatch", "ambiguous"])
def test_intake_catalog_identity_controls_receipt_and_reserved_capacity(api, db, scenario, case):
    catalog_name = "Oil Change (Full Synthetic)"
    db("INSERT INTO services (name, duration_minutes, price_range) VALUES (%s, 45, '$79 - $119')", (catalog_name,))
    args = {
        "customer_name": "Intake E2E", "phone": "+15550100006",
        "make": "Toyota", "model": "Camry", "year": 2021,
        "issue_description": catalog_name, "booking_type": "appointment",
        "booking_time": scenario["start"].isoformat(), "call_sid": "catalog-intake-contract",
    }
    expected_name, expected_duration = catalog_name, 45
    if case == "case_and_space":
        args["issue_description"] = f"  {catalog_name.lower()}  "
    elif case == "explicit":
        args["service_type"] = "Oil Change"
        expected_name, expected_duration = "Oil Change", 60
    elif case == "uncataloged":
        args["is_uncataloged"] = True
        expected_name, expected_duration = "Repair", 60
    elif case == "nonmatch":
        args["issue_description"] = "Oil Change (Full Synthetic) requested with unusual engine noise"
        expected_name, expected_duration = "Repair", 60
    elif case == "ambiguous":
        db("INSERT INTO services (name, duration_minutes, price_range) VALUES (%s, 30, '$49')", (catalog_name.upper(),))
        expected_name, expected_duration = "Repair", 60

    result = voice(api, "create_service_request", args)
    assert result["success"] is True, result
    assert result["duration_minutes"] == expected_duration
    assert result["expected_end_time"] == (scenario["start"] + timedelta(minutes=expected_duration)).strftime("%Y-%m-%d %H:%M:%S")
    request_id = result["service_request_id"]
    persisted = db("SELECT service_type, issue_description, duration_minutes, is_uncataloged FROM service_requests WHERE id=%s", (request_id,))[0]
    assert persisted["service_type"] == expected_name
    assert persisted["duration_minutes"] == expected_duration
    assert persisted["issue_description"] == args["issue_description"]
    assert persisted["is_uncataloged"] is (case == "uncataloged")
    reservation = db("SELECT id, starts_at, ends_at FROM appointment_reservations WHERE service_request_id=%s AND status='ACTIVE'", (request_id,))[0]
    assert reservation["ends_at"] - reservation["starts_at"] == timedelta(minutes=expected_duration)
    assert len(db("SELECT segment_start FROM appointment_reservation_segments WHERE reservation_id=%s", (reservation["id"],))) == expected_duration // 15
    if expected_duration == 45:
        assert "$79 - $119" in result["message"]
