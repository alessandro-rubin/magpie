"""Tests for market regime classification, persistence, and prompt rendering."""

import math
from unittest.mock import patch

import pytest

from magpie.analysis.regime import (
    _compute_momentum,
    _compute_realized_vol_fallback,
    _compute_sma,
    classify_regime,
    get_latest_regime,
    save_regime_snapshot,
)


# ── Classification tests (pure functions, no mocks) ─────────────────────────


def test_classify_regime_bullish():
    trend, vol, composite = classify_regime(
        vix=14.0, spy_price=500.0, sma_50=480.0, sma_200=460.0, momentum_20d=0.03
    )
    assert trend == "bullish"
    assert vol == "low"
    assert composite == "bullish_low_vol"


def test_classify_regime_bearish():
    trend, vol, composite = classify_regime(
        vix=30.0, spy_price=420.0, sma_50=450.0, sma_200=470.0, momentum_20d=-0.05
    )
    assert trend == "bearish"
    assert vol == "high"
    assert composite == "bearish_high_vol"


def test_classify_regime_neutral():
    # SPY above SMA-200 (+1) but below SMA-50 (-1), flat momentum (0) → score 0
    trend, vol, composite = classify_regime(
        vix=18.0, spy_price=460.0, sma_50=470.0, sma_200=450.0, momentum_20d=0.005
    )
    assert trend == "neutral"
    assert vol == "normal"
    assert composite == "neutral_normal_vol"


def test_classify_regime_none_vix():
    """VIX=None should default to 'normal' volatility."""
    _, vol, _ = classify_regime(
        vix=None, spy_price=500.0, sma_50=480.0, sma_200=460.0, momentum_20d=0.03
    )
    assert vol == "normal"


def test_classify_regime_none_sma():
    """Missing SMAs should not crash — just reduce scoring signals."""
    trend, vol, composite = classify_regime(
        vix=20.0, spy_price=500.0, sma_50=None, sma_200=None, momentum_20d=0.05
    )
    # Only momentum contributes: +1 → neutral (need >=2 for bullish)
    assert trend == "neutral"
    assert vol == "normal"


# ── SMA and momentum helpers ────────────────────────────────────────────────


def test_compute_sma():
    bars = [{"close": float(i)} for i in range(1, 21)]  # 1..20
    sma = _compute_sma(bars, 5)
    assert sma == pytest.approx(18.0)  # avg of 16,17,18,19,20


def test_compute_sma_insufficient_data():
    bars = [{"close": 100.0}]
    assert _compute_sma(bars, 50) is None


def test_compute_momentum():
    bars = [{"close": 100.0}] * 20 + [{"close": 110.0}]
    momentum = _compute_momentum(bars, 20)
    assert momentum == pytest.approx(0.10)  # 10% gain


def test_compute_momentum_insufficient_data():
    bars = [{"close": 100.0}]
    assert _compute_momentum(bars, 20) is None


# ── Realized vol fallback ───────────────────────────────────────────────────


def test_realized_vol_fallback():
    """Synthetic bars with alternating returns → non-zero annualized vol."""
    # Alternating +1% / -1% gives clear daily variance
    bars = []
    price = 100.0
    for i in range(30):
        price *= 1.01 if i % 2 == 0 else 0.99
        bars.append({"close": price})
    vol = _compute_realized_vol_fallback(bars)
    assert vol is not None
    assert vol > 5   # should be meaningful vol
    assert vol < 100  # but not absurd


def test_realized_vol_fallback_insufficient_data():
    bars = [{"close": 100.0}] * 5
    assert _compute_realized_vol_fallback(bars) is None


# ── Persistence (DB round-trip) ─────────────────────────────────────────────


def test_save_and_get_regime_snapshot(db, monkeypatch):
    import magpie.db.connection as conn_mod

    monkeypatch.setattr(conn_mod, "get_connection", lambda: db)

    regime = {
        "vix_level": 22.5,
        "vix_source": "yahoo_finance",
        "spy_price": 485.30,
        "spy_sma_50": 478.00,
        "spy_sma_200": 465.50,
        "spy_momentum_20d": 0.015,
        "spy_put_call_ratio": 0.92,
        "trend_regime": "bullish",
        "volatility_regime": "normal",
        "composite_regime": "bullish_normal_vol",
    }

    save_regime_snapshot(regime)
    loaded = get_latest_regime()

    assert loaded is not None
    assert loaded["trend_regime"] == "bullish"
    assert loaded["volatility_regime"] == "normal"
    assert loaded["vix_level"] == pytest.approx(22.5)
    assert loaded["spy_price"] == pytest.approx(485.30)
    assert loaded["spy_put_call_ratio"] == pytest.approx(0.92)


