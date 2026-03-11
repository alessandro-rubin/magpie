"""Trade journal — read/write operations on the trade_journal table."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from magpie.db.connection import get_connection
from magpie.db.models import TradeJournalEntry


def create_trade(
    trade_mode: str,
    underlying_symbol: str,
    asset_class: str,
    quantity: int,
    status: str = "pending_review",
    **kwargs,
) -> str:
    """Insert a new trade journal entry. Returns the generated trade ID."""
    conn = get_connection()
    trade_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    legs = kwargs.get("legs")
    legs_json = json.dumps(legs) if legs is not None else None

    tags = kwargs.get("tags", [])
    tags_json = json.dumps(tags) if tags else None

    conn.execute(
        """
        INSERT INTO trade_journal (
            id, created_at, updated_at, trade_mode, status,
            underlying_symbol, asset_class, strategy_type,
            entry_time, entry_price, quantity, entry_commission, legs,
            entry_iv, entry_delta, entry_theta, entry_vega, entry_gamma,
            entry_underlying_price, dte_at_entry,
            max_profit, max_loss, breakeven_price,
            alpaca_order_id, alpaca_position_id, tags, notes,
            entry_rationale
        ) VALUES (
            ?, ?, ?, ?, ?,
            ?, ?, ?,
            ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?,
            ?, ?,
            ?, ?, ?,
            ?, ?, ?, ?,
            ?
        )
        """,
        [
            trade_id, now, now, trade_mode, status,
            underlying_symbol.upper(), asset_class, kwargs.get("strategy_type"),
            kwargs.get("entry_time", now), kwargs.get("entry_price"), quantity,
            kwargs.get("entry_commission", 0.0), legs_json,
            kwargs.get("entry_iv"), kwargs.get("entry_delta"),
            kwargs.get("entry_theta"), kwargs.get("entry_vega"), kwargs.get("entry_gamma"),
            kwargs.get("entry_underlying_price"), kwargs.get("dte_at_entry"),
            kwargs.get("max_profit"), kwargs.get("max_loss"), kwargs.get("breakeven_price"),
            kwargs.get("alpaca_order_id"), kwargs.get("alpaca_position_id"),
            tags_json, kwargs.get("notes"),
            kwargs.get("entry_rationale"),
        ],
    )
    conn.commit()
    return trade_id


def update_trade_status(
    trade_id: str,
    status: str,
    exit_price: float | None = None,
    exit_time: datetime | None = None,
    exit_reason: str | None = None,
    realized_pnl: float | None = None,
    realized_pnl_pct: float | None = None,
    exit_rationale: str | None = None,
) -> None:
    """Update trade status and exit information."""
    conn = get_connection()
    conn.execute(
        """
        UPDATE trade_journal
        SET status = ?, exit_price = ?, exit_time = ?, exit_reason = ?,
            realized_pnl = ?, realized_pnl_pct = ?, exit_rationale = ?,
            updated_at = datetime('now')
        WHERE id = ?
        """,
        [status, exit_price, exit_time, exit_reason, realized_pnl, realized_pnl_pct,
         exit_rationale, trade_id],
    )
    conn.commit()


def update_unrealized_pnl(trade_id: str, unrealized_pnl: float) -> None:
    """Update the unrealized P&L for an open trade."""
    conn = get_connection()
    conn.execute(
        "UPDATE trade_journal SET unrealized_pnl = ?, updated_at = datetime('now') WHERE id = ?",
        [unrealized_pnl, trade_id],
    )
    conn.commit()


def build_contract_leg_map(
    trades: list[TradeJournalEntry],
) -> dict[str, tuple[str, int]]:
    """Build a mapping from contract_symbol to (trade_id, leg_index).

    Scans all trades' legs for the ``contract_symbol`` key.
    """
    result: dict[str, tuple[str, int]] = {}
    for trade in trades:
        if not trade.legs:
            continue
        for i, leg in enumerate(trade.legs):
            cs = leg.get("contract_symbol")
            if cs:
                result[cs] = (trade.id, i)
    return result


def update_legs(trade_id: str, legs: list[dict]) -> None:
    """Update the legs JSON for a trade."""
    conn = get_connection()
    conn.execute(
        "UPDATE trade_journal SET legs = ?, updated_at = datetime('now') WHERE id = ?",
        [json.dumps(legs), trade_id],
    )
    conn.commit()


def link_analysis(trade_id: str, analysis_id: str) -> None:
    """Link an LLM analysis to a trade."""
    conn = get_connection()
    conn.execute(
        "UPDATE llm_analyses SET linked_trade_id = ? WHERE id = ?",
        [trade_id, analysis_id],
    )
    conn.commit()


def find_linked_analyses(trade_id: str) -> list[dict]:
    """Find all llm_analyses linked to a trade."""
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT id, was_correct, underlying_symbol, strategy_suggested
        FROM llm_analyses
        WHERE linked_trade_id = ?
        """,
        [trade_id],
    ).fetchall()
    return [
        {"id": r[0], "was_correct": r[1], "symbol": r[2], "strategy": r[3]}
        for r in rows
    ]


