"""Unit coverage for the explicit PostgreSQL migration contract."""

from serviceBot.db.migrations import (
    apply_migrations,
    available_migrations,
    migration_version,
    rollback_migration,
)


class FakeCursor:
    def __init__(self, applied):
        self.applied = applied
        self.executed = []
        self._rows = []

    def execute(self, statement, params=None):
        self.executed.append((statement, params))
        normalized = str(statement).strip().upper()
        if normalized.startswith("SELECT VERSION"):
            self._rows = [(version,) for version in sorted(self.applied)]
        elif normalized.startswith("INSERT INTO SCHEMA_MIGRATIONS"):
            self.applied.add(params[0])
        elif normalized.startswith("DELETE FROM SCHEMA_MIGRATIONS"):
            self.applied.discard(params[0])

    def fetchall(self):
        return self._rows

    def close(self):
        pass


class FakeConnection:
    def __init__(self):
        self.applied = set()
        self.cursor_instance = FakeCursor(self.applied)
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return self.cursor_instance

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def test_booking_integrity_migrations_have_explicit_rollbacks():
    migrations = available_migrations()
    assert [migration_version(path) for path in migrations] == [
        "0001_booking_integrity",
        "0002_webhook_replay_and_reservation_backfill",
        "0003_reminders_escalation",
        "0004_audit_trace_enrichment",
        "0005_staff_agent_soft_delete_and_escalation",
        "0006_calendar_deletion_state",
        "0007_service_components",
        "0008_authenticated_webhook_ingress",
        "0009_simulation_fault_leases",
        "0010_business_intake",
        "0011_simulation_staff_intents",
        "0012_admin_notification_settings",
        "0013_admin_auth",
    ]

    for forward in migrations:
        rollback = forward.with_name(f"{forward.stem}.down.sql")
        assert rollback.exists()

    integrity_sql = migrations[0].read_text(encoding="utf-8")
    assert "appointment_reservation_segments" in integrity_sql
    assert "webhook_events" in integrity_sql
    assert "OUT_OF_BUSINESS_HOURS" in integrity_sql

    backfill_sql = migrations[1].read_text(encoding="utf-8")
    assert "updated_at" in backfill_sql
    assert "appointment_reservation_segments" in backfill_sql

    admin_email_path = next(path for path in migrations if migration_version(path) == "0012_admin_notification_settings")
    admin_email_migration = admin_email_path.read_text(encoding="utf-8")
    assert "admin_notification_settings" in admin_email_migration
    assert "gmail_recipient TEXT NOT NULL" in admin_email_migration
    assert "ENABLE ROW LEVEL SECURITY" in admin_email_migration
    assert "REVOKE ALL PRIVILEGES" in admin_email_migration
    verification = admin_email_path.parent.parent / "migration_verification" / admin_email_path.name
    statements = "\n".join(
        line for line in verification.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("--")
    )
    queries = [statement.strip() for statement in statements.split(";") if statement.strip()]
    assert len(queries) == 3
    assert all(query.startswith("SELECT ") for query in queries)


def test_migration_runner_is_idempotent_and_can_rollback(tmp_path):
    forward = tmp_path / "0001_example.sql"
    forward.write_text("CREATE TABLE example (id INTEGER);", encoding="utf-8")
    rollback = tmp_path / "0001_example.down.sql"
    rollback.write_text("DROP TABLE example;", encoding="utf-8")

    conn = FakeConnection()
    assert apply_migrations(conn, tmp_path) == ["0001_example"]
    assert apply_migrations(conn, tmp_path) == []

    rollback_migration(conn, "0001_example", tmp_path)
    statements = [statement for statement, _ in conn.cursor_instance.executed]
    assert any("DROP TABLE example" in statement for statement in statements)
    assert conn.applied == set()



def test_service_component_migration_preserves_legacy_rows_and_has_read_only_verification():
    forward = next(path for path in available_migrations()
                   if migration_version(path) == "0007_service_components")
    sql = forward.read_text(encoding="utf-8")
    assert "ADD COLUMN IF NOT EXISTS service_components JSONB" in sql
    assert "NOT NULL" not in sql
    assert "DEFAULT" not in sql
    assert "UPDATE service_requests" not in sql
    assert "IF NOT EXISTS (SELECT 1 FROM pg_constraint" in sql
    assert "conrelid='service_requests'::regclass" in sql
    assert "conname='service_requests_components_array'" in sql
    assert "service_components IS NULL OR jsonb_typeof(service_components) = 'array'" in sql

    rollback = forward.with_name(f"{forward.stem}.down.sql").read_text(encoding="utf-8")
    assert "DROP COLUMN IF EXISTS service_components" in rollback
    assert "DROP TABLE" not in rollback
    assert "DELETE FROM" not in rollback

    verification = forward.parent.parent / "migration_verification" / forward.name
    statements = "\n".join(line for line in verification.read_text(encoding="utf-8").splitlines()
                           if not line.lstrip().startswith("--"))
    queries = [statement.strip() for statement in statements.split(";") if statement.strip()]
    assert len(queries) == 2
    assert all(query.startswith("SELECT ") for query in queries)
    assert "data_type, is_nullable" in queries[0]
    assert "column_name='service_components'" in queries[0]
    assert "invalid_component_types" in queries[1]
    assert "jsonb_typeof(service_components) <> 'array'" in queries[1]


