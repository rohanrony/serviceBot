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
