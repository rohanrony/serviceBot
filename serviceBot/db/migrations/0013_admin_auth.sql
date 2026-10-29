CREATE TABLE public.admin_accounts (
    id SMALLINT PRIMARY KEY CHECK (id = 1),
    email TEXT NOT NULL UNIQUE CHECK (email = lower(btrim(email))),
    password_hash TEXT NOT NULL CHECK (password_hash LIKE '$argon2id$%'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE public.admin_sessions (
    id BIGSERIAL PRIMARY KEY,
    token_hash TEXT NOT NULL UNIQUE CHECK (token_hash ~ '^[0-9a-f]{64}$'),
    csrf_token_hash TEXT NOT NULL CHECK (csrf_token_hash ~ '^[0-9a-f]{64}$'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,
    CHECK (expires_at > created_at)
);
CREATE INDEX admin_sessions_active_expiry_idx ON public.admin_sessions (expires_at)
    WHERE revoked_at IS NULL;

CREATE TABLE public.admin_login_attempts (
    id BIGSERIAL PRIMARY KEY,
    client_ip INET NOT NULL,
    attempted_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX admin_login_attempts_ip_time_idx
    ON public.admin_login_attempts (client_ip, attempted_at DESC);

DO $$
DECLARE table_name TEXT;
DECLARE role_name TEXT;
BEGIN
    FOREACH table_name IN ARRAY ARRAY['admin_accounts', 'admin_sessions', 'admin_login_attempts'] LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', table_name);
        EXECUTE format('REVOKE ALL PRIVILEGES ON TABLE public.%I FROM PUBLIC', table_name);
        FOREACH role_name IN ARRAY ARRAY['anon', 'authenticated', 'service_role'] LOOP
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = role_name) THEN
                EXECUTE format('REVOKE ALL PRIVILEGES ON TABLE public.%I FROM %I', table_name, role_name);
            END IF;
        END LOOP;
    END LOOP;
END $$;
