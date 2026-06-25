import sys
import os
import time
from unittest.mock import patch, MagicMock

# Force test database path
TEST_DB_PATH = "/Users/rohanroy/.gemini/antigravity-ide/scratch/test_voice_service.db"
os.environ["DATABASE_URL"] = TEST_DB_PATH

# Force DB_PATH override on the connection module
import serviceBot.db.connection
serviceBot.db.connection.DB_PATH = TEST_DB_PATH

from serviceBot.db.connection import get_db_connection, init_db
from serviceBot.db.queries import check_availability

def setup_test_data():
    # Make sure DB schema exists
    init_db(TEST_DB_PATH)
    
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

def cleanup_test_data():
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM mock_calendar_slots WHERE slot_datetime LIKE '2026-07-20%';")
        cursor.execute("DELETE FROM user_google_accounts WHERE agent_id IN (201, 202);")
        cursor.execute("DELETE FROM staff_agents WHERE id IN (201, 202);")
        conn.commit()

@patch("serviceBot.services.google_calendar.fetch_agent_events")
def test_run_tests_with_fetch_mock(mock_fetch):
    setup_test_data()
    print("\n--- RUNNING PARALLEL AVAILABILITY TESTS ---")
    try:
        # Case 1: Both agents are free
        mock_fetch.return_value = []
        slots = check_availability(preferred_date="2026-07-20 09:00:00")
        print(f"Case 1 (Both Free): slots = {slots}")
        assert "2026-07-20 10:00:00" in slots
        assert "2026-07-20 11:00:00" in slots
        
        # Case 2: Agent One is busy (has overlapping event), Agent Two is free (no events)
        # 10:00 AM slot is 2026-07-20 10:00:00
        # Overlapping event: 10:00 AM to 11:00 AM
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
        print(f"Case 2 (Agent One Busy, Agent Two Free): slots = {slots}")
        # 10:00 AM should still be available because Agent Two is free!
        assert "2026-07-20 10:00:00" in slots
        # 11:00 AM should be available too because Agent One is not busy at 11:00 AM (event ends at 11:00 AM)
        assert "2026-07-20 11:00:00" in slots

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
        assert "2026-07-20 10:00:00" in slots  # Agent Two is free
        assert "2026-07-20 11:00:00" not in slots  # Agent One is busy, and Agent One is the only advisor with this slot
        
        # Case 3: Both agents are busy at 10:00 AM and 11:00 AM
        def side_effect_both_busy(agent_id, start_iso, end_iso):
            return [{
                "status": "confirmed",
                "start": {"dateTime": "2026-07-20T10:00:00-04:00"},
                "end": {"dateTime": "2026-07-20T12:00:00-04:00"}
            }]
        mock_fetch.side_effect = side_effect_both_busy
        
        slots = check_availability(preferred_date="2026-07-20 09:00:00")
        print(f"Case 3 (Both Busy): slots = {slots}")
        assert "2026-07-20 10:00:00" not in slots
        assert "2026-07-20 11:00:00" not in slots
        
        print("ALL TESTS PASSED SUCCESSFULLY!")
        
    finally:
        cleanup_test_data()

if __name__ == "__main__":
    test_run_tests_with_fetch_mock()
