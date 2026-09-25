"""Order placement via alpaca-py. Paper trading only in Phase 1."""

from __future__ import annotations

from alpaca.trading.requests import (
    MarketOrderRequest,
    LimitOrderRequest,
    OptionLegRequest,
)
from alpaca.trading.enums import OrderClass, OrderSide, TimeInForce, OrderType

from magpie.market.client import get_trading_client


def place_single_option_order(
    contract_id: str,
    action: str,                # 'buy' | 'sell'
    quantity: int,
    limit_price: float | None = None,
) -> dict:
    """
    Place a single-leg option order.

    Returns the Alpaca order object as a dict.
    """
    client = get_trading_client()
    side = OrderSide.BUY if action.lower() == "buy" else OrderSide.SELL

    if limit_price is not None:
        request = LimitOrderRequest(
            symbol=contract_id,
            qty=quantity,
            side=side,
            time_in_force=TimeInForce.DAY,
            limit_price=limit_price,
            type=OrderType.LIMIT,
        )
    else:
        request = MarketOrderRequest(
            symbol=contract_id,
            qty=quantity,
            side=side,
            time_in_force=TimeInForce.DAY,
        )

    order = client.submit_order(request)
    return _order_to_dict(order)


def place_multileg_order(
    legs: list[dict],
    limit_price: float | None = None,
    qty: int = 1,
) -> dict:
    """
    Place a multi-leg options order (spreads, condors, etc.).

    legs format (qty is the leg's ratio within one spread, normally 1):
        [{"contract_id": "...", "action": "buy"/"sell", "qty": 1}, ...]

    qty is the number of spreads. limit_price follows Alpaca's mleg sign convention:
    positive = net debit paid, negative = net credit received — use signed_limit_price().
    A positive limit on a credit spread is a debit cap and fills like a market order.
    """
    client = get_trading_client()

    option_legs = [
        OptionLegRequest(
            symbol=leg["contract_id"],
            ratio_qty=leg.get("qty", 1),
            side=OrderSide.BUY if leg["action"].lower() == "buy" else OrderSide.SELL,
        )
        for leg in legs
    ]

    common = dict(qty=qty, order_class=OrderClass.MLEG, time_in_force=TimeInForce.DAY, legs=option_legs)
    if limit_price is not None:
        request = LimitOrderRequest(limit_price=limit_price, **common)
    else:
        request = MarketOrderRequest(**common)

    order = client.submit_order(request)
    return _order_to_dict(order)


def net_premium(legs: list[dict]) -> float:
    """Net premium per share for one lot: positive = credit received, negative = debit paid.

    Uses journal-format legs (quantity: +long / -short, premium per share).
    """
    return sum(-int(leg["quantity"]) * float(leg["premium"]) for leg in legs)


def signed_limit_price(legs: list[dict], price: float) -> float:
    """Apply Alpaca's mleg sign to a positive price magnitude: credit → negative, debit → positive."""
    magnitude = round(abs(price), 2)
    return -magnitude if net_premium(legs) > 0 else magnitude


def cancel_order(order_id: str) -> None:
    """Cancel an open order by ID."""
    client = get_trading_client()
    client.cancel_order_by_id(order_id)


def _order_to_dict(order: object) -> dict:
    """Convert an Alpaca order object to a plain dict."""
    return {
        "id": str(order.id),  # type: ignore[attr-defined]
        "status": str(order.status),  # type: ignore[attr-defined]
        "symbol": str(order.symbol),  # type: ignore[attr-defined]
        "qty": order.qty,  # type: ignore[attr-defined]
        "side": str(order.side),  # type: ignore[attr-defined]
        "filled_avg_price": float(order.filled_avg_price) if order.filled_avg_price else None,  # type: ignore[attr-defined]
        "created_at": order.created_at,  # type: ignore[attr-defined]
    }
