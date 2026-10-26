"""
Tests for prompt and catalogue synchronization corrections.
Validates business hours and timezone prompt updates, provider sync reporting,
service catalogue freshness, RAG refresh, and prompt isolation.
"""

import asyncio
import json
import os
import tempfile
from contextlib import contextmanager
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


# ==============================================================================
# 13. Regression Test 1: Serialize Provider Publication (Req 1)
# ==============================================================================

def test_publication_boundary_serializes_updates_and_prevents_stale_remote(isolated_env, monkeypatch):
    """
    Test provider publication serialization across concurrent and delayed requests:
    1. Concurrent / Overlapping: Task 1 (older) PATCH is slow (0.05s). Task 2 (newer)
       waits at the publication boundary, then executes. Assert final remote content
       is the newest prompt (Prompt 2), and remote is never left with Prompt 1.
    2. Delayed older request: When a newer update (Gen 2) has already been published,
       an older request (Gen 1) entering the boundary checks published_generation,
       skips PATCH entirely, and reports superseded.
    """
    import asyncio

    agent_id = "test-agent-serialize-001"
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key-pub")
    monkeypatch.setenv("ELEVENLABS_AGENT_ID", agent_id)
    monkeypatch.delenv("ELEVENLABS_PRODUCTION_AGENT_ID", raising=False)

    remote_agent_state = {"prompt": None, "call_count": 0}

    async def mock_patch(client_self, url, json=None, **kwargs):
        nonlocal remote_agent_state
        prompt_in_payload = json.get("conversation_config", {}).get("agent", {}).get("prompt", {}).get("prompt")

        # Older update takes 0.05s to simulate network latency
        if "Prompt Generation 1 (Old)" in (prompt_in_payload or ""):
            await asyncio.sleep(0.05)
            remote_agent_state["prompt"] = prompt_in_payload
            remote_agent_state["call_count"] += 1
            return httpx.Response(status_code=200, json={"status": "ok"})
        else:
            # Newer update completes
            remote_agent_state["prompt"] = prompt_in_payload
            remote_agent_state["call_count"] += 1
            return httpx.Response(status_code=200, json={"status": "ok"})

    monkeypatch.setattr(httpx.AsyncClient, "patch", mock_patch)

    async def run_scenario_concurrent():
        # Setup initial config
        cfg = portal.load_config()
        cfg["system_prompt"] = "Prompt Generation 1 (Old)"
        cfg["prompt_generation"] = 1
        portal.save_config(cfg)

        async def run_old():
            return await portal.sync_prompt_to_elevenlabs("Prompt Generation 1 (Old)", generation=1)

        async def run_new():
            await asyncio.sleep(0.01)  # Start slightly after old so old enters boundary first
            cfg = portal.load_config()
            cfg["system_prompt"] = "Prompt Generation 2 (Newest)"
            cfg["prompt_generation"] = 2
            portal.save_config(cfg)
            return await portal.sync_prompt_to_elevenlabs("Prompt Generation 2 (Newest)", generation=2)

        res1, res2 = await asyncio.gather(run_old(), run_new())

        # Assert final simulated remote content is the newest prompt
        assert "Prompt Generation 2 (Newest)" in remote_agent_state["prompt"]
        assert res2["status"] == "synced"
        assert res2["generation"] == 2

    async def run_scenario_delayed():
        # Reset remote state
        remote_agent_state["prompt"] = None
        remote_agent_state["call_count"] = 0

        # Newer update completes first
        cfg = portal.load_config()
        cfg["system_prompt"] = "Prompt Generation 2 (Newest)"
        cfg["prompt_generation"] = 2
        portal.save_config(cfg)
        res2 = await portal.sync_prompt_to_elevenlabs("Prompt Generation 2 (Newest)", generation=2)
        assert res2["status"] == "synced"
        assert "Prompt Generation 2 (Newest)" in remote_agent_state["prompt"]
        assert remote_agent_state["call_count"] == 1

        # Now delayed older PATCH attempts to run for generation 1
        res1 = await portal.sync_prompt_to_elevenlabs("Prompt Generation 1 (Old)", generation=1)
        assert res1["status"] == "superseded"
        # Remote agent prompt must still be the newest prompt and NOT overwritten!
        assert "Prompt Generation 2 (Newest)" in remote_agent_state["prompt"]
        assert remote_agent_state["call_count"] == 1  # No extra PATCH sent!

    asyncio.run(run_scenario_concurrent())
    asyncio.run(run_scenario_delayed())


