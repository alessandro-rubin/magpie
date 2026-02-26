"""Dashboard data queries — all DB access for Streamlit pages."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from magpie.db.connection import execute_df


@st.cache_data(ttl=60)
def get_equity_df(days: int = 90) -> pd.DataFrame:
    """Portfolio equity snapshots for the equity curve."""
    return execute_df(
        f"""
        SELECT snapshot_date, equity, cash, unrealized_pnl, realized_pnl_today
        FROM portfolio_snapshots
        WHERE snapshot_date >= CURRENT_DATE - INTERVAL {int(days)} DAY
        ORDER BY snapshot_date ASC
        """
    )


@st.cache_data(ttl=60)
def get_trades_df(
    status: str | None = None,
    symbol: str | None = None,
    window_days: int | None = None,
) -> pd.DataFrame:
    """Trade journal entries with optional filters."""
    filters = ["1=1"]
    params: list = []

    if status:
        filters.append("status = ?")
        params.append(status)
    if symbol:
        filters.append("underlying_symbol = ?")
        params.append(symbol.upper())
    if window_days:
        filters.append(f"created_at >= NOW() - INTERVAL {int(window_days)} DAY")

    where = " AND ".join(filters)
    return execute_df(
        f"""
        SELECT *
        FROM trade_journal
        WHERE {where}
        ORDER BY created_at DESC
        """,
        params or None,
    )


@st.cache_data(ttl=60)
def get_greeks_exposure_df() -> pd.DataFrame:
    """Aggregated Greeks exposure for open option positions."""
    return execute_df(
        """
        SELECT underlying_symbol,
               SUM(entry_delta * quantity * 100) AS total_delta,
               SUM(entry_theta * quantity * 100) AS total_theta,
               SUM(entry_vega  * quantity * 100) AS total_vega,
               SUM(entry_gamma * quantity * 100) AS total_gamma
        FROM trade_journal
        WHERE status = 'open' AND asset_class = 'option'
          AND entry_delta IS NOT NULL
        GROUP BY underlying_symbol
        """
    )


@st.cache_data(ttl=60)
def get_iv_history_df(symbol: str, days: int = 90) -> pd.DataFrame:
    """IV over time for a symbol from option_snapshots."""
    return execute_df(
        f"""
        SELECT os.snapshot_time, os.implied_volatility, os.delta,
               oc.strike_price, oc.option_type, oc.expiration_date
        FROM option_snapshots os
        JOIN option_contracts oc ON os.contract_id = oc.contract_id
        WHERE oc.underlying_symbol = ?
          AND os.snapshot_time >= NOW() - INTERVAL {int(days)} DAY
        ORDER BY os.snapshot_time
        """,
        [symbol.upper()],
    )


@st.cache_data(ttl=60)
def get_contract_snapshots_df(contract_id: str, days: int = 90) -> pd.DataFrame:
    """Greeks over time for a single contract."""
    return execute_df(
        f"""
        SELECT snapshot_time, implied_volatility, delta, gamma, theta, vega,
               underlying_price, bid, ask, mid, last_price
        FROM option_snapshots
        WHERE contract_id = ?
          AND snapshot_time >= NOW() - INTERVAL {int(days)} DAY
        ORDER BY snapshot_time
        """,
        [contract_id],
    )


@st.cache_data(ttl=60)
def get_contracts_for_symbol(symbol: str) -> pd.DataFrame:
    """List option contracts for a symbol (for selectors)."""
    return execute_df(
        """
        SELECT contract_id, strike_price, option_type, expiration_date
        FROM option_contracts
        WHERE underlying_symbol = ?
        ORDER BY expiration_date, strike_price
        """,
        [symbol.upper()],
    )


@st.cache_data(ttl=60)
def get_winrate_by_strategy_df(window_days: int = 90) -> pd.DataFrame:
    """Win rate grouped by strategy type."""
    return execute_df(
        f"""
        SELECT strategy_type,
               COUNT(*)                                              AS total,
               SUM(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END)    AS wins,
               SUM(CASE WHEN realized_pnl <= 0 THEN 1 ELSE 0 END)   AS losses,
               AVG(realized_pnl_pct) * 100                           AS avg_return_pct
        FROM trade_journal
        WHERE status = 'closed'
          AND realized_pnl IS NOT NULL
          AND exit_time >= NOW() - INTERVAL {int(window_days)} DAY
        GROUP BY strategy_type
        """
    )


@st.cache_data(ttl=60)
def get_winrate_by_prompt_df() -> pd.DataFrame:
    """Win rate grouped by prompt version."""
    return execute_df(
        """
        SELECT prompt_version,
               COUNT(*)                                           AS total,
               SUM(CASE WHEN was_correct THEN 1 ELSE 0 END)      AS wins,
               SUM(CASE WHEN NOT was_correct THEN 1 ELSE 0 END)  AS losses
        FROM llm_analyses
        WHERE was_correct IS NOT NULL
        GROUP BY prompt_version
        """
    )


@st.cache_data(ttl=60)
def get_winrate_by_symbol_df(window_days: int = 90) -> pd.DataFrame:
    """Win rate grouped by underlying symbol."""
    return execute_df(
        f"""
        SELECT underlying_symbol,
               COUNT(*)                                              AS total,
               SUM(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END)    AS wins,
               AVG(realized_pnl_pct) * 100                           AS avg_return_pct
        FROM trade_journal
        WHERE status = 'closed'
          AND realized_pnl IS NOT NULL
          AND exit_time >= NOW() - INTERVAL {int(window_days)} DAY
        GROUP BY underlying_symbol
        """
    )


@st.cache_data(ttl=60)
def get_pnl_distribution_df(window_days: int = 90) -> pd.DataFrame:
    """Realized P&L percentages for histogram."""
    return execute_df(
        f"""
        SELECT realized_pnl_pct * 100 AS return_pct, realized_pnl,
               underlying_symbol, strategy_type, exit_time
        FROM trade_journal
        WHERE status = 'closed'
          AND realized_pnl IS NOT NULL
          AND exit_time >= NOW() - INTERVAL {int(window_days)} DAY
        ORDER BY exit_time ASC
        """
    )


@st.cache_data(ttl=60)
def get_trades_with_legs_df() -> pd.DataFrame:
    """Trades that have legs JSON for payoff diagrams."""
    return execute_df(
        """
        SELECT id, underlying_symbol, strategy_type, entry_price, status,
               legs, entry_time, entry_underlying_price
        FROM trade_journal
        WHERE legs IS NOT NULL
        ORDER BY created_at DESC
        """
    )


@st.cache_data(ttl=60)
def get_symbols() -> list[str]:
    """All symbols that appear in trade_journal or option_contracts."""
    df = execute_df(
        """
        SELECT DISTINCT underlying_symbol
        FROM trade_journal
        WHERE underlying_symbol IS NOT NULL
        ORDER BY underlying_symbol
        """
    )
    return df["underlying_symbol"].tolist() if not df.empty else []
