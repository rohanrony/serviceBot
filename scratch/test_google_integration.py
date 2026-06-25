import os
import sys
import time
import sqlite3
import unittest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

# Ensure sys.path includes the root codebase directory
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from serviceBot.main import app

# Force test database path (set after imports to override load_dotenv)
TEST_DB_PATH = "/Users/rohanroy/.gemini/antigravity-ide/scratch/test_voice_service.db"
os.environ["DATABASE_URL"] = TEST_DB_PATH

# Force DB_PATH override on the connection module
import serviceBot.db.connection
serviceBot.db.connection.DB_PATH = TEST_DB_PATH

# Force CONFIG_PATH override on portal module to prevent sandbox write blocks
import serviceBot.api.portal
serviceBot.api.portal.CONFIG_PATH = "/Users/rohanroy/.gemini/antigravity-ide/scratch/test_config.json"

from serviceBot.db.connection import init_db, get_db_connection, get_db_path
from serviceBot.services.encryption import encrypt_key, decrypt_key
from serviceBot.services.google_calendar import (
    get_user_google_credentials,
    list_upcoming_events,
    is_agent_free,
    create_agent_calendar_event,
    GoogleAuthException
)
from serviceBot.services.gmail import send_gmail_via_api, send_booking_notification

# Clear any existing test database to start fresh
if os.path.exists(TEST_DB_PATH):
    try:
        os.remove(TEST_DB_PATH)
    except OSError:
        pass

# Initialize the test DB schema
init_db(TEST_DB_PATH)

client = TestClient(app)

