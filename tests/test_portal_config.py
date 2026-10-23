import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient

from serviceBot.api import portal
from serviceBot.main import app
from serviceBot.db.queries import get_sms_config, update_sms_config

client = TestClient(app)


def test_business_settings_canonical_fields_persistence(tmp_path, monkeypatch):
    """US1/AC1: Business Address, Google Maps Link, Time Zone, and Support Helpline are canonically managed in Business Settings."""
    monkeypatch.setattr(portal, "CONFIG_PATH", str(tmp_path / "config.json"))
    monkeypatch.setattr(portal, "SYSTEM_PROMPT_PATH", str(tmp_path / "prompt.txt"))
    sync = AsyncMock()
    monkeypatch.setattr(portal, "sync_prompt_to_elevenlabs", sync)

    payload = {
        "business_name": "Acme Services",
        "business_address": "789 Main St, Austin, TX 78701",
        "google_maps_url": "https://maps.google.com/?q=Acme+Services",
        "business_timezone": "America/Chicago",
        "support_phone_number": "+15125550199",
    }
    response = client.post("/api/v1/portal/config", json=payload)
    assert response.status_code == 200

    # Verify GET /api/v1/portal/config returns canonical values
    get_res = client.get("/api/v1/portal/config").json()
    assert get_res["business_name"] == "Acme Services"
    assert get_res["business_address"] == "789 Main St, Austin, TX 78701"
    assert get_res["google_maps_url"] == "https://maps.google.com/?q=Acme+Services"
    assert get_res["business_timezone"] == "America/Chicago"
    assert get_res["support_phone_number"] == "+15125550199"

    # Verify GET /api/v1/portal/sms/config also reflects canonical values
    sms_cfg_res = client.get("/api/v1/portal/sms/config").json()
    assert sms_cfg_res["business_address"] == "789 Main St, Austin, TX 78701"
    assert sms_cfg_res["google_maps_url"] == "https://maps.google.com/?q=Acme+Services"
    assert sms_cfg_res["business_timezone"] == "America/Chicago"
    assert sms_cfg_res.get("support_phone_number") == "+15125550199"


def test_business_settings_save_confirmation_contract(tmp_path, monkeypatch):
    """US1/AC2: POST /api/v1/portal/config supports regenerate_business_prompt flag cleanly."""
    monkeypatch.setattr(portal, "CONFIG_PATH", str(tmp_path / "config.json"))
    monkeypatch.setattr(portal, "SYSTEM_PROMPT_PATH", str(tmp_path / "prompt.txt"))
    sync = AsyncMock()
    monkeypatch.setattr(portal, "sync_prompt_to_elevenlabs", sync)

    portal.save_config({"business_name": "Old Name", "system_prompt": "Old prompt", "first_message": "Old greeting"})

    # When regenerate_business_prompt is True, prompt and greeting are regenerated
    res = client.post("/api/v1/portal/config", json={
        "business_name": "New Studio",
        "regenerate_business_prompt": True,
    })
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data.get("saved") is True

    cfg = portal.load_config()
    assert "New Studio" in cfg["system_prompt"]
    assert "New Studio" in cfg["first_message"]


def test_provider_sync_status_reported_separately_on_failure(tmp_path, monkeypatch):
    """US1/AC3: Report saved settings separately from voice-provider synchronization status on failure."""
    monkeypatch.setattr(portal, "CONFIG_PATH", str(tmp_path / "config.json"))
    monkeypatch.setattr(portal, "SYSTEM_PROMPT_PATH", str(tmp_path / "prompt.txt"))

    # Mock sync failure
    failed_sync = AsyncMock(side_effect=RuntimeError("ElevenLabs connection timed out"))
    monkeypatch.setattr(portal, "sync_prompt_to_elevenlabs", failed_sync)

    response = client.post("/api/v1/portal/config", json={
        "business_name": "Resilient Co",
        "regenerate_business_prompt": True,
    })
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["saved"] is True
    assert "provider_sync" in data
    assert data["provider_sync"]["status"] in ("failed", "unavailable")
    assert "ElevenLabs" in data["provider_sync"]["message"] or "failed" in data["provider_sync"]["message"].lower()

    # Settings must remain durably saved in config.json
    cfg = portal.load_config()
    assert cfg["business_name"] == "Resilient Co"


