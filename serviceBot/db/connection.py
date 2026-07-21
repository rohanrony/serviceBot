import psycopg2
import psycopg2.extras
import psycopg2.pool
import psycopg2.errors
import os
from contextlib import contextmanager
import sys
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()


def get_db_url():
    """Returns the DATABASE_URL for PostgreSQL connections."""
    is_testing = "pytest" in sys.modules or any("pytest" in arg or "unittest" in arg for arg in sys.argv)
    if is_testing:
        env_val = os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL")
        if env_val and env_val.startswith("postgresql"):
            return env_val
        return os.getenv("DATABASE_URL", "")
    return os.getenv("DATABASE_URL", "")


# Lazy connection pool (initialized on first use)
_pool = None


def _get_pool():
    global _pool
    if _pool is None:
        db_url = get_db_url()
        if not db_url or not db_url.startswith("postgresql"):
            raise RuntimeError(
                "DATABASE_URL must be a PostgreSQL connection string "
                "(e.g. postgresql://user:pass@host/dbname). "
                f"Current value: {db_url!r}"
            )
        _pool = psycopg2.pool.SimpleConnectionPool(
            minconn=1,
            maxconn=10,
            dsn=db_url,
        )
    return _pool


# PostgreSQL DDL Schema
DDL_SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    phone VARCHAR(50) NOT NULL UNIQUE,
    email VARCHAR(255) DEFAULT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_customers_phone ON customers(phone);

CREATE TABLE IF NOT EXISTS staff_agents (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    role VARCHAR(100) DEFAULT NULL,
    email VARCHAR(255) DEFAULT NULL,
    google_access_token TEXT DEFAULT NULL,
    google_refresh_token TEXT DEFAULT NULL,
    google_token_expires_at REAL DEFAULT NULL
);

