"""Assembles the full market context dict fed to the LLM for analysis."""

from __future__ import annotations

from datetime import date

from magpie.market.stocks import get_snapshot, get_bars, compute_52w_range
from magpie.market.options import get_option_chain

TARGET_DTE = 35          # preferred expiry for new defined-risk positions
STRIKE_RANGE_PCT = 0.20  # fetch strikes within ±20% of spot
# One contract per target |delta|, ATM → OTM — covers short strikes and wings for spreads/condors
LADDER_DELTAS = (0.50, 0.40, 0.30, 0.25, 0.20, 0.16, 0.12, 0.08, 0.05)


def build_analysis_context(symbol: str) -> dict:
    """
    Build the complete market context package for LLM analysis.

    Returns a structured dict containing:
    - underlying price and change metrics
    - recent price history summary
    - option chain snapshot: one expiry near TARGET_DTE, ATM → OTM strike ladder per side
    - IV metrics (ATM IV of that expiry)
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
    price = stock_snap.get("price")
    try:
        chain = get_option_chain(
            symbol,
            dte_min=15,
            dte_max=45,
            strike_min=price * (1 - STRIKE_RANGE_PCT) if price else None,
            strike_max=price * (1 + STRIKE_RANGE_PCT) if price else None,
        )
    except Exception:
        chain = []

    # Focus on a single expiry so the LLM sees one coherent strike ladder
    expiry = _pick_expiry(chain, TARGET_DTE)
    expiry_chain = [c for c in chain if c.get("expiry") == expiry]
    calls = _delta_ladder(expiry_chain, "call")
    puts = _delta_ladder(expiry_chain, "put")

    # ── IV metrics ───────────────────────────────────────────────────────────
    atm_iv = _atm_iv(expiry_chain, price)
    iv_rank = _compute_iv_rank(symbol, atm_iv)

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
            "expiry": expiry,
            "dte": (date.fromisoformat(expiry) - date.today()).days if expiry else None,
            "calls": calls,
            "puts": puts,
            "total_contracts": len(chain),
        },
        "iv_metrics": {
            "current_iv": atm_iv,
            "iv_rank": iv_rank,
        },
        "price_history_summary": {
            "bars_30d": bars_30d[-5:],  # last 5 days for context
            "sma_20": sma_20,
        },
        "market_regime": regime,
    }


def _pick_expiry(chain: list[dict], target_dte: int, today: date | None = None) -> str | None:
    """Return the ISO expiry in the chain closest to target_dte (ties → later expiry)."""
    today = today or date.today()
    expiries = {c["expiry"] for c in chain if c.get("expiry")}
    if not expiries:
        return None
    return min(
        expiries,
        key=lambda e: (abs((date.fromisoformat(e) - today).days - target_dte), -date.fromisoformat(e).toordinal()),
    )


def _delta_ladder(contracts: list[dict], option_type: str) -> list[dict]:
    """Pick the quoted contract nearest each LADDER_DELTAS target, ordered ATM → OTM."""
    quoted = [
        c for c in contracts
        if c.get("option_type") == option_type and c.get("delta") is not None and c.get("mid")
    ]
    picked: dict[str, dict] = {}
    for target in LADDER_DELTAS:
        if not quoted:
            break
        best = min(quoted, key=lambda c: abs(abs(c["delta"]) - target))
        # Skip targets far outside what the chain offers (e.g. no 5Δ strike within range)
        if abs(abs(best["delta"]) - target) <= max(0.05, target * 0.35):
            picked[best["contract_id"]] = best
    return sorted(picked.values(), key=lambda c: abs(c["delta"]), reverse=True)


def _atm_iv(contracts: list[dict], price: float | None) -> float | None:
    """Average IV of the call and put struck nearest the underlying price."""
    if not price:
        return None
    ivs = []
    for option_type in ("call", "put"):
        side = [
            c for c in contracts
            if c.get("option_type") == option_type
            and c.get("implied_volatility")
            and c.get("strike") is not None
        ]
        if side:
            ivs.append(min(side, key=lambda c: abs(c["strike"] - price))["implied_volatility"])
    return sum(ivs) / len(ivs) if ivs else None


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
              AND os.snapshot_time >= datetime('now', '-90 days')
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
