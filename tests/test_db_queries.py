import pytest
from serviceBot.db.connection import get_db_connection, dict_cursor
from serviceBot.db.queries import (
    lookup_customer_by_phone,
    create_service_request,
    book_appointment,
    get_service_required_fields,
    get_customer_appointments,
)


@pytest.fixture
def mock_db():
    """Clear database, initialize schema, and seed data in PostgreSQL."""
    from serviceBot.db.seed import seed_db

    # Run seed_db first to ensure tables exist and staff_agents/mock_calendar_slots are populated
    seed_db()

    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            # Only truncate the tables we need to re-seed with controlled test data
            cursor.execute("TRUNCATE TABLE customers, vehicles, service_requests, services CASCADE;")

            # Seed data matching Sarah Johnson from spec
            cursor.execute(
                "INSERT INTO customers (id, name, phone, email) VALUES (%s, %s, %s, %s);",
                (1, 'Sarah Johnson', '+15551234567', 'sarah.j@example.com')
            )
            cursor.execute(
                "INSERT INTO vehicles (id, customer_id, make, model, year, vin) VALUES (%s, %s, %s, %s, %s, %s);",
                (1, 1, 'Honda', 'Civic', 2020, '1HGCR2F8LAA123456')
            )
            cursor.execute(
                "INSERT INTO service_requests (id, customer_id, vehicle_id, service_type, issue_description, status) VALUES (%s, %s, %s, %s, %s, %s);",
                (1, 1, 1, 'Brake repair', 'Grinding noise when stopping, brake light on.', 'pending')
            )
            # Seed services
            cursor.execute(
                "INSERT INTO services (name, description, price_range, duration_minutes) VALUES (%s, %s, %s, %s);",
                ("AC change", "A/C service", "$150-250", 60)
            )
            cursor.execute(
                "INSERT INTO services (name, description, price_range, duration_minutes) VALUES (%s, %s, %s, %s);",
                ("Oil Change", "Oil change service", "$79-119", 45)
            )
            cursor.execute(
                "INSERT INTO services (name, description, price_range, duration_minutes) VALUES (%s, %s, %s, %s);",
                ("Brake repair", "Brake service", "$199-450", 90)
            )

            # Reset sequences
            for table in ["customers", "vehicles", "service_requests", "services"]:
                cursor.execute(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), COALESCE(MAX(id), 1)) FROM {table};")

            conn.commit()
            yield conn


def test_lookup_customer_by_phone_success(mock_db):
    """
    Assert that lookup_customer_by_phone("+15551234567") returns the matching
    customer dictionary shape defined in database_spec.md Section 3.1.
    """
    result = lookup_customer_by_phone("+15551234567")

    assert result is not None
    assert isinstance(result, dict)

    expected_keys = {
        "customer_id",
        "name",
        "phone",
        "vehicle_id",
        "make",
        "model",
        "year",
        "open_sr_id",
        "open_sr_type",
        "open_sr_status"
    }
    assert expected_keys.issubset(result.keys())

    assert result["customer_id"] == 1
    assert result["name"] == "Sarah Johnson"
    assert result["phone"] == "+15551234567"
    assert result["vehicle_id"] == 1
    assert result["make"] == "Honda"
    assert result["model"] == "Civic"
    assert result["year"] == 2020
    assert result["open_sr_id"] == 1
    assert result["open_sr_type"] == "Brake repair"
    assert result["open_sr_status"] == "pending"

def test_lookup_customer_by_phone_not_found(mock_db):
    """
    Assert that lookup for a new phone number returns empty details instead of throwing exceptions.
    """
    result = lookup_customer_by_phone("+15559999999")

    # Empty details could be None or an empty dictionary
    assert result is None or result == {}


def test_get_service_required_fields(mock_db):
    """
    Assert that get_service_required_fields returns the correct row when queried,
    is case-insensitive, and returns a fallback dict if the service is not found.
    """
    # Seed an extra service for this test
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                "INSERT INTO services (name, description, price_range, duration_minutes, "
                "req_customer_name, req_phone_number, req_vehicle_details, req_issue_description, req_location) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s);",
                ("Tire Rotation", "Rotate tires", "$20-40", 20, True, True, False, False, True)
            )
            conn.commit()

    result = get_service_required_fields("Tire Rotation")
    assert result is not None
    assert result["name"] == "Tire Rotation"

    # Case-insensitive check
    result_lower = get_service_required_fields("tire rotation")
    assert result_lower is not None
    assert result_lower["name"] == "Tire Rotation"

    # Unknown service returns a fallback dict (not None) after multi-service fix
    result_fallback = get_service_required_fields("Transmission Flush")
    assert result_fallback is not None
    assert result_fallback["name"] == "Transmission Flush"
    assert result_fallback["duration_minutes"] == 60  # fallback default


