"""One-time migration: copy data from DuckDB to SQLite.

Usage:
    uv run python scripts/migrate_duckdb_to_sqlite.py [--duckdb-path data/magpie.duckdb] [--sqlite-path data/magpie.sqlite]

Requires duckdb to still be installed. Run this BEFORE removing duckdb from deps.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

try:
    import duckdb
except ImportError:
    print("ERROR: duckdb package is required for migration. Install it first:")
    print("  uv pip install duckdb")
    sys.exit(1)


# Tables to migrate, in dependency order (foreign keys)
TABLES = [
    "assets",
    "option_contracts",
    "option_snapshots",
    "trade_journal",
    "llm_analyses",
    "prediction_accuracy",
    "portfolio_snapshots",
    "watchlist",
    "market_regime_snapshots",
    "trading_rules",
]


def migrate(duckdb_path: str, sqlite_path: str) -> None:
    """Copy all data from DuckDB to a fresh SQLite database."""
    if not Path(duckdb_path).exists():
        print(f"DuckDB file not found: {duckdb_path}")
        sys.exit(1)

    sqlite_file = Path(sqlite_path)
    if sqlite_file.exists():
        print(f"SQLite file already exists: {sqlite_path}")
        resp = input("Overwrite? [y/N] ").strip().lower()
        if resp != "y":
            print("Aborted.")
            sys.exit(0)
        sqlite_file.unlink()

    # Connect to DuckDB (read-only)
    duck = duckdb.connect(duckdb_path, read_only=True)

    # Create SQLite DB with migrations
    from magpie.db.connection import _make_connection, run_migrations

    sqlite_conn = _make_connection(sqlite_path)
    run_migrations(sqlite_conn)

    total_rows = 0
    for table in TABLES:
        try:
            # Check if table exists in DuckDB
            exists = duck.execute(
                f"SELECT COUNT(*) FROM information_schema.tables WHERE table_name = '{table}'"
            ).fetchone()[0]
            if not exists:
                print(f"  {table}: skipped (not in DuckDB)")
                continue

            rows = duck.execute(f"SELECT * FROM {table}").fetchall()
            if not rows:
                print(f"  {table}: 0 rows")
                continue

            # Get column names from DuckDB
            cols = [desc[0] for desc in duck.execute(f"SELECT * FROM {table} LIMIT 0").description]

            # For tables with auto-increment IDs, skip the id column if it's INTEGER
            placeholders = ", ".join("?" for _ in cols)
            col_names = ", ".join(cols)

            for row in rows:
                # Convert DuckDB-specific types to SQLite-compatible
                from decimal import Decimal

                converted = []
                for val in row:
                    if isinstance(val, Decimal):
                        converted.append(float(val))
                    elif isinstance(val, list):
                        converted.append(json.dumps(val))
                    elif isinstance(val, dict):
                        converted.append(json.dumps(val))
                    elif hasattr(val, "isoformat"):
                        converted.append(val.isoformat())
                    else:
                        converted.append(val)

                try:
                    sqlite_conn.execute(
                        f"INSERT OR IGNORE INTO {table} ({col_names}) VALUES ({placeholders})",
                        converted,
                    )
                except sqlite3.Error as e:
                    print(f"  WARNING: {table} row error: {e}")
                    continue

            sqlite_conn.commit()
            count = len(rows)
            total_rows += count
            print(f"  {table}: {count} rows migrated")

        except duckdb.CatalogException:
            print(f"  {table}: skipped (not in DuckDB)")
        except Exception as e:
            print(f"  {table}: ERROR - {e}")

    duck.close()
    sqlite_conn.close()

    print(f"\nDone! Migrated {total_rows} total rows to {sqlite_path}")


if __name__ == "__main__":
    # Load .env for settings
    from dotenv import load_dotenv
    load_dotenv()

    parser = argparse.ArgumentParser(description="Migrate DuckDB data to SQLite")
    parser.add_argument("--duckdb-path", default="data/magpie.duckdb", help="Source DuckDB file")
    parser.add_argument("--sqlite-path", default="data/magpie.sqlite", help="Target SQLite file")
    args = parser.parse_args()

    print(f"Migrating: {args.duckdb_path} -> {args.sqlite_path}")
    migrate(args.duckdb_path, args.sqlite_path)
