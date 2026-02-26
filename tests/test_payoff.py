"""Tests for options payoff diagram math."""

from __future__ import annotations

import numpy as np
import pytest

from magpie.dashboard.payoff import compute_payoff, find_breakevens, price_range_for_legs


class TestComputePayoff:
    """Test P&L computation at expiration."""

    def test_long_call(self):
        """Long 1 call at strike 100, premium $5."""
        legs = [{"option_type": "call", "strike_price": 100, "quantity": 1, "premium": 5.0}]
        prices = np.array([90.0, 95.0, 100.0, 105.0, 110.0, 120.0])
        pnl = compute_payoff(legs, prices)

        # Below strike: lose premium ($500)
        assert pnl[0] == pytest.approx(-500.0)
        assert pnl[2] == pytest.approx(-500.0)  # at strike
        # At $105: intrinsic $5 - premium $5 = breakeven
        assert pnl[3] == pytest.approx(0.0)
        # At $110: profit $500
        assert pnl[4] == pytest.approx(500.0)
        # At $120: profit $1500
        assert pnl[5] == pytest.approx(1500.0)

    def test_long_put(self):
        """Long 1 put at strike 100, premium $4."""
        legs = [{"option_type": "put", "strike_price": 100, "quantity": 1, "premium": 4.0}]
        prices = np.array([80.0, 90.0, 96.0, 100.0, 110.0])
        pnl = compute_payoff(legs, prices)

        assert pnl[0] == pytest.approx(1600.0)  # $20 intrinsic - $4 premium = $16 * 100
        assert pnl[2] == pytest.approx(0.0)  # breakeven at $96
        assert pnl[3] == pytest.approx(-400.0)  # at strike, lose premium
        assert pnl[4] == pytest.approx(-400.0)  # above strike, lose premium

    def test_bull_call_spread(self):
        """Long 275C at $5.85, short 285C at $2.15 (net debit $3.70)."""
        legs = [
            {"option_type": "call", "strike_price": 275, "quantity": 1, "premium": 5.85},
            {"option_type": "call", "strike_price": 285, "quantity": -1, "premium": 2.15},
        ]
        prices = np.array([270.0, 275.0, 278.70, 280.0, 285.0, 290.0])
        pnl = compute_payoff(legs, prices)

        # Below both strikes: max loss = net debit * 100 = -$370
        assert pnl[0] == pytest.approx(-370.0)
        assert pnl[1] == pytest.approx(-370.0)

        # Breakeven: $275 + $3.70 = $278.70
        assert pnl[2] == pytest.approx(0.0, abs=1e-6)

        # Above both strikes: max profit = (spread width - net debit) * 100 = $630
        assert pnl[4] == pytest.approx(630.0)
        assert pnl[5] == pytest.approx(630.0)  # capped at max profit

    def test_bear_put_spread(self):
        """Long 400P at $17.45, short 385P at $11.35 (net debit $6.10)."""
        legs = [
            {"option_type": "put", "strike_price": 400, "quantity": 1, "premium": 17.45},
            {"option_type": "put", "strike_price": 385, "quantity": -1, "premium": 11.35},
        ]
        prices = np.array([370.0, 385.0, 393.90, 400.0, 410.0])
        pnl = compute_payoff(legs, prices)

        # Below both strikes: max profit = (spread width - net debit) * 100 = $890
        assert pnl[0] == pytest.approx(890.0)
        assert pnl[1] == pytest.approx(890.0)

        # Breakeven: $400 - $6.10 = $393.90
        assert pnl[2] == pytest.approx(0.0, abs=1e-6)

        # Above both strikes: max loss = net debit * 100 = -$610
        assert pnl[3] == pytest.approx(-610.0)
        assert pnl[4] == pytest.approx(-610.0)

    def test_short_straddle(self):
        """Short straddle: sell call + put at 100, collect $3 + $3."""
        legs = [
            {"option_type": "call", "strike_price": 100, "quantity": -1, "premium": 3.0},
            {"option_type": "put", "strike_price": 100, "quantity": -1, "premium": 3.0},
        ]
        prices = np.array([90.0, 94.0, 100.0, 106.0, 110.0])
        pnl = compute_payoff(legs, prices)

        # At strike: max profit = total premium collected = $600
        assert pnl[2] == pytest.approx(600.0)
        # Breakevens at 94 and 106
        assert pnl[1] == pytest.approx(0.0)
        assert pnl[3] == pytest.approx(0.0)

    def test_multiple_contracts(self):
        """10 contracts of a bull call spread."""
        legs = [
            {"option_type": "call", "strike_price": 275, "quantity": 10, "premium": 5.85},
            {"option_type": "call", "strike_price": 285, "quantity": -10, "premium": 2.15},
        ]
        prices = np.array([270.0, 290.0])
        pnl = compute_payoff(legs, prices)

        assert pnl[0] == pytest.approx(-3700.0)  # max loss * 10
        assert pnl[1] == pytest.approx(6300.0)  # max profit * 10


class TestFindBreakevens:
    """Test breakeven point detection."""

    def test_single_breakeven_long_call(self):
        legs = [{"option_type": "call", "strike_price": 100, "quantity": 1, "premium": 5.0}]
        bks = find_breakevens(legs, 80, 120)
        assert len(bks) == 1
        assert bks[0] == pytest.approx(105.0, abs=0.1)

    def test_two_breakevens_short_straddle(self):
        legs = [
            {"option_type": "call", "strike_price": 100, "quantity": -1, "premium": 3.0},
            {"option_type": "put", "strike_price": 100, "quantity": -1, "premium": 3.0},
        ]
        bks = find_breakevens(legs, 80, 120)
        assert len(bks) == 2
        assert bks[0] == pytest.approx(94.0, abs=0.1)
        assert bks[1] == pytest.approx(106.0, abs=0.1)


class TestPriceRange:
    """Test price range calculation."""

    def test_centers_on_underlying(self):
        legs = [{"option_type": "call", "strike_price": 100, "quantity": 1, "premium": 5.0}]
        low, high = price_range_for_legs(legs, underlying_price=100)
        assert low < 100 < high
        assert low == pytest.approx(80.0, abs=1)
        assert high == pytest.approx(120.0, abs=1)

    def test_centers_on_strikes_without_underlying(self):
        legs = [
            {"option_type": "call", "strike_price": 275, "quantity": 1, "premium": 5.0},
            {"option_type": "call", "strike_price": 285, "quantity": -1, "premium": 2.0},
        ]
        low, high = price_range_for_legs(legs)
        center = 280  # average of strikes
        assert low < center < high
