"""Python dataclasses mirroring the DuckDB schema tables."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any


@dataclass
class TradeJournalEntry:
    id: str
    trade_mode: str                         # 'paper' | 'hypothetical' | 'live'
    status: str                             # 'pending_review' | 'approved' | 'open' | 'closed' | 'expired'
    underlying_symbol: str
    asset_class: str                        # 'option' | 'stock' | 'crypto'
    quantity: int
    created_at: datetime | None = None
    updated_at: datetime | None = None
    strategy_type: str | None = None
    # Entry
    entry_time: datetime | None = None
    entry_price: float | None = None
    entry_commission: float = 0.0
    legs: list[dict[str, Any]] | None = None
    # Exit
    exit_time: datetime | None = None
    exit_price: float | None = None
    exit_commission: float = 0.0
    exit_reason: str | None = None
    # P&L
    realized_pnl: float | None = None
    realized_pnl_pct: float | None = None
    unrealized_pnl: float | None = None
    # Greeks at entry
    entry_iv: float | None = None
    entry_delta: float | None = None
    entry_theta: float | None = None
    entry_vega: float | None = None
    entry_gamma: float | None = None
    entry_underlying_price: float | None = None
    dte_at_entry: int | None = None
    # Risk
    max_profit: float | None = None
    max_loss: float | None = None
    breakeven_price: float | None = None
    # Alpaca
    alpaca_order_id: str | None = None
    alpaca_position_id: str | None = None
    # Metadata
    tags: list[str] = field(default_factory=list)
    notes: str | None = None


@dataclass
class LLMAnalysis:
    id: str
    underlying_symbol: str
    analysis_type: str
    model: str
    prompt_version: str
    context_snapshot: dict[str, Any]
    raw_response: str
    created_at: datetime | None = None
    past_performance_summary: dict[str, Any] | None = None
    recommendation: str | None = None       # 'enter' | 'avoid' | 'exit' | 'hold' | 'reduce'
    confidence_score: float | None = None
    strategy_suggested: str | None = None
    reasoning_summary: str | None = None
    suggested_entry: float | None = None
    suggested_stop: float | None = None
    suggested_target: float | None = None
    linked_trade_id: str | None = None
    was_correct: bool | None = None
    outcome_notes: str | None = None
    outcome_recorded_at: datetime | None = None


@dataclass
class OptionContract:
    contract_id: str                        # OCC symbol
    underlying_symbol: str
    expiration_date: date
    strike_price: float
    option_type: str                        # 'call' | 'put'
    multiplier: int = 100
    style: str = "american"
    created_at: datetime | None = None


@dataclass
class OptionSnapshot:
    contract_id: str
    snapshot_time: datetime
    bid: float | None = None
    ask: float | None = None
    mid: float | None = None
    last_price: float | None = None
    volume: int | None = None
    open_interest: int | None = None
    implied_volatility: float | None = None
    delta: float | None = None
    gamma: float | None = None
    theta: float | None = None
    vega: float | None = None
    rho: float | None = None
    underlying_price: float | None = None
    underlying_iv_rank: float | None = None
    data_source: str = "alpaca_mcp"


@dataclass
class PortfolioSnapshot:
    snapshot_date: date
    equity: float
    cash: float | None = None
    buying_power: float | None = None
    open_positions_count: int | None = None
    unrealized_pnl: float | None = None
    realized_pnl_today: float | None = None
    source: str = "alpaca"


@dataclass
class WatchlistEntry:
    symbol: str
    added_at: datetime | None = None
    priority: int = 5
    notes: str | None = None
    alpaca_watchlist_id: str | None = None
