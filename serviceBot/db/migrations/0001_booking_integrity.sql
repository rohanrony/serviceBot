-- PostgreSQL booking authority, calendar integration state, and webhook idempotency.
-- This migration is intentionally append-only; see 0001_booking_integrity.down.sql
-- for an explicit development rollback.

CREATE TABLE IF NOT EXISTS mock_calendar_slots (
    id SERIAL PRIMARY KEY,
    slot_datetime TIMESTAMP NOT NULL,
    is_booked BOOLEAN NOT NULL DEFAULT FALSE,
    staff_agent_id INTEGER NOT NULL REFERENCES staff_agents(id) ON DELETE CASCADE,
    reservation_status VARCHAR(32) NOT NULL DEFAULT 'AVAILABLE'
        CHECK (reservation_status IN ('AVAILABLE', 'RESERVED', 'BLOCKED')),
    service_request_id INTEGER DEFAULT NULL REFERENCES service_requests(id) ON DELETE SET NULL,
    calendar_integration_status VARCHAR(32) NOT NULL DEFAULT 'NOT_REQUIRED'
        CHECK (calendar_integration_status IN ('NOT_REQUIRED', 'PENDING_CALENDAR', 'CREATED', 'FAILED')),
    calendar_event_id TEXT DEFAULT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(slot_datetime, staff_agent_id)
);

ALTER TABLE mock_calendar_slots
    ADD COLUMN IF NOT EXISTS reservation_status VARCHAR(32) NOT NULL DEFAULT 'AVAILABLE';
ALTER TABLE mock_calendar_slots
    ADD COLUMN IF NOT EXISTS service_request_id INTEGER DEFAULT NULL REFERENCES service_requests(id) ON DELETE SET NULL;
ALTER TABLE mock_calendar_slots
    ADD COLUMN IF NOT EXISTS calendar_integration_status VARCHAR(32) NOT NULL DEFAULT 'NOT_REQUIRED';
ALTER TABLE mock_calendar_slots
    ADD COLUMN IF NOT EXISTS calendar_event_id TEXT DEFAULT NULL;
ALTER TABLE mock_calendar_slots
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;
ALTER TABLE mock_calendar_slots
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

CREATE INDEX IF NOT EXISTS idx_calendar_slots_agent_time
    ON mock_calendar_slots(staff_agent_id, slot_datetime);

ALTER TABLE service_requests
    ADD COLUMN IF NOT EXISTS booking_start_at TIMESTAMP DEFAULT NULL;
ALTER TABLE service_requests
    ADD COLUMN IF NOT EXISTS booking_end_at TIMESTAMP DEFAULT NULL;
ALTER TABLE service_requests
    ADD COLUMN IF NOT EXISTS calendar_integration_status VARCHAR(32) NOT NULL DEFAULT 'NOT_REQUIRED';
ALTER TABLE service_requests
    ADD COLUMN IF NOT EXISTS calendar_event_id TEXT DEFAULT NULL;

CREATE TABLE IF NOT EXISTS appointment_reservations (
    id SERIAL PRIMARY KEY,
    service_request_id INTEGER NOT NULL UNIQUE REFERENCES service_requests(id) ON DELETE CASCADE,
    staff_agent_id INTEGER NOT NULL REFERENCES staff_agents(id) ON DELETE RESTRICT,
    starts_at TIMESTAMP NOT NULL,
    ends_at TIMESTAMP NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'ACTIVE'
        CHECK (status IN ('ACTIVE', 'CANCELLED')),
    calendar_integration_status VARCHAR(32) NOT NULL DEFAULT 'PENDING_CALENDAR'
        CHECK (calendar_integration_status IN ('PENDING_CALENDAR', 'CREATED', 'FAILED')),
    calendar_event_id TEXT DEFAULT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (ends_at > starts_at)
);

CREATE TABLE IF NOT EXISTS appointment_reservation_segments (
    reservation_id INTEGER NOT NULL REFERENCES appointment_reservations(id) ON DELETE CASCADE,
    staff_agent_id INTEGER NOT NULL REFERENCES staff_agents(id) ON DELETE RESTRICT,
    segment_start TIMESTAMP NOT NULL,
    PRIMARY KEY (staff_agent_id, segment_start)
);

CREATE INDEX IF NOT EXISTS idx_appointment_reservations_agent_time
    ON appointment_reservations(staff_agent_id, starts_at);

CREATE TABLE IF NOT EXISTS webhook_events (
    id SERIAL PRIMARY KEY,
    provider VARCHAR(32) NOT NULL,
    event_id VARCHAR(255) NOT NULL,
    payload_hash VARCHAR(128) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'PROCESSING'
        CHECK (status IN ('PROCESSING', 'COMPLETED', 'FAILED')),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP DEFAULT NULL,
    UNIQUE(provider, event_id)
);

ALTER TABLE sms_log
    ADD COLUMN IF NOT EXISTS body TEXT DEFAULT NULL;
ALTER TABLE sms_log
    ADD COLUMN IF NOT EXISTS channel VARCHAR(20) NOT NULL DEFAULT 'SMS';

DO $$
DECLARE
    existing_constraint TEXT;
BEGIN
    SELECT conname
      INTO existing_constraint
      FROM pg_constraint
     WHERE conrelid = 'sms_conversations'::regclass
       AND contype = 'c'
       AND pg_get_constraintdef(oid) LIKE '%state%';

    IF existing_constraint IS NOT NULL THEN
        EXECUTE format('ALTER TABLE sms_conversations DROP CONSTRAINT %I', existing_constraint);
    END IF;
END $$;

ALTER TABLE sms_conversations
    ADD CONSTRAINT sms_conversations_state_check
    CHECK (state IN (
        'AUTOMATED',
        'HANDOFF_REQUIRED',
        'IN_PROGRESS',
        'RESOLVED',
        'OUT_OF_BUSINESS_HOURS'
    ));

