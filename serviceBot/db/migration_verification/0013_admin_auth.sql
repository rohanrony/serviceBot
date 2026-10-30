-- Must return no rows: all auth tables exist with RLS enabled.
SELECT c.relname, c.relrowsecurity
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public'
  AND c.relname IN ('admin_accounts', 'admin_sessions', 'admin_login_attempts')
  AND (NOT c.relrowsecurity OR c.relkind <> 'r');

-- Must return no rows: required auth columns are present.
SELECT required.table_name, required.column_name
FROM (VALUES
  ('admin_accounts','email'), ('admin_accounts','password_hash'),
  ('admin_sessions','token_hash'), ('admin_sessions','csrf_token_hash'),
  ('admin_sessions','expires_at'), ('admin_sessions','revoked_at'),
  ('admin_login_attempts','client_ip'), ('admin_login_attempts','attempted_at')
) AS required(table_name, column_name)
LEFT JOIN information_schema.columns c
  ON c.table_schema='public' AND c.table_name=required.table_name AND c.column_name=required.column_name
WHERE c.column_name IS NULL;

-- Must return no rows: browser-facing and public roles have no table grants.
SELECT grantee, table_name, privilege_type
FROM information_schema.role_table_grants
WHERE table_schema='public'
  AND table_name IN ('admin_accounts', 'admin_sessions', 'admin_login_attempts')
  AND grantee IN ('PUBLIC', 'anon', 'authenticated', 'service_role');

-- Must return no rows: expected checks and key constraints exist in the live
-- catalog with their exact required columns and expressions.
SELECT required.violation
FROM (VALUES
    ('admin_accounts singleton check missing or altered', 'admin_accounts', '((id=1))'),
    ('admin_accounts email normalization check missing or altered', 'admin_accounts', '((email=lower(btrim(email))))'),
    ('admin_accounts Argon2id check missing or altered', 'admin_accounts', '((password_hash~~''$argon2id$%''::text))'),
    ('admin_sessions token digest check missing or altered', 'admin_sessions', '((token_hash~''^[0-9a-f]{64}$''::text))'),
    ('admin_sessions CSRF digest check missing or altered', 'admin_sessions', '((csrf_token_hash~''^[0-9a-f]{64}$''::text))'),
    ('admin_sessions expiry check missing or altered', 'admin_sessions', '((expires_at>created_at))')
) AS required(violation, table_name, normalized_definition)
WHERE NOT EXISTS (
    SELECT 1 FROM pg_constraint constraint_row
    WHERE constraint_row.conrelid = format('public.%I', required.table_name)::regclass
      AND constraint_row.contype = 'c'
      -- pg_get_constraintdef consistently wraps CHECK expressions in two
      -- formatting parentheses. Preserve parentheses and strip only whitespace
      -- so function calls and the complete expression are compared exactly.
      AND regexp_replace(
            regexp_replace(lower(pg_get_constraintdef(constraint_row.oid)), '^[[:space:]]*check[[:space:]]*', '', 'g'),
            '[[:space:]]', '', 'g'
          )
          = required.normalized_definition
)
UNION ALL
SELECT required.violation
FROM (VALUES
    ('admin_accounts primary key on id missing or altered', 'admin_accounts', 'p', 'id'),
    ('admin_accounts unique email missing or altered', 'admin_accounts', 'u', 'email'),
    ('admin_sessions unique token_hash missing or altered', 'admin_sessions', 'u', 'token_hash')
) AS required(violation, table_name, constraint_type, column_name)
WHERE NOT EXISTS (
    SELECT 1
    FROM pg_constraint constraint_row
    JOIN pg_attribute attribute_row
      ON attribute_row.attrelid = constraint_row.conrelid
     AND attribute_row.attname = required.column_name
     AND NOT attribute_row.attisdropped
    WHERE constraint_row.conrelid = format('public.%I', required.table_name)::regclass
      AND constraint_row.contype = required.constraint_type
      AND constraint_row.conkey = ARRAY[attribute_row.attnum]::smallint[]
)
UNION ALL
SELECT 'admin_accounts data invariant'
WHERE EXISTS (
    SELECT 1 FROM public.admin_accounts
    WHERE id <> 1 OR email <> lower(btrim(email)) OR password_hash NOT LIKE '$argon2id$%'
) OR (SELECT COUNT(*) FROM public.admin_accounts) > 1;

-- Must return no rows: session secrets are lowercase SHA-256 digests and
-- their expiry follows creation.
SELECT 'admin_sessions data invariant' AS violation
WHERE EXISTS (
    SELECT 1 FROM public.admin_sessions
    WHERE token_hash !~ '^[0-9a-f]{64}$'
       OR csrf_token_hash !~ '^[0-9a-f]{64}$'
       OR expires_at <= created_at
);
