"""
Tests for prompt and catalogue synchronization corrections.
Validates business hours and timezone prompt updates, provider sync reporting,
service catalogue freshness, RAG refresh, and prompt isolation.
"""

import json
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from serviceBot.api import portal
from serviceBot.db.connection import get_db_connection, dict_cursor
from serviceBot.main import app
from serviceBot.services.rag import FAQService

client = TestClient(app)


@pytest.fixture
def isolated_env(tmp_path, monkeypatch):
    """Isolates CONFIG_PATH, SYSTEM_PROMPT_PATH, and KB_DIR to temporary directories."""
    config_file = str(tmp_path / "config.json")
    prompt_file = str(tmp_path / "system_prompt.txt")
    kb_dir = str(tmp_path / "kb_documents")
    os.makedirs(kb_dir, exist_ok=True)

    base_dir = os.path.dirname(os.path.dirname(__file__))
    orig_prompt_path = os.path.join(base_dir, "serviceBot", "system_prompt.txt")
    with open(orig_prompt_path, "r", encoding="utf-8") as f:
        prompt_content = f.read()

    initial_config = {
        "business_name": "Acme Auto Care",
        "business_timezone": "America/New_York",
        "business_hours_start": 7,
        "business_hours_end": 18,
        "business_days": [0, 1, 2, 3, 4],
        "min_booking_buffer_hours": 4,
        "min_callback_buffer_hours": 2,
        "system_prompt": prompt_content,
        "first_message": "Hello! Thank you for calling Acme Auto Care.",
    }

    with open(config_file, "w", encoding="utf-8") as f:
        json.dump(initial_config, f, indent=2)

    with open(prompt_file, "w", encoding="utf-8") as f:
        f.write(prompt_content)

    monkeypatch.setattr(portal, "CONFIG_PATH", config_file)
    monkeypatch.setattr(portal, "SYSTEM_PROMPT_PATH", prompt_file)
    monkeypatch.setattr(portal, "KB_DIR", kb_dir)

    return {
        "config_file": config_file,
        "prompt_file": prompt_file,
        "kb_dir": kb_dir,
        "prompt_content": prompt_content,
    }


# ==============================================================================
# 1. Business Hours & Timezone Prompt Updates & Provider Sync Reporting
# ==============================================================================

