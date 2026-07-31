import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

# We'll import app from app.main
from serviceBot.main import app

client = TestClient(app)

@patch("httpx.AsyncClient.get")
def test_get_elevenlabs_voices_success(mock_get):
    # Mock Response from ElevenLabs API
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "voices": [
            {"voice_id": "voice_1", "name": "Rachel", "category": "premade", "preview_url": "http://rachel.mp3"},
            {"voice_id": "voice_2", "name": "Clyde", "category": "premade", "preview_url": "http://clyde.mp3"}
        ]
    }
    mock_get.return_value = mock_response

    response = client.get("/api/v1/portal/elevenlabs/voices")
    
    assert response.status_code == 200
    data = response.json()
    assert "voices" in data
    assert len(data["voices"]) == 2
    assert data["voices"][0]["voice_id"] == "voice_1"
    assert data["voices"][0]["name"] == "Rachel"

@patch("httpx.AsyncClient.patch")
def test_update_elevenlabs_agent_success(mock_patch):
    # Mock response from ElevenLabs API
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"status": "ok"}
    mock_patch.return_value = mock_response

    payload = {
        "voice_id": "voice_1",
        "model": "gpt-4o"
      }
    
    response = client.patch("/api/v1/portal/elevenlabs/agent", json=payload)
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True

def test_get_services_endpoint():
    response = client.get("/api/v1/portal/services")
    assert response.status_code == 200
    services = response.json()
    assert isinstance(services, list)
    assert len(services) > 0

def test_seed_default_services_endpoint():
    response = client.post("/api/v1/portal/services/seed-defaults")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "inserted_count" in data
    assert data["total_defaults"] == 33

