import json
import os
from unittest.mock import patch, MagicMock
import pytest
from fastapi.testclient import TestClient

from serviceBot.main import app
import serviceBot.api.portal as portal_mod

client = TestClient(app)


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    """
    Isolates CONFIG_PATH and SYSTEM_PROMPT_PATH to a temporary test directory
    seeded with the real config and system prompt templates.
    """
    base_dir = os.path.dirname(os.path.dirname(__file__))
    orig_config_path = os.path.join(base_dir, "serviceBot", "config.json")
    orig_prompt_path = os.path.join(base_dir, "serviceBot", "system_prompt.txt")

    with open(orig_config_path, "r", encoding="utf-8") as f:
        config_data = json.load(f)

    with open(orig_prompt_path, "r", encoding="utf-8") as f:
        prompt_content = f.read()

    test_config_file = str(tmp_path / "config.json")
    test_prompt_file = str(tmp_path / "system_prompt.txt")

    with open(test_config_file, "w", encoding="utf-8") as f:
        json.dump(config_data, f, indent=2)

    with open(test_prompt_file, "w", encoding="utf-8") as f:
        f.write(prompt_content)

    monkeypatch.setattr(portal_mod, "CONFIG_PATH", test_config_file)
    monkeypatch.setattr(portal_mod, "SYSTEM_PROMPT_PATH", test_prompt_file)

    yield {
        "config_file": test_config_file,
        "prompt_file": test_prompt_file,
        "orig_config": config_data,
        "orig_prompt": prompt_content,
    }


def test_update_prompt_business_hours_standard_unit():
    """Unit test for the prompt service transformation function."""
    from serviceBot.services.prompt_service import update_prompt_business_hours

    base_dir = os.path.dirname(os.path.dirname(__file__))
    orig_prompt_path = os.path.join(base_dir, "serviceBot", "system_prompt.txt")
    with open(orig_prompt_path, "r", encoding="utf-8") as f:
        prompt_text = f.read()

    # Change to 8:00 AM - 5:00 PM (8 to 17), Monday-Friday (0-4)
    updated = update_prompt_business_hours(
        prompt_text=prompt_text,
        start_hour=8,
        end_hour=17,
        business_days=[0, 1, 2, 3, 4],
        timezone_str="America/New_York",
    )

    # 1. Closing boundary closing time
    assert "conclude by 5:00 PM" in updated
    assert "conclude by 6:00 PM" not in updated

    # 2. Calculated duration start times for 5:00 PM close:
    # 60m -> 4:00 PM; 90m -> 3:30 PM; 120m -> 3:00 PM
    assert "60-minute service: Latest possible start is 4:00 PM (concludes at 5:00 PM)" in updated
    assert "90-minute (1.5-hour) service: Latest possible start is 3:30 PM (concludes at 5:00 PM)" in updated
    assert "120-minute (2-hour) service: Latest possible start is 3:00 PM (concludes at 5:00 PM)" in updated

    # 3. Proactive explanation example
    assert "service center closes at 5:00 PM" in updated
    assert "latest appointment we can begin is 3:30 PM" in updated

    # 4. FAQ and callback hours
    assert "8:00 AM - 5:00 PM" in updated or "8:00 AM – 5:00 PM" in updated
    assert "closed weekends" in updated


def test_update_prompt_business_hours_saturday_and_different_timezone():
    """Unit test for Tuesday-Saturday operating schedule in Central Time."""
    from serviceBot.services.prompt_service import update_prompt_business_hours

    base_dir = os.path.dirname(os.path.dirname(__file__))
    orig_prompt_path = os.path.join(base_dir, "serviceBot", "system_prompt.txt")
    with open(orig_prompt_path, "r", encoding="utf-8") as f:
        prompt_text = f.read()

    # 9:00 AM - 7:00 PM (9 to 19), Monday to Saturday [0, 1, 2, 3, 4, 5], Central Time
    updated = update_prompt_business_hours(
        prompt_text=prompt_text,
        start_hour=9,
        end_hour=19,
        business_days=[0, 1, 2, 3, 4, 5],
        timezone_str="America/Chicago",
    )

    assert "7:00 PM" in updated
    assert "CT" in updated
    assert "closed Sundays" in updated
    # 90m service latest start for 7:00 PM is 5:30 PM
    assert "5:30 PM" in updated
    assert "Monday–Saturday" in updated or "Monday-Saturday" in updated


@patch("httpx.AsyncClient.patch")
@patch.dict(os.environ, {"ELEVENLABS_API_KEY": "test-key-123", "ELEVENLABS_AGENT_ID": "agent-123"})
def test_portal_config_endpoint_updates_prompt_when_staff_hours_change(mock_patch, isolated_config):
    """
    Integration test: saving business hours via POST /api/v1/portal/config
    (as done by the Staff Calendar view) automatically regenerates the prompt
    and synchronizes the updated prompt to ElevenLabs.
    """
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"status": "ok"}
    mock_patch.return_value = mock_response

    # Simulate payload sent by Staff Calendar view:
    payload = {
        "business_hours_start": 8,
        "business_hours_end": 17,
        "business_days": [0, 1, 2, 3, 4],
    }

    res = client.post("/api/v1/portal/config", json=payload)
    assert res.status_code == 200
    assert res.json().get("success") is True

    # Check GET /api/v1/portal/config returns the updated system prompt
    get_res = client.get("/api/v1/portal/config")
    assert get_res.status_code == 200
    updated_config = get_res.json()
    new_prompt = updated_config.get("system_prompt", "")

    # Assert new prompt contains the updated hours and duration calculations
    assert "5:00 PM" in new_prompt
    assert "3:30 PM" in new_prompt
    assert "conclude by 5:00 PM" in new_prompt
    assert "conclude by 6:00 PM" not in new_prompt

    # Verify that file on disk (system_prompt.txt) also got written with the new hours
    with open(isolated_config["prompt_file"], "r", encoding="utf-8") as f:
        disk_prompt = f.read()
    assert "5:00 PM" in disk_prompt
    assert "3:30 PM" in disk_prompt

    # Verify ElevenLabs sync was invoked with the newly updated prompt
    mock_patch.assert_called_once()
    _args, kwargs = mock_patch.call_args
    synced_prompt = kwargs["json"]["conversation_config"]["agent"]["prompt"]["prompt"]
    assert "5:00 PM" in synced_prompt
    assert "3:30 PM" in synced_prompt


def test_portal_config_custom_prompt_without_hours_change_preserved(isolated_config):
    """Custom prompts without business hour updates are preserved as-is."""
    payload = {
        "system_prompt": "You are a custom AI agent without standard business hours text.",
    }
    res = client.post("/api/v1/portal/config", json=payload)
    assert res.status_code == 200

    get_res = client.get("/api/v1/portal/config")
    assert get_res.json()["system_prompt"] == "You are a custom AI agent without standard business hours text."
