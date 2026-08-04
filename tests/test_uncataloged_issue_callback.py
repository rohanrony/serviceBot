import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from serviceBot.main import app
from serviceBot.db.queries import (
    create_service_request,
    find_pending_callback_by_phone,
    create_dual_intake_request,
    lookup_customer_by_phone,
)
from serviceBot.db.connection import get_db_connection, dict_cursor



def test_create_uncataloged_issue_callback():
    """Test creating a standalone uncataloged issue callback request in the database."""
    print("--> STEP 1: BEFORE CUSTOMER INSERT")
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                "INSERT INTO customers (name, phone) VALUES (%s, %s) ON CONFLICT (phone) DO UPDATE SET name = EXCLUDED.name RETURNING id;",
                ("John Custom", "555-999-8888")
            )
            c_id = cursor.fetchone()["id"]
            conn.commit()
    print(f"--> STEP 2: AFTER CUSTOMER INSERT c_id={c_id}")

    sr_id = create_service_request(
        customer_id=c_id,
        vehicle_details={"make": "Mustang", "model": "Fastback", "year": 1968},
        issue="Custom carburetor tuning and exhaust headers check",
        service_type="Custom Tuning",
        booking_type="callback",
        booking_time="2026-06-25 10:00:00",
        is_uncataloged=True,
        callback_priority="high",
        callback_number="555-999-8888"
    )
    print(f"--> STEP 3: AFTER CREATE_SERVICE_REQUEST sr_id={sr_id}")

    assert sr_id is not None
    assert sr_id > 0

    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("SELECT * FROM service_requests WHERE id = %s;", (sr_id,))
            row = cursor.fetchone()
            assert row["is_uncataloged"] is True
            assert row["booking_type"] == "callback"
            assert row["callback_priority"] == "high"
            assert row["callback_number"] == "555-999-8888"


def test_create_dual_intake_request():
    """Test creating a dual-intake request (catalog appointment + linked uncataloged callback)."""
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                "INSERT INTO customers (name, phone) VALUES (%s, %s) ON CONFLICT (phone) DO UPDATE SET name = EXCLUDED.name RETURNING id;",
                ("Sarah Dual", "555-888-7777")
            )
            c_id = cursor.fetchone()["id"]
            conn.commit()

    res = create_dual_intake_request(
        customer_id=c_id,
        vehicle_details={"make": "Honda", "model": "Civic", "year": 2020},
        catalog_issue="Synthetic Oil Change",
        uncataloged_issue="Unexplained metallic clunking when turning left",
        service_type="Oil Change & Inspection",
        time_slot="2026-08-10 14:00:00",
        booking_time="2026-08-10 14:00:00",
        callback_priority="medium"
    )

    apt_id = res["appointment_id"]
    cb_id = res["callback_id"]

    assert apt_id is not None
    assert cb_id is not None
    assert apt_id != cb_id

    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("SELECT * FROM service_requests WHERE id = %s;", (apt_id,))
            apt_row = cursor.fetchone()
            assert apt_row["booking_type"] == "appointment"
            assert apt_row["is_uncataloged"] is False

            cursor.execute("SELECT * FROM service_requests WHERE id = %s;", (cb_id,))
            cb_row = cursor.fetchone()
            assert cb_row["booking_type"] == "appointment_and_callback"
            assert cb_row["is_uncataloged"] is True
            assert cb_row["linked_appointment_id"] == apt_id


def test_find_pending_callback_by_phone():
    """Test finding an existing pending callback request by customer phone to prevent duplicates."""
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                "INSERT INTO customers (name, phone) VALUES (%s, %s) ON CONFLICT (phone) DO UPDATE SET name = EXCLUDED.name RETURNING id;",
                ("Repeat Caller", "555-777-6666")
            )
            c_id = cursor.fetchone()["id"]
            conn.commit()

    # Create a pending callback
    sr_id = create_service_request(
        customer_id=c_id,
        vehicle_details={"make": "Toyota", "model": "Camry", "year": 2018},
        issue="Dashboard rattle investigation",
        service_type="Diagnostic",
        booking_type="callback",
        booking_time="2026-06-25 10:00:00",
        is_uncataloged=True
    )

    pending_cb = find_pending_callback_by_phone("555-777-6666")
    assert pending_cb is not None
    assert pending_cb["id"] == sr_id
    assert "Dashboard rattle" in pending_cb["issue_description"]


@patch("serviceBot.api.telephony.lookup_customer_by_phone")
@patch("serviceBot.api.telephony.create_service_request")
def test_voice_tools_create_uncataloged_callback_endpoint(mock_create, mock_lookup):
    """Test telephony tool endpoint handling uncataloged issue callback."""
    mock_lookup.return_value = {"customer_id": 99}
    mock_create.return_value = 201

    payload = {
        "tool_call_id": "call_uncataloged_1",
        "name": "create_service_request",
        "arguments": {
            "customer_name": "John Custom",
            "phone": "555-999-8888",
            "make": "Mustang",
            "model": "Fastback",
            "year": 1968,
            "issue_description": "Custom carburetor tuning and headers check",
            "booking_type": "callback",
            "is_uncataloged": True,
        }
    }
    client = TestClient(app)
    response = client.post("/api/v1/voice/tools", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["tool_call_id"] == "call_uncataloged_1"
    assert data["result"]["success"] is True
    assert data["result"]["service_request_id"] == 201
    assert data["result"]["is_uncataloged"] is True
