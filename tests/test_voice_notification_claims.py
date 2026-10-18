"""A saved scheduling change is distinct from native notification evidence."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from serviceBot.api import portal, telephony
from serviceBot.main import app

MUTATIONS = (
    "create_service_request", "book_appointment", "request_callback",
    "consolidate_appointment_service", "reschedule_appointment", "cancel_appointment",
)
PROMPT_PATH = Path(__file__).resolve().parents[1] / "serviceBot" / "system_prompt.txt"


def test_native_cancel_confirms_saved_state_without_claiming_text_dispatch():
    with patch.object(telephony, "get_customer_appointments", return_value=[{"id": 23}]), \
         patch.object(telephony, "cancel_appointment", return_value={"request_id": 23, "cancelled": True}):
        response = TestClient(app).post("/api/v1/voice/tools", json={
            "name": "cancel_appointment",
            "arguments": {"phone": "5550100001", "appointment_id": 23},
        })
    assert response.status_code == 200
    result = response.json()["result"]
    assert result["success"] is True and result["appointment_id"] == 23
    assert "cancelled" in result["message"].lower()
    assert "dispatched" not in result["message"].lower()
    assert "text has been sent" not in result["message"].lower()
    assert result["notification_delivery_status"] == "unverified"
    assert "native notification receipt" in result["agent_guidance"]


@pytest.mark.parametrize("tool", MUTATIONS)
def test_each_successful_mutation_preserves_outcome_and_adds_receipt_guidance(tool):
    result = {"success": True, "appointment_id": 23, "message": "Saved scheduling state.", "already_cancelled": True}
    guided = telephony._with_notification_delivery_guidance(tool, result)
    assert all(guided[key] == value for key, value in result.items())
    assert result == {"success": True, "appointment_id": 23, "message": "Saved scheduling state.", "already_cancelled": True}
    assert guided["notification_delivery_status"] == "unverified"
    assert "native notification receipt" in guided["agent_guidance"]
    assert "queued" not in guided["agent_guidance"].lower()


@pytest.mark.parametrize("tool,result", [
    ("cancel_appointment", {"success": False, "message": "No active appointment"}),
    ("get_customer_appointments", {"success": True, "appointments": []}),
    ("verify_caller_identity", {"success": True, "read_only": True}),
])
def test_guidance_preserves_failure_and_read_only_results(tool, result):
    assert telephony._with_notification_delivery_guidance(tool, result) == result


def test_prompt_requires_native_receipt_and_removes_sent_text_example():
    prompt = PROMPT_PATH.read_text()
    assert "confirmation text message has been sent" not in prompt.lower()
    assert "native notification receipt" in prompt.lower()
    assert "queued" in prompt.lower() and "delivered" in prompt.lower()


def test_published_prompt_file_overrides_stale_config_prompt(tmp_path, monkeypatch):
    config_path = tmp_path / "synthetic-config.json"
    config_path.write_text(json.dumps({"system_prompt": "Stale synthetic prompt"}))
    monkeypatch.setattr(portal, "CONFIG_PATH", str(config_path))
    monkeypatch.setattr(portal, "SYSTEM_PROMPT_PATH", str(PROMPT_PATH))
    assert portal.load_config()["system_prompt"] == PROMPT_PATH.read_text().strip()
