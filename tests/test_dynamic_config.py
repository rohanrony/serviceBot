import pytest
import os
import json
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from serviceBot.main import app
from serviceBot.api.portal import load_config, save_config, sync_services_to_kb
from serviceBot.graph.nodes import service_request_node
from langchain_core.messages import HumanMessage, AIMessage

client = TestClient(app)

@pytest.fixture(autouse=True)
def mock_httpx_patch():
    with patch("httpx.AsyncClient.patch") as mock_patch:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "ok"}
        mock_patch.return_value = mock_response
        yield mock_patch

_in_memory_config = {}

@pytest.fixture(autouse=True)
def mock_config_in_memory(monkeypatch):
    import serviceBot.api.portal as portal_mod
    import serviceBot.graph.nodes as nodes_mod
    import tests.test_dynamic_config as test_mod
    
    # Load the actual config once to populate in-memory
    config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "serviceBot", "config.json")
    if os.path.exists(config_path):
        with open(config_path, "r") as f:
            global _in_memory_config
            _in_memory_config = json.load(f)
            
    def mock_load():
        return _in_memory_config.copy()
        
    def mock_save(new_config):
        global _in_memory_config
        _in_memory_config = new_config.copy()
        
    monkeypatch.setattr(portal_mod, "load_config", mock_load)
    monkeypatch.setattr(portal_mod, "save_config", mock_save)
    monkeypatch.setattr(nodes_mod, "load_config", mock_load)
    monkeypatch.setattr(test_mod, "load_config", mock_load)
    monkeypatch.setattr(test_mod, "save_config", mock_save)
    
    yield

@pytest.fixture(autouse=True)
def clean_services():
    yield
    from serviceBot.db.connection import get_db_connection
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM services WHERE name != 'Oil Change'")
        cursor.execute("SELECT COUNT(*) FROM services WHERE name = 'Oil Change'")
        if cursor.fetchone()[0] == 0:
            cursor.execute(
                "INSERT INTO services (name, description, price_range, duration_minutes, req_customer_name, req_phone_number, req_vehicle_details, req_issue_description, req_location) VALUES (?, ?, ?, ?, 1, 1, 1, 1, 1)",
                ("Oil Change", "Regular oil change with premium motor oil", "$49-69", 30)
            )
        conn.commit()

def test_get_and_post_config():
    response = client.get("/api/v1/portal/config")
    assert response.status_code == 200
    config = response.json()
    assert "required_fields" in config
    assert "prompts" in config
    
    payload = {
        "required_fields": {
            "customer_name": False,
            "phone_number": True,
            "vehicle_details": False,
            "issue_description": True,
            "location": True
        },
        "prompts": {
            "router": "Custom Router Prompt",
            "service_request": "Custom SR Prompt",
            "appointment": "Custom Appt Prompt",
            "faq": "Custom FAQ Prompt",
            "handoff": "Custom Handoff Prompt"
        },
        "first_message": "Hello, Rachel here!"
    }
    
    post_res = client.post("/api/v1/portal/config", json=payload)
    assert post_res.status_code == 200
    
    # Reload and verify
    get_res = client.get("/api/v1/portal/config")
    new_config = get_res.json()
    assert new_config["required_fields"]["customer_name"] is False
    assert new_config["required_fields"]["phone_number"] is True
    assert new_config["prompts"]["router"] == "Custom Router Prompt"
    assert new_config["first_message"] == "Hello, Rachel here!"

def test_dynamic_required_fields_intake():
    # Configure only phone_number and issue_description as required
    payload = {
        "required_fields": {
            "customer_name": False,
            "phone_number": True,
            "vehicle_details": False,
            "issue_description": True,
            "location": False
        },
        "prompts": {
            "router": "Router",
            "service_request": "Service Request Prompt",
            "appointment": "Appt",
            "faq": "FAQ",
            "handoff": "Handoff"
        }
    }
    save_config(payload)
    
    # State containing only phone and issue (no customer name or vehicle details)
    state = {
        "messages": [HumanMessage(content="My engine has a tick.")],
        "customer": {
            "id": 1,
            "name": None,
            "phone": "+15551234567",
            "vehicle_make": None,
            "vehicle_model": None,
            "vehicle_year": None,
            "location": None
        },
        "service_request_id": None,
        "appointment_id": None,
        "current_agent": "service_request"
    }
    
    with patch("serviceBot.graph.nodes.ChatOpenAI") as mock_chat, \
         patch("serviceBot.db.queries.create_service_request") as mock_create:
         
        mock_create.return_value = 101
        mock_instance = mock_chat.return_value
        mock_instance.invoke.return_value = AIMessage(content="Service request generated successfully.")
        
        final_state = service_request_node(state)
        
        # Verify service request was created because name and vehicle details are not required!
        mock_create.assert_called_once()
        assert final_state["service_request_id"] == 101