def test_canonical_support_phone_synchronization(tmp_path, monkeypatch):
    """US1/AC4: Business Settings is canonical owner of support number; legacy SMS config endpoint synchronizes."""
    monkeypatch.setattr(portal, "CONFIG_PATH", str(tmp_path / "config.json"))
    monkeypatch.setattr(portal, "SYSTEM_PROMPT_PATH", str(tmp_path / "prompt.txt"))
    sync = AsyncMock()
    monkeypatch.setattr(portal, "sync_prompt_to_elevenlabs", sync)

    # 1. Update support_phone_number via Business Settings (/api/v1/portal/config)
    res1 = client.post("/api/v1/portal/config", json={"support_phone_number": "+18005550111"})
    assert res1.status_code == 200
    assert portal.load_config().get("support_phone_number") == "+18005550111"
    db_cfg = get_sms_config()
    assert db_cfg.get("support_phone_number") == "+18005550111"

    # 2. Update via legacy SMS config (/api/v1/portal/sms/config)
    res2 = client.put("/api/v1/portal/sms/config", json={"support_phone_number": "+18005550222"})
    assert res2.status_code == 200
    assert portal.load_config().get("support_phone_number") == "+18005550222"
    assert get_sms_config().get("support_phone_number") == "+18005550222"


def test_saving_sms_config_does_not_erase_business_settings(tmp_path, monkeypatch):
    """Saving notifications/SMS config does not erase previously persisted business settings."""
    monkeypatch.setattr(portal, "CONFIG_PATH", str(tmp_path / "config.json"))
    monkeypatch.setattr(portal, "SYSTEM_PROMPT_PATH", str(tmp_path / "prompt.txt"))
    sync = AsyncMock()
    monkeypatch.setattr(portal, "sync_prompt_to_elevenlabs", sync)

    # 1. Save canonical business settings
    payload = {
        "business_address": "456 Oak Avenue, Durham, NC 27701",
        "google_maps_url": "https://maps.google.com/?q=Durham+Care",
        "business_timezone": "America/New_York",
        "support_phone_number": "+19195550144",
    }
    assert client.post("/api/v1/portal/config", json=payload).status_code == 200

    # 2. Save SMS config without business address/maps/support_phone or with empty/null values
    sms_payload = {
        "auto_responder_template": "Thanks for contacting us! We will follow up shortly.",
        "admin_phone_number": "+19195550188",
        "business_address": "",
        "google_maps_url": "",
        "support_phone_number": None,
    }
    res = client.put("/api/v1/portal/sms/config", json=sms_payload)
    assert res.status_code == 200

    # 3. Assert canonical business settings were not overwritten
    cfg = portal.load_config()
    assert cfg["business_address"] == "456 Oak Avenue, Durham, NC 27701"
    assert cfg["google_maps_url"] == "https://maps.google.com/?q=Durham+Care"
    assert cfg["business_timezone"] == "America/New_York"
    assert cfg["support_phone_number"] == "+19195550144"


def test_provider_http_500_reported_as_failed_sync(tmp_path, monkeypatch):
    """When voice provider returns HTTP 500, update_config reports provider_sync status failed."""
    import httpx
    monkeypatch.setattr(portal, "CONFIG_PATH", str(tmp_path / "config.json"))
    monkeypatch.setattr(portal, "SYSTEM_PROMPT_PATH", str(tmp_path / "prompt.txt"))
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-xi-key")
    monkeypatch.setenv("ELEVENLABS_AGENT_ID", "test-agent-id")

    # Mock httpx AsyncClient patch returning HTTP 500
    mock_resp = httpx.Response(status_code=500, text="Internal Server Error from ElevenLabs")

    async def mock_patch(*args, **kwargs):
        return mock_resp

    monkeypatch.setattr(httpx.AsyncClient, "patch", mock_patch)

    res = client.post("/api/v1/portal/config", json={
        "business_name": "Test Co",
        "regenerate_business_prompt": True,
    })
    assert res.status_code == 200
    data = res.json()
    assert data["saved"] is True
    assert data["provider_sync"]["status"] == "failed"
    assert "500" in data["provider_sync"]["message"]


