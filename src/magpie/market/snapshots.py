"""Assembles the full market context dict fed to the LLM for analysis."""

from __future__ import annotations

from magpie.market.stocks import get_snapshot, get_bars, compute_52w_range
from magpie.market.options import get_option_chain


def build_analysis_context(symbol: str) -> dict:
    """
    Build the complete market context package for LLM analysis.

    Returns a structured dict containing:
    - underlying price and change metrics
    - recent price history summary
    - option chain snapshot (calls and puts, filtered by liquidity)
    - IV metrics
    """
    # ── Underlying ──────────────────────────────────────────────────────────
    stock_snap = get_snapshot(symbol)
    bars_30d = get_bars(symbol, days=30)
    bars_252d = get_bars(symbol, days=252)
    low_52w, high_52w = compute_52w_range(bars_252d)

    # Simple 20-day SMA
    closes_20 = [b["close"] for b in bars_30d[-20:] if b.get("close")]
    sma_20 = sum(closes_20) / len(closes_20) if closes_20 else None

    underlying = {
        **stock_snap,
        "sma_20": sma_20,
        "low_52w": low_52w,
        "high_52w": high_52w,
        "price_vs_sma20": (
            (stock_snap["price"] - sma_20) / sma_20 if stock_snap.get("price") and sma_20 else None
        ),
    }

    # ── Options chain ────────────────────────────────────────────────────────
    # Fetch 15–45 DTE range — the sweet spot for most defined-risk strategies
    try:
        chain = get_option_chain(symbol, dte_min=15, dte_max=45, strike_count=8)
    except Exception:
        chain = []

    calls = [c for c in chain if _is_call(c)]
    puts = [c for c in chain if not _is_call(c)]

    # Sort by absolute delta descending (most ATM first)
    calls.sort(key=lambda c: abs(c.get("delta") or 0), reverse=True)
    puts.sort(key=lambda c: abs(c.get("delta") or 0), reverse=True)

    # ── IV metrics ───────────────────────────────────────────────────────────
    ivs = [c["implied_volatility"] for c in chain if c.get("implied_volatility")]
    avg_iv = sum(ivs) / len(ivs) if ivs else None
    iv_rank = _compute_iv_rank(symbol, avg_iv)

    # ── Market regime ──────────────────────────────────────────────────────
    try:
        from magpie.analysis.regime import get_market_regime, save_regime_snapshot

        regime = get_market_regime()
        save_regime_snapshot(regime)
    except Exception:
        regime = None

    return {
        "symbol": symbol,
        "underlying": underlying,
        "options_chain": {
            "calls": calls[:10],    # top 10 most ATM calls
            "puts": puts[:10],
            "total_contracts": len(chain),
        },
        "iv_metrics": {
            "current_iv": avg_iv,
            "iv_rank": iv_rank,
        },
        "price_history_summary": {
            "bars_30d": bars_30d[-5:],  # last 5 days for context
            "sma_20": sma_20,
        },
        "market_regime": regime,
    }


def _is_call(contract: dict) -> bool:
    """Determine if a contract is a call by its delta sign (positive = call)."""
    delta = contract.get("delta")
    if delta is None:
        # Fall back to contract_id OCC parsing: ...C... or ...P...
        cid = contract.get("contract_id", "")
        return "C" in cid[-10:]
    return delta >= 0


def _compute_iv_rank(symbol: str, current_iv: float | None) -> float | None:
    """
    Compute IV rank (0-100) using the last 30 days of stored snapshots.
    Returns None if insufficient history.
    """
    if current_iv is None:
        return None

    try:
        from magpie.db.connection import get_connection

        conn = get_connection()
        rows = conn.execute(
            """
            SELECT implied_volatility FROM option_snapshots os
            JOIN option_contracts oc ON os.contract_id = oc.contract_id
            WHERE oc.underlying_symbol = ?
              AND os.snapshot_time >= NOW() - INTERVAL 90 DAY
              AND os.implied_volatility IS NOT NULL
            """,
            [symbol],
        ).fetchall()

        if len(rows) < 10:
            return None

        ivs = [r[0] for r in rows]
        low, high = min(ivs), max(ivs)
        if high == low:
            return 50.0
        return round((current_iv - low) / (high - low) * 100, 1)
    except Exception:
        return None