def test_create_service_endpoint():
    payload = {
        "name": "Brake Repair",
        "description": "Front/Rear brake pad and rotor replacement",
        "price_range": "$150-400",
        "duration_minutes": 90
    }
    response = client.post("/api/v1/portal/services", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["success"] is True
    assert data["id"] is not None

def test_update_service_endpoint():
    # First create a service
    create_payload = {
        "name": "Spark Plug Replacement",
        "description": "Replace engine spark plugs",
        "price_range": "$80-150",
        "duration_minutes": 45
    }
    create_response = client.post("/api/v1/portal/services", json=create_payload)
    assert create_response.status_code == 201
    service_id = create_response.json()["id"]

    # Now update it
    update_payload = {
        "name": "Spark Plug Replacement (Platinum)",
        "description": "Replace engine spark plugs with platinum ones",
        "price_range": "$120-200",
        "duration_minutes": 60
    }
    update_response = client.put(f"/api/v1/portal/services/{service_id}", json=update_payload)
    assert update_response.status_code == 200
    update_data = update_response.json()
    assert update_data["success"] is True
    assert update_data["id"] == service_id

    # Get services and verify updated details
    get_response = client.get("/api/v1/portal/services")
    assert get_response.status_code == 200
    services = get_response.json()
    updated_svc = next((s for s in services if s["id"] == service_id), None)
    assert updated_svc is not None
    assert updated_svc["name"] == "Spark Plug Replacement (Platinum)"
    assert updated_svc["description"] == "Replace engine spark plugs with platinum ones"
    assert updated_svc["price_range"] == "$120-200"
    assert updated_svc["duration_minutes"] == 60

def test_update_service_not_found():
    payload = {
        "name": "Non-existent Service",
        "description": "Does not exist",
        "price_range": "$100",
        "duration_minutes": 30
    }
    response = client.put("/api/v1/portal/services/99999", json=payload)
    assert response.status_code == 404
    assert response.json()["detail"] == "Service not found"

def test_delete_service_endpoint():
    # First create a service
    create_payload = {
        "name": "Cabin Air Filter Replacement",
        "description": "Replace cabin air filter",
        "price_range": "$30-50",
        "duration_minutes": 15
    }
    create_response = client.post("/api/v1/portal/services", json=create_payload)
    assert create_response.status_code == 201
    service_id = create_response.json()["id"]

    # Delete it
    delete_response = client.delete(f"/api/v1/portal/services/{service_id}")
    assert delete_response.status_code == 200
    assert delete_response.json()["success"] is True

    # Verify it's no longer returned in get
    get_response = client.get("/api/v1/portal/services")
    services = get_response.json()
    assert not any(s["id"] == service_id for s in services)

def test_delete_service_not_found():
    response = client.delete("/api/v1/portal/services/99999")
    assert response.status_code == 404
    assert response.json()["detail"] == "Service not found"

def test_api_key_encryption_decryption():
    from serviceBot.services.encryption import encrypt_key, decrypt_key
    
    raw_key = "sk-elevenlabs-test-12345"
    encrypted = encrypt_key(raw_key)
    
    assert encrypted != raw_key
    assert raw_key not in encrypted
    
    decrypted = decrypt_key(encrypted)
    assert decrypted == raw_key

def test_get_calls_endpoint():
    response = client.get("/api/v1/portal/calls")
    assert response.status_code == 200
    calls = response.json()
    assert isinstance(calls, list)
    if calls:
        for call in calls:
            assert "vehicle" in call

@patch("serviceBot.services.rag.FAQService.index_text")
def test_kb_upload_endpoint(mock_index_text):
    mock_index_text.return_value = 5
    # Send a mock text file
    file_content = b"Mock auto pricing guidelines. Oil change is $50. Brake repair is $150."
    response = client.post(
        "/api/v1/portal/kb/upload",
        files={"file": ("test_pricing.txt", file_content, "text/plain")}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["chunk_count"] == 5

@patch("serviceBot.services.rag.FAQService.index_text")
@patch("serviceBot.services.rag.FAQService.delete_file")
def test_kb_upload_list_download_delete_flow(mock_delete_file, mock_index_text):
    mock_index_text.return_value = 3
    mock_delete_file.return_value = None
    
    # Setup test file
    filename = "test_manual_kb.txt"
    file_content = b"Some mock content about Test guidelines."
    
    # 1. Upload
    response = client.post(
        "/api/v1/portal/kb/upload",
        files={"file": (filename, file_content, "text/plain")}
    )
    assert response.status_code == 200
    assert response.json()["success"] is True
    
    # 2. List
    list_response = client.get("/api/v1/portal/kb")
    assert list_response.status_code == 200
    files = list_response.json()
    assert any(f["filename"] == filename for f in files)
    
    # 3. Download
    download_response = client.get(f"/api/v1/portal/kb/download/{filename}")
    assert download_response.status_code == 200
    assert download_response.content == file_content
    
    # 4. Delete
    delete_response = client.delete(f"/api/v1/portal/kb/{filename}")
    assert delete_response.status_code == 200
    assert delete_response.json()["success"] is True
    
    # Verify deleted from directory
    get_response = client.get("/api/v1/portal/kb")
    files_after = get_response.json()
    assert not any(f["filename"] == filename for f in files_after)

def test_kb_download_not_found():
    response = client.get("/api/v1/portal/kb/download/nonexistent.txt")
    assert response.status_code == 404

def test_kb_delete_not_found():
    response = client.delete("/api/v1/portal/kb/nonexistent.txt")
    assert response.status_code == 404

def test_get_appointments_endpoint():
    response = client.get("/api/v1/portal/appointments")
    assert response.status_code == 200
    appointments = response.json()
    assert isinstance(appointments, list)

def test_get_service_requests_endpoint():
    response = client.get("/api/v1/portal/service-requests")
    assert response.status_code == 200
    requests = response.json()
    assert isinstance(requests, list)
    if requests:
        first = requests[0]
        assert "duration_minutes" in first
        assert "booking_start_time" in first
        assert "booking_end_time" in first

def test_get_stats_endpoint():
    response = client.get("/api/v1/portal/stats")
    assert response.status_code == 200
    stats = response.json()
    assert "total_calls" in stats
    assert "total_appointments" in stats
    assert "total_requests" in stats
    assert "pending_requests" in stats
    assert "open_slots" in stats
    assert "total_callbacks" in stats
    assert stats.get("timeframe") == "7d"

    # Test timeframe parameters
    for tf in ["24h", "7d", "30d", "all"]:
        tf_resp = client.get(f"/api/v1/portal/stats?calls_timeframe={tf}")
        assert tf_resp.status_code == 200
        tf_data = tf_resp.json()
        assert "total_calls" in tf_data
        assert tf_data.get("timeframe") == tf


def test_update_service_request_status_endpoint():
    # 1. Fetch existing requests
    res = client.get("/api/v1/portal/service-requests")
    assert res.status_code == 200
    reqs = res.json()
    if reqs:
        req_id = reqs[0]["id"]
        # Update status to completed
        patch_res = client.patch(f"/api/v1/portal/service-requests/{req_id}/status", json={"status": "completed"})
        assert patch_res.status_code == 200
        data = patch_res.json()
        assert data["success"] is True
        assert data["data"]["status"] == "completed"

        # Update status to rescheduled
        resched_res = client.patch(f"/api/v1/portal/service-requests/{req_id}/status", json={"status": "rescheduled"})
        assert resched_res.status_code == 200
        assert resched_res.json()["data"]["status"] == "rescheduled"

        # Update status to cancelled
        cancel_res = client.patch(f"/api/v1/portal/service-requests/{req_id}/status", json={"status": "cancelled"})
        assert cancel_res.status_code == 200
        assert cancel_res.json()["data"]["status"] == "cancelled"

        # Update back to pending
        patch_res_2 = client.patch(f"/api/v1/portal/service-requests/{req_id}/status", json={"status": "pending"})
        assert patch_res_2.status_code == 200
        assert patch_res_2.json()["data"]["status"] == "pending"


def test_get_calls_and_service_requests_pagination():
    res_calls = client.get("/api/v1/portal/calls?limit=2&offset=0")
    assert res_calls.status_code == 200
    assert isinstance(res_calls.json(), list)
    assert len(res_calls.json()) <= 2

    res_reqs = client.get("/api/v1/portal/service-requests?limit=2&offset=0")
    assert res_reqs.status_code == 200
    assert isinstance(res_reqs.json(), list)
    assert len(res_reqs.json()) <= 2


def test_agent_availability_and_assignment_endpoints():
    res = client.get("/api/v1/portal/service-requests")
    assert res.status_code == 200
    reqs = res.json()
    if reqs:
        req_id = reqs[0]["id"]
        
        # Test available agents endpoint
        avail_res = client.get(f"/api/v1/portal/service-requests/{req_id}/available-agents")
        assert avail_res.status_code == 200
        avail_data = avail_res.json()
        assert avail_data["success"] is True
        assert "agents" in avail_data
        assert isinstance(avail_data["agents"], list)

        # Test assign agent endpoint
        if avail_data["agents"]:
            target_agent_id = avail_data["agents"][0]["id"]
            assign_res = client.patch(f"/api/v1/portal/service-requests/{req_id}/assign-agent", json={"staff_agent_id": target_agent_id})
            assert assign_res.status_code == 200
            assert assign_res.json()["success"] is True
            assert assign_res.json()["data"]["staff_agent_id"] == target_agent_id

            # Verify in service requests list
            verify_res = client.get("/api/v1/portal/service-requests")
            assert verify_res.status_code == 200
            matched = [r for r in verify_res.json() if r["id"] == req_id]
            if matched:
                assert matched[0]["staff_agent_id"] == target_agent_id


def test_cannot_assign_agent_for_completed_service_request():
    from serviceBot.db.connection import get_db_connection, dict_cursor
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("INSERT INTO customers (name, phone) VALUES ('Completed Cust', '555-9999') RETURNING id;")
            cust_id = cursor.fetchone()["id"]
            cursor.execute("INSERT INTO staff_agents (name, role) VALUES ('Target Agent', 'Tech') RETURNING id;")
            agent_id = cursor.fetchone()["id"]
            cursor.execute("INSERT INTO service_requests (customer_id, status, booking_type) VALUES (%s, 'completed', 'appointment') RETURNING id;", (cust_id,))
            req_id1 = cursor.fetchone()["id"]
            cursor.execute("INSERT INTO service_requests (customer_id, status, booking_type) VALUES (%s, 'cancelled', 'appointment') RETURNING id;", (cust_id,))
            req_id2 = cursor.fetchone()["id"]

    res1 = client.patch(f"/api/v1/portal/service-requests/{req_id1}/assign-agent", json={"staff_agent_id": agent_id})
    assert res1.status_code == 400

    res2 = client.patch(f"/api/v1/portal/service-requests/{req_id2}/assign-agent", json={"staff_agent_id": agent_id})
    assert res2.status_code == 400


def test_agent_switch_triggers_slot_invite_and_admin_mail():
    from serviceBot.db.queries import assign_staff_agent_to_service_request
    from serviceBot.db.connection import get_db_connection, dict_cursor

    # Setup database records for testing reassign logic
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("INSERT INTO customers (name, phone) VALUES ('Test Reassign Cust', '555-0199') RETURNING id;")
            cust_id = cursor.fetchone()["id"]

            cursor.execute("INSERT INTO staff_agents (name, role, email) VALUES ('Old Agent', 'Mechanic', 'oldagent@example.com') RETURNING id;")
            agent1_id = cursor.fetchone()["id"]

            cursor.execute("INSERT INTO staff_agents (name, role, email) VALUES ('New Agent', 'Mechanic', 'newagent@example.com') RETURNING id;")
            agent2_id = cursor.fetchone()["id"]

            slot_time = "2026-08-01 10:00:00"
            cursor.execute("INSERT INTO mock_calendar_slots (slot_datetime, is_booked, staff_agent_id) VALUES (CAST(%s AS TIMESTAMP), TRUE, %s);", (slot_time, agent1_id))
            cursor.execute("INSERT INTO mock_calendar_slots (slot_datetime, is_booked, staff_agent_id) VALUES (CAST(%s AS TIMESTAMP), FALSE, %s);", (slot_time, agent2_id))

            cursor.execute("""
                INSERT INTO service_requests (customer_id, service_type, booking_type, booking_time, staff_agent_id, status)
                VALUES (%s, 'Brake Service', 'appointment', %s, %s, 'pending') RETURNING id;
            """, (cust_id, slot_time, agent1_id))
            sr_id = cursor.fetchone()["id"]

    # Reassign service request from agent1 to agent2
    res = assign_staff_agent_to_service_request(sr_id, agent2_id)
    assert res["staff_agent_id"] == agent2_id

    # Verify mock slots updated
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("SELECT is_booked FROM mock_calendar_slots WHERE staff_agent_id = %s AND slot_datetime = CAST(%s AS TIMESTAMP);", (agent1_id, slot_time))
            a1_slot = cursor.fetchone()
            assert a1_slot["is_booked"] is False

            cursor.execute("SELECT is_booked FROM mock_calendar_slots WHERE staff_agent_id = %s AND slot_datetime = CAST(%s AS TIMESTAMP);", (agent2_id, slot_time))
            a2_slot = cursor.fetchone()
            assert a2_slot["is_booked"] is True






