"""DuckDB connection factory and schema migration runner."""

from __future__ import annotations

import os
from pathlib import Path

import duckdb

_connection: duckdb.DuckDBPyConnection | None = None

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def get_db_path() -> Path:
    """Resolve the database file path from env or default."""
    raw = os.environ.get("MAGPIE_DB_PATH", "./data/magpie.duckdb")
    path = Path(raw)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def get_connection() -> duckdb.DuckDBPyConnection:
    """Return the singleton DuckDB connection, running migrations on first call."""
    global _connection
    if _connection is None:
        db_path = get_db_path()
        _connection = duckdb.connect(str(db_path))
        run_migrations(_connection)
    return _connection


def get_in_memory_connection() -> duckdb.DuckDBPyConnection:
    """Return a fresh in-memory DuckDB connection with schema applied (for tests)."""
    conn = duckdb.connect(":memory:")
    run_migrations(conn)
    return conn


def run_migrations(conn: duckdb.DuckDBPyConnection) -> None:
    """Apply any un-applied SQL migration files in order."""
    # Ensure migration tracker exists (bootstrap)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS magpie_migrations (
            filename    VARCHAR PRIMARY KEY,
            applied_at  TIMESTAMPTZ DEFAULT NOW()
        )
    """)

    applied = {
        row[0]
        for row in conn.execute("SELECT filename FROM magpie_migrations").fetchall()
    }

    migration_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    for migration_file in migration_files:
        if migration_file.name in applied:
            continue
        sql = migration_file.read_text(encoding="utf-8")
        conn.execute(sql)
        conn.execute(
            "INSERT INTO magpie_migrations (filename) VALUES (?)",
            [migration_file.name],
        )


def close() -> None:
    """Close the global connection (call on app shutdown)."""
    global _connection
    if _connection is not None:
        _connection.close()
        _connection = None


def execute_df(sql: str, params: list | None = None):  # type: ignore[return]
    """Execute a SQL query and return results as a pandas DataFrame."""
    conn = get_connection()
    if params:
        return conn.execute(sql, params).df()
    return conn.execute(sql).df()
