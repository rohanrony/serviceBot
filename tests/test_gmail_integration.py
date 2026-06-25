import pytest
import os
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

# Force CONFIG_PATH override on portal module to prevent sandbox write blocks
import serviceBot.api.portal
serviceBot.api.portal.CONFIG_PATH = "/Users/rohanroy/.gemini/antigravity-ide/scratch/test_config.json"

from serviceBot.main import app
from serviceBot.db.connection import get_db_connection
from serviceBot.api.portal import load_config, save_config

client = TestClient(app)

@pytest.fixture(autouse=True)
def clean_gmail_config():
    # Save original config
    original_config = load_config()
    yield
    # Restore original config after tests
    save_config(original_config)

def test_get_gmail_config():
    """Verify that get_gmail_config returns the correct settings structure."""
    response = client.get("/api/v1/portal/gmail-config")
    assert response.status_code == 200
    data = response.json()
    assert "gmail_enabled" in data
    assert "gmail_sender" in data
    assert "gmail_recipient" in data
    assert "gmail_smtp_server" in data
    assert "gmail_smtp_port" in data
    assert "has_password" in data

def test_post_gmail_config():
    """Verify that update_gmail_config updates settings and encrypts passwords."""
    payload = {
        "gmail_enabled": True,
        "gmail_auth_type": "app_password",
        "gmail_sender": "test-sender@gmail.com",
        "gmail_password": "test-app-password-1234",
        "gmail_recipient": "test-recipient@gmail.com",
        "gmail_smtp_server": "smtp.gmail.com",
        "gmail_smtp_port": 587
    }
    response = client.post("/api/v1/portal/gmail-config", json=payload)
    assert response.status_code == 200
    
    # Reload config to verify encryption occurred
    config = load_config()
    assert config["gmail_enabled"] is True
    assert config["gmail_sender"] == "test-sender@gmail.com"
    assert config["gmail_recipient"] == "test-recipient@gmail.com"
    assert config["gmail_password"] != "test-app-password-1234"  # should be encrypted
    
    # Verify we can decrypt it back
    from serviceBot.services.encryption import decrypt_key
    decrypted = decrypt_key(config["gmail_password"])
    assert decrypted == "test-app-password-1234"

@patch("smtplib.SMTP")
def test_gmail_connection_test_endpoint(mock_smtp):
    """Verify SMTP connection test endpoint uses configured parameters and sends test email."""
    mock_instance = MagicMock()
    mock_smtp.return_value = mock_instance
    
    payload = {
        "gmail_enabled": True,
        "gmail_auth_type": "app_password",
        "gmail_sender": "test-sender@gmail.com",
        "gmail_password": "test-app-password-1234",
        "gmail_recipient": "test-recipient@gmail.com",
        "gmail_smtp_server": "smtp.gmail.com",
        "gmail_smtp_port": 587
    }
    
    response = client.post("/api/v1/portal/gmail-config/test", json=payload)
    assert response.status_code == 200
    assert response.json() == {"success": True}
    
    # Verify smtplib methods were called
    mock_smtp.assert_called_once_with("smtp.gmail.com", 587, timeout=10)
    mock_instance.login.assert_called_once_with("test-sender@gmail.com", "test-app-password-1234")
    assert mock_instance.sendmail.called

@patch("serviceBot.services.gmail.send_booking_notification")
def test_appointment_booking_triggers_email(mock_send_email):
    """Verify that booking an appointment through the voice tools endpoint triggers the email notification."""
    # Ensure customer/service request exists and clean up conflicts
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM crm_notes WHERE customer_id = 15 OR customer_id IN (SELECT id FROM customers WHERE phone IN ('555-987-6543', '5559876543'))")
        cursor.execute("DELETE FROM service_requests WHERE customer_id = 15 OR customer_id IN (SELECT id FROM customers WHERE phone IN ('555-987-6543', '5559876543'))")
        cursor.execute("DELETE FROM vehicles WHERE customer_id = 15 OR customer_id IN (SELECT id FROM customers WHERE phone IN ('555-987-6543', '5559876543'))")
        cursor.execute("DELETE FROM customers WHERE id = 15 OR phone IN ('555-987-6543', '5559876543')")
        
        cursor.execute("INSERT INTO customers (id, name, phone) VALUES (15, 'Booking Tester', '5559876543')")
        cursor.execute("INSERT INTO vehicles (id, customer_id, make, model, year) VALUES (5, 15, 'Honda', 'Civic', 2018)")
        cursor.execute("""
            INSERT INTO service_requests (id, customer_id, vehicle_id, service_type, issue_description, status) 
            VALUES (30, 15, 5, 'Brakes', 'Grinding noise', 'pending')
        """)
        # Seed staff agent
        cursor.execute("DELETE FROM staff_agents WHERE id = 1")
        cursor.execute("INSERT INTO staff_agents (id, name, role, email) VALUES (1, 'John Doe', 'Advisor', 'john@example.com')")
        conn.commit()

    payload = {
        "tool_call_id": "call_book_appt_test",
        "name": "book_appointment",
        "arguments": {
            "phone": "555-987-6543",
            "appointment_datetime": "2026-06-25 14:00:00",
            "service_type": "Brake Service & Repair"
        }
    }
    
    response = client.post("/api/v1/voice/tools", json=payload)
    assert response.status_code == 200
    assert response.json()["result"]["success"] is True
    
    # Verify email notification was triggered with correct parameters
    mock_send_email.assert_called_once()
    args, kwargs = mock_send_email.call_args
    assert args[0] == "appointment"
    details = args[1]
    assert details["customer_name"] == "Booking Tester"
    assert details["phone"] == "5559876543"
    assert details["vehicle"] == "2018 Honda Civic"
    assert details["service_type"] == "Brake Service & Repair"
    assert details["time"] == "2026-06-25 14:00:00"

