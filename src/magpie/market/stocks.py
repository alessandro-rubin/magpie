"""Stock market data fetching via alpaca-py."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from alpaca.data.enums import DataFeed
from alpaca.data.requests import StockBarsRequest, StockLatestQuoteRequest, StockSnapshotRequest
from alpaca.data.timeframe import TimeFrame
from tenacity import retry, stop_after_attempt, wait_exponential

from magpie.market.client import get_stock_data_client


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def get_latest_quote(symbol: str) -> dict:
    """Return the latest bid/ask quote for a symbol."""
    client = get_stock_data_client()
    request = StockLatestQuoteRequest(symbol_or_symbols=symbol, feed=DataFeed.IEX)
    response = client.get_stock_latest_quote(request)
    quote = response[symbol]
    return {
        "symbol": symbol,
        "bid": float(quote.bid_price or 0),
        "ask": float(quote.ask_price or 0),
        "mid": (float(quote.bid_price or 0) + float(quote.ask_price or 0)) / 2,
        "timestamp": quote.timestamp,
    }


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def get_snapshot(symbol: str) -> dict:
    """Return a full snapshot (price, volume, VWAP, daily change) for a symbol."""
    client = get_stock_data_client()
    request = StockSnapshotRequest(symbol_or_symbols=symbol, feed=DataFeed.IEX)
    response = client.get_stock_snapshot(request)
    snap = response[symbol]

    daily = snap.daily_bar
    prev = snap.previous_daily_bar
    latest = snap.latest_trade

    prev_close = float(prev.close) if prev else None
    current_price = float(latest.price) if latest else (float(daily.close) if daily else None)
    change_pct = None
    if current_price and prev_close and prev_close != 0:
        change_pct = (current_price - prev_close) / prev_close

    return {
        "symbol": symbol,
        "price": current_price,
        "prev_close": prev_close,
        "change_pct": change_pct,
        "volume": int(daily.volume) if daily else None,
        "vwap": float(daily.vwap) if daily and daily.vwap else None,
        "open": float(daily.open) if daily else None,
        "high": float(daily.high) if daily else None,
        "low": float(daily.low) if daily else None,
    }


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def get_bars(symbol: str, days: int = 30, timeframe: TimeFrame = TimeFrame.Day) -> list[dict]:
    """Return historical OHLCV bars for a symbol."""
    client = get_stock_data_client()
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days + 5)  # +5 buffer for weekends/holidays

    request = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=timeframe,
        start=start,
        end=end,
        limit=days,
        feed=DataFeed.IEX,
    )
    response = client.get_stock_bars(request)
    bars = response[symbol]

    return [
        {
            "timestamp": bar.timestamp,
            "open": float(bar.open),
            "high": float(bar.high),
            "low": float(bar.low),
            "close": float(bar.close),
            "volume": int(bar.volume),
            "vwap": float(bar.vwap) if bar.vwap else None,
        }
        for bar in bars
    ]


def compute_52w_range(bars: list[dict]) -> tuple[float | None, float | None]:
    """Return (52-week low, 52-week high) from a list of bars."""
    if not bars:
        return None, None
    highs = [b["high"] for b in bars if b.get("high")]
    lows = [b["low"] for b in bars if b.get("low")]
    return (min(lows) if lows else None, max(highs) if highs else None)
