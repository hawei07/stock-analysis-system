"""Lightweight database migration runner.

Migrations are plain SQL files in ./migrations, applied once and recorded in
schema_migrations. Keep files idempotent when possible so old local databases
can be upgraded safely.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from db import transaction


APP_DIR = Path(__file__).resolve().parent
MIGRATIONS_DIR = APP_DIR / "migrations"


def _ensure_migration_table(cursor):
    cursor.execute(
        """CREATE TABLE IF NOT EXISTS schema_migrations (
            version VARCHAR(160) NOT NULL,
            name VARCHAR(255) NOT NULL,
            checksum CHAR(64) NOT NULL,
            applied_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (version)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"""
    )


def _migration_files():
    if not MIGRATIONS_DIR.exists():
        return []
    return sorted(path for path in MIGRATIONS_DIR.glob("*.sql") if path.is_file())


def _checksum(sql_text):
    return hashlib.sha256(sql_text.encode("utf-8")).hexdigest()


def _split_sql(sql_text):
    statements = []
    current = []
    for line in sql_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        current.append(line)
        if stripped.endswith(";"):
            statement = "\n".join(current).strip().rstrip(";").strip()
            if statement:
                statements.append(statement)
            current = []
    tail = "\n".join(current).strip()
    if tail:
        statements.append(tail)
    return statements


def migration_status():
    """Return applied and pending migrations without executing pending files."""
    with transaction(dictionary=True) as cursor:
        _ensure_migration_table(cursor)
        cursor.execute("SELECT version, name, checksum, applied_at FROM schema_migrations ORDER BY version")
        applied_rows = cursor.fetchall()
        applied = {row["version"]: row for row in applied_rows}

    files = []
    for path in _migration_files():
        sql_text = path.read_text(encoding="utf-8")
        files.append({
            "version": path.stem,
            "name": path.name,
            "checksum": _checksum(sql_text),
            "applied": path.stem in applied,
        })
    pending = [item for item in files if not item["applied"]]
    return {"applied": applied_rows, "files": files, "pending": pending}


def run_migrations():
    """Apply pending SQL migrations and return a summary."""
    applied_now = []
    with transaction(dictionary=True) as cursor:
        _ensure_migration_table(cursor)
        cursor.execute("SELECT version, checksum FROM schema_migrations")
        applied = {row["version"]: row["checksum"] for row in cursor.fetchall()}

    for path in _migration_files():
        version = path.stem
        sql_text = path.read_text(encoding="utf-8")
        checksum = _checksum(sql_text)
        if version in applied:
            if applied[version] != checksum:
                raise RuntimeError(f"Migration checksum changed after apply: {path.name}")
            continue

        with transaction(dictionary=True) as cursor:
            for statement in _split_sql(sql_text):
                cursor.execute(statement)

            cursor.execute(
                "INSERT INTO schema_migrations (version, name, checksum) VALUES (%s, %s, %s)",
                (version, path.name, checksum),
            )
        applied_now.append(path.name)
    return {"applied": applied_now, "count": len(applied_now)}
