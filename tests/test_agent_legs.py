"""Tests for agent leg resolution, costing, and order pricing (no API calls)."""

import pytest

from magpie.agent.loop import AgentLoop, resolve_legs
from magpie.execution.orders import net_premium, signed_limit_price

CONTEXT = {
    "options_chain": {
        "expiry": "2026-11-06",
        "calls": [{"contract_id": "SPY261106C00803000", "mid": 2.84}],
        "puts": [
            {"contract_id": "SPY261106P00731000", "mid": 3.95},
            {"contract_id": "SPY261106P00721000", "mid": 3.04},
        ],
    }
}

BULL_PUT = [
    {"action": "sell", "option_type": "put", "strike": 731, "expiry": "2026-11-06"},
    {"action": "buy", "option_type": "put", "strike": 721, "expiry": "2026-11-06"},
]


def _no_fetch(contract):
    raise AssertionError(f"unexpected snapshot fetch for {contract}")


# ── resolve_legs ─────────────────────────────────────────────────────────────


def test_resolves_from_context_chain():
    legs = resolve_legs("SPY", BULL_PUT, CONTEXT, fetch_snapshot=_no_fetch)
    assert legs == [
        {"contract_symbol": "SPY261106P00731000", "option_type": "put", "strike_price": 731.0,
         "expiry": "2026-11-06", "quantity": -1, "premium": 3.95, "side": "sell"},
        {"contract_symbol": "SPY261106P00721000", "option_type": "put", "strike_price": 721.0,
         "expiry": "2026-11-06", "quantity": 1, "premium": 3.04, "side": "buy"},
    ]


def test_falls_back_to_live_snapshot_for_strikes_outside_ladder():
    fetched = []

    def fetch(contract):
        fetched.append(contract)
        return {"mid": 1.48}

    llm_legs = [
        {"action": "sell", "option_type": "call", "strike": 803, "expiry": "2026-11-06"},
        {"action": "buy", "option_type": "call", "strike": 813, "expiry": "2026-11-06"},
    ]
    legs = resolve_legs("SPY", llm_legs, CONTEXT, fetch_snapshot=fetch)
    assert fetched == ["SPY261106C00813000"]
    assert [leg["premium"] for leg in legs] == [2.84, 1.48]


@pytest.mark.parametrize("bad_leg", [
    {"action": "sell", "option_type": "put", "strike": 731},                               # no expiry
    {"action": "hold", "option_type": "put", "strike": 731, "expiry": "2026-11-06"},       # bad action
    {"action": "sell", "option_type": "future", "strike": 731, "expiry": "2026-11-06"},    # bad type
    {"action": "sell", "option_type": "put", "strike": "abc", "expiry": "2026-11-06"},     # bad strike
    {"action": "sell", "option_type": "put", "strike": 731, "expiry": "Nov 6"},            # bad date
])
def test_any_malformed_leg_rejects_whole_trade(bad_leg):
    assert resolve_legs("SPY", [bad_leg, BULL_PUT[1]], CONTEXT, fetch_snapshot=_no_fetch) == []


def test_unquoted_leg_rejects_whole_trade():
    llm_legs = [BULL_PUT[0], {"action": "buy", "option_type": "put", "strike": 700, "expiry": "2026-11-06"}]
    assert resolve_legs("SPY", llm_legs, CONTEXT, fetch_snapshot=lambda c: None) == []


def test_snapshot_error_rejects_whole_trade():
    def boom(contract):
        raise RuntimeError("API down")

    llm_legs = [BULL_PUT[0], {"action": "buy", "option_type": "put", "strike": 700, "expiry": "2026-11-06"}]
    assert resolve_legs("SPY", llm_legs, CONTEXT, fetch_snapshot=boom) == []


def test_rejects_empty_and_more_than_four_legs():
    assert resolve_legs("SPY", [], CONTEXT, fetch_snapshot=_no_fetch) == []
    assert resolve_legs("SPY", BULL_PUT * 3, CONTEXT, fetch_snapshot=_no_fetch) == []


# ── Pricing & cost ───────────────────────────────────────────────────────────


def _legs():
    return resolve_legs("SPY", BULL_PUT, CONTEXT, fetch_snapshot=_no_fetch)


def test_net_premium_credit_positive_debit_negative():
    credit_legs = _legs()
    assert net_premium(credit_legs) == pytest.approx(0.91)
    debit_legs = [{**leg, "quantity": -leg["quantity"]} for leg in credit_legs]
    assert net_premium(debit_legs) == pytest.approx(-0.91)


def test_signed_limit_price_follows_alpaca_mleg_convention():
    credit_legs = _legs()
    debit_legs = [{**leg, "quantity": -leg["quantity"]} for leg in credit_legs]
    assert signed_limit_price(credit_legs, 0.91) == -0.91   # credit → negative
    assert signed_limit_price(debit_legs, 0.91) == 0.91     # debit → positive
    assert signed_limit_price(credit_legs, -0.91) == -0.91  # sign of input is ignored


def test_estimate_cost_is_max_loss_not_premium():
    # $10-wide bull put for 0.91 credit → $909 at risk per lot
    assert AgentLoop()._estimate_cost(_legs()) == pytest.approx(909.0)