def test_admin_auth_migration_applies_schema_privileges_and_reversible_contract():
    migrations = available_migrations()
    forward = next(path for path in migrations if migration_version(path) == "0013_admin_auth")
    assert migrations[-1] == forward
    sql = forward.read_text(encoding="utf-8").lower()
    rollback_path = forward.with_name(f"{forward.stem}.down.sql")
    rollback = rollback_path.read_text(encoding="utf-8").lower()
    verification_path = forward.parent.parent / "migration_verification" / forward.name
    verification_text = verification_path.read_text(encoding="utf-8")
    verification = "\n".join(line for line in verification_text.splitlines() if not line.lstrip().startswith("--"))
    queries = [statement.strip() for statement in verification.split(";") if statement.strip()]
    assert all(term in sql for term in ("password_hash", "token_hash", "csrf", "expires_at", "revoked_at", "row level security", "revoke all privileges"))
    assert "id smallint primary key check (id = 1)" in sql
    assert "email text not null unique check (email = lower(btrim(email)))" in sql
    assert "password_hash text not null check (password_hash like '$argon2id$%')" in sql
    assert "token_hash ~ '^[0-9a-f]{64}$'" in sql
    assert "csrf_token_hash ~ '^[0-9a-f]{64}$'" in sql
    assert "check (expires_at > created_at)" in sql
    assert "drop table" in rollback and "delete from" not in rollback
    assert len(queries) == 5
    assert all(statement.startswith("SELECT ") for statement in queries)
    constraint_audit = next(statement for statement in queries if "pg_constraint" in statement)
    normalized_constraint_audit = "".join(constraint_audit.lower().split())
    assert "id=1" in normalized_constraint_audit
    assert "email=lower(btrim(email))" in normalized_constraint_audit
    assert "((email=lower(btrim(email))))" in normalized_constraint_audit
    assert "'[[:space:]]'" in normalized_constraint_audit
    assert "$argon2id$" in normalized_constraint_audit
    assert "token_hash~''^[0-9a-f]{64}$''" in normalized_constraint_audit
    assert "csrf_token_hash~''^[0-9a-f]{64}$''" in normalized_constraint_audit
    assert "expires_at>created_at" in normalized_constraint_audit
    assert "constraint_row.contype='c'" in normalized_constraint_audit
    assert "notexists" in normalized_constraint_audit
    assert any("password_hash not like '$argon2id$%'" in statement.lower() for statement in queries)
    assert any("token_hash !~" in statement and "expires_at <= created_at" in statement for statement in queries)


def test_admin_auth_migration_schema_is_present_in_disposable_database():
    from serviceBot.db.connection import get_db_connection

    with get_db_connection() as conn, conn.cursor() as cursor:
        cursor.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'")
        tables = {row[0] for row in cursor.fetchall()}
        auth_tables = {name for name in tables if "admin" in name and any(part in name for part in ("account", "session", "attempt"))}
        assert len(auth_tables) >= 3
        cursor.execute("SELECT tablename, rowsecurity FROM pg_tables WHERE schemaname='public' AND tablename = ANY(%s)", (list(auth_tables),))
        assert all(enabled for _, enabled in cursor.fetchall())
        cursor.execute("SELECT version FROM schema_migrations WHERE version='0013_admin_auth'")
        version_row = cursor.fetchone()
        assert version_row is not None and tuple(version_row) == ("0013_admin_auth",)
        verification_path = next(path for path in available_migrations() if migration_version(path) == "0013_admin_auth").parent.parent / "migration_verification" / "0013_admin_auth.sql"
        statements = "\n".join(line for line in verification_path.read_text(encoding="utf-8").splitlines() if not line.lstrip().startswith("--"))
        for statement in (part.strip() for part in statements.split(";") if part.strip()):
            cursor.execute(statement)
            assert cursor.fetchall() == [], f"migration verification found a violation: {statement[:100]}"


def test_admin_auth_migration_verifier_reports_missing_or_weakened_constraints_transactionally():
    from serviceBot.db.connection import get_db_connection

    verification_path = next(path for path in available_migrations() if migration_version(path) == "0013_admin_auth").parent.parent / "migration_verification" / "0013_admin_auth.sql"
    statements = "\n".join(line for line in verification_path.read_text(encoding="utf-8").splitlines() if not line.lstrip().startswith("--"))
    verifier_queries = [part.strip() for part in statements.split(";") if part.strip()]
    constraint_audit = next(statement for statement in verifier_queries if "pg_constraint" in statement)

    with get_db_connection() as conn, conn.cursor() as cursor:
        cursor.execute("BEGIN")
        try:
            cursor.execute("ALTER TABLE public.admin_accounts DROP CONSTRAINT admin_accounts_password_hash_check")
            cursor.execute("ALTER TABLE public.admin_accounts ADD CONSTRAINT admin_accounts_password_hash_check CHECK (TRUE)")
            cursor.execute(constraint_audit)
            violations = {row[0] for row in cursor.fetchall()}
            assert "admin_accounts Argon2id check missing or altered" in violations

            cursor.execute("ALTER TABLE public.admin_sessions DROP CONSTRAINT admin_sessions_token_hash_key")
            cursor.execute(constraint_audit)
            violations = {row[0] for row in cursor.fetchall()}
            assert "admin_sessions unique token_hash missing or altered" in violations
        finally:
            conn.rollback()


def test_admin_auth_migration_rolls_back_and_reapplies_on_disposable_database():
    from serviceBot.db.connection import get_db_connection

    with get_db_connection() as conn:
        rollback_migration(conn, "0013_admin_auth")
        with conn.cursor() as cursor:
            cursor.execute("SELECT version FROM schema_migrations WHERE version='0013_admin_auth'")
            assert cursor.fetchone() is None
            cursor.execute(
                """SELECT COUNT(*) FROM information_schema.columns
                   WHERE table_schema='public' AND column_name IN
                     ('password_hash', 'token_hash', 'csrf_token_hash')"""
            )
            assert cursor.fetchone()[0] == 0
        assert apply_migrations(conn) == ["0013_admin_auth"]