CREATE TABLE IF NOT EXISTS vehicles (
    id SERIAL PRIMARY KEY,
    customer_id INTEGER NOT NULL,
    make VARCHAR(100) NOT NULL,
    model VARCHAR(100) NOT NULL,
    year INTEGER NOT NULL,
    vin VARCHAR(17) DEFAULT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_vehicles_customer_id ON vehicles(customer_id);

CREATE TABLE IF NOT EXISTS service_requests (
    id SERIAL PRIMARY KEY,
    customer_id INTEGER NOT NULL,
    vehicle_id INTEGER NOT NULL,
    service_type VARCHAR(100) NOT NULL,
    issue_description TEXT NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'in_progress', 'completed', 'cancelled')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    time_slot VARCHAR(100) DEFAULT NULL,
    booking_type VARCHAR(50) DEFAULT NULL CHECK (booking_type IN ('appointment', 'callback')),
    booking_time VARCHAR(100) DEFAULT NULL,
    staff_agent_id INTEGER DEFAULT NULL REFERENCES staff_agents(id) ON DELETE SET NULL,
    FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE RESTRICT,
    FOREIGN KEY (vehicle_id) REFERENCES vehicles(id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_service_requests_customer ON service_requests(customer_id);

CREATE TABLE IF NOT EXISTS crm_notes (
    id SERIAL PRIMARY KEY,
    call_id VARCHAR(255) NOT NULL UNIQUE,
    customer_id INTEGER NOT NULL,
    summary TEXT NOT NULL,
    transcript TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_crm_notes_customer ON crm_notes(customer_id);

CREATE TABLE IF NOT EXISTS mock_calendar_slots (
    id SERIAL PRIMARY KEY,
    slot_datetime TIMESTAMP NOT NULL,
    is_booked BOOLEAN NOT NULL DEFAULT FALSE,
    staff_agent_id INTEGER DEFAULT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (staff_agent_id) REFERENCES staff_agents(id) ON DELETE CASCADE,
    UNIQUE(slot_datetime, staff_agent_id)
);

CREATE INDEX IF NOT EXISTS idx_mock_calendar_slots_datetime ON mock_calendar_slots(slot_datetime);

CREATE TABLE IF NOT EXISTS services (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    price_range VARCHAR(100),
    duration_minutes INTEGER,
    req_customer_name BOOLEAN DEFAULT TRUE,
    req_phone_number BOOLEAN DEFAULT TRUE,
    req_vehicle_details BOOLEAN DEFAULT TRUE,
    req_issue_description BOOLEAN DEFAULT TRUE,
    req_location BOOLEAN DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS user_google_accounts (
    agent_id INTEGER PRIMARY KEY,
    provider VARCHAR(50) NOT NULL DEFAULT 'google',
    google_account_id VARCHAR(255) DEFAULT NULL,
    email VARCHAR(255) DEFAULT NULL,
    access_token TEXT DEFAULT NULL,
    refresh_token TEXT DEFAULT NULL,
    expires_at REAL DEFAULT NULL,
    granted_scopes TEXT DEFAULT NULL,
    last_refresh_time REAL DEFAULT NULL,
    FOREIGN KEY (agent_id) REFERENCES staff_agents(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS oauth_states (
    state VARCHAR(255) PRIMARY KEY,
    agent_id INTEGER NOT NULL,
    action_type VARCHAR(50) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (agent_id) REFERENCES staff_agents(id) ON DELETE CASCADE
);
"""

_db_initialized = False


def _safe_alter(cursor, conn, sql):
    """Run an ALTER TABLE statement, rolling back on DuplicateColumn."""
    try:
        cursor.execute(sql)
    except psycopg2.errors.DuplicateColumn:
        conn.rollback()
    except Exception:
        conn.rollback()
        raise


def init_db(db_url: str = None):
    """Initializes the database by running the DDL schema."""
    global _db_initialized
    if db_url is None:
        db_url = get_db_url()

    conn = psycopg2.connect(db_url)
    try:
        conn.autocommit = False
        cursor = conn.cursor()

        # Run each DDL statement individually
        for statement in DDL_SCHEMA.split(";"):
            stmt = statement.strip()
            if stmt:
                cursor.execute(stmt)
        conn.commit()

        # Auto-migration: add missing columns to services table
        for col, col_def in [
            ("req_customer_name", "BOOLEAN DEFAULT TRUE"),
            ("req_phone_number", "BOOLEAN DEFAULT TRUE"),
            ("req_vehicle_details", "BOOLEAN DEFAULT TRUE"),
            ("req_issue_description", "BOOLEAN DEFAULT TRUE"),
            ("req_location", "BOOLEAN DEFAULT TRUE"),
        ]:
            _safe_alter(cursor, conn, f"ALTER TABLE services ADD COLUMN {col} {col_def}")

        # Auto-migration: add missing columns to staff_agents table
        for col, col_type in [
            ("email", "VARCHAR(255) DEFAULT NULL"),
            ("google_access_token", "TEXT DEFAULT NULL"),
            ("google_refresh_token", "TEXT DEFAULT NULL"),
            ("google_token_expires_at", "REAL DEFAULT NULL"),
        ]:
            _safe_alter(cursor, conn, f"ALTER TABLE staff_agents ADD COLUMN {col} {col_type}")

        # Auto-migration: add missing columns to service_requests table
        for col, col_type in [
            ("time_slot", "VARCHAR(100) DEFAULT NULL"),
            ("booking_type", "VARCHAR(50) DEFAULT NULL CHECK (booking_type IN ('appointment', 'callback'))"),
            ("booking_time", "VARCHAR(100) DEFAULT NULL"),
            ("staff_agent_id", "INTEGER REFERENCES staff_agents(id) ON DELETE SET NULL"),
        ]:
            _safe_alter(cursor, conn, f"ALTER TABLE service_requests ADD COLUMN {col} {col_type}")

        # Drop legacy tables
        cursor.execute("DROP TABLE IF EXISTS appointments")
        cursor.execute("DROP TABLE IF EXISTS callback_requests")

        conn.commit()
        _db_initialized = True
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()


@contextmanager
def get_db_connection():
    """Context manager yielding a psycopg2 connection with RealDictCursor support."""
    global _db_initialized
    db_url = get_db_url()
    try:
        if not _db_initialized:
            init_db(db_url)

        pool = _get_pool()
        conn = pool.getconn()
        conn.autocommit = False
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            pool.putconn(conn)
    except Exception as err:
        print(f"[get_db_connection] Database connection unavailable: {err}")
        raise


def dict_cursor(conn):
    """Returns a RealDictCursor for dict-like row access (use instead of sqlite3.Row)."""
    return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
