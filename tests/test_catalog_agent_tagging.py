import pytest
from fastapi.testclient import TestClient
from serviceBot.main import app
from serviceBot.db.connection import get_db_connection, dict_cursor
from serviceBot.db.seed import seed_db
from serviceBot.db.queries import (
    get_service_agent_ids,
    set_service_agents,
    get_qualified_agent_ids,
)


@pytest.fixture(autouse=True)
def clean_database():
    seed_db(force=True)
    yield


def test_service_agent_tagging_crud():
    """Test setting, retrieving, and updating assigned agent IDs for a catalog service."""
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            # Create a test service
            cursor.execute(
                "INSERT INTO services (name, description, price_range, duration_minutes) VALUES (%s, %s, %s, %s) RETURNING id;",
                ("Test Diagnostic Service", "Deep electrical diagnostics", "$150", 60)
            )
            svc_id = cursor.fetchone()["id"]

            # Fetch staff agents
            cursor.execute("SELECT id FROM staff_agents ORDER BY id ASC LIMIT 3;")
            agents = [r["id"] for r in cursor.fetchall()]
            assert len(agents) >= 2, "Need at least 2 staff agents in seed"
            agent_1, agent_2 = agents[0], agents[1]

    # 1. Untagged initially
    assert get_service_agent_ids(svc_id) == []
    # get_qualified_agent_ids should return empty list or all agents (empty list indicates open to any agent)
    assert get_qualified_agent_ids("Test Diagnostic Service") == []

    # 2. Tag agent_1 and agent_2
    set_service_agents(svc_id, [agent_1, agent_2])
    tagged = get_service_agent_ids(svc_id)
    assert sorted(tagged) == sorted([agent_1, agent_2])

    qualified = get_qualified_agent_ids("Test Diagnostic Service")
    assert sorted(qualified) == sorted([agent_1, agent_2])

    # 3. Update to only agent_2
    set_service_agents(svc_id, [agent_2])
    assert get_service_agent_ids(svc_id) == [agent_2]
    assert get_qualified_agent_ids("Test Diagnostic Service") == [agent_2]

    # 4. Clear all tags (revert to open to any agent)
    set_service_agents(svc_id, [])
    assert get_service_agent_ids(svc_id) == []
    assert get_qualified_agent_ids("Test Diagnostic Service") == []


def test_service_agent_foreign_key_cascade():
    """Test that deleting a staff agent cascades and removes the tag from service_staff_agents."""
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            # Create a service and a temporary agent
            cursor.execute("INSERT INTO staff_agents (name, role, email) VALUES (%s, %s, %s) RETURNING id;", ("Temp Tech", "Mechanic", "temp@cba.com"))
            temp_agent_id = cursor.fetchone()["id"]

            cursor.execute("INSERT INTO services (name, description, duration_minutes) VALUES (%s, %s, %s) RETURNING id;", ("Temp Svc", "Test", 45))
            svc_id = cursor.fetchone()["id"]

    set_service_agents(svc_id, [temp_agent_id])
    assert get_service_agent_ids(svc_id) == [temp_agent_id]

    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("DELETE FROM staff_agents WHERE id = %s;", (temp_agent_id,))

    # Tag should be gone automatically due to ON DELETE CASCADE
    assert get_service_agent_ids(svc_id) == []


def test_portal_api_services_agent_tagging():
    """Test Portal API endpoints GET /services, POST /services, and PUT /services/{id} for agent tags."""
    client = TestClient(app)

    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("SELECT id FROM staff_agents ORDER BY id ASC LIMIT 2;")
            agents = [r["id"] for r in cursor.fetchall()]
            a1, a2 = agents[0], agents[1]

    # 1. POST /services with agent_ids
    new_svc_payload = {
        "name": "Custom Wheel Alignment",
        "description": "Precision laser alignment",
        "price_range": "$120-180",
        "duration_minutes": 60,
        "req_customer_name": True,
        "req_phone_number": True,
        "req_vehicle_details": True,
        "req_issue_description": False,
        "req_location": False,
        "agent_ids": [a1, a2]
    }
    resp = client.post("/api/v1/portal/services", json=new_svc_payload)
    assert resp.status_code == 201, resp.text
    created_id = resp.json()["id"]

    # 2. GET /services should include assigned_agent_ids and assigned_agent_names
    get_resp = client.get("/api/v1/portal/services")
    assert get_resp.status_code == 200
    services = get_resp.json()
    svc_record = next((s for s in services if s["id"] == created_id), None)
    assert svc_record is not None
    assert "assigned_agent_ids" in svc_record
    assert sorted(svc_record["assigned_agent_ids"]) == sorted([a1, a2])
    assert len(svc_record["assigned_agent_names"]) == 2

    # 3. PUT /services/{id} to update agent tags to just a1
    update_payload = dict(new_svc_payload)
    update_payload["agent_ids"] = [a1]
    put_resp = client.put(f"/api/v1/portal/services/{created_id}", json=update_payload)
    assert put_resp.status_code == 200

    # Verify updated tags
    assert get_service_agent_ids(created_id) == [a1]

    # Verify untagged service shows empty list
    untagged_svc = next((s for s in services if s["name"] != "Custom Wheel Alignment"), None)
    if untagged_svc:
        assert isinstance(untagged_svc.get("assigned_agent_ids", []), list)