def test_save_regime_upserts(db, monkeypatch):
    """Saving twice on the same day should upsert, not duplicate."""
    import magpie.db.connection as conn_mod

    monkeypatch.setattr(conn_mod, "get_connection", lambda: db)

    base = {
        "vix_level": 20.0, "vix_source": "yahoo_finance",
        "spy_price": 480.0, "spy_sma_50": 475.0, "spy_sma_200": 460.0,
        "spy_momentum_20d": 0.01, "spy_put_call_ratio": None,
        "trend_regime": "neutral", "volatility_regime": "normal",
        "composite_regime": "neutral_normal_vol",
    }

    save_regime_snapshot(base)
    save_regime_snapshot({**base, "vix_level": 25.0, "volatility_regime": "high",
                          "composite_regime": "neutral_high_vol"})

    count = db.execute("SELECT COUNT(*) FROM market_regime_snapshots").fetchone()[0]
    assert count == 1

    loaded = get_latest_regime()
    assert loaded["vix_level"] == pytest.approx(25.0)


# ── Prompt rendering ────────────────────────────────────────────────────────


def test_format_regime_section_with_data():
    from magpie.analysis.prompts import _format_regime_section

    regime = {
        "vix_level": 22.5,
        "vix_source": "yahoo_finance",
        "spy_price": 485.30,
        "spy_sma_50": 478.00,
        "spy_sma_200": 465.50,
        "spy_momentum_20d": 0.015,
        "spy_put_call_ratio": 0.92,
        "trend_regime": "bullish",
        "volatility_regime": "normal",
        "composite_regime": "bullish_normal_vol",
    }

    result = _format_regime_section(regime)
    assert "Market Regime & Sentiment" in result
    assert "22.50" in result
    assert "bullish" in result
    assert "yahoo_finance" in result
    assert "485.30" in result


def test_format_regime_section_none():
    from magpie.analysis.prompts import _format_regime_section

    result = _format_regime_section(None)
    assert "unavailable" in result


def test_format_analysis_prompt_includes_regime():
    from magpie.analysis.prompts import format_analysis_prompt

    context = {
        "underlying": {"price": 260.0, "change_pct": -0.01, "sma_20": 265.0,
                        "price_vs_sma20": -0.019, "low_52w": 200.0, "high_52w": 280.0,
                        "volume": 50000000},
        "iv_metrics": {"current_iv": 0.25, "iv_rank": None},
        "options_chain": {"calls": [], "puts": [], "total_contracts": 0},
        "price_history_summary": {"bars_30d": [], "sma_20": 265.0},
        "market_regime": {
            "vix_level": 22.5, "vix_source": "yahoo_finance",
            "spy_price": 485.0, "spy_sma_50": 478.0, "spy_sma_200": 465.0,
            "spy_momentum_20d": 0.015, "spy_put_call_ratio": 0.92,
            "trend_regime": "bullish", "volatility_regime": "normal",
            "composite_regime": "bullish_normal_vol",
        },
    }

    result = format_analysis_prompt("AAPL", context)
    assert "Market Regime & Sentiment" in result
    assert "bullish" in result
    assert "VIX" in result


def test_format_analysis_prompt_without_regime():
    """When market_regime is None, prompt should still render with fallback text."""
    from magpie.analysis.prompts import format_analysis_prompt

    context = {
        "underlying": {"price": 260.0, "change_pct": -0.01, "sma_20": 265.0,
                        "price_vs_sma20": -0.019, "low_52w": 200.0, "high_52w": 280.0,
                        "volume": 50000000},
        "iv_metrics": {"current_iv": 0.25, "iv_rank": None},
        "options_chain": {"calls": [], "puts": [], "total_contracts": 0},
        "price_history_summary": {"bars_30d": [], "sma_20": 265.0},
        "market_regime": None,
    }

    result = format_analysis_prompt("AAPL", context)
    assert "unavailable" in result
