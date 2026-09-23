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