def find_unlinked_analysis(symbol: str) -> str | None:
    """Find the most recent unlinked analysis for a symbol.

    Useful for auto-linking trades created via MCP to their originating analysis.
    """
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT id FROM llm_analyses
        WHERE underlying_symbol = ?
          AND linked_trade_id IS NULL
          AND created_at >= datetime('now', '-7 days')
        ORDER BY created_at DESC
        LIMIT 1
        """,
        [symbol.upper()],
    ).fetchall()
    return rows[0][0] if rows else None


def list_trades(
    status: str | None = None,
    symbol: str | None = None,
    mode: str | None = None,
    limit: int = 50,
) -> list[TradeJournalEntry]:
    """Fetch trade journal entries with optional filters."""
    conn = get_connection()
    filters = []
    params: list = []

    if status:
        filters.append("status = ?")
        params.append(status)
    if symbol:
        filters.append("underlying_symbol = ?")
        params.append(symbol.upper())
    if mode:
        filters.append("trade_mode = ?")
        params.append(mode)

    where = f"WHERE {' AND '.join(filters)}" if filters else ""
    params.append(limit)

    rows = conn.execute(
        f"""
        SELECT id, trade_mode, status, underlying_symbol, asset_class, quantity,
               created_at, updated_at, strategy_type, entry_time, entry_price,
               entry_commission, legs, exit_time, exit_price, exit_commission, exit_reason,
               realized_pnl, realized_pnl_pct, unrealized_pnl,
               entry_iv, entry_delta, entry_theta, entry_vega, entry_gamma,
               entry_underlying_price, dte_at_entry,
               max_profit, max_loss, breakeven_price,
               alpaca_order_id, alpaca_position_id, tags, notes,
               entry_rationale, exit_rationale
        FROM trade_journal {where}
        ORDER BY created_at DESC
        LIMIT ?
        """,
        params,
    ).fetchall()

    return [_row_to_entry(r) for r in rows]


def get_trade(trade_id_prefix: str) -> TradeJournalEntry | None:
    """Fetch a single trade by ID or ID prefix."""
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT id, trade_mode, status, underlying_symbol, asset_class, quantity,
               created_at, updated_at, strategy_type, entry_time, entry_price,
               entry_commission, legs, exit_time, exit_price, exit_commission, exit_reason,
               realized_pnl, realized_pnl_pct, unrealized_pnl,
               entry_iv, entry_delta, entry_theta, entry_vega, entry_gamma,
               entry_underlying_price, dte_at_entry,
               max_profit, max_loss, breakeven_price,
               alpaca_order_id, alpaca_position_id, tags, notes,
               entry_rationale, exit_rationale
        FROM trade_journal
        WHERE id LIKE ?
        LIMIT 1
        """,
        [f"{trade_id_prefix}%"],
    ).fetchall()

    return _row_to_entry(rows[0]) if rows else None


def _row_to_entry(row: tuple) -> TradeJournalEntry:
    legs_raw = row[12]
    legs = json.loads(legs_raw) if isinstance(legs_raw, str) else legs_raw

    return TradeJournalEntry(
        id=row[0],
        trade_mode=row[1],
        status=row[2],
        underlying_symbol=row[3],
        asset_class=row[4],
        quantity=row[5],
        created_at=row[6],
        updated_at=row[7],
        strategy_type=row[8],
        entry_time=row[9],
        entry_price=float(row[10]) if row[10] is not None else None,
        entry_commission=float(row[11]) if row[11] is not None else 0.0,
        legs=legs,
        exit_time=row[13],
        exit_price=float(row[14]) if row[14] is not None else None,
        exit_commission=float(row[15]) if row[15] is not None else 0.0,
        exit_reason=row[16],
        realized_pnl=float(row[17]) if row[17] is not None else None,
        realized_pnl_pct=float(row[18]) if row[18] is not None else None,
        unrealized_pnl=float(row[19]) if row[19] is not None else None,
        entry_iv=float(row[20]) if row[20] is not None else None,
        entry_delta=float(row[21]) if row[21] is not None else None,
        entry_theta=float(row[22]) if row[22] is not None else None,
        entry_vega=float(row[23]) if row[23] is not None else None,
        entry_gamma=float(row[24]) if row[24] is not None else None,
        entry_underlying_price=float(row[25]) if row[25] is not None else None,
        dte_at_entry=int(row[26]) if row[26] is not None else None,
        max_profit=float(row[27]) if row[27] is not None else None,
        max_loss=float(row[28]) if row[28] is not None else None,
        breakeven_price=float(row[29]) if row[29] is not None else None,
        alpaca_order_id=row[30],
        alpaca_position_id=row[31],
        tags=json.loads(row[32]) if row[32] else [],
        notes=row[33],
        entry_rationale=row[34],
        exit_rationale=row[35],
    )