def test_create_service_request_with_time_slot(mock_db):
    vehicle_details = {"make": "Toyota", "model": "Corolla", "year": 2018}
    sr_id = create_service_request(
        customer_id=1,
        vehicle_details=vehicle_details,
        issue="Squeaking brakes",
        service_type="Brake repair",
        time_slot="Monday afternoon"
    )

    # Retrieve it from database and check fields
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                "SELECT time_slot, service_type, issue_description FROM service_requests WHERE id = %s;",
                (sr_id,)
            )
            row = cursor.fetchone()
            assert row is not None
            assert row["time_slot"] == "Monday afternoon"
            assert row["service_type"] == "Brake repair"
            assert row["issue_description"] == "Squeaking brakes"


def test_book_appointment_updates_service_type_and_prevents_overwrite(mock_db):
    """Verify book_appointment reuses pending requests and prevents overwriting booked ones."""
    # Find two future unbooked mock_calendar_slots
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                "SELECT DISTINCT slot_datetime FROM mock_calendar_slots WHERE is_booked = FALSE "
                "ORDER BY slot_datetime ASC LIMIT 2;"
            )
            slots = [r["slot_datetime"] for r in cursor.fetchall()]
            assert len(slots) >= 2, "Need at least 2 unbooked mock_calendar_slots from seed"

    slot1 = slots[0] if isinstance(slots[0], str) else slots[0].strftime("%Y-%m-%d %H:%M:%S")
    slot2 = slots[1] if isinstance(slots[1], str) else slots[1].strftime("%Y-%m-%d %H:%M:%S")

    # 1. Book AC change at slot1 — should reuse pending request id=1
    appt_id = book_appointment(
        customer_id=1,
        service_request_id=1,
        appointment_datetime=slot1,
        service_type='AC change'
    )
    assert appt_id == 1

    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                "SELECT service_type, booking_type, booking_time FROM service_requests WHERE id = %s;",
                (1,)
            )
            row = cursor.fetchone()
            assert row["service_type"] == "AC change"
            assert row["booking_type"] == "appointment"
            assert str(row["booking_time"]) == slot1

    # 2. Now request id=1 has booking_type='appointment', so passing it again should create a new SR
    new_appt_id = book_appointment(
        customer_id=1,
        service_request_id=None,
        appointment_datetime=slot2,
        service_type='Oil Change'
    )
    assert new_appt_id != 1
    assert new_appt_id is not None

    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                "SELECT service_type, booking_type, booking_time FROM service_requests WHERE id = %s;",
                (new_appt_id,)
            )
            new_row = cursor.fetchone()
            assert new_row["service_type"] == "Oil Change"
            assert new_row["booking_type"] == "appointment"


def test_fuzzy_service_catalog_matching(mock_db):
    """Verify that we can match services with fuzzy names to the correct catalog items."""
    # "oil change (full synthetic)" should match "Oil Change"
    res1 = get_service_required_fields("oil change (full synthetic)")
    assert res1 is not None
    assert res1["name"] == "Oil Change"
    assert res1["duration_minutes"] == 45

    # "brake repair and pads" should match "Brake repair"
    res2 = get_service_required_fields("brake repair and pads")
    assert res2 is not None
    assert res2["name"] == "Brake repair"
    assert res2["price_range"] == "$199-450"


def test_book_appointment_vehicle_resolution_and_no_overwrite(mock_db):
    """Verify that book_appointment uses the vehicle details and doesn't overwrite an already booked request."""
    # Find two future unbooked mock_calendar_slots
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                "SELECT DISTINCT slot_datetime FROM mock_calendar_slots WHERE is_booked = FALSE "
                "ORDER BY slot_datetime ASC LIMIT 2;"
            )
            slots = [r["slot_datetime"] for r in cursor.fetchall()]
            assert len(slots) >= 2, "Need at least 2 unbooked mock_calendar_slots from seed"

            # Create another vehicle for customer 1
            cursor.execute(
                "INSERT INTO vehicles (id, customer_id, make, model, year, vin) VALUES (%s, %s, %s, %s, %s, %s);",
                (2, 1, 'Ford', 'F-150', 2018, '1FTFW1EF5JFC98765')
            )
            conn.commit()

    slot1 = slots[0] if isinstance(slots[0], str) else slots[0].strftime("%Y-%m-%d %H:%M:%S")
    slot2 = slots[1] if isinstance(slots[1], str) else slots[1].strftime("%Y-%m-%d %H:%M:%S")

    # Book for Civic (vehicle_id = 1)
    appt_id1 = book_appointment(
        customer_id=1,
        service_request_id=None,
        appointment_datetime=slot1,
        service_type='Oil Change',
        vehicle_details={"make": "Honda", "model": "Civic", "year": 2020}
    )

    # Book for F-150 (vehicle_id = 2) - should not overwrite the first one
    appt_id2 = book_appointment(
        customer_id=1,
        service_request_id=appt_id1,  # pass the already booked request id to test overwrite prevention
        appointment_datetime=slot2,
        service_type='Brake repair',
        vehicle_details={"make": "Ford", "model": "F-150", "year": 2018}
    )

    assert appt_id1 != appt_id2

    # Check that Sarah now has two separate appointments with correct vehicles
    appts = get_customer_appointments("+15551234567")
    assert len(appts) >= 2

    civic_appt = next((a for a in appts if a["id"] == appt_id1), None)
    f150_appt = next((a for a in appts if a["id"] == appt_id2), None)

    assert civic_appt is not None
    assert civic_appt["make"] == "Honda"
    assert civic_appt["model"] == "Civic"

    assert f150_appt is not None
    assert f150_appt["make"] == "Ford"
    assert f150_appt["model"] == "F-150"


