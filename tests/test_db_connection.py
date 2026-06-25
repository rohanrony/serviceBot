import sqlite3
import pytest
from serviceBot.db.connection import get_db_connection

def test_sqlite_connection():
    """Verify that an SQLite connection can be opened and is configured correctly."""
    # The connection should be openable using get_db_connection context manager
    with get_db_connection() as conn:
        assert isinstance(conn, sqlite3.Connection)

def test_foreign_keys_pragma():
    """Assert that 'PRAGMA foreign_keys = ON;' is successfully enforced on connection initialization."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("PRAGMA foreign_keys;")
        result = cursor.fetchone()
        # PRAGMA foreign_keys returns (1,) if enabled, or (0,) if disabled
        assert result is not None
        assert result[0] == 1

def test_tables_exist():
    """Assert that the required tables exist in the database schema."""
    required_tables = {
        "customers",
        "vehicles",
        "service_requests",
        "crm_notes",
        "mock_calendar_slots"
    }
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = {row[0] for row in cursor.fetchall()}
        
        missing_tables = required_tables - tables
        assert not missing_tables, f"Missing tables: {missing_tables}"
