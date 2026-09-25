"""Unit and integration tests for ElevenLabs call sync service."""

import pytest
from unittest.mock import patch, MagicMock

from serviceBot.services.call_sync import sync_recent_elevenlabs_calls, _ingest_conversation
from serviceBot.db.connection import get_db_connection, dict_cursor


@pytest.fixture(autouse=True)
def clean_db():
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("DELETE FROM crm_notes WHERE call_id LIKE 'conv_sync_test_%';")
            cursor.execute("DELETE FROM webhook_events WHERE provider = 'elevenlabs_reconciliation' AND event_id LIKE 'conv_sync_test_%';")
            cursor.execute("DELETE FROM customers WHERE phone = '+15551234567';")
            conn.commit()
    yield
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("DELETE FROM crm_notes WHERE call_id LIKE 'conv_sync_test_%';")
            cursor.execute("DELETE FROM webhook_events WHERE provider = 'elevenlabs_reconciliation' AND event_id LIKE 'conv_sync_test_%';")
            cursor.execute("DELETE FROM customers WHERE phone = '+15551234567';")
            conn.commit()


def test_sync_skips_when_missing_credentials(monkeypatch):
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.delenv("ELEVENLABS_AGENT_ID", raising=False)
    assert sync_recent_elevenlabs_calls() == 0


@patch("httpx.Client.get")
def test_sync_reconciles_missing_calls(mock_get, monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-api-key")
    monkeypatch.setenv("ELEVENLABS_AGENT_ID", "agent-test-123")

    # Mock list response
    list_response = MagicMock()
    list_response.status_code = 200
    list_response.json.return_value = {
        "conversations": [
            {
                "conversation_id": "conv_sync_test_001",
                "status": "done",
                "start_time_unix_secs": 1700000000
            }
        ]
    }

    # Mock detail response
    detail_response = MagicMock()
    detail_response.status_code = 200
    detail_response.json.return_value = {
        "conversation_id": "conv_sync_test_001",
        "metadata": {
            "phone_call": {
                "external_number": "+15551234567"
            }
        },
        "transcript": [
            {"role": "user", "message": "I need an oil change."},
            {"role": "agent", "message": "I can schedule that for you."}
        ],
        "analysis": {
            "transcript_summary": "Customer requested an oil change."
        }
    }

    mock_get.side_effect = [list_response, detail_response]

    synced = sync_recent_elevenlabs_calls(limit=5)
    assert synced == 1

    # Verify database insertion
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("SELECT call_id, summary, transcript FROM crm_notes WHERE call_id = %s;", ("conv_sync_test_001",))
            note = cursor.fetchone()
            assert note is not None
            assert note["call_id"] == "conv_sync_test_001"
            assert "User: I need an oil change." in note["transcript"]

    # Second run should skip since it is already in DB
    mock_get.side_effect = [list_response]
    synced_second = sync_recent_elevenlabs_calls(limit=5)
    assert synced_second == 0
