import psycopg2
import pytest
from serviceBot.db.connection import get_db_connection, dict_cursor

def test_postgres_connection():
    """Verify that a PostgreSQL connection can be opened and is configured correctly."""
    with get_db_connection() as conn:
        # Check that it's a psycopg2 connection (can be the connection pool's connection or standard)
        assert hasattr(conn, 'cursor')

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
        with dict_cursor(conn) as cursor:
            cursor.execute("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'public';
            """)
            tables = {row["table_name"] for row in cursor.fetchall()}
            
            missing_tables = required_tables - tables
            assert not missing_tables, f"Missing tables: {missing_tables}"