# ==============================================================================
# 14. Regression Test 2: Authoritative JSON Persistence & Migration (Req 2)
# ==============================================================================

def test_authoritative_config_persistence_and_stale_export_protection(isolated_env, monkeypatch):
    """
    1. Failed authoritative persistence (config.json) leaves effective settings unchanged.
    2. Failed compatibility export (system_prompt.txt) cannot cause later loads to restore stale instructions.
    """
    # 1. Authoritative write failure leaves effective settings unchanged
    initial_cfg = portal.load_config()
    orig_prompt = initial_cfg.get("system_prompt")

    orig_atomic_write = portal._atomic_write_file
    def mock_atomic_write_fail(filepath, content):
        if filepath.endswith("config.json"):
            raise IOError("Simulated disk error writing config.json")
        orig_atomic_write(filepath, content)

    bad_cfg = dict(initial_cfg)
    bad_cfg["system_prompt"] = "Corrupted Prompt That Should Fail"
    with monkeypatch.context() as write_failure:
        write_failure.setattr(portal, "_atomic_write_file", mock_atomic_write_fail)
        with pytest.raises(IOError, match="Simulated disk error writing config.json"):
            portal.save_config(bad_cfg)

    # Effective settings remain unchanged
    assert portal.CONFIG_PATH == isolated_env["config_file"]
    assert portal.SYSTEM_PROMPT_PATH == isolated_env["prompt_file"]
    loaded_cfg = portal.load_config()
    assert loaded_cfg.get("system_prompt") == orig_prompt

    # 2. Failed compatibility export cannot cause later loads to restore stale instructions
    new_authoritative_prompt = "Authoritative New System Prompt 2026"
    test_cfg = portal.load_config()
    test_cfg["system_prompt"] = new_authoritative_prompt
    portal.save_config(test_cfg)

    # Intentionally write stale instructions into system_prompt.txt
    stale_text = "Stale Legacy system_prompt.txt Content"
    with open(isolated_env["prompt_file"], "w", encoding="utf-8") as f:
        f.write(stale_text)

    # Loading configuration must read from authoritative JSON and NOT restore stale text
    reloaded_cfg = portal.load_config()
    assert reloaded_cfg["system_prompt"] == new_authoritative_prompt
    assert stale_text not in reloaded_cfg["system_prompt"]


# ==============================================================================
# 15. Regression Test 3: Preserve Ambiguous Custom Instructions (Req 3)
# ==============================================================================

def test_preserve_ambiguous_custom_instructions_with_warning():
    """
    Business hours: Mon-Fri 7am-6pm ET. Never request credit card numbers.
    Saving hours must retain the second sentence without an expanding list of punctuation rules.
    """
    from serviceBot.services.prompt_service import update_prompt_business_hours

    prompt = (
        "You are Rachel, AI voice assistant.\n"
        "Business hours: Mon-Fri 7am-6pm ET. Never request credit card numbers.\n"
        "Always be courteous."
    )

    updated = update_prompt_business_hours(
        prompt,
        start_hour=8,
        end_hour=17,
        business_days=[0, 1, 2, 3, 4],
        timezone_str="America/New_York"
    )

    # Must preserve the second sentence
    assert "Never request credit card numbers." in updated
    assert "8:00 AM - 5:00 PM ET" in updated
    assert hasattr(update_prompt_business_hours, "unsynchronized_schedules")
    assert any("Never request credit card numbers." in s for s in update_prompt_business_hours.unsynchronized_schedules)


# ==============================================================================
# 16. Regression Test 4: Unsafe FAQ Fallback Simplification (Req 4)
# ==============================================================================

