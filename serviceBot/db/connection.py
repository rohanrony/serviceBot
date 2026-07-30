import psycopg2
import psycopg2.extras
import psycopg2.pool
import psycopg2.errors
import os
from contextlib import contextmanager
import threading
import sys

from dotenv import load_dotenv
from serviceBot.logger import get_logger

logger = get_logger("db.connection")

# Load environment variables from .env
load_dotenv()


def get_db_url():
    """Returns the DATABASE_URL for PostgreSQL connections."""
    is_testing = "pytest" in sys.modules or any("pytest" in arg or "unittest" in arg for arg in sys.argv)
    if is_testing:
        env_val = os.getenv("TEST_DATABASE_URL")
        if env_val and (env_val.startswith("postgresql") or env_val.startswith("postgres")):
            if env_val.startswith("postgres://"):
                env_val = env_val.replace("postgres://", "postgresql://", 1)
            return env_val
    url = os.getenv("DATABASE_URL", "")
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url


# Lazy connection pool (initialized on first use)
_pool = None


def _get_pool():
    global _pool
    if _pool is None:
        db_url = get_db_url()
        if not db_url or not (db_url.startswith("postgresql") or db_url.startswith("postgres")):
            logger.error(f"Invalid DATABASE_URL configuration: {db_url!r}")
            raise RuntimeError(
                "DATABASE_URL must be a PostgreSQL connection string "
                "(e.g. postgresql://user:pass@host/dbname). "
                f"Current value: {db_url!r}"
            )
        _pool = psycopg2.pool.SimpleConnectionPool(
            minconn=1,
            maxconn=10,
            dsn=db_url,
            keepalives=1,
            keepalives_idle=30,
            keepalives_interval=10,
            keepalives_count=5,
        )
        logger.info("Initialized PostgreSQL connection pool (minconn=1, maxconn=10).")
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
    phone_number VARCHAR(50) DEFAULT NULL,
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
    status VARCHAR(50) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'in_progress', 'completed', 'cancelled', 'rescheduled')),
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

CREATE TABLE IF NOT EXISTS outbox_notifications (
    id SERIAL PRIMARY KEY,
    event_type VARCHAR(50) NOT NULL,
    request_id INTEGER DEFAULT NULL,
    payload JSONB NOT NULL,
    attempts INTEGER DEFAULT 0,
    max_attempts INTEGER DEFAULT 7,
    status VARCHAR(50) DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'PROCESSING', 'DELIVERED', 'FAILED_REVERTED')),
    next_retry_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    error_log TEXT DEFAULT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_outbox_status_next_retry ON outbox_notifications(status, next_retry_at);

