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
