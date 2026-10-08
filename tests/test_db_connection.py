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


def test_threaded_connection_pool_type():
    """Verify that the connection pool uses ThreadedConnectionPool for multi-threaded safety."""
    from psycopg2.pool import ThreadedConnectionPool
    from serviceBot.db.connection import _get_pool
    pool = _get_pool()
    assert isinstance(pool, ThreadedConnectionPool)


def test_multithreaded_concurrent_connections():
    """Verify that multiple concurrent threads can query using get_db_connection without collision."""
    import threading
    errors = []

    def worker(worker_id):
        try:
            with get_db_connection() as conn:
                with dict_cursor(conn) as cur:
                    cur.execute("SELECT %s as id;", (worker_id,))
                    row = cur.fetchone()
                    assert row["id"] == worker_id
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5.0)

    assert not errors, f"Concurrent workers encountered errors: {errors}"


def test_standalone_fallback_connection_closes_cleanly():
    """Verify that fallback standalone connections are closed rather than placed into pool."""
    from unittest.mock import patch
    from serviceBot.db.connection import _get_pool
    pool = _get_pool()

    with patch.object(pool, "getconn", side_effect=Exception("Pool full")):
        with get_db_connection() as conn:
            assert hasattr(conn, "cursor")
            saved_conn = conn
        # Upon exit, standalone connection must be closed
        assert saved_conn.closed != 0


def test_init_db_throttling_on_failure():
    """Verify that consecutive init_db failures are throttled to prevent reconnection storms."""
    from unittest.mock import patch
    import serviceBot.db.connection as conn_mod

    call_count = 0
    def fake_init_db(db_url):
        nonlocal call_count
        call_count += 1
        raise Exception("Simulated connection failure")

    with patch.object(conn_mod, "_db_initialized", False), \
         patch.object(conn_mod, "init_db", side_effect=fake_init_db):
        conn_mod._last_init_attempt = 0.0

        # First attempt triggers init_db
        try:
            with conn_mod.get_db_connection():
                pass
        except Exception:
            pass
        assert call_count == 1

        # Immediate second attempt within 15s should be throttled (skipped)
        try:
            with conn_mod.get_db_connection():
                pass
        except Exception:
            pass
        assert call_count == 1