def test_catalog_deduplication():
    from serviceBot.db.connection import get_db_connection
    with get_db_connection() as conn:
        cursor = conn.cursor()
        # Clean services table first
        cursor.execute("DELETE FROM services")
        # Insert duplicates
        cursor.execute(
            "INSERT INTO services (name, description, price_range, duration_minutes) VALUES (?, ?, ?, ?)",
            ("Tire Rotation", "Rotate tires", "$20-40", 15)
        )
        cursor.execute(
            "INSERT INTO services (name, description, price_range, duration_minutes) VALUES (?, ?, ?, ?)",
            ("Tire Rotation", "Rotate tires duplicate", "$25-45", 20)
        )
        conn.commit()
        
    # GET endpoint should trigger deduplication automatically
    response = client.get("/api/v1/portal/services")
    assert response.status_code == 200
    services = response.json()
    
    # Check that only one "Tire Rotation" exists now
    tire_rotations = [s for s in services if s["name"] == "Tire Rotation"]
    assert len(tire_rotations) == 1
    # Description should match the first inserted one (with lower ID)
    assert tire_rotations[0]["description"] == "Rotate tires"

def test_create_service_duplicate_prevention():
    # Add a service first
    payload = {
        "name": "Spark Plug Replacement",
        "description": "Replace spark plugs",
        "price_range": "$80-120",
        "duration_minutes": 45
    }
    client.post("/api/v1/portal/services", json=payload)
    
    # Try adding the same service again
    response = client.post("/api/v1/portal/services", json=payload)
    assert response.status_code == 400
    assert "already exists" in response.json()["detail"]

def test_service_specific_required_location():
    # Insert a service "Location Test" requiring Location
    payload = {
        "name": "Location Test",
        "description": "Test location requirement",
        "price_range": "$100",
        "duration_minutes": 30,
        "req_customer_name": False,
        "req_phone_number": False,
        "req_vehicle_details": False,
        "req_issue_description": False,
        "req_location": True
    }
    create_res = client.post("/api/v1/portal/services", json=payload)
    assert create_res.status_code == 201
    
    # State matching "Location Test" in conversation but missing customer location
    state = {
        "messages": [HumanMessage(content="I want to book a Location Test")],
        "customer": {
            "id": 1,
            "name": "Sarah",
            "phone": "+15551234567",
            "vehicle_make": "Honda",
            "vehicle_model": "Civic",
            "vehicle_year": 2020,
            "location": None
        },
        "service_request_id": None,
        "appointment_id": None,
        "current_agent": "service_request"
    }
    
    with patch("serviceBot.graph.nodes.ChatOpenAI") as mock_chat, \
         patch("serviceBot.db.queries.create_service_request") as mock_create:
         
        mock_instance = mock_chat.return_value
        mock_instance.invoke.return_value = AIMessage(content="Where are you located? Please specify your location.")
        
        final_state = service_request_node(state)
        
        # Should not create because location is required and missing!
        mock_create.assert_not_called()
        assert final_state["service_request_id"] is None
        assert "location" in final_state["messages"][-1].content

def test_view_kb_file_endpoint():
    KB_DIR = "kb_documents"
    os.makedirs(KB_DIR, exist_ok=True)
    filename = "test_view_doc.txt"
    file_path = os.path.join(KB_DIR, filename)
    with open(file_path, "w") as f:
        f.write("This is a test document in the knowledge base.")
        
    try:
        response = client.get(f"/api/v1/portal/kb/view/{filename}")
        assert response.status_code == 200
        data = response.json()
        assert data["filename"] == filename
        assert "test document" in data["content"]
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)


@patch("httpx.AsyncClient.patch")
@patch.dict(os.environ, {"ELEVENLABS_API_KEY": "test-key-123", "ELEVENLABS_AGENT_ID": "agent-123"})
def test_post_config_syncs_to_elevenlabs(mock_patch):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"status": "ok"}
    mock_patch.return_value = mock_response

    payload = {
        "required_fields": {
            "customer_name": True,
            "phone_number": True,
            "vehicle_details": True,
            "issue_description": True,
            "location": True
        },
        "prompts": {
            "router": "Custom Router Prompt",
            "service_request": "Custom SR Prompt",
            "appointment": "Custom Appt Prompt",
            "faq": "Custom FAQ Prompt",
            "handoff": "Custom Handoff Prompt"
        },
        "first_message": "Hello, I am Rachel!"
    }
    
    response = client.post("/api/v1/portal/config", json=payload)
    assert response.status_code == 200
    
    mock_patch.assert_called_once()
    args, kwargs = mock_patch.call_args
    assert args[0] == "https://api.elevenlabs.io/v1/convai/agents/agent-123"
    assert kwargs["headers"]["xi-api-key"] == "test-key-123"
    assert "conversation_config" in kwargs["json"]
    assert "prompt" in kwargs["json"]["conversation_config"]["agent"]
    prompt_text = kwargs["json"]["conversation_config"]["agent"]["prompt"]["prompt"]
    assert "Custom Router Prompt" in prompt_text
    assert "Custom SR Prompt" in prompt_text
    assert kwargs["json"]["conversation_config"]["agent"]["first_message"] == "Hello, I am Rachel!"

