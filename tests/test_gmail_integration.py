import datetime as dt_mod
import json
import os
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

# Force CONFIG_PATH override on portal module to prevent sandbox write blocks
import serviceBot.api.portal
serviceBot.api.portal.CONFIG_PATH = "/Users/rohanroy/.gemini/antigravity-ide/scratch/test_config.json"

from serviceBot.main import app
from serviceBot.db.connection import dict_cursor, get_db_connection
from serviceBot.api.portal import load_config, save_config

client = TestClient(app)


def _future_business_datetime(hour: int = 14, days_ahead: int = 21) -> str:
    candidate = dt_mod.date.today() + dt_mod.timedelta(days=days_ahead)
    while candidate.weekday() > 4:
        candidate += dt_mod.timedelta(days=1)
    return f"{candidate.isoformat()} {hour:02d}:00:00"


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
def test_appointment_booking_queues_email_notification(mock_send_email):
    """Booking commits locally and persists its email work for outbox delivery."""
    booking_time = _future_business_datetime()
    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                """
                DELETE FROM outbox_notifications
                WHERE request_id IN (
                    SELECT sr.id
                    FROM service_requests sr
                    JOIN customers c ON c.id = sr.customer_id
                    WHERE c.phone IN ('555-987-6543', '5559876543')
                );
                """
            )
            cursor.execute("DELETE FROM crm_notes WHERE customer_id IN (SELECT id FROM customers WHERE phone IN ('555-987-6543', '5559876543'))")
            cursor.execute("DELETE FROM service_requests WHERE customer_id IN (SELECT id FROM customers WHERE phone IN ('555-987-6543', '5559876543'))")
            cursor.execute("DELETE FROM vehicles WHERE customer_id IN (SELECT id FROM customers WHERE phone IN ('555-987-6543', '5559876543'))")
            cursor.execute("DELETE FROM customers WHERE phone IN ('555-987-6543', '5559876543')")

            cursor.execute(
                "INSERT INTO customers (name, phone) VALUES ('Booking Tester', '5559876543') RETURNING id;"
            )
            customer_id = cursor.fetchone()["id"]
            cursor.execute(
                """
                INSERT INTO vehicles (customer_id, make, model, year)
                VALUES (%s, 'Honda', 'Civic', 2018)
                RETURNING id;
                """,
                (customer_id,),
            )
            vehicle_id = cursor.fetchone()["id"]
            cursor.execute(
                """
                INSERT INTO service_requests (customer_id, vehicle_id, service_type, issue_description, status)
                VALUES (%s, %s, 'Brakes', 'Grinding noise', 'pending')
                RETURNING id;
                """,
                (customer_id, vehicle_id),
            )
            service_request_id = cursor.fetchone()["id"]
            cursor.execute("UPDATE staff_agents SET email = 'john@example.com' WHERE id = 1;")
            cursor.execute(
                """
                INSERT INTO mock_calendar_slots (slot_datetime, is_booked, staff_agent_id)
                VALUES (%s, false, 1)
                ON CONFLICT (slot_datetime, staff_agent_id) DO NOTHING;
                """,
                (booking_time,),
            )
            cursor.execute(
                """
                INSERT INTO services (name, description, price_range, duration_minutes)
                VALUES ('Brake Service & Repair', 'Brake inspection and repair', '$199-450 per axle', 90);
                """
            )
        conn.commit()

    payload = {
        "tool_call_id": "call_book_appt_test",
        "name": "book_appointment",
        "arguments": {
            "phone": "555-987-6543",
            "appointment_datetime": booking_time,
            "service_type": "Brake Service & Repair",
        },
    }

    response = client.post("/api/v1/voice/tools", json=payload)
    assert response.status_code == 200
    result = response.json()["result"]
    assert result["success"] is True
    assert result["appointment_id"] == service_request_id
    assert "queued" in result["message"].lower()
    mock_send_email.assert_not_called()

    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute(
                """
                SELECT event_type, payload
                FROM outbox_notifications
                WHERE request_id = %s
                ORDER BY id;
                """,
                (result["appointment_id"],),
            )
            queued = cursor.fetchall()

    assert [row["event_type"] for row in queued] == [
        "calendar_projection",
        "booking_notification",
    ]
    booking_event = queued[-1]["payload"]
    if isinstance(booking_event, str):
        booking_event = json.loads(booking_event)

    assert booking_event["agent_email"] == "john@example.com"
    assert booking_event["booking_time_str"] == booking_time
    assert booking_event["details"]["customer_name"] == "Booking Tester"
    assert booking_event["details"]["phone"] == "5559876543"
    assert booking_event["details"]["service_type"] == "Brake Service & Repair"

    with get_db_connection() as conn:
        with dict_cursor(conn) as cursor:
            cursor.execute("DELETE FROM outbox_notifications WHERE request_id = %s;", (result["appointment_id"],))
            cursor.execute("DELETE FROM service_requests WHERE id = %s;", (service_request_id,))
            cursor.execute("DELETE FROM vehicles WHERE id = %s;", (vehicle_id,))
            cursor.execute("DELETE FROM customers WHERE id = %s;", (customer_id,))
            cursor.execute("DELETE FROM services WHERE name = 'Brake Service & Repair';")
        conn.commit()

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
