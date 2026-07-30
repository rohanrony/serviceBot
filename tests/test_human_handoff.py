import pytest
from fastapi.testclient import TestClient
from serviceBot.main import app
from serviceBot.services.handoff_service import trigger_human_handoff, send_agent_reply, resolve_conversation
from serviceBot.db.queries import get_or_create_sms_conversation, get_sms_conversations, get_sms_messages, update_customer_opt_in

from unittest.mock import patch

client = TestClient(app)


@patch("serviceBot.services.handoff_service.is_within_business_hours", return_value=True)
def test_handoff_state_transitions_and_auto_responder(mock_biz):
    phone = "+15550195555"
    conv = get_or_create_sms_conversation(phone)
    conv_id = conv["id"]
    assert conv["state"] == "AUTOMATED"

    # Trigger free-text message
    res_handoff = trigger_human_handoff(conv_id, phone, "I'll be 15 minutes late")
    assert res_handoff["state"] == "HANDOFF_REQUIRED"
    assert res_handoff["auto_responder_sent"] is True

    # Immediate second message within 60s -> debounce should suppress duplicate auto-responder!
    res_debounce = trigger_human_handoff(conv_id, phone, "Also traffic is heavy")
    assert res_debounce["state"] == "HANDOFF_REQUIRED"
    assert res_debounce["auto_responder_sent"] is False


@patch("serviceBot.services.handoff_service.is_within_business_hours", return_value=True)
def test_agent_reply_and_resolve_flow(mock_biz):
    phone = "+15550194444"
    conv = get_or_create_sms_conversation(phone)
    conv_id = conv["id"]

    trigger_human_handoff(conv_id, phone, "Can I change my address?")

    # Agent reply via API
    reply_res = client.post("/api/v1/portal/sms/reply", json={
        "conversation_id": conv_id,
        "message": "No problem! What is your updated address?"
    })
    assert reply_res.status_code == 200
    assert reply_res.json()["state"] == "IN_PROGRESS"

    # Verify conversation state is IN_PROGRESS
    convs = get_sms_conversations(state="IN_PROGRESS")
    ids = [c["id"] for c in convs]
    assert conv_id in ids

    # Resolve conversation via API
    res_resolve = client.post("/api/v1/portal/sms/resolve", json={
        "conversation_id": conv_id
    })
    assert res_resolve.status_code == 200
    assert res_resolve.json()["state"] == "AUTOMATED"
