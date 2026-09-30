-- Migration: 0003_reminders_escalation
-- Adds confirmation and escalation tracking to service_requests and sms_reminders

ALTER TABLE service_requests 
ADD COLUMN IF NOT EXISTS confirmation_status VARCHAR(40) DEFAULT 'pending_agent_confirmation',
ADD COLUMN IF NOT EXISTS escalation_status VARCHAR(40) DEFAULT 'none',
ADD COLUMN IF NOT EXISTS escalation_reason VARCHAR(50) DEFAULT NULL,
ADD COLUMN IF NOT EXISTS confirmation_cutoff_at TIMESTAMP DEFAULT NULL,
ADD COLUMN IF NOT EXISTS confirmed_at TIMESTAMP DEFAULT NULL;

CREATE INDEX IF NOT EXISTS idx_sr_confirmation_cutoff 
    ON service_requests(confirmation_status, confirmation_cutoff_at);

CREATE INDEX IF NOT EXISTS idx_sr_escalation_status 
    ON service_requests(escalation_status);

ALTER TABLE sms_reminders 
ADD COLUMN IF NOT EXISTS attempt_number INTEGER DEFAULT 1,
ADD COLUMN IF NOT EXISTS attempt_kind VARCHAR(50) DEFAULT 'final_reminder',
ADD COLUMN IF NOT EXISTS retry_count INTEGER DEFAULT 0,
ADD COLUMN IF NOT EXISTS last_error TEXT DEFAULT NULL;

CREATE INDEX IF NOT EXISTS idx_sms_reminders_polling 
    ON sms_reminders(status, scheduled_at);

CREATE INDEX IF NOT EXISTS idx_staff_agents_phone 
    ON staff_agents(phone_number);
