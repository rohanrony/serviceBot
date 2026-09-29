import os
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from serviceBot.main import app
from serviceBot.db.queries import (
    is_agent_whatsapp_connected,
    get_agent_whatsapp_status,
    disconnect_agent_whatsapp
)

client = TestClient(app)


def test_html_dom_contains_agent_whatsapp_components():
    """Verify that index.html contains all agent WhatsApp status and control elements."""
    html_path = os.path.join(os.path.dirname(__file__), "..", "serviceBot", "static", "index.html")
    assert os.path.exists(html_path)

    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()

    # Agent WhatsApp Connection Status elements
    assert 'id="agent-whatsapp-status-badge"' in html
    assert 'id="connect-agent-whatsapp-btn"' in html
    assert 'id="agent-whatsapp-warning"' in html
    assert 'Agent WhatsApp not connected' in html

    # Edit Agent Drawer WhatsApp badge
    assert 'id="edit-agent-whatsapp-badge"' in html

    # QR Onboard Modal Verify button
    assert 'id="qr-modal-verify-btn"' in html


def test_js_app_contains_agent_whatsapp_logic():
    """Verify that app.js registers and manages agent WhatsApp status and interaction."""
    js_path = os.path.join(os.path.dirname(__file__), "..", "serviceBot", "static", "app.js")
    assert os.path.exists(js_path)

    with open(js_path, "r", encoding="utf-8") as f:
        js = f.read()

    # Check status UI handling
    assert "agent-whatsapp-status-badge" in js
    assert "connect-agent-whatsapp-btn" in js
    assert "agent-whatsapp-warning" in js
    assert "edit-agent-whatsapp-badge" in js
    assert "qr-modal-verify-btn" in js

    # Check Service Request WhatsApp warning
    assert "⚠️ WhatsApp Disconnected" in js

    # Check staff dropdown WhatsApp metadata
    assert "whatsappConnected" in js


def test_is_agent_whatsapp_connected_helper():
    """Test the is_agent_whatsapp_connected logic with various phone formats."""
    # Empty or None should return False
    assert is_agent_whatsapp_connected("") is False
    assert is_agent_whatsapp_connected(None) is False
    assert is_agent_whatsapp_connected("   ") is False

    mock_records = [
        {"phone_number": "+14242704893", "whatsapp_onboarded": True},
        {"phone_number": "+15551234567", "whatsapp_onboarded": False},
    ]

    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = mock_records
    mock_conn = MagicMock()

    with patch("serviceBot.db.queries.get_db_connection") as mock_get_conn, \
         patch("serviceBot.db.queries.dict_cursor") as mock_dict_cursor:
        mock_get_conn.return_value.__enter__.return_value = mock_conn
        mock_dict_cursor.return_value.__enter__.return_value = mock_cursor

        # Exact match
        assert is_agent_whatsapp_connected("+14242704893") is True
        # Stripped digits match
        assert is_agent_whatsapp_connected("14242704893") is True
        # 10-digit match
        assert is_agent_whatsapp_connected("4242704893") is True
        # Formatted match
        assert is_agent_whatsapp_connected("(424) 270-4893") is True
        # Unverified number
        assert is_agent_whatsapp_connected("+15551234567") is False
        # Unknown number
        assert is_agent_whatsapp_connected("+19999999999") is False


def test_get_agent_whatsapp_status_helper():
    """Test get_agent_whatsapp_status for agents with and without phones."""
    mock_cursor = MagicMock()
    mock_conn = MagicMock()

    with patch("serviceBot.db.queries.get_db_connection") as mock_get_conn, \
         patch("serviceBot.db.queries.dict_cursor") as mock_dict_cursor:
        mock_get_conn.return_value.__enter__.return_value = mock_conn
        mock_dict_cursor.return_value.__enter__.return_value = mock_cursor

        # Case 1: Agent not found
        mock_cursor.fetchone.return_value = None
        status = get_agent_whatsapp_status(999)
        assert status["is_connected"] is False
        assert status["has_phone"] is False
        assert status["phone_number"] is None

        # Case 2: Agent has no phone
        mock_cursor.fetchone.return_value = {"id": 1, "name": "Agent No Phone", "phone_number": None}
        status = get_agent_whatsapp_status(1)
        assert status["is_connected"] is False
        assert status["has_phone"] is False

        # Case 3: Agent has phone and is onboarded
        mock_cursor.fetchone.side_effect = [
            {"id": 2, "name": "Agent Connected", "phone_number": "+14242704893"},
            {"whatsapp_onboarded_at": None}
        ]
        with patch("serviceBot.db.queries.is_agent_whatsapp_connected", return_value=True):
            status = get_agent_whatsapp_status(2)
            assert status["is_connected"] is True
            assert status["has_phone"] is True
            assert status["phone_number"] == "+14242704893"


def test_disconnect_agent_whatsapp_helper():
    """Test disconnect_agent_whatsapp marks whatsapp_onboarded as False."""
    mock_cursor = MagicMock()
    mock_conn = MagicMock()

    with patch("serviceBot.db.queries.get_db_connection") as mock_get_conn, \
         patch("serviceBot.db.queries.dict_cursor") as mock_dict_cursor:
        mock_get_conn.return_value.__enter__.return_value = mock_conn
        mock_dict_cursor.return_value.__enter__.return_value = mock_cursor

        mock_cursor.fetchone.return_value = {"id": 3, "name": "Agent 3", "phone_number": "+14242704893"}
        res = disconnect_agent_whatsapp(3)
        assert res["success"] is True
        assert res["is_connected"] is False
        assert mock_conn.commit.called


def test_agent_whatsapp_endpoints():
    """Test the API endpoints for fetching and disconnecting agent WhatsApp status."""
    with patch("serviceBot.db.queries.get_agent_whatsapp_status") as mock_status, \
         patch("serviceBot.db.queries.disconnect_agent_whatsapp") as mock_disc:
        
        mock_status.return_value = {
            "agent_id": 5,
            "has_phone": True,
            "phone_number": "+14242704893",
            "is_connected": False,
            "whatsapp_onboarded_at": None
        }
        res = client.get("/api/v1/portal/agents/5/whatsapp/status")
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert data["is_connected"] is False
        assert data["has_phone"] is True

        mock_disc.return_value = {"success": True, "agent_id": 5, "is_connected": False}
        res_disc = client.post("/api/v1/portal/agents/5/whatsapp/disconnect")
        assert res_disc.status_code == 200
        assert res_disc.json()["success"] is True
        assert res_disc.json()["is_connected"] is False