def test_rag_fallback_does_not_return_stale_duration_for_deleted_service(isolated_env, monkeypatch):
    """
    'How long does balayage take?' must not return an old uploaded duration for a deleted service,
    including during database failure. Preserve working non-catalogue FAQ behavior during normal model operation.
    """
    from serviceBot.services.rag import FAQService

    mock_collection = MagicMock()
    mock_collection.count.return_value = 1
    mock_collection.query.return_value = {
        "documents": [["Balayage hair coloring takes 3 hours and costs $250."]],
        "metadatas": [[{"filename": "salon_hair_treatment_guide.pdf"}]]
    }

    service = FAQService(collection=mock_collection)

    # 1. Database is available, but 'balayage' is deleted / not in catalog
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_cur.__enter__.return_value = mock_cur
    mock_cur.fetchall.return_value = [
        {"name": "Standard Haircut", "description": "Quick trim", "price_range": "$40", "duration_minutes": 30}
    ]
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur
    mock_conn.__enter__.return_value = mock_conn

    def mock_invoke_fail(*args, **kwargs):
        raise RuntimeError("OpenAI rate limit or outage")

    monkeypatch.setattr("langchain_core.runnables.base.RunnableSequence.invoke", mock_invoke_fail)
    monkeypatch.setattr("serviceBot.db.connection.get_db_connection", lambda: mock_conn)
    monkeypatch.setattr("serviceBot.db.connection.dict_cursor", lambda c: mock_cur)

    ans_deleted = service.answer_question("How long does balayage take?")
    assert "3 hours" not in ans_deleted
    assert "$250" not in ans_deleted
    assert "unable to retrieve" in ans_deleted.lower()

    # 2. Database outage: must report catalog information unavailable, not return 3 hours
    def mock_db_fail():
        raise ConnectionError("PostgreSQL unreachable")

    monkeypatch.setattr("serviceBot.db.connection.get_db_connection", mock_db_fail)

    ans_db_outage = service.answer_question("How long does balayage take?")
    assert "3 hours" not in ans_db_outage
    assert "$250" not in ans_db_outage
    assert "unavailable due to a database connection error" in ans_db_outage.lower()

    # 3. Normal model operation on non-catalogue FAQ: works properly
    mock_response = MagicMock()
    mock_response.content = "Yes, our waiting lounge has free Wi-Fi and complimentary beverages."
    monkeypatch.setattr("langchain_core.runnables.base.RunnableSequence.invoke", lambda self, *args, **kwargs: mock_response)

    mock_collection.query.return_value = {
        "documents": [["Our waiting lounge offers free high-speed Wi-Fi and complimentary beverages."]],
        "metadatas": [[{"filename": "salon_amenities.pdf"}]]
    }

    ans_wifi = service.answer_question("Do you have Wi-Fi in the waiting lounge?")
    assert "free Wi-Fi" in ans_wifi


# ==============================================================================
# 17. Regression Test 5: Catalogue Completion Generation-Aware (Req 5)
# ==============================================================================

def test_catalogue_completion_generation_aware(isolated_env, monkeypatch):
    """
    Commit generation 2 while generation 1 is embedding.
    Generation 1 completion must not report the catalogue synced; subsequent refresh must index generation 2.
    """
    from serviceBot.services.rag import FAQService

    replace_calls = []

    def mock_replace(self, text, filename, generation=None):
        replace_calls.append(generation)
        # While generation 1 is embedding, simulate a newer mutation (Gen 2) arriving!
        if generation == 1:
            try:
                with get_db_connection() as conn:
                    with dict_cursor(conn) as cur:
                        cur.execute("""
                            UPDATE catalog_sync_state
                            SET desired_generation = 2, status = 'pending', updated_at = NOW()
                            WHERE id = 1
                        """)
                    conn.commit()
            except Exception:
                pass
            portal._catalog_sync_status["desired_generation"] = 2
        return 1

    monkeypatch.setattr(FAQService, "replace_text", mock_replace)

    # Set initial DB state: Gen 1 desired
    try:
        with get_db_connection() as conn:
            with dict_cursor(conn) as cur:
                cur.execute("""
                    INSERT INTO catalog_sync_state (id, desired_generation, indexed_generation, status, updated_at)
                    VALUES (1, 1, 0, 'pending', NOW())
                    ON CONFLICT (id) DO UPDATE SET desired_generation = 1, indexed_generation = 0, status = 'pending';
                """)
            conn.commit()
    except Exception:
        pass

    portal._catalog_sync_status["desired_generation"] = 1
    portal._catalog_sync_status["indexed_generation"] = 0
    portal._catalog_sync_status["status"] = "pending"

    # Run sync for generation 1
    portal.sync_services_to_kb()

    # Generation 1 completion must NOT report synced because Gen 2 arrived while embedding!
    status = portal.get_catalog_sync_status()
    assert status["status"] == "pending"
    assert status["indexed_generation"] == 1
    assert status["desired_generation"] == 2

    # Subsequent refresh indexes generation 2
    import time
    time.sleep(0.1)
    status_after = portal.get_catalog_sync_status()
    if status_after["status"] != "synced":
        portal.sync_services_to_kb()
        status_after = portal.get_catalog_sync_status()
    assert status_after["status"] == "synced"
    assert status_after["indexed_generation"] == 2
    assert 2 in replace_calls