def test_business_hours_and_timezone_update_all_prompt_sections(isolated_env, monkeypatch):
    """
    Changing business hours, operating days, and timezone via POST /api/v1/portal/config
    updates every applicable prompt section and reports provider sync status cleanly.
    """
    mock_patch = AsyncMock()
    mock_patch.return_value = httpx.Response(status_code=200, json={"status": "ok"})
    monkeypatch.setattr(httpx.AsyncClient, "patch", mock_patch)
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-xi-key")
    monkeypatch.setenv("ELEVENLABS_AGENT_ID", "test-agent-id")

    payload = {
        "business_hours_start": 8,
        "business_hours_end": 17,
        "business_days": [0, 1, 2, 3, 4, 5],  # Mon-Sat
        "business_timezone": "America/Chicago",  # CT
    }

    res = client.post("/api/v1/portal/config", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["saved"] is True
    assert data["provider_sync"]["status"] == "synced"

    # Verify saved prompt in config and file on disk
    cfg = portal.load_config()
    saved_prompt = cfg["system_prompt"]
    with open(isolated_env["prompt_file"], "r", encoding="utf-8") as f:
        disk_prompt = f.read()

    for p in (saved_prompt, disk_prompt):
        # 1. Closing boundary with latest start calculations for 5:00 PM
        assert "conclude by 5:00 PM" in p
        assert "60-minute service: Latest possible start is 4:00 PM (concludes at 5:00 PM)" in p
        assert "90-minute (1.5-hour) service: Latest possible start is 3:30 PM (concludes at 5:00 PM)" in p
        assert "120-minute (2-hour) service: Latest possible start is 3:00 PM (concludes at 5:00 PM)" in p
        assert "service center closes at 5:00 PM" in p
        assert "latest appointment we can begin is 3:30 PM" in p

        # 2. Operating schedule & timezone in constraints and callback
        assert "CT" in p
        assert "closed Sundays" in p
        assert "Monday–Saturday" in p or "Monday-Saturday" in p
        assert "8:00 AM – 5:00 PM CT" in p or "8:00 AM - 5:00 PM CT" in p


def test_business_hours_update_with_missing_credentials_reports_unavailable(isolated_env, monkeypatch):
    """When voice provider credentials are not configured, provider_sync is unavailable."""
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.delenv("ELEVENLABS_AGENT_ID", raising=False)
    monkeypatch.delenv("ELEVENLABS_PRODUCTION_AGENT_ID", raising=False)

    payload = {
        "business_hours_start": 9,
        "business_hours_end": 18,
    }

    res = client.post("/api/v1/portal/config", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["saved"] is True
    assert data["provider_sync"]["status"] == "unavailable"
    assert "not configured" in data["provider_sync"]["message"].lower()

    # The prompt itself is still saved locally
    cfg = portal.load_config()
    assert "conclude by 6:00 PM" in cfg["system_prompt"]


def test_business_hours_update_with_provider_error_reports_failed(isolated_env, monkeypatch):
    """When voice provider rejects the sync, provider_sync reports failed with status code."""
    mock_patch = AsyncMock()
    mock_patch.return_value = httpx.Response(status_code=500, text="Internal Server Error")
    monkeypatch.setattr(httpx.AsyncClient, "patch", mock_patch)
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    monkeypatch.setenv("ELEVENLABS_AGENT_ID", "test-agent")

    payload = {
        "business_hours_start": 8,
        "business_hours_end": 16,
    }

    res = client.post("/api/v1/portal/config", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["saved"] is True
    assert data["provider_sync"]["status"] == "failed"
    assert "500" in data["provider_sync"]["message"]


# ==============================================================================
# 2. Service Catalogue Lifecycle, Freshness & RAG Collision Prevention
# ==============================================================================

def test_service_catalogue_lifecycle_and_freshness(isolated_env):
    """
    Creating, updating, and deleting a service in PostgreSQL immediately updates
    get_service_fields and FAQ lookup, while RAG sync purges obsolete chunks.
    """
    # 1. Create a new service
    create_payload = {
        "name": "Synthetic Hydrostatic Calibration",
        "description": "Complete hydrostatic calibration and safety inspection.",
        "price_range": "$189 - $249",
        "duration_minutes": 75,
        "req_customer_name": True,
        "req_phone_number": True,
        "req_vehicle_details": True,
        "req_issue_description": True,
        "req_location": False,
    }

    create_res = client.post("/api/v1/portal/services", json=create_payload)
    assert create_res.status_code == 201
    service_id = create_res.json()["id"]

    try:
        # Run sync to KB
        portal.sync_services_to_kb()

        # Check sync status endpoint
        sync_status_res = client.get("/api/v1/portal/services/sync-status")
        assert sync_status_res.status_code == 200
        assert sync_status_res.json()["status"] == "synced"

        # Verify get_service_fields returns the fresh record
        tool_res = client.post(
            "/api/v1/voice/tools?name=get_service_fields",
            json={"service_name": "Synthetic Hydrostatic Calibration"}
        )
        assert tool_res.status_code == 200
        result = tool_res.json()["result"]
        assert result["service_found"] is True
        assert result["service_name"] == "Synthetic Hydrostatic Calibration"
        assert result["price_range"] == "$189 - $249"
        assert result["duration_minutes"] == 75

        # Verify FAQ context retrieval contains the new service
        faq_service = FAQService()
        with patch("serviceBot.services.rag.ChatOpenAI") as mock_openai:
            mock_chain = MagicMock()
            mock_resp = MagicMock()
            mock_resp.content = "Synthetic Hydrostatic Calibration costs $189 - $249 and takes 75 minutes."
            mock_chain.invoke.return_value = mock_resp
            with patch("serviceBot.services.rag.ChatPromptTemplate.from_messages", return_value=MagicMock(__or__=lambda self, other: mock_chain)):
                faq_ans = faq_service.answer_question("What is the cost of hydrostatic calibration?")
                assert "189" in faq_ans

        # 2. Update the service (e.g. price change and duration change)
        update_payload = dict(create_payload)
        update_payload["price_range"] = "$219 - $279"
        update_payload["duration_minutes"] = 90
        update_res = client.put(f"/api/v1/portal/services/{service_id}", json=update_payload)
        assert update_res.status_code == 200

        portal.sync_services_to_kb()

        # Verify get_service_fields returns updated values immediately
        tool_res2 = client.post(
            "/api/v1/voice/tools?name=get_service_fields",
            json={"service_name": "Synthetic Hydrostatic Calibration"}
        )
        result2 = tool_res2.json()["result"]
        assert result2["price_range"] == "$219 - $279"
        assert result2["duration_minutes"] == 90

        # 3. Delete the service
        del_res = client.delete(f"/api/v1/portal/services/{service_id}")
        assert del_res.status_code == 200

        portal.sync_services_to_kb()

        # Verify get_service_fields reports service not found
        tool_res3 = client.post(
            "/api/v1/voice/tools?name=get_service_fields",
            json={"service_name": "Synthetic Hydrostatic Calibration"}
        )
        result3 = tool_res3.json()["result"]
        assert result3["service_found"] is False

        # Verify catalog text file no longer contains the deleted service
        catalog_path = os.path.join(isolated_env["kb_dir"], "auto_services_catalog.txt")
        if os.path.exists(catalog_path):
            with open(catalog_path, "r", encoding="utf-8") as f:
                content = f.read()
            assert "Synthetic Hydrostatic Calibration" not in content

    finally:
        # Cleanup in case delete failed
        with get_db_connection() as conn:
            with dict_cursor(conn) as cur:
                cur.execute("DELETE FROM services WHERE id = %s", (service_id,))
            conn.commit()


def test_stale_rag_chunks_do_not_conflict_with_live_catalogue(isolated_env):
    """
    When live database services are queried, stale chunks from auto_services_catalog.txt
    are filtered out so they never conflict with the live database in FAQ lookup.
    """
    mock_collection = MagicMock()
    # Simulate ChromaDB returning stale chunks of an obsolete deleted service
    mock_collection.count.return_value = 2
    mock_collection.query.return_value = {
        "documents": [
            [
                "## Obsolete Deleted Service\nDescription: Stale\nPrice Range: $999\nDuration: 999 minutes",
                "Warranty policy: All work has a 12-month warranty."
            ]
        ],
        "metadatas": [
            [
                {"filename": "auto_services_catalog.txt"},
                {"filename": "warranty.txt"}
            ]
        ]
    }

    faq = FAQService(collection=mock_collection)

    captured_context = []

    with patch("serviceBot.services.rag.ChatOpenAI") as mock_openai:
        mock_chain = MagicMock()
        mock_resp = MagicMock()
        mock_resp.content = "Warranty is 12 months."

        def capture_invoke(input_dict):
            captured_context.append(input_dict["context"])
            return mock_resp

        mock_chain.invoke.side_effect = capture_invoke
        with patch("serviceBot.services.rag.ChatPromptTemplate.from_messages", return_value=MagicMock(__or__=lambda self, other: mock_chain)):
            faq.answer_question("Do you have a warranty?")

    assert len(captured_context) == 1
    ctx = captured_context[0]
    # Stale auto_services_catalog chunk must be stripped
    assert "Obsolete Deleted Service" not in ctx
    assert "$999" not in ctx
    # Non-catalogue knowledge snippet is preserved
    assert "Warranty policy: All work has a 12-month warranty." in ctx
    # Live catalog from database is present
    assert "Actual Available Services (from the live service catalog):" in ctx


# ==============================================================================
# 3. Catalogue Edits Do Not Rewrite Prompt; Business Profile Edits Do
# ==============================================================================

def test_catalogue_mutations_do_not_rewrite_prompt_or_call_sync(isolated_env, monkeypatch):
    """
    Creating, updating, or deleting services does NOT modify system_prompt.txt
    or config.json and does not trigger voice provider prompt synchronization.
    """
    mock_sync = AsyncMock()
    monkeypatch.setattr(portal, "sync_prompt_to_elevenlabs", mock_sync)

    initial_prompt = isolated_env["prompt_content"]

    # 1. Create service
    res = client.post("/api/v1/portal/services", json={
        "name": "Tire Rotation Diagnostic",
        "description": "Rotate 4 tires",
        "price_range": "$50",
        "duration_minutes": 30
    })
    assert res.status_code == 201
    svc_id = res.json()["id"]

    try:
        # Check prompt untouched
        cfg = portal.load_config()
        assert cfg["system_prompt"] == initial_prompt
        with open(isolated_env["prompt_file"], "r", encoding="utf-8") as f:
            assert f.read() == initial_prompt
        mock_sync.assert_not_called()

        # 2. Update service
        res_upd = client.put(f"/api/v1/portal/services/{svc_id}", json={
            "name": "Tire Rotation Diagnostic",
            "description": "Rotate 4 tires and balance",
            "price_range": "$75",
            "duration_minutes": 45
        })
        assert res_upd.status_code == 200

        assert portal.load_config()["system_prompt"] == initial_prompt
        with open(isolated_env["prompt_file"], "r", encoding="utf-8") as f:
            assert f.read() == initial_prompt
        mock_sync.assert_not_called()

        # 3. Delete service
        res_del = client.delete(f"/api/v1/portal/services/{svc_id}")
        assert res_del.status_code == 200

        assert portal.load_config()["system_prompt"] == initial_prompt
        with open(isolated_env["prompt_file"], "r", encoding="utf-8") as f:
            assert f.read() == initial_prompt
        mock_sync.assert_not_called()

    finally:
        with get_db_connection() as conn:
            with dict_cursor(conn) as cur:
                cur.execute("DELETE FROM services WHERE id = %s", (svc_id,))
            conn.commit()


def test_business_profile_with_regenerate_flag_updates_prompt_and_syncs(isolated_env, monkeypatch):
    """
    Changes to prompt-backed business profile values with regenerate_business_prompt: True
    DO rebuild the system prompt and trigger voice provider synchronization.
    """
    mock_sync = AsyncMock()
    mock_sync.return_value = {"status": "synced", "message": "Voice provider instructions synchronized successfully."}
    monkeypatch.setattr(portal, "sync_prompt_to_elevenlabs", mock_sync)

    payload = {
        "business_name": "Zenith Wellness",
        "business_profile": {
            "industry": "Wellness Spa",
            "collect_vehicle_details": False,
            "intake_fields": [
                {"key": "allergies", "detail_type": "general", "label": "Skin allergies", "type": "text", "required": True}
            ]
        },
        "regenerate_business_prompt": True
    }

    res = client.post("/api/v1/portal/config", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["saved"] is True
    assert data["provider_sync"]["status"] == "synced"

    cfg = portal.load_config()
    assert "Zenith Wellness" in cfg["system_prompt"]
    assert "Wellness Spa" in cfg["system_prompt"]
    assert "Skin allergies" in cfg["system_prompt"]
    with open(isolated_env["prompt_file"], "r", encoding="utf-8") as f:
        disk_prompt = f.read()
    assert "Zenith Wellness" in disk_prompt

    mock_sync.assert_called_once()
