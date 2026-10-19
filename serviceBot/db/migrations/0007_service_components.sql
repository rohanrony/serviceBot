-- Nullable: historical composite labels are never guessed or rewritten.
ALTER TABLE service_requests ADD COLUMN IF NOT EXISTS service_components JSONB;
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
        WHERE conrelid='service_requests'::regclass AND conname='service_requests_components_array') THEN
        ALTER TABLE service_requests ADD CONSTRAINT service_requests_components_array
            CHECK (service_components IS NULL OR jsonb_typeof(service_components) = 'array');
    END IF;
END $$;
