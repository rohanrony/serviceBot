# Database Specification (VoiceAI)

This document defines the schema, relations, index strategy, and query patterns for the VoiceAI local SQLite (MVP) and PostgreSQL (Production) database.

---

## 1. Entity Relationship Diagram (ERD)

```mermaid
erDiagram
    CUSTOMERS ||--o{ VEHICLES : owns
    CUSTOMERS ||--o{ SERVICE_REQUESTS : requests
    CUSTOMERS ||--o{ CRM_NOTES : has
    VEHICLES ||--o{ SERVICE_REQUESTS : service_history
    STAFF_AGENTS ||--o{ MOCK_CALENDAR_SLOTS : schedules
    STAFF_AGENTS ||--o| USER_GOOGLE_ACCOUNTS : authenticates
    STAFF_AGENTS ||--o{ OAUTH_STATES : initiates
    STAFF_AGENTS ||--o{ SERVICE_REQUESTS : handles

    CUSTOMERS {
        INTEGER id PK
        VARCHAR name
        VARCHAR phone UNIQUE
        VARCHAR email
        TIMESTAMP created_at
    }

    VEHICLES {
        INTEGER id PK
        INTEGER customer_id FK
        VARCHAR make
        VARCHAR model
        INTEGER year
        VARCHAR vin
        TIMESTAMP created_at
    }

    SERVICE_REQUESTS {
        INTEGER id PK
        INTEGER customer_id FK
        INTEGER vehicle_id FK
        VARCHAR service_type
        TEXT issue_description
        VARCHAR status "pending | in_progress | completed | cancelled"
        VARCHAR time_slot
        VARCHAR booking_type "appointment | callback | NULL"
        VARCHAR booking_time "datetime | ASAP | NULL"
        INTEGER staff_agent_id FK "nullable"
        TIMESTAMP created_at
        TIMESTAMP updated_at
    }

    CRM_NOTES {
        INTEGER id PK
        VARCHAR call_id "external (Twilio/ElevenLabs)"
        INTEGER customer_id FK
        TEXT summary
        TEXT transcript
        TIMESTAMP created_at
    }

    STAFF_AGENTS {
        INTEGER id PK
        VARCHAR name
        VARCHAR role
        VARCHAR email
        TEXT google_access_token
        TEXT google_refresh_token
        REAL google_token_expires_at
    }

    MOCK_CALENDAR_SLOTS {
        INTEGER id PK
        TIMESTAMP slot_datetime
        BOOLEAN is_booked
        INTEGER staff_agent_id FK "nullable"
        TIMESTAMP created_at
    }

    SERVICES {
        INTEGER id PK
        VARCHAR name
        TEXT description
        VARCHAR price_range
        INTEGER duration_minutes
        BOOLEAN req_customer_name
        BOOLEAN req_phone_number
        BOOLEAN req_vehicle_details
        BOOLEAN req_issue_description
        BOOLEAN req_location
    }

    USER_GOOGLE_ACCOUNTS {
        INTEGER agent_id PK
        VARCHAR provider
        VARCHAR google_account_id
        VARCHAR email
        TEXT access_token
        TEXT refresh_token
        REAL expires_at
        TEXT granted_scopes
        REAL last_refresh_time
    }

    OAUTH_STATES {
        VARCHAR state PK
        INTEGER agent_id FK
        VARCHAR action_type
        TIMESTAMP created_at
    }
```

---

## 2. Table Definitions & Schema DDL

