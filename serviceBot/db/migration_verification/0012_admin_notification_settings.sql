-- Confirm the durable recipient schema and row-level security are present.
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'admin_notification_settings'
ORDER BY ordinal_position;

SELECT relrowsecurity, relforcerowsecurity
FROM pg_class
WHERE oid = 'public.admin_notification_settings'::regclass;

-- This query should return no rows for browser-facing Supabase roles.
SELECT grantee, privilege_type
FROM information_schema.role_table_grants
WHERE table_schema = 'public'
  AND table_name = 'admin_notification_settings'
  AND grantee IN ('PUBLIC', 'anon', 'authenticated', 'service_role')
ORDER BY grantee, privilege_type;
