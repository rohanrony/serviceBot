import pytest
from fastapi.testclient import TestClient
from serviceBot.main import app
from serviceBot.db.connection import get_db_connection
from serviceBot.db.queries import lookup_customer_by_phone, create_service_request

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_db():
    yield
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM crm_notes WHERE customer_id IN (SELECT id FROM customers WHERE phone LIKE '%5550001111%');")
        cursor.execute("DELETE FROM service_requests WHERE customer_id IN (SELECT id FROM customers WHERE phone LIKE '%5550001111%');")
        cursor.execute("DELETE FROM customers WHERE phone LIKE '%5550001111%';")
        conn.commit()


def test_e164_phone_normalization_and_lookup():
    """
    Verifies that phone numbers in various formats ((555) 000-1111, 5550001111, +15550001111)
    all resolve to the same normalized E.164 customer record (+15550001111).
    """
    # Create customer with raw format
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO customers (name, phone) VALUES (%s, %s) RETURNING id;",
            ("John Smith", "+15550001111")
        )
        c_id = cursor.fetchone()["id"]
        conn.commit()

    # Look up using variations
    lookup1 = lookup_customer_by_phone("(555) 000-1111")
    lookup2 = lookup_customer_by_phone("5550001111")
    lookup3 = lookup_customer_by_phone("+15550001111")

    assert lookup1 is not None and lookup1["customer_id"] == c_id
    assert lookup2 is not None and lookup2["customer_id"] == c_id
    assert lookup3 is not None and lookup3["customer_id"] == c_id


def test_verify_caller_identity_voice_tool():
    """
    Verifies the verify_caller_identity tool endpoint for ElevenLabs voice agent.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO customers (name, phone) VALUES (%s, %s) RETURNING id;",
            ("Alice Smith", "+15550001111")
        )
        c_id = cursor.fetchone()["id"]
        conn.commit()

    # Test matching name
    payload_match = {
        "name": "verify_caller_identity",
        "arguments": {
            "phone": "+15550001111",
            "claimed_name": "Alice Smith"
        }
    }
    res_match = client.post("/api/v1/voice/tools", json=payload_match)
    assert res_match.status_code == 200
    data_match = res_match.json()
    assert data_match["success"] is True
    assert data_match["is_verified_existing_customer"] is True
    assert data_match["customer_name"] == "Alice Smith"

    # Test mismatching name (e.g. household member calling)
    payload_diff = {
        "name": "verify_caller_identity",
        "arguments": {
            "phone": "+15550001111",
            "claimed_name": "Bob Smith"
        }
    }
    res_diff = client.post("/api/v1/voice/tools", json=payload_diff)
    assert res_diff.status_code == 200
    data_diff = res_diff.json()
    assert data_diff["success"] is True
    assert data_diff["is_verified_existing_customer"] is False
    assert "Bob Smith" in data_diff["message"]
