"""Tests for option chain selection in the analysis context (pure helpers, no API calls)."""

from datetime import date

from magpie.analysis.prompts import format_analysis_prompt
from magpie.market.snapshots import _atm_iv, _delta_ladder, _pick_expiry

TODAY = date(2026, 9, 25)


def _contract(option_type, strike, delta, iv=0.30, expiry="2026-11-06", mid=1.0):
    cp = "C" if option_type == "call" else "P"
    return {
        "contract_id": f"XYZ261106{cp}{int(strike * 1000):08d}",
        "option_type": option_type,
        "strike": strike,
        "expiry": expiry,
        "delta": delta,
        "implied_volatility": iv,
        "bid": mid - 0.05 if mid else None,
        "ask": mid + 0.05 if mid else None,
        "mid": mid,
        "theta": -0.05,
    }


def _call_chain():
    """Calls from deep ITM (0.99Δ) to far OTM (0.03Δ) at strikes 60..140."""
    deltas = [0.99, 0.95, 0.85, 0.70, 0.52, 0.41, 0.31, 0.24, 0.19, 0.15, 0.11, 0.08, 0.05, 0.03]
    return [_contract("call", 60 + i * 6, d) for i, d in enumerate(deltas)]


# ── _pick_expiry ─────────────────────────────────────────────────────────────


def test_pick_expiry_closest_to_target():
    chain = [_contract("call", 100, 0.5, expiry=e) for e in ("2026-10-16", "2026-10-30", "2026-11-20")]
    assert _pick_expiry(chain, 35, today=TODAY) == "2026-10-30"  # 35 DTE exactly


def test_pick_expiry_tie_prefers_later():
    chain = [_contract("call", 100, 0.5, expiry=e) for e in ("2026-10-23", "2026-11-06")]  # 28 / 42 DTE
    assert _pick_expiry(chain, 35, today=TODAY) == "2026-11-06"


def test_pick_expiry_empty_chain():
    assert _pick_expiry([], 35, today=TODAY) is None


# ── _delta_ladder ────────────────────────────────────────────────────────────


def test_delta_ladder_excludes_deep_itm_and_orders_atm_to_otm():
    ladder = _delta_ladder(_call_chain(), "call")
    deltas = [c["delta"] for c in ladder]
    assert max(deltas) <= 0.55, "ITM contracts must not appear in the ladder"
    assert deltas == sorted(deltas, reverse=True), "ladder must run ATM → OTM"
    assert deltas[0] == 0.52
    # Short-strike and wing candidates for spreads/condors are present
    assert {0.31, 0.24, 0.19, 0.15, 0.11, 0.08, 0.05} <= set(deltas)


def test_delta_ladder_puts_use_absolute_delta():
    puts = [_contract("put", k, d) for k, d in [(100, -0.48), (95, -0.30), (90, -0.16), (85, -0.08), (70, -0.99)]]
    ladder = _delta_ladder(puts, "put")
    assert [c["strike"] for c in ladder] == [100, 95, 90, 85]


def test_delta_ladder_skips_unquoted_and_wrong_type():
    chain = [
        _contract("call", 100, 0.50, mid=None),   # no quote
        _contract("put", 100, -0.50),             # wrong side
        _contract("call", 105, 0.30),
    ]
    ladder = _delta_ladder(chain, "call")
    assert [c["strike"] for c in ladder] == [105]


def test_delta_ladder_no_duplicates():
    chain = [_contract("call", 100, 0.50), _contract("call", 110, 0.20)]
    ladder = _delta_ladder(chain, "call")
    assert len(ladder) == len({c["contract_id"] for c in ladder})


# ── _atm_iv ──────────────────────────────────────────────────────────────────


def test_atm_iv_uses_nearest_strike_not_chain_average():
    chain = [
        _contract("call", 60, 0.99, iv=0.90),   # deep ITM junk IV
        _contract("call", 100, 0.51, iv=0.30),
        _contract("put", 100, -0.49, iv=0.34),
        _contract("put", 140, -0.99, iv=0.85),
    ]
    assert abs(_atm_iv(chain, 101.0) - 0.32) < 1e-9


def test_atm_iv_no_price():
    assert _atm_iv([_contract("call", 100, 0.5)], None) is None


# ── Prompt rendering ─────────────────────────────────────────────────────────


def test_prompt_renders_ladder_with_strikes_and_quotes():
    ladder = _delta_ladder(_call_chain(), "call")
    context = {
        "underlying": {"price": 100.0},
        "iv_metrics": {"current_iv": 0.32, "iv_rank": None},
        "options_chain": {"expiry": "2026-11-06", "dte": 42, "calls": ladder, "puts": [], "total_contracts": 14},
        "price_history_summary": {"bars_30d": []},
        "market_regime": None,
    }
    prompt = format_analysis_prompt("XYZ", context)
    assert "expiry 2026-11-06 (42 DTE)" in prompt
    assert "ATM IV (2026-11-06): 32.0%" in prompt
    assert "strike=84.00" in prompt and "bid/ask=$0.95/$1.05" in prompt
    assert prompt.count("XYZ261106C") == len(ladder), "all ladder rungs rendered, not just the first 5"
    assert "OI=" not in prompt
