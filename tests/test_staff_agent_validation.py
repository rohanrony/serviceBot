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


@pytest.mark.parametrize("email", ["jane@@example.com", "@example.com", "jane@example.com other", "jane..doe@example.com", "jane@example"])
def test_malformed_staff_email_is_rejected_on_create_and_update(email):
    """Review Finding 2: Reject malformed staff emails consistently before persistence."""
    # 1. Create rejection
    res_create = client.post("/api/v1/portal/agents", json={
        "name": "Invalid Email Agent",
        "role": "Advisor",
        "email": email,
        "phone_number": "+15550100077"
    })
    assert res_create.status_code in (400, 422), "Malformed staff email must be rejected before persistence"
    with get_db_connection() as conn, dict_cursor(conn) as cursor:
        cursor.execute("SELECT id FROM staff_agents WHERE name = %s;", ("Invalid Email Agent",))
        assert cursor.fetchone() is None, "Rejected creation must not insert a staff record"

    # 2. Setup a valid agent for update test
    res_valid = client.post("/api/v1/portal/agents", json={
        "name": "Valid Email Agent",
        "role": "Advisor",
        "email": "valid.staff@example.com",
        "phone_number": "+15550100088"
    })
    assert res_valid.status_code == 201
    agent_id = res_valid.json()["id"]

    # 3. Update rejection
    res_update = client.put(f"/api/v1/portal/agents/{agent_id}", json={
        "email": email
    })
    assert res_update.status_code in (400, 422), "Malformed email update must be rejected"
    with get_db_connection() as conn, dict_cursor(conn) as cursor:
        cursor.execute("SELECT email FROM staff_agents WHERE id = %s;", (agent_id,))
        row = cursor.fetchone()
        assert row["email"] == "valid.staff@example.com", "Rejected update must preserve original email"


def test_staff_email_trims_whitespace_and_stores_cleanly():
    """Review Finding 2: Valid email with surrounding whitespace is accepted and stored cleanly."""
    res_create = client.post("/api/v1/portal/agents", json={
        "name": "Whitespace Agent",
        "role": "Advisor",
        "email": "   whitespace.agent@example.com   ",
        "phone_number": "+15550100099"
    })
    assert res_create.status_code == 201
    agent_id = res_create.json()["id"]

    with get_db_connection() as conn, dict_cursor(conn) as cursor:
        cursor.execute("SELECT email FROM staff_agents WHERE id = %s;", (agent_id,))
        row = cursor.fetchone()
        assert row["email"] == "whitespace.agent@example.com", "Surrounding whitespace must be trimmed on creation"

    res_update = client.put(f"/api/v1/portal/agents/{agent_id}", json={
        "email": "   updated.whitespace@example.com   "
    })
    assert res_update.status_code == 200
    with get_db_connection() as conn, dict_cursor(conn) as cursor:
        cursor.execute("SELECT email FROM staff_agents WHERE id = %s;", (agent_id,))
        row = cursor.fetchone()
        assert row["email"] == "updated.whitespace@example.com", "Surrounding whitespace must be trimmed on update"
