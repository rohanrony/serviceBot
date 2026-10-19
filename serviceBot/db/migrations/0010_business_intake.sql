ALTER TABLE service_requests ADD COLUMN IF NOT EXISTS intake_data JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE service_requests ADD CONSTRAINT service_requests_intake_object CHECK (jsonb_typeof(intake_data) = 'object');