def test_sync_prompt_to_elevenlabs_multi_agent_resilience(tmp_path, monkeypatch):
    """Review Finding 4: Attempt synchronization for every configured voice agent."""
    import asyncio
    import httpx
    from serviceBot.api.portal import sync_prompt_to_elevenlabs, load_config

    monkeypatch.setattr(portal, "CONFIG_PATH", str(tmp_path / "config.json"))
    monkeypatch.setattr(portal, "SYSTEM_PROMPT_PATH", str(tmp_path / "prompt.txt"))
    portal.save_config({"business_name": "MultiAgent Co"})
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-api-key")
    monkeypatch.setenv("ELEVENLABS_AGENT_ID", "dev-agent-id")
    monkeypatch.setenv("ELEVENLABS_PRODUCTION_AGENT_ID", "prod-agent-id")

    called_targets = []

    # Case 1: First-target 404, second-target 200 -> mixed failure, both attempted
    async def mock_patch_404_then_200(self, url, *args, **kwargs):
        target = url.split("/")[-1]
        called_targets.append(target)
        if target == "dev-agent-id":
            return httpx.Response(status_code=404, text="Agent not found")
        return httpx.Response(status_code=200, json={"status": "ok"})

    monkeypatch.setattr(httpx.AsyncClient, "patch", mock_patch_404_then_200)

    called_targets.clear()
    res = asyncio.run(sync_prompt_to_elevenlabs("System prompt instructions"))
    assert called_targets == ["dev-agent-id", "prod-agent-id"], "Both agents must be attempted even if the first returns 404"
    assert res["status"] == "failed"
    assert "agents" in res
    assert res["agents"]["dev-agent-id"]["status"] == "failed"
    assert res["agents"]["dev-agent-id"]["status_code"] == 404
    assert res["agents"]["prod-agent-id"]["status"] == "synced"
    assert res["agents"]["prod-agent-id"]["status_code"] == 200

    # Case 2: First-target timeout, second-target 200 -> transport exception handled, both attempted
    async def mock_patch_timeout_then_200(self, url, *args, **kwargs):
        target = url.split("/")[-1]
        called_targets.append(target)
        if target == "dev-agent-id":
            raise httpx.TimeoutException("Read timed out")
        return httpx.Response(status_code=200, json={"status": "ok"})

    monkeypatch.setattr(httpx.AsyncClient, "patch", mock_patch_timeout_then_200)

    called_targets.clear()
    res = asyncio.run(sync_prompt_to_elevenlabs("System prompt instructions"))
    assert called_targets == ["dev-agent-id", "prod-agent-id"], "Both agents must be attempted even if the first times out"
    assert res["status"] == "failed"
    assert res["agents"]["dev-agent-id"]["status"] == "failed"
    assert "timed out" in res["agents"]["dev-agent-id"]["error"].lower()
    assert res["agents"]["prod-agent-id"]["status"] == "synced"

    # Case 3: All-success -> overall status synced
    async def mock_patch_all_200(self, url, *args, **kwargs):
        target = url.split("/")[-1]
        called_targets.append(target)
        return httpx.Response(status_code=200, json={"status": "ok"})

    monkeypatch.setattr(httpx.AsyncClient, "patch", mock_patch_all_200)

    called_targets.clear()
    res = asyncio.run(sync_prompt_to_elevenlabs("System prompt instructions"))
    assert called_targets == ["dev-agent-id", "prod-agent-id"]
    assert res["status"] == "synced"
    assert res["agents"]["dev-agent-id"]["status"] == "synced"
    assert res["agents"]["prod-agent-id"]["status"] == "synced"

    # Case 4: Duplicate target IDs are deduplicated
    monkeypatch.setenv("ELEVENLABS_PRODUCTION_AGENT_ID", "dev-agent-id")
    called_targets.clear()
    res = asyncio.run(sync_prompt_to_elevenlabs("System prompt instructions"))
    assert called_targets == ["dev-agent-id"], "Duplicate target IDs must be deduplicated"
    assert res["status"] == "synced"

    # Case 5: Single configured target
    monkeypatch.delenv("ELEVENLABS_PRODUCTION_AGENT_ID", raising=False)
    monkeypatch.setenv("ELEVENLABS_AGENT_ID", "single-agent-id")
    called_targets.clear()
    res = asyncio.run(sync_prompt_to_elevenlabs("System prompt instructions"))
    assert called_targets == ["single-agent-id"]
    assert res["status"] == "synced"

    # Case 6: Missing credentials/targets report unavailable
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    called_targets.clear()
    res = asyncio.run(sync_prompt_to_elevenlabs("System prompt instructions"))
    assert res["status"] == "unavailable"
    assert len(called_targets) == 0


