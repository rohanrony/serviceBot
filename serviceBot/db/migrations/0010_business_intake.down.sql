DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM service_requests WHERE intake_data <> '{}'::jsonb) THEN
        RAISE EXCEPTION 'Cannot roll back business intake while recorded intake exists; export and migrate it first';
    END IF;
END $$;
ALTER TABLE service_requests DROP COLUMN intake_data;
