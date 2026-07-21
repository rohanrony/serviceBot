import pytest
import time
from unittest.mock import patch, MagicMock
from serviceBot.services.encryption import encrypt_key
from serviceBot.services.gmail import (
    refresh_gmail_token,
    get_gmail_access_token,
    send_gmail_api_email,
    send_smtp_email,
    send_booking_notification
)

@patch("httpx.post")
@patch("serviceBot.services.gmail.load_config")
@patch("serviceBot.services.gmail.save_config")
def test_refresh_gmail_token_success(mock_save, mock_load, mock_post):
    """Verify refresh_gmail_token returns fresh token and saves config when HTTP 200."""
    mock_load.return_value = {
        "gmail_client_id": encrypt_key("dummy_id"),
        "gmail_client_secret": encrypt_key("dummy_secret"),
        "gmail_refresh_token": encrypt_key("dummy_refresh")
    }
    
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "access_token": "fresh_access_token_abc",
        "expires_in": 3600
    }
    mock_post.return_value = mock_response
    
    token = refresh_gmail_token()
    assert token == "fresh_access_token_abc"
    assert mock_save.called

@patch("httpx.post")
@patch("serviceBot.services.gmail.load_config")
def test_refresh_gmail_token_failure(mock_load, mock_post):
    """Verify refresh_gmail_token returns None on HTTP error."""
    mock_load.return_value = {
        "gmail_client_id": encrypt_key("dummy_id"),
        "gmail_client_secret": encrypt_key("dummy_secret"),
        "gmail_refresh_token": encrypt_key("dummy_refresh")
    }
    
    mock_response = MagicMock()
    mock_response.status_code = 400
    mock_response.text = "Invalid Refresh Token"
    mock_post.return_value = mock_response
    
    token = refresh_gmail_token()
    assert token is None

@patch("serviceBot.services.gmail.load_config")
@patch("serviceBot.services.gmail.decrypt_key")
def test_get_gmail_access_token_valid(mock_decrypt, mock_load):
    """Verify get_gmail_access_token returns cached token if not expired."""
    mock_load.return_value = {
        "gmail_access_token": "encrypted_token",
        "gmail_token_expires_at": time.time() + 1000
    }
    mock_decrypt.return_value = "cached_token_123"
    
    assert get_gmail_access_token() == "cached_token_123"

@patch("serviceBot.services.gmail.get_gmail_access_token")
@patch("httpx.post")
def test_send_gmail_api_email(mock_post, mock_get_token):
    """Verify send_gmail_api_email constructs MIME and makes POST call."""
    mock_get_token.return_value = "dummy_token"
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_post.return_value = mock_response
    
    res = send_gmail_api_email(
        sender="sender@example.com",
        recipient="recipient@example.com",
        subject="Test Subject",
        html_body="<h1>Hello</h1>"
    )
    assert res is True
    assert mock_post.called

@patch("smtplib.SMTP")
def test_send_smtp_email(mock_smtp):
    """Verify send_smtp_email interacts correctly with smtplib.SMTP."""
    mock_instance = MagicMock()
    mock_smtp.return_value = mock_instance
    
    res = send_smtp_email(
        sender="sender@example.com",
        encrypted_password=encrypt_key("pwd"), # must be valid encrypted string
        recipient="recipient@example.com",
        server="smtp.example.com",
        port=587,
        subject="SMTP Test",
        html_body="<p>Body</p>"
    )
    
    assert res is True
    assert mock_instance.starttls.called
    assert mock_instance.login.called
    assert mock_instance.sendmail.called

@patch("serviceBot.services.gmail.send_gmail_api_email")
@patch("serviceBot.services.gmail.load_config")
def test_send_booking_notification(mock_load, mock_send_api):
    """Verify send_booking_notification formats and routes booking details."""
    mock_load.return_value = {
        "gmail_enabled": True, # enable notifications in config
        "gmail_sender": "sender@example.com",
        "gmail_recipient": "recipient@example.com",
        "gmail_auth_type": "oauth2", # select oauth2 system delivery
        "email_delivery_method": "gmail_api",
        "gmail_api_sender_email": "sender@example.com",
        "notifications_recipient_email": "recipient@example.com"
    }
    mock_send_api.return_value = True
    
    details = {
        "customer_name": "Alice Smith",
        "phone": "5551234567",
        "vehicle": "2021 Toyota Camry",
        "service_type": "Oil Change",
        "time": "2026-06-30 09:00:00"
    }
    
    res = send_booking_notification("appointment", details)
    assert res is True
    assert mock_send_api.called
    
    # Check that HTML body mentions appointment details
    _, kwargs = mock_send_api.call_args
    assert "Alice Smith" in kwargs.get("html_body", "")
    assert "2021 Toyota Camry" in kwargs.get("html_body", "")
