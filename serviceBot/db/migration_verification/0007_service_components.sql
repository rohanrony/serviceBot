-- Read-only verification; expect jsonb, nullable YES and zero invalid snapshots.
SELECT data_type, is_nullable FROM information_schema.columns
WHERE table_schema='public' AND table_name='service_requests' AND column_name='service_components';
SELECT count(*) AS invalid_component_types FROM service_requests
WHERE service_components IS NOT NULL AND jsonb_typeof(service_components) <> 'array';
