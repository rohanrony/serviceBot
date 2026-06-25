import sqlite3
import pytest
from unittest.mock import patch
from serviceBot.db.connection import DDL_SCHEMA
from serviceBot.db.queries import lookup_customer_by_phone

@pytest.fixture
def mock_db(tmp_path):
    """Create a temporary SQLite database, initialize, and seed data."""
    db_file = tmp_path / "test_voice_service.db"
    conn = sqlite3.connect(db_file)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.executescript(DDL_SCHEMA)
    
    cursor = conn.cursor()
    # Seed data matching Sarah Johnson from spec
    cursor.execute(
        "INSERT INTO customers (id, name, phone, email) VALUES (?, ?, ?, ?);",
        (1, 'Sarah Johnson', '+15551234567', 'sarah.j@example.com')
    )
    cursor.execute(
        "INSERT INTO vehicles (id, customer_id, make, model, year, vin) VALUES (?, ?, ?, ?, ?, ?);",
        (1, 1, 'Honda', 'Civic', 2020, '1HGCR2F8LAA123456')
    )
    cursor.execute(
        "INSERT INTO service_requests (id, customer_id, vehicle_id, service_type, issue_description, status) VALUES (?, ?, ?, ?, ?, ?);",
        (1, 1, 1, 'Brake repair', 'Grinding noise when stopping, brake light on.', 'pending')
    )
    # Seed services
    cursor.execute(
        "INSERT INTO services (name, description, price_range, duration_minutes) VALUES (?, ?, ?, ?);",
        ("AC change", "A/C service", "$150-250", 60)
    )
    cursor.execute(
        "INSERT INTO services (name, description, price_range, duration_minutes) VALUES (?, ?, ?, ?);",
        ("Oil Change", "Oil change service", "$79-119", 45)
    )
    cursor.execute(
        "INSERT INTO services (name, description, price_range, duration_minutes) VALUES (?, ?, ?, ?);",
        ("Brake repair", "Brake service", "$199-450", 90)
    )
    conn.commit()
    
    # We patch the default DB_PATH to use our temp test db file
    with patch("serviceBot.db.connection.DB_PATH", str(db_file)):
        with patch("serviceBot.db.connection._db_initialized", True):
            yield conn
    
    conn.close()

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
    is case-insensitive, and returns None if the service is not found.
    """
    cursor = mock_db.cursor()
    cursor.execute(
        "INSERT INTO services (name, description, price_range, duration_minutes, "
        "req_customer_name, req_phone_number, req_vehicle_details, req_issue_description, req_location) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
        ("Tire Rotation", "Rotate tires", "$20-40", 20, 1, 1, 0, 0, 1)
    )
    mock_db.commit()

    from serviceBot.db.queries import get_service_required_fields
    result = get_service_required_fields("Tire Rotation")
    assert result is not None
    assert result["name"] == "Tire Rotation"
    assert result["req_vehicle_details"] == 0
    assert result["req_location"] == 1

    # Case-insensitive check
    result_lower = get_service_required_fields("tire rotation")
    assert result_lower is not None
    assert result_lower["name"] == "Tire Rotation"

    # Not found check
    result_none = get_service_required_fields("Transmission Flush")
    assert result_none is None

def test_create_service_request_with_time_slot(mock_db):
    from serviceBot.db.queries import create_service_request
    
    # Create a service request with time_slot
    vehicle_details = {"make": "Toyota", "model": "Corolla", "year": 2018}
    sr_id = create_service_request(
        customer_id=1,
        vehicle_details=vehicle_details,
        issue="Squeaking brakes",
        service_type="Brake repair",
        time_slot="Monday afternoon"
    )
    
    # Retrieve it from database and check fields
    cursor = mock_db.cursor()
    cursor.execute("SELECT time_slot, service_type, issue_description FROM service_requests WHERE id = ?;", (sr_id,))
    row = cursor.fetchone()
    assert row is not None
    assert row[0] == "Monday afternoon"
    assert row[1] == "Brake repair"
    assert row[2] == "Squeaking brakes"


def test_book_appointment_updates_service_type_and_prevents_overwrite(mock_db):
    from serviceBot.db.queries import book_appointment, create_callback_request
    
    # Seed available calendar slots
    cursor = mock_db.cursor()
    cursor.execute(
        "INSERT INTO mock_calendar_slots (slot_datetime, is_booked) VALUES (?, ?);",
        ('2026-06-19 09:00:00', 0)
    )
    cursor.execute(
        "INSERT INTO mock_calendar_slots (slot_datetime, is_booked) VALUES (?, ?);",
        ('2026-06-19 10:00:00', 0)
    )
    mock_db.commit()
    
    # 1. Test updating an existing raw pending request (where booking_type IS NULL)
    # The database already has Sarah Johnson (id=1) with a pending service request (id=1, service_type='Brake repair', booking_type=NULL)
    # Book an appointment for AC change. It should reuse request 1 and update its service_type to 'AC change'
    appt_id = book_appointment(
        customer_id=1,
        service_request_id=1,
        appointment_datetime='2026-06-19 09:00:00',
        service_type='AC change'
    )
    assert appt_id == 1
    
    cursor.execute("SELECT service_type, booking_type, booking_time FROM service_requests WHERE id = ?;", (1,))
    row = cursor.fetchone()
    assert row[0] == 'AC change'
    assert row[1] == 'appointment'
    assert row[2] == '2026-06-19 09:00:00'
    
    # 2. Test preventing overwrite:
    # Now Sarah Johnson has a pending request (id=1) but it has booking_type='appointment'.
    # If we call book_appointment without a service_request_id, it should NOT reuse request 1.
    # It should create a new service request and book it.
    new_appt_id = book_appointment(
        customer_id=1,
        service_request_id=None,
        appointment_datetime='2026-06-19 10:00:00',
        service_type='Oil Change'
    )
    assert new_appt_id != 1
    assert new_appt_id is not None
    
    cursor.execute("SELECT service_type, booking_type, booking_time FROM service_requests WHERE id = ?;", (new_appt_id,))
    new_row = cursor.fetchone()
    assert new_row[0] == 'Oil Change'
    assert new_row[1] == 'appointment'
    assert new_row[2] == '2026-06-19 10:00:00'


