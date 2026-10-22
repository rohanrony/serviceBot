from unittest.mock import patch, MagicMock
import pytest

from serviceBot.api import portal
from serviceBot.services.sms_classifier import handle_agent_confirmation_action


@pytest.fixture
def mock_twilio():
    with patch("serviceBot.services.sms_classifier.TwilioSMSClient") as mock_cls:
        instance = MagicMock()
        mock_cls.return_value = instance
        yield instance


def test_acknowledgment_with_configured_helpline(tmp_path, monkeypatch, mock_twilio):
    """US7/AC1: Inbound message acknowledgment references configured support helpline."""
    monkeypatch.setattr(portal, "CONFIG_PATH", str(tmp_path / "config.json"))
    monkeypatch.setattr(portal, "SYSTEM_PROMPT_PATH", str(tmp_path / "prompt.txt"))

    portal.save_config({
        "support_phone_number": "+18005550199",
    })

    agent = {"id": 1, "name": "Sam Advisor", "phone_number": "+15551239999"}
    result = handle_agent_confirmation_action(agent, "Can you tell me more details about tomorrow?", from_phone="+15551239999")

    assert result["status"] == "processed"
    reply = result["reply"]
    assert reply == "Message received. For urgent scheduling assistance, please call +18005550199."
    assert "dispatch" not in reply.lower()


def test_acknowledgment_with_unconfigured_helpline(tmp_path, monkeypatch, mock_twilio):
    """US7/AC1: Inbound message acknowledgment falls back to 'Message received.' when helpline is unset or blank."""
    monkeypatch.setattr(portal, "CONFIG_PATH", str(tmp_path / "config.json"))
    monkeypatch.setattr(portal, "SYSTEM_PROMPT_PATH", str(tmp_path / "prompt.txt"))

    # Explicitly empty / unset support_phone_number
    portal.save_config({
        "support_phone_number": "",
    })
    from serviceBot.db.queries import update_sms_config
    update_sms_config({"support_phone_number": ""})

    agent = {"id": 1, "name": "Sam Advisor", "phone_number": "+15551239999"}
    result = handle_agent_confirmation_action(agent, "Just checking in.", from_phone="+15551239999")

    assert result["status"] == "processed"
    reply = result["reply"]
    assert reply == "Message received."
    assert "dispatch" not in reply.lower()
    assert "please call" not in reply.lower()