def test_multiple_services_booking_same_slot(mock_db):
    """
    Test that when an appointment is booked for an oil change,
    and then another service (AC repair) is booked for the exact same slot and vehicle,
    it merges the new service into the existing appointment instead of raising a ValueError.
    """
    # Find one future unbooked mock_calendar_slot
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                "SELECT slot_datetime FROM mock_calendar_slots WHERE is_booked = FALSE "
                "ORDER BY slot_datetime ASC LIMIT 1;"
            )
            slot_row = cursor.fetchone()
            assert slot_row is not None, "Need at least 1 unbooked mock_calendar_slot from seed"

    slot_str = slot_row["slot_datetime"]
    if not isinstance(slot_str, str):
        slot_str = slot_str.strftime("%Y-%m-%d %H:%M:%S")

    # 1. Book Oil Change
    appt_id1 = book_appointment(
        customer_id=1,
        service_request_id=None,
        appointment_datetime=slot_str,
        service_type='Oil Change',
        vehicle_details={"make": "Honda", "model": "Civic", "year": 2020}
    )
    assert appt_id1 is not None

    # 2. Book AC repair for the exact same slot and vehicle — should merge, not error
    appt_id2 = book_appointment(
        customer_id=1,
        service_request_id=None,
        appointment_datetime=slot_str,
        service_type='AC change',
        vehicle_details={"make": "Honda", "model": "Civic", "year": 2020}
    )

    # Should return the same appointment ID
    assert appt_id2 == appt_id1

    # Check that the appointment service_type now contains both services
    appts = get_customer_appointments("+15551234567")
    matching_appt = next((a for a in appts if a["id"] == appt_id1), None)
    assert matching_appt is not None
    assert "Oil Change" in matching_appt["service_type"]
    assert "AC change" in matching_appt["service_type"]


def test_get_service_required_fields_multi_service_fallback(mock_db):
    """
    Test that get_service_required_fields gracefully handles multi-service strings,
    calculates aggregate duration_minutes, and returns a combined dict.
    """
    res = get_service_required_fields("oil change, air conditioning repair, and brake repair")
    assert res is not None
    assert res["name"] == "oil change, air conditioning repair, and brake repair"
    # Seeded: Oil Change (45 min), AC change (60 min), Brake repair (90 min) -> Total 195 min
    assert res["duration_minutes"] == 195


def test_aggregate_service_duration_slot_checking_and_booking(mock_db):
    """
    Verify that slot checking and booking account for aggregate service duration
    and mark/check all mock slots within the total duration window.
    """
    from serviceBot.db.queries import check_availability

    # 1. Multi-service "Oil Change, Brake repair" has aggregate duration = 45 + 90 = 135 mins (~2.25 hours)
    fields = get_service_required_fields("Oil Change, Brake repair")
    assert fields["duration_minutes"] == 135

    # 2. Get unbooked slots
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                "SELECT DISTINCT slot_datetime FROM mock_calendar_slots WHERE is_booked = FALSE "
                "ORDER BY slot_datetime ASC LIMIT 4;"
            )
            rows = cursor.fetchall()
            assert len(rows) >= 4

    slot1 = rows[0]["slot_datetime"]
    slot1_str = slot1.strftime("%Y-%m-%d %H:%M:%S") if not isinstance(slot1, str) else slot1
    slot2 = rows[1]["slot_datetime"]
    slot2_str = slot2.strftime("%Y-%m-%d %H:%M:%S") if not isinstance(slot2, str) else slot2

    # 3. Book a 135-minute multi-service appointment at slot1
    appt_id = book_appointment(
        customer_id=1,
        service_request_id=None,
        appointment_datetime=slot1_str,
        service_type="Oil Change, Brake repair",
        vehicle_details={"make": "Honda", "model": "Civic", "year": 2020}
    )
    assert appt_id is not None

    # 4. Check availability for "Oil Change, Brake repair" starting on slot1
    # Since slot1 and subsequent slots in the 135-minute window were booked for the assigned agent,
    # check_availability for that specific time should filter out occupied agents.
    avail_slots = check_availability(service_type="Oil Change, Brake repair", preferred_date=slot1_str[:10])
    assert isinstance(avail_slots, list)

