"""Small, dependency-free PostgreSQL migration runner for ServiceBot."""

from __future__ import annotations

from pathlib import Path


MIGRATIONS_DIR = Path(__file__).resolve().parent
MIGRATION_TABLE = "schema_migrations"


class MigrationError(RuntimeError):
    """Raised when a requested migration cannot be safely applied or rolled back."""


def available_migrations(migrations_dir: Path = MIGRATIONS_DIR) -> list[Path]:
    """Return forward migrations in deterministic version order."""
    return sorted(
        path
        for path in migrations_dir.glob("[0-9][0-9][0-9][0-9]_*.sql")
        if not path.name.endswith(".down.sql")
    )


def migration_version(path: Path) -> str:
    """Use the file stem as the durable, human-readable migration version."""
    return path.stem


def _row_value(row, key: str):
    if isinstance(row, dict):
        return row[key]
    try:
        return row[key]
    except (KeyError, TypeError):
        return row[0]


def _recorded_versions(cursor) -> set[str]:
    cursor.execute(f"SELECT version FROM {MIGRATION_TABLE};")
    return {str(_row_value(row, "version")) for row in cursor.fetchall()}


def _ensure_migration_table(cursor) -> None:
    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {MIGRATION_TABLE} (
            version VARCHAR(255) PRIMARY KEY,
            applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        """
    )


def apply_migrations(conn, migrations_dir: Path = MIGRATIONS_DIR) -> list[str]:
    """Apply every unapplied forward migration and return their versions."""
    cursor = conn.cursor()
    try:
        _ensure_migration_table(cursor)
        applied = _recorded_versions(cursor)
        newly_applied: list[str] = []

        for path in available_migrations(migrations_dir):
            version = migration_version(path)
            if version in applied:
                continue
            cursor.execute(path.read_text(encoding="utf-8"))
            cursor.execute(
                f"INSERT INTO {MIGRATION_TABLE} (version) VALUES (%s);",
                (version,),
            )
            newly_applied.append(version)

        conn.commit()
        return newly_applied
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()


def rollback_migration(conn, version: str, migrations_dir: Path = MIGRATIONS_DIR) -> None:
    """Apply the explicit rollback script for one recorded migration."""
    forward = next(
        (path for path in available_migrations(migrations_dir) if migration_version(path) == version),
        None,
    )
    if forward is None:
        raise MigrationError(f"Unknown migration version: {version}")

    rollback_path = forward.with_name(f"{forward.stem}.down.sql")
    if not rollback_path.exists():
        raise MigrationError(f"Migration {version} has no rollback script.")

    cursor = conn.cursor()
    try:
        _ensure_migration_table(cursor)
        if version not in _recorded_versions(cursor):
            raise MigrationError(f"Migration {version} is not applied.")

        cursor.execute(rollback_path.read_text(encoding="utf-8"))
        cursor.execute(
            f"DELETE FROM {MIGRATION_TABLE} WHERE version = %s;",
            (version,),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()

