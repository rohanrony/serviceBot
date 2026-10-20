-- Inert unless explicitly enabled. Owns only fresh simulation services/requests.
CREATE TABLE IF NOT EXISTS simulation_fault_leases (
    handle UUID PRIMARY KEY,
    run_id VARCHAR(80) NOT NULL,
    mode TEXT NOT NULL CHECK (mode IN ('calendar_once','response_loss_once')),
    service_id INTEGER UNIQUE REFERENCES services(id) ON DELETE RESTRICT,
    original_service_id INTEGER NOT NULL,
    service_name VARCHAR(100) NOT NULL UNIQUE,
    service_snapshot JSONB NOT NULL,
    technician_id INTEGER NOT NULL REFERENCES staff_agents(id) ON DELETE RESTRICT,
    arguments JSONB NOT NULL,
    arguments_hash CHAR(64) NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    phase TEXT NOT NULL DEFAULT 'prepared' CHECK (phase IN ('prepared','executing','bound','committed','unknown','disarmed','cleaned')),
    request_watermark BIGINT,
    tool_payload_hash CHAR(64),
    request_id INTEGER UNIQUE REFERENCES service_requests(id) ON DELETE RESTRICT,
    reservation_id INTEGER UNIQUE REFERENCES appointment_reservations(id) ON DELETE RESTRICT,
    outbox_id BIGINT UNIQUE REFERENCES outbox_notifications(id) ON DELETE RESTRICT,
    outbox_payload_hash CHAR(64),
    fault_consumed_at TIMESTAMPTZ,
    response_loss_consumed_at TIMESTAMPTZ,
    result JSONB,
    retired_binding JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(run_id,mode),
    CHECK ((request_id IS NULL) = (reservation_id IS NULL)),
    CHECK ((request_id IS NULL) = (outbox_id IS NULL)),
    CHECK ((outbox_id IS NULL) = (outbox_payload_hash IS NULL)),
    CHECK (phase NOT IN ('bound','committed') OR request_id IS NOT NULL),
    CHECK (phase <> 'cleaned' OR service_id IS NULL),
    CHECK (fault_consumed_at IS NULL OR (mode='calendar_once' AND (outbox_id IS NOT NULL OR phase='cleaned'))),
    CHECK (response_loss_consumed_at IS NULL OR (mode='response_loss_once' AND (request_id IS NOT NULL OR phase='cleaned'))),
    CHECK (arguments_hash ~ '^[0-9a-f]{64}$')
);
CREATE TABLE IF NOT EXISTS simulation_fault_journal (
    id BIGSERIAL PRIMARY KEY,
    handle UUID NOT NULL REFERENCES simulation_fault_leases(handle) ON DELETE RESTRICT,
    event TEXT NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS simulation_fault_outbox_idx ON simulation_fault_leases(outbox_id)
    WHERE mode='calendar_once';
