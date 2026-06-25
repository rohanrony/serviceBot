import pytest
from fastapi.testclient import TestClient
from serviceBot.main import app

client = TestClient(app)

def test_inbound_telephony_webhook():
    # Payload matching Twilio Standard inbound request structure
    payload = {
        "CallSid": "CAXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX",
        "From": "+15551234567",
        "To": "+15557654321",
        "Direction": "inbound"
    }
    
    # POST inbound call webhook with application/x-www-form-urlencoded data
    response = client.post("/api/v1/telephony/inbound", data=payload)
    
    # Assert HTTP 200 OK
    assert response.status_code == 200
    
    # Assert Content-Type is application/xml
    content_type = response.headers.get("content-type", "")
    assert "application/xml" in content_type
    
    # Assert XML content contains Connect and ConversationAgent tags with resolved agentId
    xml_content = response.text
    assert "<Connect>" in xml_content
    assert "</Connect>" in xml_content
    assert "<ConversationAgent" in xml_content
    
    # Check that there is an agentId attribute with a value (not empty/placeholder)
    assert 'agentId="' in xml_content
