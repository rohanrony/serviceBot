import pytest
from fastapi.testclient import TestClient
from serviceBot.main import app
from serviceBot.db.connection import get_db_connection

client = TestClient(app)

from unittest.mock import patch

@pytest.fixture(autouse=True)
def clean_db():
    # Setup: clean test customer and CRM notes
    yield
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM crm_notes WHERE call_id = 'conv_test_123';")
        cursor.execute("DELETE FROM service_requests WHERE customer_id IN (SELECT id FROM customers WHERE phone = '+15559998888');")
        cursor.execute("DELETE FROM customers WHERE phone = '+15559998888';")
        conn.commit()

@patch("serviceBot.api.telephony.generate_service_summary")
def test_post_call_webhook_saves_data(mock_summarize):
    mock_summarize.return_value = "The customer requested a brake repair."
    # Prepare the ElevenLabs post-call transcription payload
    payload = {
        "type": "post_call_transcription",
        "event_timestamp": 1700000000,
        "data": {
            "conversation_id": "conv_test_123",
            "agent_id": "agent_test_123",
            "analysis": {
                "summary": "The customer requested a brake repair."
            },
            "metadata": {
                "from_number": "+15559998888"
            },
            "transcript": [
                {
                    "role": "user",
                    "message": "I need to fix my brakes."
                },
                {
                    "role": "agent",
                    "message": "I can help with that."
                }
            ]
        }
    }
    
    # Send request to endpoint
    response = client.post("/api/v1/telephony/webhook", json=payload)
    assert response.status_code == 200
    assert response.json() == {"success": True}
    
    # Verify database state
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # Customer should be auto-created
        cursor.execute("SELECT id, name, phone FROM customers WHERE phone = ?;", ("+15559998888",))
        customer = cursor.fetchone()
        assert customer is not None
        assert customer["name"] == "Unknown Customer"
        customer_id = customer["id"]
        
        # CRM note should be created
        cursor.execute("SELECT call_id, customer_id, summary, transcript FROM crm_notes WHERE call_id = ?;", ("conv_test_123",))
        note = cursor.fetchone()
        assert note is not None
        assert note["customer_id"] == customer_id
        assert note["summary"] == "The customer requested a brake repair."
        assert "User: I need to fix my brakes." in note["transcript"]
        assert "Agent: I can help with that." in note["transcript"]


@patch("serviceBot.api.telephony.extract_callback_from_transcript")
@patch("serviceBot.api.telephony.generate_service_summary")
def test_post_call_webhook_extracts_callback(mock_summarize, mock_extract_callback):
    mock_summarize.return_value = "The customer requested a callback."
    mock_extract_callback.return_value = {
        "preferred_time": "tomorrow morning at 8:00 AM",
        "service_type": "Brake repair",
        "issue_description": "Grinding noise"
    }
    
    payload = {
        "type": "post_call_transcription",
        "event_timestamp": 1700000000,
        "data": {
            "conversation_id": "conv_test_123",
            "agent_id": "agent_test_123",
            "analysis": {
                "summary": "The customer requested a callback."
            },
            "metadata": {
                "from_number": "+15559998888"
            },
            "transcript": [
                {
                    "role": "user",
                    "message": "Can you call me back tomorrow morning at 8:00 AM?"
                }
            ]
        }
    }
    
    # Send request to endpoint
    response = client.post("/api/v1/telephony/webhook", json=payload)
    assert response.status_code == 200
    assert response.json() == {"success": True}
    
    # Verify database state
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # Get customer ID
        cursor.execute("SELECT id FROM customers WHERE phone = ?;", ("+15559998888",))
        customer = cursor.fetchone()
        assert customer is not None
        customer_id = customer["id"]
        
        # Callback request should be created
        cursor.execute("SELECT customer_id, booking_time, booking_type FROM service_requests WHERE customer_id = ?;", (customer_id,))
        callback = cursor.fetchone()
        assert callback is not None
        assert callback["booking_time"] == "tomorrow morning at 8:00 AM"
        assert callback["booking_type"] == "callback"
