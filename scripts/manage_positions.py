#!/usr/bin/env python
"""
Scan open positions and flag/close those hitting profit targets, stop losses, or DTE limits.

Run this on a schedule alongside sync_positions.py (e.g. every 15 minutes during market hours).

Configurable via .env:
    MAGPIE_PROFIT_TARGET_PCT=0.50   # close at 50% of max profit
    MAGPIE_STOP_LOSS_PCT=1.0        # close at 100% of max loss
    MAGPIE_MIN_DTE_CLOSE=3          # close if DTE <= 3
"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from magpie.config import settings
from magpie.db.connection import get_connection, run_migrations
from magpie.market.occ import parse_occ
from magpie.tracking.journal import list_trades, update_trade_status
from magpie.tracking.positions import _mark_analysis_outcomes


def compute_dte(trade) -> int | None:
    """Compute current DTE from legs' OCC symbols."""
    if not trade.legs:
        return trade.dte_at_entry
    for leg in trade.legs:
        cs = leg.get("contract_symbol", "")
        try:
            parsed = parse_occ(cs)
            return (parsed.expiry - date.today()).days
        except Exception:
            continue
    return trade.dte_at_entry


def scan_positions(dry_run: bool = True) -> list[dict]:
    """Scan open trades and return actions to take.

    Returns list of dicts: {trade_id, symbol, action, reason, details}
    """
    open_trades = list_trades(status="open", mode="paper")
    actions = []

    profit_target = settings.magpie_profit_target_pct
    stop_loss = settings.magpie_stop_loss_pct
    min_dte = settings.magpie_min_dte_close

    for trade in open_trades:
        current_dte = compute_dte(trade)
        unrealized = trade.unrealized_pnl

        # Check profit target
        if trade.max_profit and unrealized is not None:
            target = trade.max_profit * profit_target
            if unrealized >= target:
                actions.append({
                    "trade_id": trade.id,
                    "symbol": trade.underlying_symbol,
                    "action": "close_profit",
                    "reason": "target_hit",
                    "details": (
                        f"Unrealized ${unrealized:+,.0f} >= "
                        f"{profit_target*100:.0f}% of max profit ${trade.max_profit:,.0f} "
                        f"(target ${target:,.0f})"
                    ),
                    "trade": trade,
                })
                continue

        # Check stop loss
        if trade.max_loss and unrealized is not None:
            stop = trade.max_loss * stop_loss
            if unrealized <= -stop:
                actions.append({
                    "trade_id": trade.id,
                    "symbol": trade.underlying_symbol,
                    "action": "close_stop",
                    "reason": "stop_loss",
                    "details": (
                        f"Unrealized ${unrealized:+,.0f} <= "
                        f"-{stop_loss*100:.0f}% of max loss ${trade.max_loss:,.0f} "
                        f"(stop -${stop:,.0f})"
                    ),
                    "trade": trade,
                })
                continue

        # Check DTE
        if current_dte is not None and current_dte <= min_dte:
            actions.append({
                "trade_id": trade.id,
                "symbol": trade.underlying_symbol,
                "action": "close_dte",
                "reason": "low_dte",
                "details": f"DTE={current_dte} <= min threshold {min_dte} (gamma risk)",
                "trade": trade,
            })
            continue

    return actions


def execute_close(trade, reason: str, details: str) -> None:
    """Close a trade in the journal (Alpaca close must be done via MCP or API)."""
    realized_pnl = trade.unrealized_pnl
    realized_pnl_pct = None
    exit_price = None

    if realized_pnl is not None and trade.entry_price and trade.quantity:
        cost = trade.entry_price * trade.quantity * 100
        if cost != 0:
            realized_pnl_pct = realized_pnl / cost
        exit_price = trade.entry_price + realized_pnl / (trade.quantity * 100)

    update_trade_status(
        trade.id,
        status="closed",
        exit_price=exit_price,
        exit_reason=reason,
        realized_pnl=realized_pnl,
        realized_pnl_pct=realized_pnl_pct,
        exit_rationale=f"Auto-managed: {details}",
    )

    # Close feedback loop
    _mark_analysis_outcomes(trade.id, realized_pnl)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Manage open positions")
    parser.add_argument("--execute", action="store_true",
                        help="Actually close positions (default: dry-run only)")
    parser.add_argument("--sync-first", action="store_true",
                        help="Run position sync before scanning")
    args = parser.parse_args()

    conn = get_connection()
    run_migrations(conn)

    if args.sync_first:
        from magpie.tracking.positions import sync_from_alpaca
        print("Syncing positions from Alpaca...")
        result = sync_from_alpaca()
        print(f"  Updated: {result['updated']} | Auto-closed: {result['auto_closed']}")

    print("\nScanning open positions...")
    print(f"  Profit target: {settings.magpie_profit_target_pct*100:.0f}% of max profit")
    print(f"  Stop loss: {settings.magpie_stop_loss_pct*100:.0f}% of max loss")
    print(f"  Min DTE: {settings.magpie_min_dte_close} days")
    print()

    actions = scan_positions(dry_run=not args.execute)

    if not actions:
        print("No positions need attention.")
        return

    for a in actions:
        icon = {"close_profit": "+", "close_stop": "!", "close_dte": "~"}
        prefix = icon.get(a["action"], "?")
        print(f"  [{prefix}] {a['symbol']} — {a['details']}")

        if args.execute:
            execute_close(a["trade"], a["reason"], a["details"])
            print("      -> CLOSED in journal (close Alpaca position separately)")

    if not args.execute:
        print(f"\n  {len(actions)} action(s) recommended. Run with --execute to close in journal.")
        print("  NOTE: Alpaca positions must be closed separately via MCP or API.")


if __name__ == "__main__":
    main()