# ==============================================================================
# 18. Regression Test 6: Truthful Business-Name Changes (Req 6)
# ==============================================================================

def test_name_only_sms_update_truthfully_reports_pending_identity(isolated_env, monkeypatch):
    """
    A name-only SMS configuration update must never report voice identity synchronized
    while the published prompt or greeting contains the previous business name.
    """
    mock_sync = AsyncMock()
    mock_sync.return_value = {"status": "synced", "message": "Voice provider instructions synchronized successfully."}
    monkeypatch.setattr(portal, "sync_prompt_to_elevenlabs", mock_sync)

    # Initial state has business_name "Davidson Car Care"
    init_cfg = portal.load_config()
    init_cfg["business_name"] = "Davidson Car Care"
    portal.save_config(init_cfg)

    # Name-only SMS update
    sms_res = client.put("/api/v1/portal/sms/config", json={
        "business_name": "Apex Premier Auto"
    })
    assert sms_res.status_code == 200
    data = sms_res.json()
    assert data["business_name"] == "Apex Premier Auto"

    # Voice provider sync must report pending_identity_update and NOT synced!
    provider_sync = data.get("provider_sync", {})
    assert provider_sync.get("status") == "pending_identity_update"
    assert "Voice agent prompt and greeting still use 'Davidson Car Care'" in provider_sync.get("message", "")
    assert provider_sync.get("status") != "synced"

    # sync_prompt_to_elevenlabs must NOT have been called to publish the old prompt/greeting
    mock_sync.assert_not_called()


# ==============================================================================
# 19. Regression Test 7: Database Publication Locking (Issue 1)
# ==============================================================================

def test_db_publication_locking_lifecycle_and_cleanup(monkeypatch):
    """
    Assert:
    - Connection context manager is entered and retained throughout publication
    - Lock SQL (SELECT pg_advisory_lock(%s)) executes with agent lock ID
    - Unlock SQL (SELECT pg_advisory_unlock(%s)) executes in finally
    - Pooled connection is returned through its context manager
    - Cleanup runs reliably even after provider failure
    - Independent publishers for the same agent cannot overlap
    """
    execution_log = []
    pool_events = []

    class MockCursor:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def execute(self, q, p=None):
            execution_log.append(("execute", q.strip(), p))

    class MockConn:
        def __init__(self): self.closed = 0
        def cursor(self, *a, **k): return MockCursor()
        def close(self): self.closed = 1

    conn = MockConn()

    @contextmanager
    def mock_get_db_connection():
        pool_events.append("enter_ctx")
        try:
            yield conn
        finally:
            pool_events.append("exit_ctx")

    monkeypatch.setattr("serviceBot.db.connection.get_db_connection", mock_get_db_connection)

    agent_id = "test-agent-lock-lifecycle"
    expected_lock_id = portal._get_agent_advisory_lock_id(agent_id)

    # 1. Normal publication lifecycle
    async def run_lifecycle():
        async with portal.agent_publication_boundary(agent_id):
            assert "enter_ctx" in pool_events
            assert ("execute", "SELECT pg_advisory_lock(%s)", (expected_lock_id,)) in execution_log
            assert "exit_ctx" not in pool_events

    asyncio.run(run_lifecycle())
    assert ("execute", "SELECT pg_advisory_unlock(%s)", (expected_lock_id,)) in execution_log
    assert "exit_ctx" in pool_events

    # 2. Cleanup after provider failure
    execution_log.clear()
    pool_events.clear()

    async def run_failing():
        async with portal.agent_publication_boundary(agent_id):
            raise RuntimeError("Provider 500 network failure")

    with pytest.raises(RuntimeError, match="Provider 500 network failure"):
        asyncio.run(run_failing())

    assert ("execute", "SELECT pg_advisory_unlock(%s)", (expected_lock_id,)) in execution_log
    assert "exit_ctx" in pool_events
    assert not portal._get_agent_async_lock(agent_id).locked()

    # 3. Independent publishers cannot overlap
    overlap = False
    active = []

    async def publisher(pid: int):
        nonlocal overlap
        async with portal.agent_publication_boundary(agent_id):
            active.append(pid)
            if len(active) > 1:
                overlap = True
            await asyncio.sleep(0.02)
            active.remove(pid)

    async def run_both():
        await asyncio.gather(publisher(1), publisher(2))

    asyncio.run(run_both())
    assert not overlap

    # 4. Report lock acquisition failure honestly when DB coordination is required
    def failing_db():
        raise ConnectionError("DB offline")

    monkeypatch.setattr("serviceBot.db.connection.get_db_connection", failing_db)
    with pytest.raises(RuntimeError, match="Database publication lock could not be acquired"):
        portal._acquire_db_agent_lock(agent_id, require_db=True)


