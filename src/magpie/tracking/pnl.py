"""P&L calculations and rolling summaries from the trade_journal."""

from __future__ import annotations

from magpie.db.connection import get_connection


def get_pnl_summary(
    symbol: str | None = None,
    window_days: int = 30,
    mode: str | None = None,
) -> dict:
    """
    Compute a rolling P&L summary over the last window_days.

    Returns a dict with total P&L, win/loss count, win rate, and avg return.
    """
    conn = get_connection()

    filters = [
        "status = 'closed'",
        "exit_time >= NOW() - INTERVAL ? DAY",
        "realized_pnl IS NOT NULL",
    ]
    params: list = [window_days]

    if symbol:
        filters.append("underlying_symbol = ?")
        params.append(symbol.upper())
    if mode:
        filters.append("trade_mode = ?")
        params.append(mode)

    where = " AND ".join(filters)

    rows = conn.execute(
        f"""
        SELECT realized_pnl, realized_pnl_pct
        FROM trade_journal
        WHERE {where}
        ORDER BY exit_time DESC
        """,
        params,
    ).fetchall()

    if not rows:
        return {
            "window_days": window_days,
            "symbol": symbol,
            "closed_trades": 0,
            "total_realized_pnl": 0.0,
            "wins": 0,
            "losses": 0,
            "win_rate": None,
            "avg_return_pct": None,
        }

    pnls = [float(r[0]) for r in rows]
    pnl_pcts = [float(r[1]) for r in rows if r[1] is not None]

    wins = sum(1 for p in pnls if p > 0)
    losses = sum(1 for p in pnls if p < 0)
    total = len(pnls)

    return {
        "window_days": window_days,
        "symbol": symbol,
        "closed_trades": total,
        "total_realized_pnl": sum(pnls),
        "wins": wins,
        "losses": losses,
        "win_rate": wins / total if total > 0 else None,
        "avg_return_pct": sum(pnl_pcts) / len(pnl_pcts) if pnl_pcts else None,
    }


def get_equity_curve(days: int = 90) -> list[dict]:
    """Return daily portfolio equity snapshots for charting."""
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT snapshot_date, equity, unrealized_pnl, realized_pnl_today
        FROM portfolio_snapshots
        WHERE snapshot_date >= CURRENT_DATE - INTERVAL ? DAY
        ORDER BY snapshot_date ASC
        """,
        [days],
    ).fetchall()

    return [
        {
            "date": str(r[0]),
            "equity": float(r[1]),
            "unrealized_pnl": float(r[2]) if r[2] is not None else None,
            "realized_pnl_today": float(r[3]) if r[3] is not None else None,
        }
        for r in rows
    ]
