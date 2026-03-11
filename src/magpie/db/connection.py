"""SQLite connection factory and schema migration runner.

Uses WAL mode for concurrent read/write access across processes
(MCP server, CLI, sync scripts).
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

_connection: sqlite3.Connection | None = None

MIGRATIONS_DIR = Path(__file__).parent / "migrations"

# ── SQLite type adapters/converters ──────────────────────────────────────────
# Ensure Python datetime objects round-trip through SQLite TEXT columns.

sqlite3.register_adapter(datetime, lambda dt: dt.isoformat())
sqlite3.register_adapter(date, lambda d: d.isoformat())


def _convert_timestamp(val: bytes) -> datetime | None:
    """Convert an ISO-format TEXT value back to a timezone-aware datetime."""
    text = val.decode()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _convert_date(val: bytes) -> date | None:
    text = val.decode()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


sqlite3.register_converter("TIMESTAMP", _convert_timestamp)
sqlite3.register_converter("DATE", _convert_date)


# ── Connection management ────────────────────────────────────────────────────


def get_db_path() -> Path:
    """Resolve the database file path from env or default."""
    raw = os.environ.get("MAGPIE_DB_PATH", "./data/magpie.sqlite")
    path = Path(raw)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _make_connection(path: str) -> sqlite3.Connection:
    """Create a configured SQLite connection."""
    conn = sqlite3.connect(
        path,
        detect_types=sqlite3.PARSE_DECLTYPES,
        check_same_thread=False,
    )
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def get_connection() -> sqlite3.Connection:
    """Return the singleton SQLite connection, running migrations on first call."""
    global _connection
    if _connection is None:
        db_path = get_db_path()
        _connection = _make_connection(str(db_path))
        run_migrations(_connection)
    return _connection


def get_in_memory_connection() -> sqlite3.Connection:
    """Return a fresh in-memory SQLite connection with schema applied (for tests)."""
    conn = _make_connection(":memory:")
    run_migrations(conn)
    return conn


def run_migrations(conn: sqlite3.Connection) -> None:
    """Apply any un-applied SQL migration files in order."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS magpie_migrations (
            filename    TEXT PRIMARY KEY,
            applied_at  TIMESTAMP DEFAULT (datetime('now'))
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
        conn.executescript(sql)
        conn.execute(
            "INSERT INTO magpie_migrations (filename) VALUES (?)",
            [migration_file.name],
        )
        conn.commit()


def close() -> None:
    """Close the global connection (call on app shutdown)."""
    global _connection
    if _connection is not None:
        _connection.close()
        _connection = None


def execute_df(sql: str, params: list | None = None):  # type: ignore[return]
    """Execute a SQL query and return results as a pandas DataFrame."""
    conn = get_connection()
    return pd.read_sql_query(sql, conn, params=params)
