"""Options market data fetching via alpaca-py."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from alpaca.data.requests import (
    OptionChainRequest,
    OptionSnapshotRequest,
)
from tenacity import retry, stop_after_attempt, wait_exponential

from magpie.db.models import OptionContract, OptionSnapshot
from magpie.market.client import get_option_data_client


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def get_option_chain(
    symbol: str,
    dte_min: int = 7,
    dte_max: int = 60,
    option_type: str | None = None,         # 'call' | 'put' | None (both)
    strike_count: int = 10,                  # strikes above/below ATM to include
) -> list[dict]:
    """
    Return option chain contracts for a symbol filtered by DTE range.

    Returns a list of contract dicts with snapshot data (Greeks, IV, prices).
    """
    client = get_option_data_client()

    today = date.today()
    expiry_start = today + timedelta(days=dte_min)
    expiry_end = today + timedelta(days=dte_max)

    request = OptionChainRequest(
        underlying_symbol=symbol,
        expiration_date_gte=expiry_start,
        expiration_date_lte=expiry_end,
        type=option_type,
        limit=strike_count * 2 * 4,        # rough upper bound
    )

    response = client.get_option_chain(request)

    contracts = []
    for contract_symbol, snapshot in response.items():
        greeks = snapshot.greeks if hasattr(snapshot, "greeks") else None
        latest_quote = snapshot.latest_quote if hasattr(snapshot, "latest_quote") else None
        latest_trade = snapshot.latest_trade if hasattr(snapshot, "latest_trade") else None

        bid = float(latest_quote.bid_price) if latest_quote and latest_quote.bid_price else None
        ask = float(latest_quote.ask_price) if latest_quote and latest_quote.ask_price else None
        mid = ((bid + ask) / 2) if bid is not None and ask is not None else None
        last = float(latest_trade.price) if latest_trade and latest_trade.price else None

        open_interest = getattr(snapshot, "open_interest", None)

        contracts.append({
            "contract_id": contract_symbol,
            "underlying_symbol": symbol,
            # Greeks
            "implied_volatility": float(snapshot.implied_volatility) if snapshot.implied_volatility else None,
            "delta": float(greeks.delta) if greeks and greeks.delta else None,
            "gamma": float(greeks.gamma) if greeks and greeks.gamma else None,
            "theta": float(greeks.theta) if greeks and greeks.theta else None,
            "vega": float(greeks.vega) if greeks and greeks.vega else None,
            "rho": float(greeks.rho) if greeks and greeks.rho else None,
            # Prices
            "bid": bid,
            "ask": ask,
            "mid": mid,
            "last_price": last,
            "open_interest": int(open_interest) if open_interest else None,
        })

    return contracts


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def get_option_snapshot(contract_id: str) -> dict | None:
    """Return a single contract snapshot with Greeks and current prices."""
    client = get_option_data_client()
    request = OptionSnapshotRequest(symbol_or_symbols=contract_id)
    response = client.get_option_snapshot(request)

    if contract_id not in response:
        return None

    snapshot = response[contract_id]
    greeks = snapshot.greeks if hasattr(snapshot, "greeks") else None
    latest_quote = snapshot.latest_quote if hasattr(snapshot, "latest_quote") else None
    latest_trade = snapshot.latest_trade if hasattr(snapshot, "latest_trade") else None

    bid = float(latest_quote.bid_price) if latest_quote and latest_quote.bid_price else None
    ask = float(latest_quote.ask_price) if latest_quote and latest_quote.ask_price else None

    open_interest = getattr(snapshot, "open_interest", None)

    return {
        "contract_id": contract_id,
        "bid": bid,
        "ask": ask,
        "mid": ((bid + ask) / 2) if bid is not None and ask is not None else None,
        "last_price": float(latest_trade.price) if latest_trade and latest_trade.price else None,
        "open_interest": int(open_interest) if open_interest else None,
        "implied_volatility": float(snapshot.implied_volatility) if snapshot.implied_volatility else None,
        "delta": float(greeks.delta) if greeks and greeks.delta else None,
        "gamma": float(greeks.gamma) if greeks and greeks.gamma else None,
        "theta": float(greeks.theta) if greeks and greeks.theta else None,
        "vega": float(greeks.vega) if greeks and greeks.vega else None,
        "rho": float(greeks.rho) if greeks and greeks.rho else None,
    }


def save_snapshot_to_db(snapshot: dict, underlying_price: float | None = None) -> None:
    """Persist an option snapshot dict to the option_snapshots table."""
    from magpie.db.connection import get_connection

    conn = get_connection()
    now = datetime.now(timezone.utc)

    conn.execute(
        """
        INSERT INTO option_snapshots (
            contract_id, snapshot_time, bid, ask, mid, last_price, open_interest,
            implied_volatility, delta, gamma, theta, vega, rho,
            underlying_price, data_source
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            snapshot.get("contract_id"),
            now,
            snapshot.get("bid"),
            snapshot.get("ask"),
            snapshot.get("mid"),
            snapshot.get("last_price"),
            snapshot.get("open_interest"),
            snapshot.get("implied_volatility"),
            snapshot.get("delta"),
            snapshot.get("gamma"),
            snapshot.get("theta"),
            snapshot.get("vega"),
            snapshot.get("rho"),
            underlying_price,
            snapshot.get("data_source", "alpaca_py"),
        ],
    )


def filter_by_delta(
    contracts: list[dict],
    delta_min: float = 0.20,
    delta_max: float = 0.50,
    option_type: str = "call",
) -> list[dict]:
    """Filter contracts to a target delta range (useful for spread leg selection)."""
    result = []
    for c in contracts:
        delta = c.get("delta")
        if delta is None:
            continue
        # Puts have negative delta — compare absolute value
        abs_delta = abs(delta)
        if option_type == "put" and delta > 0:
            continue
        if option_type == "call" and delta < 0:
            continue
        if delta_min <= abs_delta <= delta_max:
            result.append(c)
    return result
