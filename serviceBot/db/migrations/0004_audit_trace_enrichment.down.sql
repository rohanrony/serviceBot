-- Migration Rollback: 0004_audit_trace_enrichment
DROP INDEX IF EXISTS idx_sr_audit_log_event_type;

ALTER TABLE service_request_audit_log 
DROP COLUMN IF EXISTS metadata,
DROP COLUMN IF EXISTS actor_name,
DROP COLUMN IF EXISTS event_type;
