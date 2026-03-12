"""Sync Alpaca paper positions into the local database."""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any

from magpie.market.client import get_trading_client
from magpie.market.occ import is_occ_symbol, parse_occ
from magpie.tracking.journal import (
    create_trade,
    find_linked_analyses,
    list_trades,
    update_trade_status,
    update_unrealized_pnl,
)

logger = logging.getLogger(__name__)


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
                _auto_close(trade)
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
            _auto_close(trade)
            auto_closed += 1

    # Phase 2.25: Update current underlying prices for open trades
    _update_current_underlying_prices(open_trades)

    # Phase 2.5: Backfill entry Greeks for open trades missing them
    for trade in open_trades:
        if trade.entry_delta is not None or not trade.legs:
            continue
        greeks = _fetch_spread_greeks(trade.legs)
        if greeks:
            from magpie.db.connection import get_connection as _get_conn

            conn = _get_conn()
            conn.execute(
                """
                UPDATE trade_journal
                SET entry_delta = ?, entry_theta = ?, entry_vega = ?,
                    entry_gamma = ?, entry_iv = ?, updated_at = datetime('now')
                WHERE id = ?
                """,
                [
                    greeks.get("entry_delta"),
                    greeks.get("entry_theta"),
                    greeks.get("entry_vega"),
                    greeks.get("entry_gamma"),
                    greeks.get("entry_iv"),
                    trade.id,
                ],
            )
            conn.commit()

    # Phase 3: Auto-import unmatched Alpaca positions
    unmatched = {
        sym: pos
        for sym, pos in alpaca_by_contract.items()
        if sym not in matched_contracts
    }
    imported = _import_unmatched_positions(unmatched) if unmatched else 0

    return {"updated": updated, "auto_closed": auto_closed, "imported": imported}


def _auto_close(trade: Any) -> None:
    """Mark a trade as closed when its positions are no longer in Alpaca.

    Computes realized P&L from the last synced unrealized_pnl.
    After closing, marks any linked LLM analyses with the outcome.
    """
    realized_pnl = None
    realized_pnl_pct = None
    exit_price = None

    if trade.unrealized_pnl is not None:
        realized_pnl = trade.unrealized_pnl
        if trade.entry_price and trade.quantity:
            cost = trade.entry_price * trade.quantity * 100
            if cost != 0:
                realized_pnl_pct = realized_pnl / cost
            exit_price = trade.entry_price + realized_pnl / (trade.quantity * 100)

    update_trade_status(
        trade.id,
        status="closed",
        exit_time=datetime.now(timezone.utc),
        exit_reason="auto_detected_close",
        exit_price=exit_price,
        realized_pnl=realized_pnl,
        realized_pnl_pct=realized_pnl_pct,
    )

    # Close the feedback loop: mark linked analyses with outcome
    _mark_analysis_outcomes(trade.id, realized_pnl)


def _mark_analysis_outcomes(trade_id: str, realized_pnl: float | None) -> None:
    """Mark all LLM analyses linked to a trade with their outcome.

    Also refreshes the prediction_accuracy stats.
    """
    linked = find_linked_analyses(trade_id)
    if not linked:
        return

    was_correct = realized_pnl is not None and realized_pnl > 0
    pnl_str = f"${realized_pnl:+,.0f}" if realized_pnl is not None else "unknown"

    try:
        from magpie.analysis.llm import mark_outcome

        for analysis in linked:
            if analysis["was_correct"] is not None:
                continue  # Already marked
            mark_outcome(
                analysis["id"],
                was_correct=was_correct,
                notes=f"Auto-marked on position close. Realized P&L: {pnl_str}",
            )
            logger.info(
                "Marked analysis %s outcome: was_correct=%s (P&L: %s)",
                analysis["id"][:8], was_correct, pnl_str,
            )
    except Exception:
        logger.warning("Failed to mark analysis outcomes for trade %s", trade_id, exc_info=True)

    # Refresh prediction accuracy stats
    try:
        from magpie.analysis.feedback import upsert_prediction_accuracy

        upsert_prediction_accuracy(window_days=30)
    except Exception:
        logger.warning("Failed to refresh prediction accuracy", exc_info=True)


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

        # Fetch Greeks for the legs at import time
        greeks_kwargs = _fetch_spread_greeks(legs)

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
            **greeks_kwargs,
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


def _fetch_spread_greeks(legs: list[dict]) -> dict:
    """Fetch live Greeks for spread legs and return net spread Greeks.

    Each leg dict must have ``contract_symbol`` and ``quantity`` (positive=long,
    negative=short).  Raw contract Greeks are multiplied by the sign of quantity
    so that short legs subtract from the net.

    Returns a dict of kwargs suitable for create_trade() (entry_delta, entry_iv, etc.).
    Returns empty dict on failure so the import proceeds without Greeks.
    """
    try:
        from magpie.market.options import get_option_snapshot

        net_delta = 0.0
        net_theta = 0.0
        net_vega = 0.0
        net_gamma = 0.0
        ivs = []

        for leg in legs:
            symbol = leg.get("contract_symbol")
            if not symbol:
                continue
            qty = leg.get("quantity", 1)
            sign = 1 if qty > 0 else -1

            snap = get_option_snapshot(symbol)
            if not snap:
                continue
            delta = snap.get("delta") or 0.0
            theta = snap.get("theta") or 0.0
            vega = snap.get("vega") or 0.0
            gamma = snap.get("gamma") or 0.0
            iv = snap.get("implied_volatility")

            net_delta += delta * sign
            net_theta += theta * sign
            net_vega += vega * sign
            net_gamma += gamma * sign
            if iv is not None:
                ivs.append(iv)

        result = {}
        if net_delta != 0.0:
            result["entry_delta"] = round(net_delta, 4)
        if net_theta != 0.0:
            result["entry_theta"] = round(net_theta, 4)
        if net_vega != 0.0:
            result["entry_vega"] = round(net_vega, 4)
        if net_gamma != 0.0:
            result["entry_gamma"] = round(net_gamma, 4)
        if ivs:
            result["entry_iv"] = round(sum(ivs) / len(ivs), 4)

        return result
    except Exception:
        logger.warning("Could not fetch Greeks during auto-import", exc_info=True)
        return {}


def _update_current_underlying_prices(open_trades: list) -> None:
    """Fetch current underlying prices and store them on open trades.

    Groups trades by underlying symbol to minimise API calls, then batch-updates.
    """
    symbols = {t.underlying_symbol for t in open_trades if t.underlying_symbol}
    if not symbols:
        return

    try:
        from magpie.market.stocks import get_snapshot

        prices: dict[str, float] = {}
        for sym in symbols:
            try:
                snap = get_snapshot(sym)
                if snap and snap.get("price"):
                    prices[sym] = snap["price"]
            except Exception:
                logger.debug("Could not fetch price for %s", sym, exc_info=True)

        if not prices:
            return

        from magpie.db.connection import get_connection as _get_conn

        conn = _get_conn()
        for trade in open_trades:
            price = prices.get(trade.underlying_symbol)
            if price is not None:
                conn.execute(
                    """
                    UPDATE trade_journal
                    SET current_underlying_price = ?, updated_at = datetime('now')
                    WHERE id = ?
                    """,
                    [price, trade.id],
                )
        conn.commit()
        logger.info("Updated current underlying prices for %d symbols", len(prices))
    except Exception:
        logger.warning("Failed to update current underlying prices", exc_info=True)


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
    conn.commit()