def test_helpline_consistency_across_stores_and_logic(tmp_path, monkeypatch):
    """Review Finding 2: Keep the helpline consistent across configuration and PostgreSQL."""
    from serviceBot.db.queries import get_sms_config, update_sms_config
    from serviceBot.services.sms_classifier import get_unrecognized_message_acknowledgment
    from serviceBot.services.handoff_service import trigger_human_handoff

    monkeypatch.setattr(portal, "CONFIG_PATH", str(tmp_path / "config.json"))
    monkeypatch.setattr(portal, "SYSTEM_PROMPT_PATH", str(tmp_path / "prompt.txt"))
    sync = AsyncMock()
    monkeypatch.setattr(portal, "sync_prompt_to_elevenlabs", sync)

    # 1. Initialize helpline via Business Settings (/api/v1/portal/config)
    res = client.post("/api/v1/portal/config", json={"support_phone_number": "+18005550100"})
    assert res.status_code == 200
    assert portal.load_config().get("support_phone_number") == "+18005550100"
    assert get_sms_config().get("support_phone_number") == "+18005550100"

    # 2. Omitted helpline in legacy SMS update preserves both stores
    res = client.put("/api/v1/portal/sms/config", json={"admin_phone_number": "+15550001111"})
    assert res.status_code == 200
    assert portal.load_config().get("support_phone_number") == "+18005550100"
    assert get_sms_config().get("support_phone_number") == "+18005550100"

    # 3. Null helpline in legacy SMS update preserves both stores
    res = client.put("/api/v1/portal/sms/config", json={"support_phone_number": None})
    assert res.status_code == 200
    assert portal.load_config().get("support_phone_number") == "+18005550100"
    assert get_sms_config().get("support_phone_number") == "+18005550100"

    # 4. Empty string helpline in legacy SMS update preserves both stores
    res = client.put("/api/v1/portal/sms/config", json={"support_phone_number": ""})
    assert res.status_code == 200
    assert portal.load_config().get("support_phone_number") == "+18005550100"
    assert get_sms_config().get("support_phone_number") == "+18005550100"

    # 5. Whitespace-only helpline in legacy SMS update preserves both stores
    res = client.put("/api/v1/portal/sms/config", json={"support_phone_number": "   \t\n  "})
    assert res.status_code == 200
    assert portal.load_config().get("support_phone_number") == "+18005550100"
    assert get_sms_config().get("support_phone_number") == "+18005550100"

    # 6. Valid replacement in legacy SMS update updates BOTH stores
    res = client.put("/api/v1/portal/sms/config", json={"support_phone_number": " +18005550222 "})
    assert res.status_code == 200
    assert portal.load_config().get("support_phone_number") == "+18005550222"
    assert get_sms_config().get("support_phone_number") == "+18005550222"

    # 7. Explicit clearing through Business Settings clears BOTH stores
    res = client.post("/api/v1/portal/config", json={"support_phone_number": ""})
    assert res.status_code == 200
    assert portal.load_config().get("support_phone_number") == ""
    assert (get_sms_config().get("support_phone_number") or "") == ""

    # 8. Fresh reads from both endpoints do not resurrect old number or invent placeholder
    cfg_read = client.get("/api/v1/portal/config").json()
    assert cfg_read["support_phone_number"] == ""

    sms_read = client.get("/api/v1/portal/sms/config").json()
    assert sms_read["support_phone_number"] == ""

    # 9. Acknowledgment logic does not invent placeholder number
    ack = get_unrecognized_message_acknowledgment()
    assert ack == "Message received."
    assert "1800" not in ack
    assert "please call" not in ack.lower()

    # 10. Handoff logic does not invent placeholder number +18005550199
    from unittest.mock import patch
    with patch("serviceBot.services.handoff_service.is_within_business_hours", return_value=False), \
         patch("serviceBot.services.handoff_service.get_customer_opt_in", return_value=False):
        handoff_res = trigger_human_handoff(1, "+15550009999", "Need help")
        assert "+18005550199" not in str(handoff_res)

