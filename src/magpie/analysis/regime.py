"""Market regime classification — VIX, SPY trend, and volatility regime.

Computes a composite market regime label (e.g. 'bullish_low_vol') from:
- Real VIX level (Yahoo Finance API, with realized-vol fallback)
- SPY trend (price vs SMA-50/200, 20-day momentum)
- SPY put/call ratio (options chain OI as breadth proxy)

The regime dict is injected into the LLM analysis prompt so the model
sees the macro picture alongside symbol-specific data.
"""

from __future__ import annotations

import logging
import math
from datetime import date
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from magpie.market.stocks import get_bars, get_snapshot

logger = logging.getLogger(__name__)

# ── VIX thresholds ──────────────────────────────────────────────────────────

_VIX_LOW = 15.0
_VIX_HIGH = 25.0

# ── VIX fetching ────────────────────────────────────────────────────────────

_VIX_YAHOO_URL = "https://query1.finance.yahoo.com/v8/finance/chart/%5EVIX"


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def fetch_vix() -> tuple[float, str]:
    """Fetch the current VIX level from Yahoo Finance.

    Returns ``(vix_value, source_name)``.
    Raises on failure (caller should fall back to realized vol).
    """
    resp = httpx.get(
        _VIX_YAHOO_URL,
        params={"range": "1d", "interval": "1d"},
        headers={"User-Agent": "magpie-options-bot/1.0"},
        timeout=10.0,
    )
    resp.raise_for_status()
    data = resp.json()
    meta = data["chart"]["result"][0]["meta"]
    price = meta["regularMarketPrice"]
    return float(price), "yahoo_finance"


def _compute_realized_vol_fallback(spy_bars: list[dict]) -> float | None:
    """Compute annualized realized vol from SPY bars (VIX-scale proxy).

    Uses log returns over the available bars, annualized to ~252 trading days.
    Returns None if insufficient data.
    """
    closes = [b["close"] for b in spy_bars if b.get("close")]
    if len(closes) < 10:
        return None
    log_returns = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]
    if not log_returns:
        return None
    mean = sum(log_returns) / len(log_returns)
    variance = sum((r - mean) ** 2 for r in log_returns) / len(log_returns)
    daily_vol = math.sqrt(variance)
    annualized = daily_vol * math.sqrt(252) * 100  # scale to VIX-like number
    return round(annualized, 2)


# ── SPY trend helpers ───────────────────────────────────────────────────────


def _compute_sma(bars: list[dict], period: int) -> float | None:
    """Simple moving average of close prices over the last *period* bars."""
    closes = [b["close"] for b in bars if b.get("close")]
    if len(closes) < period:
        return None
    recent = closes[-period:]
    return sum(recent) / len(recent)


def _compute_momentum(bars: list[dict], period: int = 20) -> float | None:
    """Percentage return over the lookback *period*."""
    closes = [b["close"] for b in bars if b.get("close")]
    if len(closes) < period + 1:
        return None
    return (closes[-1] - closes[-period - 1]) / closes[-period - 1]


# ── Breadth proxy ───────────────────────────────────────────────────────────


def _compute_spy_put_call_ratio() -> float | None:
    """SPY put/call open-interest ratio from the options chain.

    Ratio > 1.0 → more puts (bearish sentiment).
    Ratio < 0.7 → more calls (bullish sentiment).
    """
    try:
        from magpie.market.options import get_option_chain

        chain = get_option_chain("SPY", dte_min=15, dte_max=45, strike_count=10)
        if not chain:
            return None
        call_oi = sum(
            c.get("open_interest") or 0 for c in chain if (c.get("delta") or 0) >= 0
        )
        put_oi = sum(
            c.get("open_interest") or 0 for c in chain if (c.get("delta") or 0) < 0
        )
        if call_oi == 0:
            return None
        return round(put_oi / call_oi, 4)
    except Exception:
        logger.debug("Could not compute SPY put/call ratio", exc_info=True)
        return None


# ── Classification ──────────────────────────────────────────────────────────


def classify_regime(
    vix: float | None,
    spy_price: float | None,
    sma_50: float | None,
    sma_200: float | None,
    momentum_20d: float | None,
) -> tuple[str, str, str]:
    """Classify market into ``(trend_regime, volatility_regime, composite)``.

    Trend scoring:
        SPY > SMA-50 → +1, else −1
        SPY > SMA-200 → +1, else −1
        20d momentum > +1% → +1, < −1% → −1, else 0
        Score ≥ 2 → bullish, ≤ −2 → bearish, else neutral

    Volatility: VIX < 15 → low, > 25 → high, else normal (None → normal).
    """
    # Volatility regime
    if vix is None:
        vol_regime = "normal"
    elif vix < _VIX_LOW:
        vol_regime = "low"
    elif vix > _VIX_HIGH:
        vol_regime = "high"
    else:
        vol_regime = "normal"

    # Trend regime (score-based)
    trend_score = 0
    if spy_price and sma_50:
        trend_score += 1 if spy_price > sma_50 else -1
    if spy_price and sma_200:
        trend_score += 1 if spy_price > sma_200 else -1
    if momentum_20d is not None:
        trend_score += 1 if momentum_20d > 0.01 else (-1 if momentum_20d < -0.01 else 0)

    if trend_score >= 2:
        trend_regime = "bullish"
    elif trend_score <= -2:
        trend_regime = "bearish"
    else:
        trend_regime = "neutral"

    composite = f"{trend_regime}_{vol_regime}_vol"
    return trend_regime, vol_regime, composite


