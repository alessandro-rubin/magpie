"""Sync Alpaca paper positions into the local database."""

from __future__ import annotations

from datetime import date, datetime, timezone

from magpie.market.client import get_trading_client
from magpie.tracking.journal import list_trades, update_trade_status, update_unrealized_pnl


def sync_from_alpaca() -> dict:
    """
    Fetch all open positions from Alpaca and update the local trade_journal.

    Returns a summary dict with counts of updated and newly-closed positions.
    """
    client = get_trading_client()
    alpaca_positions = client.get_all_positions()

    # Build a lookup: alpaca_order_id -> position
    alpaca_by_symbol: dict[str, object] = {}
    for pos in alpaca_positions:
        alpaca_by_symbol[pos.symbol] = pos

    # Fetch all locally-tracked open paper trades
    open_trades = list_trades(status="open", mode="paper")

    updated = 0
    auto_closed = 0

    for trade in open_trades:
        symbol = trade.underlying_symbol
        pos = alpaca_by_symbol.get(symbol)

        if pos is None:
            # Position no longer exists in Alpaca — it was closed
            # We cannot determine the exact close price here; mark as needing review
            update_trade_status(
                trade.id,
                status="closed",
                exit_time=datetime.now(timezone.utc),
                exit_reason="auto_detected_close",
            )
            auto_closed += 1
        else:
            # Update unrealized P&L
            unrealized = float(pos.unrealized_pl) if pos.unrealized_pl else None
            if unrealized is not None:
                update_unrealized_pnl(trade.id, unrealized)
                updated += 1

    return {"updated": updated, "auto_closed": auto_closed}


def sync_portfolio_snapshot() -> None:
    """Fetch account info and write a daily portfolio snapshot to the DB."""
    from magpie.db.connection import get_connection

    client = get_trading_client()
    account = client.get_account()

    equity = float(account.equity) if account.equity else 0.0
    cash = float(account.cash) if account.cash else None
    buying_power = float(account.buying_power) if account.buying_power else None

    positions = client.get_all_positions()
    unrealized_total = sum(
        float(p.unrealized_pl) for p in positions if p.unrealized_pl is not None
    )

    conn = get_connection()
    today = date.today()

    # Upsert: replace if a snapshot for today already exists
    conn.execute(
        """
        INSERT OR REPLACE INTO portfolio_snapshots
            (snapshot_date, equity, cash, buying_power, open_positions_count, unrealized_pnl, source)
        VALUES (?, ?, ?, ?, ?, ?, 'alpaca')
        """,
        [today, equity, cash, buying_power, len(positions), unrealized_total],
    )