@patch("serviceBot.services.encryption.decrypt_key")
def test_get_gmail_oauth_url_endpoint(mock_decrypt):
    """Verify auth-url endpoint returns correct structure and values."""
    mock_decrypt.return_value = "mock-client-id"
    response = client.get("/api/v1/portal/gmail/oauth/auth-url")
    assert response.status_code == 200
    data = response.json()
    assert "auth_url" in data
    assert "redirect_uri" in data
    assert "mock-client-id" in data["auth_url"]
    assert "/api/v1/portal/gmail/oauth/callback" in data["redirect_uri"]

@patch("serviceBot.services.encryption.decrypt_key")
@patch.dict(os.environ, {"GOOGLE_CLIENT_ID": "", "GMAIL_CLIENT_ID": ""})
def test_get_gmail_oauth_url_endpoint_missing_client_id(mock_decrypt):
    """Verify auth-url endpoint returns 400 when client ID is missing."""
    mock_decrypt.return_value = ""
    response = client.get("/api/v1/portal/gmail/oauth/auth-url")
    assert response.status_code == 400
    assert "Google Client ID is not configured" in response.json()["detail"]

@patch("httpx.post")
@patch("serviceBot.services.encryption.decrypt_key")
def test_gmail_oauth_callback_success(mock_decrypt, mock_post):
    """Verify successful OAuth callback exchanges code and saves tokens."""
    mock_decrypt.side_effect = lambda val: val  # return unencrypted
    
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "access_token": "new-access-token",
        "refresh_token": "new-refresh-token",
        "expires_in": 3600
    }
    mock_post.return_value = mock_response

    # Set mock credentials in config
    config = load_config()
    from serviceBot.services.encryption import encrypt_key
    config["gmail_client_id"] = encrypt_key("some-client-id")
    config["gmail_client_secret"] = encrypt_key("some-client-secret")
    save_config(config)

    response = client.get("/api/v1/portal/gmail/oauth/callback?code=test-code")
    assert response.status_code == 200
    assert "Google Account Connected!" in response.text

    # Verify new tokens are saved in config
    updated_config = load_config()
    assert updated_config["gmail_access_token"] != ""
    assert updated_config["gmail_refresh_token"] != ""

def test_gmail_oauth_callback_error_query_param():
    """Verify callback handles error parameter from Google redirect."""
    response = client.get("/api/v1/portal/gmail/oauth/callback?error=access_denied")
    assert response.status_code == 200
    assert "Authentication Failed" in response.text
    assert "access_denied" in response.text

@patch("httpx.post")
@patch("serviceBot.services.encryption.decrypt_key")
def test_gmail_oauth_callback_exchange_failure(mock_decrypt, mock_post):
    """Verify callback handles Google token endpoint failures gracefully."""
    mock_decrypt.side_effect = lambda val: val
    
    mock_response = MagicMock()
    mock_response.status_code = 400
    mock_response.text = "invalid_grant"
    mock_post.return_value = mock_response

    config = load_config()
    from serviceBot.services.encryption import encrypt_key
    config["gmail_client_id"] = encrypt_key("some-client-id")
    config["gmail_client_secret"] = encrypt_key("some-client-secret")
    save_config(config)

    response = client.get("/api/v1/portal/gmail/oauth/callback?code=bad-code")
    assert response.status_code == 200
    assert "Token Exchange Failed" in response.text
    assert "invalid_grant" in response.text

@patch("httpx.post")
@patch("serviceBot.services.gmail.decrypt_key")
def test_refresh_gmail_token_success(mock_decrypt, mock_post):
    """Verify refresh_gmail_token exchanges refresh token and updates config."""
    mock_decrypt.side_effect = lambda val: val
    
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "access_token": "refreshed-access-token",
        "expires_in": 3600
    }
    mock_post.return_value = mock_response

    config = load_config()
    from serviceBot.services.encryption import encrypt_key
    config["gmail_client_id"] = encrypt_key("client-id")
    config["gmail_client_secret"] = encrypt_key("client-secret")
    config["gmail_refresh_token"] = encrypt_key("refresh-token")
    save_config(config)

    from serviceBot.services.gmail import refresh_gmail_token
    token = refresh_gmail_token()
    assert token == "refreshed-access-token"

    updated_config = load_config()
    from serviceBot.services.encryption import decrypt_key
    assert decrypt_key(updated_config["gmail_access_token"]) == "refreshed-access-token"

@patch("httpx.post")
@patch("serviceBot.services.gmail.get_gmail_access_token")
def test_send_gmail_api_email_success(mock_get_token, mock_post):
    """Verify send_gmail_api_email makes a successful REST request to Gmail API."""
    mock_get_token.return_value = "valid-token"
    
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_post.return_value = mock_response

    from serviceBot.services.gmail import send_gmail_api_email
    success = send_gmail_api_email(
        sender="sender@gmail.com",
        recipient="recipient@gmail.com",
        subject="OAuth Test",
        html_body="<p>Test</p>"
    )
    assert success is True
    
    mock_post.assert_called_once()
    args, kwargs = mock_post.call_args
    assert "https://gmail.googleapis.com/gmail/v1/users/me/messages/send" in args[0]
    assert kwargs["headers"]["Authorization"] == "Bearer valid-token"

