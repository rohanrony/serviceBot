-- Migration: 0004_audit_trace_enrichment
-- Enhances service_request_audit_log with event categorization, actor attribution, and JSON metadata

ALTER TABLE service_request_audit_log 
ADD COLUMN IF NOT EXISTS event_type VARCHAR(50) DEFAULT 'STATUS_CHANGE',
ADD COLUMN IF NOT EXISTS actor_name VARCHAR(100) DEFAULT NULL,
ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}'::jsonb;

CREATE INDEX IF NOT EXISTS idx_sr_audit_log_event_type 
    ON service_request_audit_log(request_id, event_type);