```sql
-- Enable foreign key support in SQLite (must run at connection start)
PRAGMA foreign_keys = ON;

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

-- Index on customer_id for fast fetching of customer's service requests
CREATE INDEX IF NOT EXISTS idx_service_requests_customer ON service_requests(customer_id);

-- 4. CRM Notes Table
CREATE TABLE IF NOT EXISTS crm_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    call_id VARCHAR(255) NOT NULL UNIQUE,
    customer_id INTEGER NOT NULL,
    summary TEXT NOT NULL,
    transcript TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE CASCADE
);

-- Index for CRM notes
CREATE INDEX IF NOT EXISTS idx_crm_notes_customer ON crm_notes(customer_id);

-- 5. Staff Agents Table
CREATE TABLE IF NOT EXISTS staff_agents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(255) NOT NULL,
    role VARCHAR(100) DEFAULT NULL,
    email VARCHAR(255) DEFAULT NULL,
    google_access_token TEXT DEFAULT NULL,
    google_refresh_token TEXT DEFAULT NULL,
    google_token_expires_at REAL DEFAULT NULL
);

-- 6. Mock Calendar Slots Table (Associated with Staff Agents)
CREATE TABLE IF NOT EXISTS mock_calendar_slots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slot_datetime TIMESTAMP NOT NULL,
    is_booked BOOLEAN NOT NULL DEFAULT 0,
    staff_agent_id INTEGER DEFAULT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (staff_agent_id) REFERENCES staff_agents(id) ON DELETE CASCADE,
    UNIQUE(slot_datetime, staff_agent_id)
);

-- Index on slot_datetime for fast availability lookups
CREATE INDEX IF NOT EXISTS idx_mock_calendar_slots_datetime ON mock_calendar_slots(slot_datetime);

-- 7. Services Catalog Table
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

-- 8. User Google Accounts Table (Agent Calendar & Email Auth)
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

-- 9. OAuth States Table (CSRF Protection for OAuth callbacks)
CREATE TABLE IF NOT EXISTS oauth_states (
    state VARCHAR(255) PRIMARY KEY,
    agent_id INTEGER NOT NULL,
    action_type VARCHAR(50) NOT NULL, -- 'calendar' or 'gmail'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (agent_id) REFERENCES staff_agents(id) ON DELETE CASCADE
);
```

---

## 3. Core Query Patterns (SQL)

### 3.1 Pre-Call CRM Lookup (Customer Search)
Used by the incoming call router to verify identity, retrieve vehicle history, and check active service requests.
```sql
SELECT 
    c.id AS customer_id,
    c.name,
    c.phone,
    v.id AS vehicle_id,
    v.make,
    v.model,
    v.year,
    sr.id AS open_sr_id,
    sr.service_type AS open_sr_type,
    sr.status AS open_sr_status
FROM customers c
LEFT JOIN vehicles v ON c.id = v.customer_id
LEFT JOIN service_requests sr ON c.id = sr.customer_id AND sr.status = 'pending'
WHERE c.phone = ?;
```

### 3.2 Calendar Availability Check
Used by the appointment agent to check available slots from the mock calendar.
```sql
SELECT slot_datetime, staff_agent_id 
FROM mock_calendar_slots 
WHERE is_booked = 0 AND slot_datetime >= ? 
ORDER BY slot_datetime ASC 
LIMIT 3;
```

### 3.3 Book Mock Calendar Slot
Used to mark a slot as booked when scheduling an appointment.
```sql
UPDATE mock_calendar_slots 
SET is_booked = 1 
WHERE slot_datetime = ? AND staff_agent_id = ?;
```

---

## 4. Mock Seed Data (CBA Demo)

```sql
INSERT INTO customers (name, phone, email) VALUES 
('Sarah Johnson', '555-123-4567', 'sarah.j@example.com'),
('David Smith', '555-987-6543', 'dsmith@example.com');

INSERT INTO vehicles (customer_id, make, model, year, vin) VALUES 
(1, 'Honda', 'Civic', 2020, '1HGCR2F8LAA123456'),
(2, 'Ford', 'F-150', 2018, '1FTFW1EF5JFC98765');

INSERT INTO service_requests (customer_id, vehicle_id, service_type, issue_description, status) VALUES 
(1, 1, 'Brake repair', 'Grinding noise when stopping, brake light on.', 'pending');

INSERT INTO staff_agents (name, role) VALUES
('John Doe', 'Master Mechanic'),
('Jane Smith', 'Senior Technician');

-- Seed Mock Calendar Slots
INSERT OR IGNORE INTO mock_calendar_slots (slot_datetime, is_booked, staff_agent_id) VALUES
('2026-06-09 14:00:00', 0, 1),
('2026-06-09 16:00:00', 0, 1),
('2026-06-10 10:00:00', 0, 2),
('2026-06-10 11:00:00', 0, 2),
('2026-06-10 14:00:00', 0, 1);
```