# ==============================================================================
# 20. Regression Test 8: Split-Schedule Parsing & Repeated Saves (Issue 2)
# ==============================================================================

def test_split_schedule_parsing_and_repeated_saves_regression():
    """
    - Save 9 AM–12 PM and 2 PM–5 PM twice; output remains identical.
    - Change it to 8 AM–4 PM; no obsolete interval remains.
    - Change one split schedule to another.
    - Preserve semicolon-separated, period-separated, and next-line custom instructions.
    - Confirm unrelated settings saves do not accumulate schedule text.
    """
    from serviceBot.services.prompt_service import update_prompt_business_hours

    # 1. Save 9 AM-12 PM and 2 PM-5 PM twice; output remains identical
    prompt_init = "Business hours: Monday-Friday 9:00 AM - 5:00 PM ET."
    save1 = update_prompt_business_hours(
        prompt_init, start_hour=9, end_hour=17, business_hours=[9, 10, 11, 14, 15, 16]
    )
    assert "9:00 AM - 12:00 PM and 2:00 PM - 5:00 PM ET." in save1
    save2 = update_prompt_business_hours(
        save1, start_hour=9, end_hour=17, business_hours=[9, 10, 11, 14, 15, 16]
    )
    assert save1 == save2
    assert save2.count("2:00 PM - 5:00 PM") == 1

    # 2. Change it to 8 AM-4 PM; no obsolete interval remains
    to_single = update_prompt_business_hours(
        save2, start_hour=8, end_hour=16, business_hours=None
    )
    assert "8:00 AM - 4:00 PM ET." in to_single
    assert "9:00 AM" not in to_single
    assert "12:00 PM" not in to_single
    assert "2:00 PM" not in to_single
    assert "5:00 PM" not in to_single

    # 3. Change one split schedule to another
    to_split2 = update_prompt_business_hours(
        save2, start_hour=8, end_hour=18, business_hours=[8, 9, 10, 13, 14, 15, 16, 17]
    )
    assert "8:00 AM - 11:00 AM and 1:00 PM - 6:00 PM ET." in to_split2
    assert "9:00 AM" not in to_split2
    assert "12:00 PM" not in to_split2
    assert "2:00 PM" not in to_split2
    assert "5:00 PM" not in to_split2

    # 4. Preserve semicolon-separated, period-separated, and next-line custom instructions
    semi = "Business hours: Monday–Friday 9:00 AM - 12:00 PM and 2:00 PM - 5:00 PM ET; by appointment only on Saturdays."
    semi_up = update_prompt_business_hours(semi, start_hour=8, end_hour=16)
    assert "8:00 AM - 4:00 PM ET; by appointment only on Saturdays." in semi_up
    assert update_prompt_business_hours(semi_up, start_hour=8, end_hour=16) == semi_up

    period = "Business hours: Monday–Friday 9:00 AM - 12:00 PM and 2:00 PM - 5:00 PM ET. Note: closed on national holidays."
    period_up = update_prompt_business_hours(period, start_hour=8, end_hour=16)
    assert "8:00 AM - 4:00 PM ET. Note: closed on national holidays." in period_up
    assert update_prompt_business_hours(period_up, start_hour=8, end_hour=16) == period_up

    next_line = (
        "Business hours: Monday–Friday 9:00 AM - 12:00 PM and 2:00 PM - 5:00 PM ET.\n"
        "Customer parking is available in the rear lot."
    )
    nl_up = update_prompt_business_hours(next_line, start_hour=8, end_hour=16)
    assert "Customer parking is available in the rear lot." in nl_up
    assert update_prompt_business_hours(nl_up, start_hour=8, end_hour=16) == nl_up

    # 5. Confirm unrelated settings saves do not accumulate schedule text
    acc_check = save2
    for _ in range(5):
        acc_check = update_prompt_business_hours(
            acc_check, start_hour=9, end_hour=17, business_hours=[9, 10, 11, 14, 15, 16]
        )
    assert acc_check == save2


# ==============================================================================
# 21. Regression Test 9: Synchronization Failures Precedence (Issue 3)
# ==============================================================================

