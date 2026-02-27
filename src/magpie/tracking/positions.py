"""Sync Alpaca paper positions into the local database."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from magpie.market.client import get_trading_client
from magpie.market.occ import is_occ_symbol, parse_occ
from magpie.tracking.journal import (
    create_trade,
    list_trades,
    update_trade_status,
    update_unrealized_pnl,
)


def sync_from_alpaca() -> dict:
    """Fetch all open positions from Alpaca and reconcile with local trade_journal.

    Returns a summary dict with counts of updated, auto-closed, and imported positions.
    """
    client = get_trading_client()
    alpaca_positions = client.get_all_positions()

    # Phase 1: Build lookup maps
    alpaca_by_contract: dict[str, Any] = {}
    for pos in alpaca_positions:
        alpaca_by_contract[pos.symbol] = pos

    open_trades = list_trades(status="open", mode="paper")

    matched_contracts: set[str] = set()
    trade_pnl: dict[str, float] = {}

    updated = 0
    auto_closed = 0

    # Phase 2: Match existing trades against Alpaca positions
    for trade in open_trades:
        if not trade.legs:
            # Legacy trade without legs — try plain symbol match as fallback
            pos = alpaca_by_contract.get(trade.underlying_symbol)
            if pos:
                unrealized = float(pos.unrealized_pl) if pos.unrealized_pl else None
                if unrealized is not None:
                    update_unrealized_pnl(trade.id, unrealized)
                matched_contracts.add(trade.underlying_symbol)
                updated += 1
            else:
                _auto_close(trade.id)
                auto_closed += 1
            continue

        trade_has_match = False
        for leg in trade.legs:
            cs = leg.get("contract_symbol")
            if not cs:
                continue
            pos = alpaca_by_contract.get(cs)
            if pos:
                matched_contracts.add(cs)
                trade_has_match = True
                unrealized = float(pos.unrealized_pl) if pos.unrealized_pl else 0.0
                trade_pnl[trade.id] = trade_pnl.get(trade.id, 0.0) + unrealized

        if trade_has_match:
            update_unrealized_pnl(trade.id, trade_pnl[trade.id])
            updated += 1
        else:
            _auto_close(trade.id)
            auto_closed += 1

    # Phase 3: Auto-import unmatched Alpaca positions
    unmatched = {
        sym: pos
        for sym, pos in alpaca_by_contract.items()
        if sym not in matched_contracts
    }
    imported = _import_unmatched_positions(unmatched) if unmatched else 0

    return {"updated": updated, "auto_closed": auto_closed, "imported": imported}


def _auto_close(trade_id: str) -> None:
    """Mark a trade as closed when its positions are no longer in Alpaca."""
    update_trade_status(
        trade_id,
        status="closed",
        exit_time=datetime.now(timezone.utc),
        exit_reason="auto_detected_close",
    )


def _import_unmatched_positions(unmatched: dict[str, Any]) -> int:
    """Import unmatched Alpaca positions into trade_journal.

    Groups option positions into spreads by (underlying, expiry).
    Stock positions become individual trades.
    Returns count of trades created.
    """
    count = 0

    stock_positions: dict[str, Any] = {}
    option_positions: dict[str, Any] = {}

    for symbol, pos in unmatched.items():
        if is_occ_symbol(symbol):
            option_positions[symbol] = pos
        else:
            stock_positions[symbol] = pos

    # Import stock positions individually
    for symbol, pos in stock_positions.items():
        qty = int(pos.qty) if pos.qty else 0
        avg_price = float(pos.avg_entry_price) if pos.avg_entry_price else None
        create_trade(
            trade_mode="paper",
            underlying_symbol=symbol,
            asset_class="stock",
            quantity=abs(qty),
            status="open",
            entry_price=avg_price,
            entry_time=datetime.now(timezone.utc),
            legs=[{"contract_symbol": symbol, "quantity": qty, "premium": avg_price or 0}],
            entry_rationale="Auto-imported from Alpaca sync",
        )
        count += 1

    # Group options by (underlying, expiry) → spread
    groups: dict[tuple[str, date], list[tuple[str, object]]] = {}
    for symbol, pos in option_positions.items():
        parsed = parse_occ(symbol)
        key = (parsed.underlying, parsed.expiry)
        groups.setdefault(key, []).append((symbol, pos))

    for (underlying, expiry), members in groups.items():
        legs = []
        net_cost = 0.0

        for symbol, pos in members:
            parsed = parse_occ(symbol)
            qty = int(pos.qty) if pos.qty else 0
            avg_price = float(pos.avg_entry_price) if pos.avg_entry_price else 0.0

            legs.append(
                {
                    "contract_symbol": symbol,
                    "option_type": parsed.option_type,
                    "strike_price": parsed.strike,
                    "quantity": qty,
                    "premium": avg_price,
                    "side": "buy" if qty > 0 else "sell",
                }
            )
            net_cost += avg_price * qty * 100

        strategy = _infer_strategy_type(legs)
        dte = (expiry - date.today()).days
        ref_qty = abs(legs[0]["quantity"]) if legs else 1
        entry_price = abs(net_cost) / (100 * ref_qty) if ref_qty else None

        create_trade(
            trade_mode="paper",
            underlying_symbol=underlying,
            asset_class="option",
            quantity=ref_qty,
            status="open",
            strategy_type=strategy,
            entry_time=datetime.now(timezone.utc),
            entry_price=entry_price,
            dte_at_entry=dte,
            legs=legs,
            entry_rationale=f"Auto-imported from Alpaca sync ({len(legs)} leg{'s' if len(legs) != 1 else ''}, {expiry})",
        )
        count += 1

    return count


def _infer_strategy_type(legs: list[dict]) -> str:
    """Infer strategy type from leg structure."""
    if len(legs) == 1:
        ot = legs[0]["option_type"]
        side = legs[0].get("side", "buy")
        return f"{'long' if side == 'buy' else 'short'}_{ot}"

    if len(legs) == 2:
        types = {leg["option_type"] for leg in legs}
        sides = {leg.get("side") for leg in legs}
        if len(types) == 1 and sides == {"buy", "sell"}:
            return "vertical_spread"
        if types == {"call", "put"}:
            strikes = {leg["strike_price"] for leg in legs}
            if sides == {"buy"}:
                return "straddle" if len(strikes) == 1 else "strangle"
            if sides == {"sell"}:
                return "short_straddle" if len(strikes) == 1 else "short_strangle"

    if len(legs) == 4:
        return "iron_condor"

    return "multi_leg"


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

    conn.execute(
        """
        INSERT OR REPLACE INTO portfolio_snapshots
            (snapshot_date, equity, cash, buying_power, open_positions_count, unrealized_pnl, source)
        VALUES (?, ?, ?, ?, ?, ?, 'alpaca')
        """,
        [today, equity, cash, buying_power, len(positions), unrealized_total],
    )
