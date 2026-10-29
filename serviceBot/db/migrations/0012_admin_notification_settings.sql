CREATE TABLE public.admin_notification_settings (
    id SMALLINT PRIMARY KEY CHECK (id = 1),
    gmail_recipient TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE public.admin_notification_settings ENABLE ROW LEVEL SECURITY;
REVOKE ALL PRIVILEGES ON TABLE public.admin_notification_settings FROM PUBLIC;

DO $$
DECLARE
    role_name TEXT;
BEGIN
    FOREACH role_name IN ARRAY ARRAY['anon', 'authenticated', 'service_role'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = role_name) THEN
            EXECUTE format(
                'REVOKE ALL PRIVILEGES ON TABLE public.admin_notification_settings FROM %I',
                role_name
            );
        END IF;
    END LOOP;
END $$;