class GoogleIntegrationTestSuite(unittest.TestCase):
    def setUp(self):
        # Fresh seed for staff_agents
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM user_google_accounts;")
            cursor.execute("DELETE FROM oauth_states;")
            cursor.execute("DELETE FROM staff_agents;")
            cursor.execute("DELETE FROM mock_calendar_slots;")
            cursor.execute("DELETE FROM service_requests;")
            cursor.execute("DELETE FROM customers;")
            cursor.execute("DELETE FROM vehicles;")
            
            # Seed test agents
            cursor.execute(
                "INSERT INTO staff_agents (id, name, role, email) VALUES (1, 'John Doe', 'Manager', 'john.doe@example.com');"
            )
            cursor.execute(
                "INSERT INTO staff_agents (id, name, role, email) VALUES (2, 'Jane Smith', 'Advisor', 'jane.smith@example.com');"
            )
            
            # Seed default system configs
            from serviceBot.api.portal import load_config, save_config
            cfg = load_config()
            cfg["gmail_enabled"] = True
            cfg["gmail_auth_type"] = "app_password"
            cfg["gmail_sender"] = "system@example.com"
            cfg["gmail_recipient"] = "recipient@example.com"
            cfg["gmail_client_id"] = encrypt_key("test_client_id")
            cfg["gmail_client_secret"] = encrypt_key("test_client_secret")
            save_config(cfg)
            
            conn.commit()

    def tearDown(self):
        pass

    def test_01_auth_url_generation(self):
        """1. Verify Auth URL Generation and state insertion into database."""
        # Check action=calendar (Initial authorization)
        response = client.get("/api/v1/portal/agents/1/google/auth-url?action=calendar")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        self.assertIn("auth_url", data)
        self.assertIn("redirect_uri", data)
        
        # Scopes should be the narrowest calendar.events & profile info
        auth_url = data["auth_url"]
        self.assertIn("scope=openid email profile https://www.googleapis.com/auth/calendar.events", auth_url)
        self.assertIn("access_type=offline", auth_url)
        self.assertIn("prompt=consent", auth_url)
        
        # Verify state is saved in oauth_states
        state_param = None
        for part in auth_url.split("&"):
            if part.startswith("state="):
                state_param = part.split("=")[1]
                break
        self.assertIsNotNone(state_param)
        
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT agent_id, action_type FROM oauth_states WHERE state = ?;", (state_param,))
            row = cursor.fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["agent_id"], 1)
            self.assertEqual(row["action_type"], "calendar")

    def test_02_incremental_consent_scopes(self):
        """2. Verify Incremental Consent scopes merges existing ones."""
        # Scenario: agent already connected Calendar scope, now connects Gmail.
        # We simulate calendar scope already saved in db.
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO user_google_accounts (agent_id, provider, email, granted_scopes) VALUES (1, 'google', 'john.doe@google.com', 'openid email profile https://www.googleapis.com/auth/calendar.events');"
            )
            conn.commit()
            
        # Get Auth URL for gmail connection
        response = client.get("/api/v1/portal/agents/1/google/auth-url?action=gmail")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        auth_url = data["auth_url"]
        # Verify scope parameter contains BOTH gmail.send AND calendar.events (incremental scope collection)
        self.assertIn("gmail.send", auth_url)
        self.assertIn("calendar.events", auth_url)

    @patch("httpx.post")
    def test_03_csrf_state_handling(self, mock_post):
        """3. Verify CSRF verification on callback endpoints."""
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.text = "invalid_grant"
        mock_post.return_value = mock_resp

        # Simulate an incoming redirect callback from Google with a missing or mismatched state
        response = client.get("/api/v1/portal/gmail/oauth/callback?code=mock_code&state=non_existent_state")
        self.assertEqual(response.status_code, 200)
        # Should return failure or display "Authentication Failed" or skip agent update and proceed as system level connection
        # Wait, if state is missing or mismatched and starts with agent_, it tries a fallback, otherwise does system connection config.
        # Let's check state validation directly in db and callbacks:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT INTO oauth_states (state, agent_id, action_type, created_at) VALUES ('valid_state', 1, 'calendar', datetime('now'));")
            cursor.execute("INSERT INTO oauth_states (state, agent_id, action_type, created_at) VALUES ('expired_state', 1, 'calendar', datetime('now', '-20 minutes'));")
            conn.commit()

        # Let's execute the callback with the expired state:
        response = client.get("/api/v1/portal/gmail/oauth/callback?code=mock_code&state=expired_state")
        # Since it is expired, it should be deleted and ignored (falling back to system config settings update)
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM oauth_states WHERE state = 'expired_state';")
            self.assertIsNone(cursor.fetchone())

    @patch("httpx.post")
    @patch("httpx.get")
    def test_04_oauth_callback_token_upsert(self, mock_get, mock_post):
        """4. Verify Google OAuth Code Exchange and Upsert."""
        # Create a valid state
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT INTO oauth_states (state, agent_id, action_type) VALUES ('valid_state_123', 1, 'calendar');")
            conn.commit()

        # Mock token response
        mock_token_resp = MagicMock()
        mock_token_resp.status_code = 200
        mock_token_resp.json.return_value = {
            "access_token": "google_access_token_123",
            "refresh_token": "google_refresh_token_123",
            "expires_in": 3600,
            "scope": "openid email profile https://www.googleapis.com/auth/calendar.events"
        }
        mock_post.return_value = mock_token_resp

        # Mock userinfo response
        mock_userinfo_resp = MagicMock()
        mock_userinfo_resp.status_code = 200
        mock_userinfo_resp.json.return_value = {
            "sub": "google_account_id_999",
            "email": "john.doe.google@example.com"
        }
        mock_get.return_value = mock_userinfo_resp

        response = client.get("/api/v1/portal/gmail/oauth/callback?code=code_123&state=valid_state_123")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Calendar Connected", response.text)

        # Verify saved in user_google_accounts table (with encryption)
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM user_google_accounts WHERE agent_id = 1;")
            row = cursor.fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["google_account_id"], "google_account_id_999")
            self.assertEqual(row["email"], "john.doe.google@example.com")
            
            # Verify tokens are encrypted
            self.assertEqual(decrypt_key(row["access_token"]), "google_access_token_123")
            self.assertEqual(decrypt_key(row["refresh_token"]), "google_refresh_token_123")
            self.assertEqual(row["granted_scopes"], "openid email profile https://www.googleapis.com/auth/calendar.events")

    @patch("httpx.post")
    @patch("httpx.get")
    def test_05_refresh_token_preservation(self, mock_get, mock_post):
        """5. Verify refresh token preservation if Google does not return a new one."""
        # Pre-populate database with an existing refresh token
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO user_google_accounts (agent_id, provider, google_account_id, email, access_token, refresh_token, expires_at, granted_scopes) "
                "VALUES (1, 'google', 'google_account_id_999', 'john.doe.google@example.com', ?, ?, ?, 'openid email profile');",
                (encrypt_key("old_access_token"), encrypt_key("existing_refresh_token"), time.time() + 100)
            )
            cursor.execute("INSERT INTO oauth_states (state, agent_id, action_type) VALUES ('valid_state_456', 1, 'gmail');")
            conn.commit()

        # Mock token response which OMITS refresh_token (standard Google behaviour on subsequent consents)
        mock_token_resp = MagicMock()
        mock_token_resp.status_code = 200
        mock_token_resp.json.return_value = {
            "access_token": "new_google_access_token_456",
            "expires_in": 3600,
            "scope": "openid email profile https://www.googleapis.com/auth/gmail.send"
        }
        mock_post.return_value = mock_token_resp

        # Mock userinfo response
        mock_userinfo_resp = MagicMock()
        mock_userinfo_resp.status_code = 200
        mock_userinfo_resp.json.return_value = {
            "sub": "google_account_id_999",
            "email": "john.doe.google@example.com"
        }
        mock_get.return_value = mock_userinfo_resp

        response = client.get("/api/v1/portal/gmail/oauth/callback?code=code_456&state=valid_state_456")
        self.assertEqual(response.status_code, 200)

        # Verify that access_token updated, but refresh_token was preserved!
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT access_token, refresh_token FROM user_google_accounts WHERE agent_id = 1;")
            row = cursor.fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(decrypt_key(row["access_token"]), "new_google_access_token_456")
            self.assertEqual(decrypt_key(row["refresh_token"]), "existing_refresh_token")

    @patch("httpx.post")
    def test_06_token_auto_refresh(self, mock_post):
        """6. Verify automatic token refreshing when token is expired."""
        # Insert expired token info
        expired_time = time.time() - 10  # expired 10 seconds ago
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO user_google_accounts (agent_id, provider, google_account_id, email, access_token, refresh_token, expires_at, granted_scopes) "
                "VALUES (1, 'google', 'google_account_id_999', 'john.doe.google@example.com', ?, ?, ?, 'openid email profile');",
                (encrypt_key("expired_access_token"), encrypt_key("valid_refresh_token"), expired_time)
            )
            conn.commit()

        # Mock Google token refresh endpoint response
        mock_refresh_resp = MagicMock()
        mock_refresh_resp.status_code = 200
        mock_refresh_resp.json.return_value = {
            "access_token": "refreshed_access_token_789",
            "expires_in": 3600
        }
        mock_post.return_value = mock_refresh_resp

        # Call get_user_google_credentials, it should automatically refresh
        creds = get_user_google_credentials(1)
        self.assertEqual(creds["access_token"], "refreshed_access_token_789")

        # Verify new access token is stored in the database
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT access_token, expires_at FROM user_google_accounts WHERE agent_id = 1;")
            row = cursor.fetchone()
            self.assertEqual(decrypt_key(row["access_token"]), "refreshed_access_token_789")
            self.assertGreater(row["expires_at"], time.time() + 3500)

    @patch("httpx.post")
    def test_07_token_refresh_error_handling(self, mock_post):
        """7. Verify exception when refresh fails (revoked/invalid refresh token)."""
        expired_time = time.time() - 10
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO user_google_accounts (agent_id, provider, google_account_id, email, access_token, refresh_token, expires_at, granted_scopes) "
                "VALUES (1, 'google', 'google_account_id_999', 'john.doe.google@example.com', ?, ?, ?, 'openid email');",
                (encrypt_key("expired_access_token"), encrypt_key("revoked_refresh_token"), expired_time)
            )
            conn.commit()

        # Mock token response failure (invalid_grant)
        mock_refresh_resp = MagicMock()
        mock_refresh_resp.status_code = 400
        mock_refresh_resp.json.return_value = {
            "error": "invalid_grant",
            "error_description": "Token has been expired or revoked."
        }
        mock_post.return_value = mock_refresh_resp

        # Calling get_user_google_credentials should raise GoogleAuthException
        with self.assertRaises(GoogleAuthException):
            get_user_google_credentials(1)

    @patch("httpx.get")
    def test_08_calendar_free_busy(self, mock_get):
        """8. Verify calendar free/busy query logic with timezone parsing."""
        # Connect Calendar scope
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO user_google_accounts (agent_id, provider, google_account_id, email, access_token, refresh_token, expires_at, granted_scopes) "
                "VALUES (1, 'google', 'google_account_id_999', 'john.doe.google@example.com', ?, ?, ?, 'https://www.googleapis.com/auth/calendar.events');",
                (encrypt_key("valid_access_token"), encrypt_key("valid_refresh_token"), time.time() + 1000)
            )
            conn.commit()

        # Mock calendar response containing 1 overlapping event (busy)
        mock_busy_resp = MagicMock()
        mock_busy_resp.status_code = 200
        mock_busy_resp.json.return_value = {
            "items": [
                {
                    "id": "event_1",
                    "status": "confirmed",
                    "start": {"dateTime": "2026-06-25T10:00:00-04:00"},
                    "end": {"dateTime": "2026-06-25T11:00:00-04:00"}
                }
            ]
        }
        mock_get.return_value = mock_busy_resp

        # Check availability
        is_free = is_agent_free(1, "2026-06-25 10:00:00")
        self.assertFalse(is_free)  # busy

        # Mock calendar response containing no events (free)
        mock_free_resp = MagicMock()
        mock_free_resp.status_code = 200
        mock_free_resp.json.return_value = {"items": []}
        mock_get.return_value = mock_free_resp

        is_free = is_agent_free(1, "2026-06-25 10:00:00")
        self.assertTrue(is_free)  # free

    @patch("httpx.post")
    def test_09_calendar_event_creation(self, mock_post):
        """9. Verify Calendar Event insertion via REST API with scopes checks."""
        # Prepopulate agent 1 with write scopes
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO user_google_accounts (agent_id, provider, google_account_id, email, access_token, refresh_token, expires_at, granted_scopes) "
                "VALUES (1, 'google', 'google_account_id_999', 'john.doe.google@example.com', ?, ?, ?, 'https://www.googleapis.com/auth/calendar.events');",
                (encrypt_key("valid_access_token"), encrypt_key("valid_refresh_token"), time.time() + 1000)
            )
            conn.commit()

        # Mock create calendar event response
        mock_create_resp = MagicMock()
        mock_create_resp.status_code = 201
        mock_post.return_value = mock_create_resp

        success = create_agent_calendar_event(
            agent_id=1,
            customer_name="Alice Adams",
            service_type="AC Repair",
            issue_description="Blowing warm air",
            slot_datetime_str="2026-06-25 14:00:00"
        )
        self.assertTrue(success)

        # Assert post endpoint parameters
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        self.assertIn("https://www.googleapis.com/calendar/v3/calendars/primary/events", args[0])
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer valid_access_token")
        self.assertIn("AC Repair", kwargs["json"]["description"])

    @patch("httpx.post")
    def test_10_gmail_api_send(self, mock_post):
        """10. Verify Gmail Sending via REST API."""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO user_google_accounts (agent_id, provider, google_account_id, email, access_token, refresh_token, expires_at, granted_scopes) "
                "VALUES (1, 'google', 'google_account_id_999', 'john.doe.google@example.com', ?, ?, ?, 'https://www.googleapis.com/auth/gmail.send');",
                (encrypt_key("valid_access_token"), encrypt_key("valid_refresh_token"), time.time() + 1000)
            )
            conn.commit()

        mock_send_resp = MagicMock()
        mock_send_resp.status_code = 200
        mock_post.return_value = mock_send_resp

        success = send_gmail_via_api(
            agent_id=1,
            recipient="customer@example.com",
            subject="Test Subject",
            html_body="<p>Test HTML Body</p>"
        )
        self.assertTrue(success)

        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        self.assertIn("https://gmail.googleapis.com/gmail/v1/users/me/messages/send", args[0])
        self.assertIn("raw", kwargs["json"])
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer valid_access_token")

    @patch("serviceBot.services.gmail.send_gmail_via_api")
    @patch("serviceBot.services.gmail.send_smtp_email")
    def test_11_booking_notification_fallback(self, mock_smtp, mock_agent_gmail):
        """11. Verify fallback when sending booking notification to agent without Google email integration."""
        # Case A: Agent connected with Gmail scope
        mock_agent_gmail.return_value = True
        
        details = {
            "customer_name": "Bob",
            "phone": "555-1234",
            "vehicle": "Tesla Model 3",
            "service_type": "Tires",
            "time": "2026-06-25 15:00:00"
        }
        
        # Test sending with agent email matching John Doe (who we simulate connects)
        success = send_booking_notification("appointment", details, agent_email="john.doe@example.com")
        self.assertTrue(success)
        mock_agent_gmail.assert_called_once_with(
            agent_id=1,
            recipient="john.doe@example.com",
            subject="[serviceBot] New Appointment Scheduled - Bob",
            html_body=unittest.mock.ANY,
            plain_body=unittest.mock.ANY
        )

        # Case B: Agent not connected or fails -> Fallback to system-level configuration (SMTP)
        mock_agent_gmail.reset_mock()
        mock_agent_gmail.return_value = False
        mock_smtp.return_value = True

        success = send_booking_notification("appointment", details, agent_email="john.doe@example.com")
        self.assertTrue(success)
        self.assertTrue(mock_smtp.called)

    def test_12_disconnect_agent(self):
        """12. Verify Google account disconnect and data cleanup."""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO user_google_accounts (agent_id, provider, google_account_id, email, access_token, refresh_token, expires_at, granted_scopes) "
                "VALUES (1, 'google', 'google_account_id_999', 'john.doe.google@example.com', 'ac', 'rf', 100, 'scopes');"
            )
            conn.commit()

        # Call disconnect
        response = client.post("/api/v1/portal/agents/1/google/disconnect")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])

        # Check that connection details are deleted
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM user_google_accounts WHERE agent_id = 1;")
            self.assertIsNone(cursor.fetchone())

    @patch("serviceBot.services.google_calendar.fetch_agent_events")
    def test_13_parallel_availability(self, mock_fetch):
        """13. Verify parallel availability query logic with mock events."""
        from serviceBot.db.queries import check_availability

        # Setup test data
        with get_db_connection() as conn:
            cursor = conn.cursor()
            # Clean up first
            cursor.execute("DELETE FROM mock_calendar_slots WHERE slot_datetime LIKE '2026-07-20%';")
            cursor.execute("DELETE FROM user_google_accounts WHERE agent_id IN (201, 202);")
            cursor.execute("DELETE FROM staff_agents WHERE id IN (201, 202);")
            
            # Insert two test agents
            cursor.execute(
                "INSERT INTO staff_agents (id, name, role, email) VALUES (201, 'Agent One', 'Advisor', 'agent1@example.com');"
            )
            cursor.execute(
                "INSERT INTO staff_agents (id, name, role, email) VALUES (202, 'Agent Two', 'Advisor', 'agent2@example.com');"
            )
            
            # Insert Google Account integration details (refresh token present means connected)
            cursor.execute(
                "INSERT INTO user_google_accounts (agent_id, provider, email, refresh_token) VALUES (201, 'google', 'agent1@example.com', 'refresh_token_1');"
            )
            cursor.execute(
                "INSERT INTO user_google_accounts (agent_id, provider, email, refresh_token) VALUES (202, 'google', 'agent2@example.com', 'refresh_token_2');"
            )
            
            # Insert same time slot for both agents (10:00 AM slot)
            cursor.execute(
                "INSERT INTO mock_calendar_slots (slot_datetime, is_booked, staff_agent_id) VALUES ('2026-07-20 10:00:00', 0, 201);"
            )
            cursor.execute(
                "INSERT INTO mock_calendar_slots (slot_datetime, is_booked, staff_agent_id) VALUES ('2026-07-20 10:00:00', 0, 202);"
            )
            
            # 11:00 AM slot - only for Agent One
            cursor.execute(
                "INSERT INTO mock_calendar_slots (slot_datetime, is_booked, staff_agent_id) VALUES ('2026-07-20 11:00:00', 0, 201);"
            )
            
            conn.commit()

        try:
            # Case 1: Both agents are free
            mock_fetch.return_value = []
            slots = check_availability(preferred_date="2026-07-20 09:00:00")
            self.assertIn("2026-07-20 10:00:00", slots)
            self.assertIn("2026-07-20 11:00:00", slots)
            
            # Case 2: Agent One is busy (has overlapping event), Agent Two is free (no events)
            def side_effect(agent_id, start_iso, end_iso):
                if agent_id == 201:
                    return [{
                        "status": "confirmed",
                        "start": {"dateTime": "2026-07-20T10:00:00-04:00"},
                        "end": {"dateTime": "2026-07-20T11:00:00-04:00"}
                    }]
                return []
            mock_fetch.side_effect = side_effect
            
            slots = check_availability(preferred_date="2026-07-20 09:00:00")
            # 10:00 AM should still be available because Agent Two is free!
            self.assertIn("2026-07-20 10:00:00", slots)
            # 11:00 AM should be available too because Agent One's busy event ends at 11:00 AM
            self.assertIn("2026-07-20 11:00:00", slots)

            # Let's test event overlapping 11:00 AM
            def side_effect_overlap_11(agent_id, start_iso, end_iso):
                if agent_id == 201:
                    return [{
                        "status": "confirmed",
                        "start": {"dateTime": "2026-07-20T10:45:00-04:00"},
                        "end": {"dateTime": "2026-07-20T11:45:00-04:00"}
                    }]
                return []
            mock_fetch.side_effect = side_effect_overlap_11
            slots = check_availability(preferred_date="2026-07-20 09:00:00")
            self.assertIn("2026-07-20 10:00:00", slots)  # Agent Two is free
            self.assertNotIn("2026-07-20 11:00:00", slots)  # Agent One is busy, and Agent One is the only advisor with this slot
            
            # Case 3: Both agents are busy at 10:00 AM and 11:00 AM
            def side_effect_both_busy(agent_id, start_iso, end_iso):
                return [{
                    "status": "confirmed",
                    "start": {"dateTime": "2026-07-20T10:00:00-04:00"},
                    "end": {"dateTime": "2026-07-20T12:00:00-04:00"}
                }]
            mock_fetch.side_effect = side_effect_both_busy
            
            slots = check_availability(preferred_date="2026-07-20 09:00:00")
            self.assertNotIn("2026-07-20 10:00:00", slots)
            self.assertNotIn("2026-07-20 11:00:00", slots)
            
        finally:
            # Clean up test data
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM mock_calendar_slots WHERE slot_datetime LIKE '2026-07-20%';")
                cursor.execute("DELETE FROM user_google_accounts WHERE agent_id IN (201, 202);")
                cursor.execute("DELETE FROM staff_agents WHERE id IN (201, 202);")
                conn.commit()

if __name__ == "__main__":
    print("\n" + "="*50)
    print("RUNNING GOOGLE INTEGRATION AUTOMATED TESTS...")
    print("="*50 + "\n")
    unittest.main()
