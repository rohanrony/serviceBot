import pytest
from fastapi.testclient import TestClient

from serviceBot.main import app
from serviceBot.db.connection import get_db_connection, dict_cursor

client = TestClient(app)


def test_create_staff_requires_nonblank_email_and_phone():
    """US6/AC1: Require valid, nonblank email and phone on Add Staff Member."""
    # Blank email
    res1 = client.post("/api/v1/portal/agents", json={
        "name": "Jane Advisor",
        "role": "Service Advisor",
        "email": "",
        "phone_number": "+15551234567",
    })
    assert res1.status_code in (400, 422)

    # Missing email
    res2 = client.post("/api/v1/portal/agents", json={
        "name": "Jane Advisor",
        "role": "Service Advisor",
        "phone_number": "+15551234567",
    })
    assert res2.status_code in (400, 422)

    # Invalid email format
    res3 = client.post("/api/v1/portal/agents", json={
        "name": "Jane Advisor",
        "role": "Service Advisor",
        "email": "not-an-email",
        "phone_number": "+15551234567",
    })
    assert res3.status_code in (400, 422)

    # Blank phone
    res4 = client.post("/api/v1/portal/agents", json={
        "name": "Jane Advisor",
        "role": "Service Advisor",
        "email": "jane@example.com",
        "phone_number": "",
    })
    assert res4.status_code in (400, 422)

    # Missing phone
    res5 = client.post("/api/v1/portal/agents", json={
        "name": "Jane Advisor",
        "role": "Service Advisor",
        "email": "jane@example.com",
    })
    assert res5.status_code in (400, 422)

    # Valid creation succeeds
    res_valid = client.post("/api/v1/portal/agents", json={
        "name": "Jane Advisor",
        "role": "Service Advisor",
        "email": "jane@example.com",
        "phone_number": "+15551234567",
    })
    assert res_valid.status_code == 201
    assert res_valid.json()["success"] is True


def test_update_staff_rejects_clearing_email_or_phone():
    """US6/AC1: Reject clearing email or phone on existing staff profile with 400 Bad Request."""
    # Create valid agent first
    res = client.post("/api/v1/portal/agents", json={
        "name": "Bob Advisor",
        "role": "Service Advisor",
        "email": "bob@example.com",
        "phone_number": "+15552345678",
    })
    agent_id = res.json()["id"]

    # Attempt to clear email with empty string
    res_clear_email = client.put(f"/api/v1/portal/agents/{agent_id}", json={
        "email": "",
    })
    assert res_clear_email.status_code == 400
    assert "email" in res_clear_email.json()["detail"].lower()

    # Attempt to clear email with whitespace
    res_clear_email_ws = client.put(f"/api/v1/portal/agents/{agent_id}", json={
        "email": "   ",
    })
    assert res_clear_email_ws.status_code == 400

    # Attempt to clear phone number
    res_clear_phone = client.put(f"/api/v1/portal/agents/{agent_id}", json={
        "phone_number": "",
    })
    assert res_clear_phone.status_code == 400
    assert "phone" in res_clear_phone.json()["detail"].lower()


def test_update_staff_allows_unrelated_edit_on_legacy_incomplete_record():
    """US6/AC1: Allow updating unrelated fields on legacy profiles with NULL email or phone in DB."""
    # Insert legacy incomplete record directly into DB
    with get_db_connection() as conn, dict_cursor(conn) as cursor:
        cursor.execute("""
            INSERT INTO staff_agents (name, role, email, phone_number, is_active)
            VALUES ('Legacy Incomplete', 'Advisor', NULL, NULL, TRUE)
            RETURNING id;
        """)
        conn.commit()
        legacy_id = cursor.fetchone()["id"]

    # Updating name on this legacy record should succeed without error
    res = client.put(f"/api/v1/portal/agents/{legacy_id}", json={
        "name": "Updated Legacy Agent",
    })
    assert res.status_code == 200
    assert res.json()["success"] is True
    assert res.json()["agent"]["name"] == "Updated Legacy Agent"
