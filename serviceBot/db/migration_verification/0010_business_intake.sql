-- Must return no rows after migration.
SELECT id FROM service_requests WHERE intake_data IS NULL OR jsonb_typeof(intake_data) <> 'object';