# ── Main entry point ────────────────────────────────────────────────────────


def get_market_regime() -> dict[str, Any]:
    """Build the full market regime dict.

    Fetches VIX (with realized-vol fallback), computes SPY trend indicators,
    classifies regime, and returns a structured dict for prompt injection.

    Never raises — returns best-effort data with graceful fallbacks.
    """
    # SPY bars (need ~250 for SMA-200)
    try:
        spy_bars = get_bars("SPY", days=250)
    except Exception:
        logger.warning("Could not fetch SPY bars for regime", exc_info=True)
        spy_bars = []

    spy_price = None
    try:
        spy_snap = get_snapshot("SPY")
        spy_price = spy_snap.get("price")
    except Exception:
        if spy_bars:
            spy_price = spy_bars[-1].get("close")

    sma_50 = _compute_sma(spy_bars, 50)
    sma_200 = _compute_sma(spy_bars, 200)
    momentum_20d = _compute_momentum(spy_bars, 20)

    # VIX with fallback to realized vol
    vix = None
    vix_source = None
    try:
        vix, vix_source = fetch_vix()
    except Exception:
        logger.info("VIX fetch failed, using realized vol fallback", exc_info=True)
        recent = spy_bars[-30:] if len(spy_bars) >= 30 else spy_bars
        realized = _compute_realized_vol_fallback(recent)
        if realized is not None:
            vix = realized
            vix_source = "spy_realized_vol"

    # Put/call ratio
    put_call = _compute_spy_put_call_ratio()

    # Classify
    trend, vol, composite = classify_regime(vix, spy_price, sma_50, sma_200, momentum_20d)

    return {
        "vix_level": vix,
        "vix_source": vix_source,
        "spy_price": round(spy_price, 2) if spy_price else None,
        "spy_sma_50": round(sma_50, 2) if sma_50 else None,
        "spy_sma_200": round(sma_200, 2) if sma_200 else None,
        "spy_momentum_20d": round(momentum_20d, 4) if momentum_20d is not None else None,
        "spy_put_call_ratio": put_call,
        "trend_regime": trend,
        "volatility_regime": vol,
        "composite_regime": composite,
    }


# ── Persistence ─────────────────────────────────────────────────────────────


def save_regime_snapshot(regime: dict) -> None:
    """Persist the regime snapshot to DB (one per day, upserts)."""
    from magpie.db.connection import get_connection

    conn = get_connection()
    today = date.today()

    conn.execute("DELETE FROM market_regime_snapshots WHERE snapshot_date = ?", [today])
    conn.execute(
        """
        INSERT INTO market_regime_snapshots (
            snapshot_date, vix_level, vix_source,
            spy_price, spy_sma_50, spy_sma_200, spy_momentum_20d,
            trend_regime, volatility_regime, composite_regime,
            spy_put_call_ratio
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            today,
            regime.get("vix_level"),
            regime.get("vix_source"),
            regime.get("spy_price"),
            regime.get("spy_sma_50"),
            regime.get("spy_sma_200"),
            regime.get("spy_momentum_20d"),
            regime["trend_regime"],
            regime["volatility_regime"],
            regime["composite_regime"],
            regime.get("spy_put_call_ratio"),
        ],
    )
    conn.commit()


def get_latest_regime() -> dict | None:
    """Return the most recent regime snapshot from DB, or None."""
    from magpie.db.connection import get_connection

    conn = get_connection()
    row = conn.execute(
        """
        SELECT snapshot_date, vix_level, vix_source,
               spy_price, spy_sma_50, spy_sma_200, spy_momentum_20d,
               trend_regime, volatility_regime, composite_regime,
               spy_put_call_ratio
        FROM market_regime_snapshots
        ORDER BY snapshot_date DESC
        LIMIT 1
        """
    ).fetchone()
    if not row:
        return None
    return {
        "snapshot_date": str(row[0]),
        "vix_level": float(row[1]) if row[1] is not None else None,
        "vix_source": row[2],
        "spy_price": float(row[3]) if row[3] is not None else None,
        "spy_sma_50": float(row[4]) if row[4] is not None else None,
        "spy_sma_200": float(row[5]) if row[5] is not None else None,
        "spy_momentum_20d": float(row[6]) if row[6] is not None else None,
        "trend_regime": row[7],
        "volatility_regime": row[8],
        "composite_regime": row[9],
        "spy_put_call_ratio": float(row[10]) if row[10] is not None else None,
    }