CREATE TABLE IF NOT EXISTS sms_config (
    id SERIAL PRIMARY KEY,
    quiet_hours_enabled BOOLEAN DEFAULT TRUE,
    quiet_start_time TIME DEFAULT '21:00',
    quiet_end_time TIME DEFAULT '08:00',
    urgent_threshold_hours INTEGER DEFAULT 12,
    support_phone_number VARCHAR(50) DEFAULT NULL,
    admin_phone_number VARCHAR(50) DEFAULT NULL,
    auto_responder_template TEXT DEFAULT 'Thank you! Our team has received your message. For urgent help, call {support_number}.',
    auto_responder_debounce_seconds INTEGER DEFAULT 60,
    environment VARCHAR(20) DEFAULT 'TEST',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sms_matrix_rules (
    id SERIAL PRIMARY KEY,
    event_type VARCHAR(50) NOT NULL,
    recipient_role VARCHAR(30) NOT NULL,
    enabled BOOLEAN DEFAULT TRUE,
    UNIQUE(event_type, recipient_role)
);

CREATE TABLE IF NOT EXISTS sms_whitelist (
    id SERIAL PRIMARY KEY,
    phone_number VARCHAR(50) NOT NULL UNIQUE,
    friendly_name VARCHAR(255) DEFAULT NULL,
    twilio_verified BOOLEAN DEFAULT FALSE,
    whatsapp_onboarded BOOLEAN DEFAULT FALSE,
    whatsapp_onboarded_at TIMESTAMP DEFAULT NULL,
    recipient_role VARCHAR(50) DEFAULT 'CUSTOMER',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sms_log (
    id SERIAL PRIMARY KEY,
    appointment_id INTEGER DEFAULT NULL REFERENCES service_requests(id) ON DELETE SET NULL,
    recipient_type VARCHAR(20) NOT NULL,
    recipient_phone VARCHAR(50) NOT NULL,
    template_type VARCHAR(50) NOT NULL,
    twilio_message_sid VARCHAR(50) DEFAULT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'PENDING',
    error_code VARCHAR(20) DEFAULT NULL,
    error_message TEXT DEFAULT NULL,
    retry_count INTEGER DEFAULT 0,
    scheduled_send_at TIMESTAMP DEFAULT NULL,
    sent_at TIMESTAMP DEFAULT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sms_reminders (
    id SERIAL PRIMARY KEY,
    appointment_id INTEGER NOT NULL REFERENCES service_requests(id) ON DELETE CASCADE,
    recipient_type VARCHAR(20) NOT NULL,
    recipient_phone VARCHAR(50) NOT NULL,
    reminder_type VARCHAR(10) NOT NULL,
    scheduled_at TIMESTAMP NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sms_conversations (
    id SERIAL PRIMARY KEY,
    customer_phone VARCHAR(50) NOT NULL UNIQUE,
    state VARCHAR(30) DEFAULT 'AUTOMATED' CHECK (state IN ('AUTOMATED', 'HANDOFF_REQUIRED', 'IN_PROGRESS', 'RESOLVED')),
    last_auto_responder_at TIMESTAMP DEFAULT NULL,
    context_appointment_id INTEGER DEFAULT NULL REFERENCES service_requests(id) ON DELETE SET NULL,
    assigned_agent_id INTEGER DEFAULT NULL REFERENCES staff_agents(id) ON DELETE SET NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_sms_conversations_state ON sms_conversations(state);

CREATE TABLE IF NOT EXISTS sms_messages (
    id SERIAL PRIMARY KEY,
    conversation_id INTEGER NOT NULL REFERENCES sms_conversations(id) ON DELETE CASCADE,
    direction VARCHAR(10) NOT NULL CHECK (direction IN ('inbound', 'outbound')),
    sender_type VARCHAR(20) NOT NULL CHECK (sender_type IN ('customer', 'system', 'agent')),
    sender_name VARCHAR(255) DEFAULT NULL,
    body TEXT NOT NULL,
    twilio_message_sid VARCHAR(50) DEFAULT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_sms_messages_conversation ON sms_messages(conversation_id);
"""

_db_initialized = False


def _safe_alter(cursor, conn, sql):
    """Run an ALTER TABLE statement cleanly using SAVEPOINT."""
    try:
        cursor.execute("SAVEPOINT alter_sp;")
        cursor.execute(sql)
        cursor.execute("RELEASE SAVEPOINT alter_sp;")
    except Exception as exc:
        cursor.execute("ROLLBACK TO SAVEPOINT alter_sp;")
        logger.debug(f"ALTER statement skipped or safe rollback: {exc}")


def init_db(db_url: str = None):
    """Initializes the database by running the DDL schema."""
    global _db_initialized
    if db_url is None:
        db_url = get_db_url()

    try:
        conn = psycopg2.connect(db_url)
        conn.autocommit = False
        cursor = conn.cursor()

        # Check if DB is already initialized
        cursor.execute("SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'sms_config');")
        table_exists = cursor.fetchone()[0]

        if not table_exists:
            # Run each DDL statement individually
            for statement in DDL_SCHEMA.split(";"):
                stmt = statement.strip()
                if stmt:
                    cursor.execute(stmt)
            conn.commit()

        # Auto-migrations for existing tables
        for col, col_def in [
            ("req_customer_name", "BOOLEAN DEFAULT TRUE"),
            ("req_phone_number", "BOOLEAN DEFAULT TRUE"),
            ("req_vehicle_details", "BOOLEAN DEFAULT TRUE"),
            ("req_issue_description", "BOOLEAN DEFAULT TRUE"),
            ("req_location", "BOOLEAN DEFAULT TRUE"),
        ]:
            _safe_alter(cursor, conn, f"ALTER TABLE services ADD COLUMN IF NOT EXISTS {col} {col_def}")

        for col, col_type in [
            ("email", "VARCHAR(255) DEFAULT NULL"),
            ("google_access_token", "TEXT DEFAULT NULL"),
            ("google_refresh_token", "TEXT DEFAULT NULL"),
            ("google_token_expires_at", "REAL DEFAULT NULL"),
            ("phone_number", "VARCHAR(50) DEFAULT NULL"),
        ]:
            _safe_alter(cursor, conn, f"ALTER TABLE staff_agents ADD COLUMN IF NOT EXISTS {col} {col_type}")

        for col, col_type in [
            ("sms_opt_in", "BOOLEAN DEFAULT TRUE"),
        ]:
            _safe_alter(cursor, conn, f"ALTER TABLE customers ADD COLUMN IF NOT EXISTS {col} {col_type}")

        for col, col_type in [
            ("time_slot", "VARCHAR(100) DEFAULT NULL"),
            ("booking_type", "VARCHAR(50) DEFAULT NULL CHECK (booking_type IN ('appointment', 'callback'))"),
            ("booking_time", "VARCHAR(100) DEFAULT NULL"),
            ("staff_agent_id", "INTEGER REFERENCES staff_agents(id) ON DELETE SET NULL"),
            ("updated_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
        ]:
            _safe_alter(cursor, conn, f"ALTER TABLE service_requests ADD COLUMN IF NOT EXISTS {col} {col_type}")

        for col, col_type in [
            ("admin_phone_number", "VARCHAR(50) DEFAULT NULL"),
        ]:
            _safe_alter(cursor, conn, f"ALTER TABLE sms_config ADD COLUMN IF NOT EXISTS {col} {col_type}")

        for col, col_type in [
            ("whatsapp_onboarded", "BOOLEAN DEFAULT FALSE"),
            ("whatsapp_onboarded_at", "TIMESTAMP DEFAULT NULL"),
            ("recipient_role", "VARCHAR(50) DEFAULT 'CUSTOMER'"),
        ]:
            _safe_alter(cursor, conn, f"ALTER TABLE sms_whitelist ADD COLUMN IF NOT EXISTS {col} {col_type}")
        conn.commit()

        # Drop legacy tables
        cursor.execute("DROP TABLE IF EXISTS appointments")
        cursor.execute("DROP TABLE IF EXISTS callback_requests")

        try:
            cursor.execute("ALTER TABLE service_requests DROP CONSTRAINT IF EXISTS service_requests_status_check;")
            cursor.execute("ALTER TABLE service_requests ADD CONSTRAINT service_requests_status_check CHECK (status IN ('pending', 'in_progress', 'completed', 'cancelled', 'rescheduled', 'confirmed', 'cancelled_by_customer'));")
            conn.commit()
        except Exception:
            conn.rollback()

        # Seed default sms_config if empty
        cursor.execute("SELECT COUNT(*) FROM sms_config;")
        if cursor.fetchone()[0] == 0:
            cursor.execute("""
                INSERT INTO sms_config (quiet_hours_enabled, quiet_start_time, quiet_end_time, urgent_threshold_hours, support_phone_number, auto_responder_template, auto_responder_debounce_seconds, environment)
                VALUES (TRUE, '21:00', '08:00', 12, '+18005550199', 'Thank you! Our team has received your message. For urgent help, call {support_number}.', 60, 'PRODUCTION');
            """)

        # Seed default sms_matrix_rules if empty
        cursor.execute("SELECT COUNT(*) FROM sms_matrix_rules;")
        if cursor.fetchone()[0] == 0:
            default_rules = [
                ('BOOKING', 'customer', True),
                ('BOOKING', 'agent', True),
                ('BOOKING', 'admin', False),
                ('RESCHEDULED', 'customer', True),
                ('RESCHEDULED', 'agent', True),
                ('RESCHEDULED', 'admin', False),
                ('REASSIGNED', 'customer', False),
                ('REASSIGNED', 'agent', True),
                ('REASSIGNED', 'previous_agent', True),
                ('REASSIGNED', 'admin', False),
                ('RESCHEDULED_REASSIGNED', 'customer', True),
                ('RESCHEDULED_REASSIGNED', 'agent', True),
                ('RESCHEDULED_REASSIGNED', 'previous_agent', True),
                ('RESCHEDULED_REASSIGNED', 'admin', False),
                ('CANCELLED_BY_CUSTOMER', 'customer', True),
                ('CANCELLED_BY_CUSTOMER', 'agent', True),
                ('CANCELLED_BY_CUSTOMER', 'admin', False),
                ('CANCELLED_BY_ADMIN', 'customer', True),
                ('CANCELLED_BY_ADMIN', 'agent', True),
                ('CANCELLED_BY_ADMIN', 'admin', False),
                ('REMINDER_24H', 'customer', True),
                ('REMINDER_24H', 'admin', False),
                ('REMINDER_2H', 'customer', True),
                ('REMINDER_2H', 'agent', True),
                ('REMINDER_2H', 'admin', False),
            ]
            for event_type, recipient_role, enabled in default_rules:
                cursor.execute(
                    "INSERT INTO sms_matrix_rules (event_type, recipient_role, enabled) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING;",
                    (event_type, recipient_role, enabled)
                )

        conn.commit()
        _db_initialized = True
        logger.info("Database schema initialized successfully.")
    except Exception as exc:
        if 'conn' in locals() and conn:
            conn.rollback()
            conn.close()
        logger.error(f"Failed to initialize database schema: {exc}", exc_info=exc)
        raise
    finally:
        if 'cursor' in locals() and cursor and not cursor.closed:
            cursor.close()
        if 'conn' in locals() and conn and not conn.closed:
            conn.close()


_init_lock = threading.Lock()


@contextmanager
def get_db_connection():
    """Context manager yielding a psycopg2 connection with RealDictCursor support."""
    global _db_initialized
    db_url = get_db_url()
    conn = None
    try:
        if not _db_initialized:
            with _init_lock:
                if not _db_initialized:
                    init_db(db_url)

        pool = _get_pool()

        # Validate connection liveness to handle Supabase pooler idle disconnects
        for _ in range(3):
            c = None
            try:
                c = pool.getconn()
                if c and c.closed == 0:
                    c.autocommit = True
                    with c.cursor() as cur:
                        cur.execute("SELECT 1;")
                    c.autocommit = False
                    conn = c
                    break
                elif c:
                    pool.putconn(c, close=True)
            except Exception as test_err:
                logger.warning(f"Discarding stale connection from pool: {test_err}")
                if c:
                    try:
                        pool.putconn(c, close=True)
                    except Exception:
                        pass

        if conn is None:
            conn = pool.getconn()

        conn.autocommit = False
        try:
            yield conn
            if conn and conn.closed == 0:
                conn.commit()
        except Exception:
            if conn and conn.closed == 0:
                try:
                    conn.rollback()
                except Exception:
                    pass
            raise
        finally:
            if conn:
                is_closed = (conn.closed != 0)
                try:
                    pool.putconn(conn, close=is_closed)
                except Exception:
                    pass
    except Exception as err:
        logger.error(f"Database connection error: {err}", exc_info=err)
        raise


def dict_cursor(conn):
    """Returns a RealDictCursor for dict-like row access (use instead of sqlite3.Row)."""
    return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
