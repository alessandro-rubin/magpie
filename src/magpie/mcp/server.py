"""Magpie MCP server — exposes trade journal, rules, sync, and analysis tools.

Run via: uv run python -m magpie.mcp.server
Or via the entry point: magpie-mcp
"""

from __future__ import annotations

import logging
import sys

from fastmcp import FastMCP

logger = logging.getLogger(__name__)

mcp = FastMCP(
    "magpie",
    instructions="Magpie options trading system — journal, rules, sync, and analysis tools.",
)


# ── Initialization ────────────────────────────────────────────────────────────

def _init_db() -> None:
    """Ensure DB connection and migrations are ready."""
    logger.debug("_init_db: connecting...")
    from magpie.db.connection import get_connection
    get_connection()
    logger.debug("_init_db: done")


# ── Journal Tools ─────────────────────────────────────────────────────────────


@mcp.tool()
def journal_list(
    status: str | None = None,
    symbol: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """List trade journal entries. Filter by status ('open','closed') and/or symbol."""
    _init_db()
    from magpie.tracking.journal import list_trades

    trades = list_trades(
        status=status,
        symbol=symbol.upper() if symbol else None,
        mode="paper",
        limit=limit,
    )
    return [
        {
            "id": t.id,
            "symbol": t.underlying_symbol,
            "strategy": t.strategy_type,
            "status": t.status,
            "entry_price": t.entry_price,
            "quantity": t.quantity,
            "unrealized_pnl": t.unrealized_pnl,
            "realized_pnl": t.realized_pnl,
            "realized_pnl_pct": t.realized_pnl_pct,
            "entry_delta": t.entry_delta,
            "dte_at_entry": t.dte_at_entry,
            "entry_rationale": t.entry_rationale,
            "exit_rationale": t.exit_rationale,
            "exit_reason": t.exit_reason,
        }
        for t in trades
    ]


@mcp.tool()
def journal_show(trade_id: str) -> dict | str:
    """Show full details for a single trade by ID or ID prefix."""
    _init_db()
    from magpie.tracking.journal import get_trade

    trade = get_trade(trade_id)
    if trade is None:
        return f"Trade '{trade_id}' not found."

    return {
        "id": trade.id,
        "symbol": trade.underlying_symbol,
        "mode": trade.trade_mode,
        "status": trade.status,
        "strategy": trade.strategy_type,
        "entry_price": trade.entry_price,
        "exit_price": trade.exit_price,
        "quantity": trade.quantity,
        "legs": trade.legs,
        "unrealized_pnl": trade.unrealized_pnl,
        "realized_pnl": trade.realized_pnl,
        "realized_pnl_pct": trade.realized_pnl_pct,
        "entry_delta": trade.entry_delta,
        "entry_theta": trade.entry_theta,
        "entry_vega": trade.entry_vega,
        "entry_gamma": trade.entry_gamma,
        "entry_iv": trade.entry_iv,
        "dte_at_entry": trade.dte_at_entry,
        "max_profit": trade.max_profit,
        "max_loss": trade.max_loss,
        "entry_rationale": trade.entry_rationale,
        "exit_rationale": trade.exit_rationale,
        "exit_reason": trade.exit_reason,
        "entry_time": str(trade.entry_time) if trade.entry_time else None,
        "exit_time": str(trade.exit_time) if trade.exit_time else None,
    }


@mcp.tool()
def journal_create(
    underlying_symbol: str,
    asset_class: str,
    quantity: int,
    strategy_type: str | None = None,
    entry_price: float | None = None,
    entry_iv: float | None = None,
    entry_delta: float | None = None,
    dte_at_entry: int | None = None,
    max_profit: float | None = None,
    max_loss: float | None = None,
    breakeven_price: float | None = None,
    legs: list[dict] | None = None,
    entry_rationale: str | None = None,
    alpaca_order_id: str | None = None,
) -> str:
    """Create a new trade journal entry. Returns the trade ID."""
    _init_db()
    from magpie.tracking.journal import create_trade

    trade_id = create_trade(
        trade_mode="paper",
        underlying_symbol=underlying_symbol,
        asset_class=asset_class,
        quantity=quantity,
        status="open",
        strategy_type=strategy_type,
        entry_price=entry_price,
        entry_iv=entry_iv,
        entry_delta=entry_delta,
        dte_at_entry=dte_at_entry,
        max_profit=max_profit,
        max_loss=max_loss,
        breakeven_price=breakeven_price,
        legs=legs,
        entry_rationale=entry_rationale,
        alpaca_order_id=alpaca_order_id,
    )
    return trade_id


@mcp.tool()
def journal_close(
    trade_id: str,
    exit_price: float | None = None,
    exit_reason: str | None = None,
    realized_pnl: float | None = None,
    realized_pnl_pct: float | None = None,
    exit_rationale: str | None = None,
) -> str:
    """Close a trade and record the outcome."""
    _init_db()
    from magpie.tracking.journal import update_trade_status

    update_trade_status(
        trade_id,
        status="closed",
        exit_price=exit_price,
        exit_reason=exit_reason,
        realized_pnl=realized_pnl,
        realized_pnl_pct=realized_pnl_pct,
        exit_rationale=exit_rationale,
    )
    return f"Trade {trade_id[:8]} closed."


# ── Sync Tools ────────────────────────────────────────────────────────────────


@mcp.tool()
def sync_positions() -> dict:
    """Sync Alpaca paper positions with the local trade journal.

    Matches positions by contract symbol, updates unrealized P&L,
    auto-closes trades whose legs are gone, and imports unmatched positions.
    """
    _init_db()
    from magpie.tracking.positions import sync_from_alpaca

    return sync_from_alpaca()


@mcp.tool()
def sync_portfolio_snapshot() -> str:
    """Save a daily portfolio equity snapshot (equity, cash, buying power)."""
    _init_db()
    from magpie.tracking.positions import sync_portfolio_snapshot as _snap

    _snap()
    return "Portfolio snapshot saved."


# ── Position Management ───────────────────────────────────────────────────────


@mcp.tool()
def manage_positions(execute: bool = False, sync_first: bool = True) -> list[dict]:
    """Scan open positions for profit targets, stop losses, and DTE limits.

    Returns a list of actions. If execute=True, closes trades in the journal.
    NOTE: Alpaca positions must be closed separately via the Alpaca MCP server.
    """
    _init_db()
    from datetime import date, datetime, timezone

    from magpie.config import settings
    from magpie.market.occ import parse_occ
    from magpie.tracking.journal import list_trades, update_trade_status
    from magpie.tracking.positions import _mark_analysis_outcomes

    if sync_first:
        from magpie.tracking.positions import sync_from_alpaca
        sync_from_alpaca()

    open_trades = list_trades(status="open", mode="paper")
    actions: list[dict] = []

    for trade in open_trades:
        unrealized = trade.unrealized_pnl
        current_dte = trade.dte_at_entry
        if trade.legs:
            for leg in trade.legs:
                try:
                    parsed = parse_occ(leg.get("contract_symbol", ""))
                    current_dte = (parsed.expiry - date.today()).days
                    break
                except Exception:
                    continue

        if trade.max_profit and unrealized is not None:
            target = trade.max_profit * settings.magpie_profit_target_pct
            if unrealized >= target:
                actions.append({
                    "trade_id": trade.id, "symbol": trade.underlying_symbol,
                    "action": "close_profit", "reason": "target_hit",
                    "details": f"P&L ${unrealized:+,.0f} >= {settings.magpie_profit_target_pct*100:.0f}% of max ${trade.max_profit:,.0f}",
                })
                continue

        if trade.max_loss and unrealized is not None:
            stop = trade.max_loss * settings.magpie_stop_loss_pct
            if unrealized <= -stop:
                actions.append({
                    "trade_id": trade.id, "symbol": trade.underlying_symbol,
                    "action": "close_stop", "reason": "stop_loss",
                    "details": f"P&L ${unrealized:+,.0f} hit stop -${stop:,.0f}",
                })
                continue

        if current_dte is not None and current_dte <= settings.magpie_min_dte_close:
            actions.append({
                "trade_id": trade.id, "symbol": trade.underlying_symbol,
                "action": "close_dte", "reason": "low_dte",
                "details": f"DTE={current_dte} <= {settings.magpie_min_dte_close}",
            })

    if execute:
        for a in actions:
            trade = next((t for t in open_trades if t.id == a["trade_id"]), None)
            if not trade:
                continue
            realized_pnl = trade.unrealized_pnl
            realized_pnl_pct = None
            exit_price = None
            if realized_pnl is not None and trade.entry_price and trade.quantity:
                cost = trade.entry_price * trade.quantity * 100
                if cost != 0:
                    realized_pnl_pct = realized_pnl / cost
                exit_price = trade.entry_price + realized_pnl / (trade.quantity * 100)

            update_trade_status(
                trade.id, status="closed", exit_price=exit_price,
                exit_time=datetime.now(timezone.utc),
                exit_reason=a["reason"], realized_pnl=realized_pnl,
                realized_pnl_pct=realized_pnl_pct,
                exit_rationale=f"Auto-managed: {a['details']}",
            )
            _mark_analysis_outcomes(trade.id, realized_pnl)
            a["executed"] = True

    return actions


# ── Feedback & Analysis Tools ─────────────────────────────────────────────────


@mcp.tool()
def get_feedback(symbol: str | None = None, window_days: int = 30) -> dict:
    """Get combined performance feedback (trade journal + LLM accuracy + trading rules).

    This is what gets injected into analysis prompts for self-correction.
    """
    _init_db()
    from magpie.analysis.feedback import get_combined_feedback

    return get_combined_feedback(symbol=symbol, window_days=window_days)


@mcp.tool()
def get_analysis_context(symbol: str) -> dict:
    """Build full market context for a symbol (price, chain, Greeks, regime).

    Returns the context dict that feeds into LLM analysis prompts.
    """
    _init_db()
    from magpie.market.snapshots import build_analysis_context

    return build_analysis_context(symbol.upper())


# ── Trading Rules Tools ───────────────────────────────────────────────────────


@mcp.tool()
def rules_list(category: str | None = None, include_inactive: bool = False) -> list[dict]:
    """List trading rules (lessons learned from past trades)."""
    _init_db()
    from magpie.tracking.rules import list_rules

    rules = list_rules(category=category, active_only=not include_inactive)
    return [
        {
            "id": r.id,
            "category": r.category,
            "rule": r.rule,
            "active": r.active,
            "source_trade_id": r.source_trade_id,
        }
        for r in rules
    ]


@mcp.tool()
def rules_add(
    category: str,
    rule: str,
    source_trade_id: str | None = None,
) -> str:
    """Add a new trading rule. Category: sizing, risk, entry, macro, execution."""
    _init_db()
    from magpie.tracking.rules import add_rule

    rule_id = add_rule(category=category, rule=rule, source_trade_id=source_trade_id)
    return f"Rule added: {rule_id}"


@mcp.tool()
def rules_remove(rule_id: str, permanent: bool = False) -> str:
    """Deactivate a trading rule (or permanently delete with permanent=True)."""
    _init_db()
    from magpie.tracking.rules import deactivate_rule, delete_rule

    if permanent:
        ok = delete_rule(rule_id)
        return f"Deleted rule {rule_id[:8]}." if ok else f"Rule '{rule_id}' not found."
    else:
        ok = deactivate_rule(rule_id)
        return f"Deactivated rule {rule_id[:8]}." if ok else f"Rule '{rule_id}' not found."


@mcp.tool()
def rules_formatted() -> str:
    """Get all active trading rules formatted for prompt injection."""
    _init_db()
    from magpie.tracking.rules import format_rules_for_prompt

    text = format_rules_for_prompt()
    return text or "No trading rules defined yet."


# ── Trading Notes Tools ──────────────────────────────────────────────────


@mcp.tool()
def notes_list(category: str | None = None, include_resolved: bool = False) -> list[dict]:
    """List trading notes (persistent memory across sessions).

    Categories: deadline, strategy, observation, portfolio.
    Active notes are auto-injected into feedback prompts.
    """
    _init_db()
    from magpie.tracking.notes import list_notes

    notes = list_notes(category=category, active_only=not include_resolved)
    return [
        {
            "id": n.id,
            "category": n.category,
            "title": n.title,
            "content": n.content,
            "source_trade_id": n.source_trade_id,
            "expires_at": str(n.expires_at) if n.expires_at else None,
            "resolved": n.resolved,
        }
        for n in notes
    ]


@mcp.tool()
def notes_add(
    category: str,
    title: str,
    content: str,
    source_trade_id: str | None = None,
    expires_at: str | None = None,
) -> str:
    """Add a trading note. Category: deadline, strategy, observation, portfolio.

    Use expires_at (ISO format, e.g. '2026-03-19') for deadline notes.
    Notes are auto-injected into every feedback/analysis prompt.
    """
    _init_db()
    from magpie.tracking.notes import add_note

    note_id = add_note(
        category=category, title=title, content=content,
        source_trade_id=source_trade_id, expires_at=expires_at,
    )
    return f"Note added: {note_id}"


@mcp.tool()
def notes_resolve(note_id: str) -> str:
    """Mark a trading note as resolved (e.g. deadline acted on, observation no longer relevant)."""
    _init_db()
    from magpie.tracking.notes import resolve_note

    ok = resolve_note(note_id)
    return f"Resolved note {note_id[:8]}." if ok else f"Note '{note_id}' not found."


@mcp.tool()
def notes_remove(note_id: str) -> str:
    """Permanently delete a trading note."""
    _init_db()
    from magpie.tracking.notes import delete_note

    ok = delete_note(note_id)
    return f"Deleted note {note_id[:8]}." if ok else f"Note '{note_id}' not found."


# ── Entry point ───────────────────────────────────────────────────────────────


def main() -> None:
    """Run the Magpie MCP server."""
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        stream=sys.stderr,
    )
    from dotenv import load_dotenv
    load_dotenv()

    # Eagerly import heavy modules before starting the event loop.
    # FastMCP runs sync tool functions in worker threads; if those threads
    # trigger first-time imports (pandas, numpy, alpaca-py …) they deadlock
    # on Python's import lock held by the main/asyncio thread.
    import magpie.db.connection  # noqa: F401 — pandas, sqlite3
    import magpie.tracking.journal  # noqa: F401
    import magpie.tracking.positions  # noqa: F401
    import magpie.tracking.rules  # noqa: F401
    import magpie.tracking.notes  # noqa: F401
    import magpie.analysis.feedback  # noqa: F401
    import magpie.market.snapshots  # noqa: F401

    mcp.run(show_banner=False)


if __name__ == "__main__":
    main()
