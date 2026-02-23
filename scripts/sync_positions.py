#!/usr/bin/env python
"""
Sync Alpaca positions and write a daily portfolio snapshot.

Run this on a schedule (e.g. every 15 minutes during market hours, once after close).
"""

import sys
from pathlib import Path

# Allow running as a script without installing the package
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from magpie.db.connection import get_connection, run_migrations
from magpie.tracking.positions import sync_from_alpaca, sync_portfolio_snapshot

if __name__ == "__main__":
    conn = get_connection()
    print("Running migrations...")
    run_migrations(conn)

    print("Syncing positions from Alpaca...")
    result = sync_from_alpaca()
    print(f"  Updated: {result['updated']} | Auto-closed: {result['auto_closed']}")

    print("Saving portfolio snapshot...")
    sync_portfolio_snapshot()
    print("Done.")
