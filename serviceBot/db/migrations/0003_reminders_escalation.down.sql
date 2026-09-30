-- Rollback migration: 0003_reminders_escalation

DROP INDEX IF EXISTS idx_staff_agents_phone;
DROP INDEX IF EXISTS idx_sms_reminders_polling;
DROP INDEX IF EXISTS idx_sr_escalation_status;
DROP INDEX IF EXISTS idx_sr_confirmation_cutoff;

ALTER TABLE sms_reminders 
DROP COLUMN IF EXISTS last_error,
DROP COLUMN IF EXISTS retry_count,
DROP COLUMN IF EXISTS attempt_kind,
DROP COLUMN IF EXISTS attempt_number;

ALTER TABLE service_requests 
DROP COLUMN IF EXISTS confirmed_at,
DROP COLUMN IF EXISTS confirmation_cutoff_at,
DROP COLUMN IF EXISTS escalation_reason,
DROP COLUMN IF EXISTS escalation_status,
DROP COLUMN IF EXISTS confirmation_status;