def test_sync_failures_precedence_ordering(monkeypatch, tmp_path):
    """
    Cover:
    - Superseded development plus production HTTP 500 -> overall failed
    - Superseded development plus production timeout -> overall failed
    - Superseded without failures -> overall superseded
    - All targets synced -> overall synced
    """
    dev_id = "agent-dev-ord"
    prod_id = "agent-prod-ord"
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key-prec")
    monkeypatch.setenv("ELEVENLABS_AGENT_ID", dev_id)
    monkeypatch.setenv("ELEVENLABS_PRODUCTION_AGENT_ID", prod_id)

    cfg_file = tmp_path / "config_ord.json"
    monkeypatch.setattr(portal, "CONFIG_PATH", str(cfg_file))
    monkeypatch.setattr(portal, "SYSTEM_PROMPT_PATH", str(tmp_path / "system_prompt_ord.txt"))
    portal.save_config({"prompt_generation": 2, "system_prompt": "Test Gen 2"})

    @contextmanager
    def mock_db():
        class MockRowConn:
            def cursor(self, *a, **k):
                class C:
                    def __init__(self): self.last_aid = None
                    def __enter__(self): return self
                    def __exit__(self, *a): pass
                    def execute(self, q, p=None):
                        if p: self.last_aid = p[0]
                    def fetchone(self):
                        if self.last_aid == dev_id:
                            return {"published_generation": 2, "desired_generation": 2}
                        return None
                    def fetchall(self): return []
                return C()
            def commit(self): pass
        yield MockRowConn()

    monkeypatch.setattr("serviceBot.db.connection.get_db_connection", mock_db)

    # 1. Superseded dev + Production HTTP 500 -> overall failed
    async def mock_patch_500(client_self, url, json=None, **kwargs):
        if prod_id in url:
            return httpx.Response(status_code=500, text="Internal Server Error")
        return httpx.Response(status_code=200, json={"status": "ok"})

    monkeypatch.setattr(httpx.AsyncClient, "patch", mock_patch_500)
    res_500 = asyncio.run(portal.sync_prompt_to_elevenlabs("Prompt Gen 1", generation=1))
    assert res_500["status"] == "failed"
    assert res_500["agents"][dev_id]["status"] == "superseded"
    assert res_500["agents"][prod_id]["status"] == "failed"
    assert res_500["agents"][prod_id]["status_code"] == 500

    # 2. Superseded dev + Production Timeout -> overall failed
    async def mock_patch_timeout(client_self, url, json=None, **kwargs):
        if prod_id in url:
            raise httpx.ReadTimeout("ElevenLabs request timed out")
        return httpx.Response(status_code=200, json={"status": "ok"})

    monkeypatch.setattr(httpx.AsyncClient, "patch", mock_patch_timeout)
    res_timeout = asyncio.run(portal.sync_prompt_to_elevenlabs("Prompt Gen 1", generation=1))
    assert res_timeout["status"] == "failed"
    assert res_timeout["agents"][dev_id]["status"] == "superseded"
    assert res_timeout["agents"][prod_id]["status"] == "failed"

    # 3. Superseded without failures -> overall superseded
    async def mock_patch_ok(client_self, url, json=None, **kwargs):
        return httpx.Response(status_code=200, json={"status": "ok"})

    monkeypatch.setattr(httpx.AsyncClient, "patch", mock_patch_ok)
    res_superseded = asyncio.run(portal.sync_prompt_to_elevenlabs("Prompt Gen 1", generation=1))
    assert res_superseded["status"] == "superseded"
    assert res_superseded["agents"][dev_id]["status"] == "superseded"
    assert not any(r["status"] == "failed" for r in res_superseded["agents"].values())

    # 4. All targets synced -> overall synced
    @contextmanager
    def mock_db_fresh():
        class MockRowConn:
            def cursor(self, *a, **k):
                class C:
                    def __enter__(self): return self
                    def __exit__(self, *a): pass
                    def execute(self, q, p=None): pass
                    def fetchone(self): return None
                    def fetchall(self): return []
                return C()
            def commit(self): pass
        yield MockRowConn()

    monkeypatch.setattr("serviceBot.db.connection.get_db_connection", mock_db_fresh)
    portal.save_config({"prompt_generation": 1, "system_prompt": "Prompt Gen 1"})
    res_synced = asyncio.run(portal.sync_prompt_to_elevenlabs("Prompt Gen 1", generation=1))
    assert res_synced["status"] == "synced"
    assert res_synced["generation"] == 1
    assert res_synced["agents"][dev_id]["status"] == "synced"
    assert res_synced["agents"][prod_id]["status"] == "synced"
