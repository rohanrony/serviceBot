import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from serviceBot.main import app
from serviceBot.db.connection import get_db_connection
from serviceBot.db.queries import lookup_customer_by_phone, update_customer_name

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_db():
    yield
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM crm_notes WHERE customer_id IN (SELECT id FROM customers WHERE phone = '+15557776666');")
        cursor.execute("DELETE FROM service_requests WHERE customer_id IN (SELECT id FROM customers WHERE phone = '+15557776666');")
        cursor.execute("DELETE FROM customers WHERE phone = '+15557776666';")
        conn.commit()


def test_inbound_call_detects_existing_customer_and_appointments():
    """
    Verifies that when a call comes in from a phone number with an existing appointment,
    lookup_customer_by_phone returns active appointments and customer details.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO customers (name, phone) VALUES (%s, %s) RETURNING id;",
            ("Alice Smith", "+15557776666")
        )
        c_id = cursor.fetchone()["id"]
        cursor.execute(
            """
            INSERT INTO service_requests (customer_id, service_type, issue_description, status, booking_type, booking_time)
            VALUES (%s, 'Brake Inspection', 'Squeaking sound', 'pending', 'appointment', '2026-08-01 10:00:00') RETURNING id;
            """,
            (c_id,)
        )
        conn.commit()

    # Verify lookup returns existing customer & active appointment details
    c_data = lookup_customer_by_phone("+15557776666")
    assert c_data is not None
    assert c_data["customer_id"] == c_id
    assert c_data["name"] == "Alice Smith"
    assert c_data["open_sr_id"] is not None
    assert c_data["open_sr_type"] == "Brake Inspection"


def test_customer_name_updates_when_real_name_provided():
    """
    Verifies that if a customer name is updated, the database correctly updates the record.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO customers (name, phone) VALUES (%s, %s) RETURNING id;",
            ("Old Name", "+15557776666")
        )
        c_id = cursor.fetchone()["id"]
        conn.commit()

    # Update name to new name provided during call
    success = update_customer_name(c_id, "New Name")
    assert success is True

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM customers WHERE id = %s;", (c_id,))
        row = cursor.fetchone()
        assert row["name"] == "New Name"
