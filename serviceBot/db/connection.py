import sqlite3
import os
from contextlib import contextmanager

import sys

def get_db_path():
    # If DB_PATH was explicitly set (e.g. patched by tests), use it
    if "DB_PATH" in globals():
        return globals()["DB_PATH"]
    is_testing = "pytest" in sys.modules or any("pytest" in arg or "unittest" in arg for arg in sys.argv)
    if is_testing:
        default_db = "/Users/rohanroy/.gemini/antigravity-ide/scratch/test_voice_service.db"
        env_val = os.getenv("DATABASE_URL")
        if not env_val or env_val == "voice_service.db":
            return default_db
        return env_val
    default_db = "voice_service.db"
    return os.getenv("DATABASE_URL", default_db)


# Define DB_PATH dynamically to prevent early import caching issues
def __getattr__(name):
    if name == "DB_PATH":
        return get_db_path()
    raise AttributeError(f"module {__name__} has no attribute {name}")



# DDL Schema definitions
DDL_SCHEMA = """
-- 1. Customers Table
CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(255) NOT NULL,
    phone VARCHAR(50) NOT NULL UNIQUE,
    email VARCHAR(255) DEFAULT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Index on phone for pre-call CRM lookup optimization
CREATE INDEX IF NOT EXISTS idx_customers_phone ON customers(phone);

-- 2. Vehicles Table
CREATE TABLE IF NOT EXISTS vehicles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL,
    make VARCHAR(100) NOT NULL,
    model VARCHAR(100) NOT NULL,
    year INTEGER NOT NULL,
    vin VARCHAR(17) DEFAULT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE CASCADE
);

-- Index on customer_id for fast fetching of customer's vehicles
CREATE INDEX IF NOT EXISTS idx_vehicles_customer_id ON vehicles(customer_id);

-- 3. Service Requests Table
CREATE TABLE IF NOT EXISTS service_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
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

-- 5. CRM Notes Table
CREATE TABLE IF NOT EXISTS crm_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    call_id VARCHAR(255) NOT NULL UNIQUE,
    customer_id INTEGER NOT NULL,
    summary TEXT NOT NULL,
    transcript TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_crm_notes_customer ON crm_notes(customer_id);

-- 8. Staff Agents Table
CREATE TABLE IF NOT EXISTS staff_agents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(255) NOT NULL,
    role VARCHAR(100) DEFAULT NULL,
    email VARCHAR(255) DEFAULT NULL,
    google_access_token TEXT DEFAULT NULL,
    google_refresh_token TEXT DEFAULT NULL,
    google_token_expires_at REAL DEFAULT NULL
);

-- 6. Mock Calendar Slots Table
CREATE TABLE IF NOT EXISTS mock_calendar_slots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slot_datetime TIMESTAMP NOT NULL,
    is_booked BOOLEAN NOT NULL DEFAULT 0,
    staff_agent_id INTEGER DEFAULT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (staff_agent_id) REFERENCES staff_agents(id) ON DELETE CASCADE,
    UNIQUE(slot_datetime, staff_agent_id)
);

CREATE INDEX IF NOT EXISTS idx_mock_calendar_slots_datetime ON mock_calendar_slots(slot_datetime);

-- 7. Services Table
CREATE TABLE IF NOT EXISTS services (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    price_range VARCHAR(100),
    duration_minutes INTEGER,
    req_customer_name BOOLEAN DEFAULT 1,
    req_phone_number BOOLEAN DEFAULT 1,
    req_vehicle_details BOOLEAN DEFAULT 1,
    req_issue_description BOOLEAN DEFAULT 1,
    req_location BOOLEAN DEFAULT 1
);

-- 9. User Google Accounts Table
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

-- 10. OAuth States Table
CREATE TABLE IF NOT EXISTS oauth_states (
    state VARCHAR(255) PRIMARY KEY,
    agent_id INTEGER NOT NULL,
    action_type VARCHAR(50) NOT NULL, -- 'calendar' or 'gmail'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (agent_id) REFERENCES staff_agents(id) ON DELETE CASCADE
);
"""

_db_initialized = False

def init_db(db_path: str = None):
    """Initializes the database by running the DDL schema."""
    global _db_initialized
    if db_path is None:
        db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.executescript(DDL_SCHEMA)
        
        # Auto-migration: check and add missing columns to services table if they don't exist
        cursor = conn.cursor()
        for col in ["req_customer_name", "req_phone_number", "req_vehicle_details", "req_issue_description", "req_location"]:
            try:
                cursor.execute(f"ALTER TABLE services ADD COLUMN {col} BOOLEAN DEFAULT 1")
            except sqlite3.OperationalError:
                # Column already exists
                pass

        # Auto-migration: check and add missing columns to staff_agents table if they don't exist
        for col, col_type in [("email", "VARCHAR(255) DEFAULT NULL"),
                              ("google_access_token", "TEXT DEFAULT NULL"),
                              ("google_refresh_token", "TEXT DEFAULT NULL"),
                              ("google_token_expires_at", "REAL DEFAULT NULL")]:
            try:
                cursor.execute(f"ALTER TABLE staff_agents ADD COLUMN {col} {col_type}")
            except sqlite3.OperationalError:
                # Column already exists
                pass

        # Auto-migration: check and add missing columns to service_requests table if they don't exist
        for col, col_type in [("time_slot", "VARCHAR(100) DEFAULT NULL"),
                              ("booking_type", "VARCHAR(50) DEFAULT NULL CHECK (booking_type IN ('appointment', 'callback'))"),
                              ("booking_time", "VARCHAR(100) DEFAULT NULL"),
                              ("staff_agent_id", "INTEGER REFERENCES staff_agents(id) ON DELETE SET NULL")]:
            try:
                cursor.execute(f"ALTER TABLE service_requests ADD COLUMN {col} {col_type}")
            except sqlite3.OperationalError:
                # Column already exists
                pass

        # Auto-migration: drop legacy tables if they exist to keep schema clean
        for table in ["appointments", "callback_requests"]:
            try:
                cursor.execute(f"DROP TABLE IF EXISTS {table}")
            except sqlite3.OperationalError:
                pass
                
        conn.commit()
        _db_initialized = True
    finally:
        conn.close()

@contextmanager
def get_db_connection():
    """Context manager yielding an SQLite connection with foreign keys enabled."""
    global _db_initialized
    db_path = get_db_path()
    if not _db_initialized:
        init_db(db_path)
        
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
