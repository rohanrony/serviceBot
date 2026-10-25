import base64
import html
import re
import pytest
import time
from email import message_from_bytes, policy
from unittest.mock import patch, MagicMock
from serviceBot.services.encryption import encrypt_key
from serviceBot.services.gmail import (
    refresh_gmail_token,
    get_gmail_access_token,
    send_gmail_api_email,
    send_gmail_via_api,
    send_booking_notification,
    send_admin_notification,
    create_admin_calendar_event
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

@patch("serviceBot.services.gmail.load_config")
@patch("serviceBot.services.gmail.get_gmail_access_token")
@patch("httpx.post")
def test_send_gmail_api_email(mock_post, mock_get_token, mock_load):
    """Verify send_gmail_api_email constructs branded MIME and makes POST call."""
    mock_load.return_value = {
        "business_name": "Davidson CarCare"
    }
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
    _, kwargs = mock_post.call_args
    raw_b64 = kwargs["json"]["raw"]
    raw_bytes = base64.urlsafe_b64decode(raw_b64)
    msg = message_from_bytes(raw_bytes, policy=policy.default)
    assert msg["From"] == "Davidson CarCare <sender@example.com>"
    assert msg["Subject"] == "Test Subject"
    assert "serviceBot" not in msg["From"]
    assert "BayFull" not in msg["From"]

@patch("serviceBot.services.gmail.get_gmail_access_token", return_value="oauth-token")
@patch("httpx.post")
def test_send_gmail_api_email_reports_provider_failure(mock_post, mock_get_token):
    mock_post.return_value.status_code = 403
    mock_post.return_value.text = "permission denied"
    with pytest.raises(Exception, match="HTTP 403"):
        send_gmail_api_email(
            sender="sender@example.com",
            recipient="recipient@example.com",
            subject="OAuth Test",
            html_body="<p>Body</p>"
        )

@patch("serviceBot.services.gmail.send_gmail_api_email")
@patch("serviceBot.services.gmail.load_config")
def test_send_booking_notification(mock_load, mock_send_api):
    """Verify send_booking_notification formats and routes booking details with business branding."""
    mock_load.return_value = {
        "gmail_enabled": True, # enable notifications in config
        "gmail_sender": "sender@example.com",
        "gmail_recipient": "recipient@example.com",
        "gmail_auth_type": "oauth2", # select oauth2 system delivery
        "email_delivery_method": "gmail_api",
        "gmail_api_sender_email": "sender@example.com",
        "notifications_recipient_email": "recipient@example.com",
        "business_name": "Davidson CarCare"
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
    
    _, kwargs = mock_send_api.call_args
    assert "Alice Smith" in kwargs.get("html_body", "")
    assert "2021 Toyota Camry" in kwargs.get("html_body", "")
    subject = kwargs.get("subject", "")
    html_body = kwargs.get("html_body", "")
    plain_body = kwargs.get("plain_body", "")
    assert "[Davidson CarCare]" in subject
    assert "serviceBot" not in subject
    assert "BayFull" not in subject
    assert "Davidson CarCare" in html_body
    assert "serviceBot" not in html_body
    assert "BayFull" not in html_body
    assert "Davidson CarCare" in plain_body
    assert "serviceBot" not in plain_body
    assert "BayFull" not in plain_body

@patch("serviceBot.services.gmail.send_gmail_api_email")
@patch("serviceBot.services.gmail.load_config")
def test_send_admin_notification(mock_load, mock_send_api):
    """Verify send_admin_notification sends email with assigned mechanic info and business branding."""
    mock_load.return_value = {
        "gmail_enabled": True,
        "gmail_routine_admin_copies_enabled": True,
        "gmail_sender": "sender@example.com",
        "gmail_recipient": "admin@example.com",
        "gmail_auth_type": "oauth2",
        "business_name": "Davidson CarCare"
    }
    mock_send_api.return_value = True

    details = {
        "customer_name": "Bob Johnson",
        "phone": "5559876543",
        "vehicle": "2020 Ford F-150",
        "service_type": "Brake Replacement",
        "time": "2026-07-01 10:00:00"
    }

    res = send_admin_notification(
        booking_type="appointment",
        details=details,
        mechanic_name="John Mechanic",
        mechanic_email="john@example.com"
    )
    assert res is True
    assert mock_send_api.called
    _, kwargs = mock_send_api.call_args
    assert kwargs.get("recipient") == "admin@example.com"
    assert "John Mechanic" in kwargs.get("html_body", "")
    assert "john@example.com" in kwargs.get("html_body", "")
    subject = kwargs.get("subject", "")
    html_body = kwargs.get("html_body", "")
    plain_body = kwargs.get("plain_body", "")
    assert "[Admin Copy]" in subject
    assert "[Davidson CarCare]" in subject
    assert "serviceBot" not in subject
    assert "BayFull" not in subject
    assert "Davidson CarCare" in html_body
    assert "serviceBot" not in html_body
    assert "BayFull" not in html_body
    assert "Davidson CarCare" in plain_body
    assert "serviceBot" not in plain_body
    assert "BayFull" not in plain_body


@patch("serviceBot.services.gmail.send_gmail_api_email")
@patch("serviceBot.services.gmail.load_config")
def test_routine_admin_copies_are_disabled_by_default(mock_load, mock_send_api):
    """A legacy config without the opt-in never sends routine admin copies."""
    mock_load.return_value = {
        "gmail_enabled": True,
        "gmail_sender": "sender@example.com",
        "gmail_recipient": "admin@example.com",
    }

    routine_event_types = (
        "appointment",
        "callback",
        "reschedule",
        "reassign",
        "cancel",
        "cancelled_by_customer",
        "cancelled_by_admin",
    )
    for event_type in routine_event_types:
        assert send_admin_notification(event_type, {}) is False

    assert mock_load.call_count == len(routine_event_types)
    mock_send_api.assert_not_called()


@patch("serviceBot.services.gmail.send_gmail_api_email")
@patch("serviceBot.services.gmail.load_config")
def test_routine_admin_copies_send_when_enabled(mock_load, mock_send_api):
    """The Admin Mail opt-in retains routine-copy delivery for lifecycle events."""
    mock_load.return_value = {
        "gmail_enabled": True,
        "gmail_routine_admin_copies_enabled": True,
        "gmail_sender": "sender@example.com",
        "gmail_recipient": "admin@example.com",
    }
    mock_send_api.return_value = True

    routine_event_types = (
        "appointment",
        "callback",
        "reschedule",
        "reassign",
        "cancel",
    )
    for event_type in routine_event_types:
        assert send_admin_notification(event_type, {}) is True

    assert mock_send_api.call_count == len(routine_event_types)


@patch("serviceBot.services.gmail.load_config")
@patch("httpx.post")
@patch("serviceBot.services.gmail.get_gmail_access_token")
def test_create_admin_calendar_event(mock_get_token, mock_post, mock_load):
    """Verify create_admin_calendar_event builds correct payload for admin calendar with business branding."""
    mock_load.return_value = {
        "business_name": "Davidson CarCare"
    }
    mock_get_token.return_value = "admin_access_token"
    mock_resp = MagicMock()
    mock_resp.status_code = 201
    mock_post.return_value = mock_resp

    res = create_admin_calendar_event(
        customer_name="Alice Smith",
        service_type="Oil Change",
        issue_description="Low oil warning light",
        slot_datetime_str="2026-07-25 14:00:00",
        mechanic_name="John Mechanic",
        duration_minutes=60
    )
    assert res is True
    assert mock_post.called
    _, kwargs = mock_post.call_args
    json_body = kwargs.get("json", {})
    summary = json_body.get("summary", "")
    desc = json_body.get("description", "")
    assert "Alice Smith" in summary
    assert "John Mechanic" in summary
    assert summary.startswith("Davidson CarCare Booking -")
    assert "serviceBot" not in summary
    assert "BayFull" not in summary
    assert "Low oil warning light" in desc
    assert "Davidson CarCare" in desc
    assert "serviceBot" not in desc
    assert "BayFull" not in desc


@patch("serviceBot.services.gmail.load_config")
@patch("httpx.post")
@patch("serviceBot.services.gmail.get_gmail_access_token")
def test_create_admin_calendar_event_callback(mock_get_token, mock_post, mock_load):
    """Verify create_admin_calendar_event callback title/description branding."""
    mock_load.return_value = {
        "business_name": "Davidson CarCare"
    }
    mock_get_token.return_value = "admin_access_token"
    mock_resp = MagicMock()
    mock_resp.status_code = 201
    mock_post.return_value = mock_resp

    res = create_admin_calendar_event(
        customer_name="Alice Smith",
        service_type="General Inquiry Callback",
        issue_description="Question about warranty",
        slot_datetime_str="2026-07-25 14:00:00",
        mechanic_name="John Mechanic",
        duration_minutes=30,
        booking_type="callback"
    )
    assert res is True
    assert mock_post.called
    _, kwargs = mock_post.call_args
    json_body = kwargs.get("json", {})
    summary = json_body.get("summary", "")
    desc = json_body.get("description", "")
    assert summary.startswith("Davidson CarCare Callback -")
    assert "serviceBot" not in summary
    assert "BayFull" not in summary
    assert "Davidson CarCare" in desc
    assert "serviceBot" not in desc
    assert "BayFull" not in desc


@patch("serviceBot.services.gmail.load_config")
@patch("serviceBot.services.google_calendar.get_user_google_credentials")
@patch("httpx.post")
def test_send_gmail_via_api_connected_agent_branding(mock_post, mock_creds, mock_load):
    """Verify connected-agent sender MIME identifies configured business while preserving sender address."""
    mock_load.return_value = {
        "business_name": "Davidson CarCare"
    }
    mock_creds.return_value = {
        "email": "agent@example.com",
        "access_token": "agent_token_123",
        "granted_scopes": ["https://www.googleapis.com/auth/gmail.send"]
    }
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_post.return_value = mock_response

    res = send_gmail_via_api(
        agent_id=42,
        recipient="customer@example.com",
        subject="Booking Confirmation",
        html_body="<p>Confirmed</p>",
        plain_body="Confirmed"
    )
    assert res is True
    assert mock_post.called
    _, kwargs = mock_post.call_args
    raw_b64 = kwargs["json"]["raw"]
    raw_bytes = base64.urlsafe_b64decode(raw_b64)
    msg = message_from_bytes(raw_bytes, policy=policy.default)
    assert msg["From"] == "Davidson CarCare <agent@example.com>"
    assert "serviceBot" not in msg["From"]
    assert "BayFull" not in msg["From"]


@patch("serviceBot.services.gmail.load_config")
@patch("serviceBot.services.gmail.get_gmail_access_token")
@patch("httpx.post")
def test_business_branding_alternate_name(mock_post, mock_get_token, mock_load):
    """Verify alternate business name avoids hardcoding Davidson."""
    mock_load.return_value = {
        "business_name": "Apex Auto Works"
    }
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
    _, kwargs = mock_post.call_args
    raw_b64 = kwargs["json"]["raw"]
    raw_bytes = base64.urlsafe_b64decode(raw_b64)
    msg = message_from_bytes(raw_bytes, policy=policy.default)
    assert msg["From"] == "Apex Auto Works <sender@example.com>"
    assert "Davidson CarCare" not in msg["From"]
    assert "serviceBot" not in msg["From"]


@patch("serviceBot.services.gmail.load_config")
@patch("serviceBot.services.gmail.get_gmail_access_token")
@patch("httpx.post")
@pytest.mark.parametrize("invalid_name", [None, "", "   ", 12345])
def test_business_branding_missing_or_blank_uses_neutral_service_notifications(
    mock_post, mock_get_token, mock_load, invalid_name
):
    """Verify missing, blank or non-string business name falls back to neutral Service Notifications."""
    mock_load.return_value = {
        "business_name": invalid_name
    }
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
    _, kwargs = mock_post.call_args
    raw_b64 = kwargs["json"]["raw"]
    raw_bytes = base64.urlsafe_b64decode(raw_b64)
    msg = message_from_bytes(raw_bytes, policy=policy.default)
    assert msg["From"] == "Service Notifications <sender@example.com>"
    assert "serviceBot" not in msg["From"]
    assert "BayFull" not in msg["From"]


@patch("serviceBot.services.gmail.load_config")
@patch("serviceBot.services.gmail.get_gmail_access_token")
@patch("httpx.post")
def test_business_branding_crlf_and_html_safety(mock_post, mock_get_token, mock_load):
    """Verify CRLF characters are stripped from headers and HTML metacharacters are escaped."""
    mock_load.return_value = {
        "business_name": "Care & Repair\r\n<script>alert('xss')</script>"
    }
    mock_get_token.return_value = "dummy_token"
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_post.return_value = mock_response

    res = send_gmail_api_email(
        sender="sender@example.com",
        recipient="recipient@example.com",
        subject="Test\r\nSubject",
        html_body="<h1>Hello</h1>"
    )
    assert res is True
    _, kwargs = mock_post.call_args
    raw_b64 = kwargs["json"]["raw"]
    raw_bytes = base64.urlsafe_b64decode(raw_b64)
    raw_text = raw_bytes.decode("utf-8", errors="replace")
    # Verify no raw newline injection inside From or Subject header lines
    for line in raw_text.splitlines():
        if line.startswith("From:"):
            assert "\r" not in line and "\n" not in line
            assert "Care & Repair" in line
            assert "<script>" not in line
        if line.startswith("Subject:"):
            assert "\r" not in line and "\n" not in line

    # Also verify HTML escaping in booking notification rendering
    with patch("serviceBot.services.gmail.send_gmail_api_email") as mock_send_email:
        mock_load.return_value = {
            "gmail_enabled": True,
            "gmail_sender": "sender@example.com",
            "gmail_recipient": "recipient@example.com",
            "business_name": "Care & Repair <script>alert('xss')</script>"
        }
        send_booking_notification("appointment", {"customer_name": "Bob"})
        mock_send_email.assert_called_once()
        html_arg = mock_send_email.call_args.kwargs.get("html_body", "")
        assert "&lt;script&gt;" in html_arg
        assert "<script>alert" not in html_arg
