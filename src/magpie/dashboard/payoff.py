"""Payoff diagram math — compute theoretical P&L at expiration for option spreads."""

from __future__ import annotations

import numpy as np


def compute_payoff(
    legs: list[dict],
    underlying_prices: np.ndarray,
) -> np.ndarray:
    """
    Compute P&L at expiration for each underlying price.

    Each leg dict needs:
        option_type: "call" or "put"
        strike_price: float
        quantity: int (positive = long, negative = short)
        premium: float (price paid/received per share)

    Returns P&L array in dollars (includes the 100x multiplier).
    """
    pnl = np.zeros_like(underlying_prices, dtype=float)
    net_premium = 0.0

    for leg in legs:
        strike = float(leg["strike_price"])
        qty = int(leg["quantity"])
        premium = float(leg["premium"])

        if leg["option_type"] == "call":
            intrinsic = np.maximum(underlying_prices - strike, 0)
        else:
            intrinsic = np.maximum(strike - underlying_prices, 0)

        pnl += intrinsic * qty * 100
        net_premium += premium * qty * 100  # long = cost (positive), short = credit (negative)

    pnl -= net_premium  # subtract cost of position
    return pnl


def find_breakevens(
    legs: list[dict],
    price_low: float,
    price_high: float,
    resolution: int = 10000,
) -> list[float]:
    """Find breakeven prices where P&L crosses zero."""
    prices = np.linspace(price_low, price_high, resolution)
    pnl = compute_payoff(legs, prices)

    breakevens = []
    for i in range(1, len(pnl)):
        if pnl[i - 1] * pnl[i] < 0:  # sign change
            # Linear interpolation for more precise breakeven
            ratio = abs(pnl[i - 1]) / (abs(pnl[i - 1]) + abs(pnl[i]))
            be = prices[i - 1] + ratio * (prices[i] - prices[i - 1])
            breakevens.append(round(be, 2))
    return breakevens


def price_range_for_legs(
    legs: list[dict],
    underlying_price: float | None = None,
    margin_pct: float = 0.20,
) -> tuple[float, float]:
    """Determine a reasonable price range for the payoff chart."""
    strikes = [float(leg["strike_price"]) for leg in legs]
    center = underlying_price if underlying_price else sum(strikes) / len(strikes)
    spread = max(strikes) - min(strikes) if len(strikes) > 1 else center * 0.1
    margin = max(center * margin_pct, spread * 2)
    return round(center - margin, 2), round(center + margin, 2)
