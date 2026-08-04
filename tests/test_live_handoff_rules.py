import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from serviceBot.main import app
from serviceBot.services.sms_classifier import classify_inbound_message, process_inbound_sms
from serviceBot.services.handoff_service import trigger_human_handoff
from serviceBot.graph.nodes import intent_classifier_node, handoff_node
from langchain_core.messages import HumanMessage

client = TestClient(app)


def test_sms_classification_requires_user_prompt_for_handoff():
    """
    Assert that general free text does NOT classify as explicit handoff request,
    while messages explicitly asking for a human/agent/manager DO classify as handoff requests.
    """
    # General question should not trigger handoff prompt flag
    general_res = classify_inbound_message("What are your hours for brake service?")
    assert general_res["category"] == "free_text"
    assert general_res.get("is_handoff_requested") is False

    # Explicit human handoff prompt
    handoff_res = classify_inbound_message("I need to speak to a human representative please")
    assert handoff_res["category"] == "free_text"
    assert handoff_res.get("is_handoff_requested") is True

    handoff_res_agent = classify_inbound_message("Transfer me to a live agent")
    assert handoff_res_agent.get("is_handoff_requested") is True


@patch("serviceBot.services.handoff_service.is_within_business_hours")
def test_sms_handoff_during_business_hours_when_requested(mock_biz_hours):
    """Assert live handoff succeeds during business hours when requested by user."""
    mock_biz_hours.return_value = True

    # Call process_inbound_sms with an explicit handoff request
    res = process_inbound_sms("+15550199999", "Can I please speak to a human manager?")
    assert res["status"] == "handoff_triggered"
    assert res["details"]["success"] is True
    assert res["details"]["state"] == "HANDOFF_REQUIRED"


@patch("serviceBot.services.handoff_service.is_within_business_hours")
def test_sms_handoff_blocked_outside_business_hours(mock_biz_hours):
    """Assert live handoff is blocked outside business hours even when requested by user."""
    mock_biz_hours.return_value = False

    res = trigger_human_handoff(999, "+15550199999", "I want to talk to an agent right now")
    assert res["success"] is False
    assert res["state"] == "OUT_OF_BUSINESS_HOURS"
    assert res["auto_responder_sent"] is True


@patch("serviceBot.api.telephony.is_within_business_hours")
def test_voice_tools_handoff_business_hours_enforcement(mock_biz_hours):
    """Assert voice tool handoff returns failure message outside business hours and success during business hours."""
    # Outside business hours
    mock_biz_hours.return_value = False
    payload = {
        "tool_call_id": "call_handoff_out",
        "name": "handoff",
        "arguments": {"phone": "5551234567"}
    }
    response = client.post("/api/v1/voice/tools", json=payload)
    assert response.status_code == 200
    res_data = response.json()["result"]
    assert res_data["success"] is False
    assert "business hours" in res_data["message"].lower()

    # During business hours
    mock_biz_hours.return_value = True
    payload_in = {
        "tool_call_id": "call_handoff_in",
        "name": "handoff",
        "arguments": {"phone": "5551234567"}
    }
    response_in = client.post("/api/v1/voice/tools", json=payload_in)
    assert response_in.status_code == 200
    res_data_in = response_in.json()["result"]
    assert res_data_in["success"] is True


@patch("serviceBot.api.telephony.is_within_business_hours")
def test_graph_handoff_node_business_hours_awareness(mock_biz_hours):
    """Assert graph handoff_node incorporates business hours status into summary."""
    mock_biz_hours.return_value = False
    state = {
        "messages": [HumanMessage(content="Connect me with a person")],
        "customer": {"name": "Test User"},
        "service_request_id": None,
        "appointment_id": None
    }
    result = handoff_node(state)
    assert "CLOSED" in result["handoff_summary"] or "OUTSIDE BUSINESS HOURS" in result["handoff_summary"]
