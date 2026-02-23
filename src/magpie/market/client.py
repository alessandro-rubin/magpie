"""Alpaca-py client factory — cached singleton instances."""

from __future__ import annotations

from alpaca.trading.client import TradingClient
from alpaca.data.historical import StockHistoricalDataClient, OptionHistoricalDataClient

_trading: TradingClient | None = None
_stock_data: StockHistoricalDataClient | None = None
_option_data: OptionHistoricalDataClient | None = None


def _get_keys() -> tuple[str, str]:
    from magpie.config import settings

    return settings.alpaca_api_key, settings.alpaca_secret_key


def get_trading_client() -> TradingClient:
    global _trading
    if _trading is None:
        api_key, secret_key = _get_keys()
        from magpie.config import settings

        _trading = TradingClient(
            api_key=api_key,
            secret_key=secret_key,
            paper=settings.alpaca_paper,
        )
    return _trading


def get_stock_data_client() -> StockHistoricalDataClient:
    global _stock_data
    if _stock_data is None:
        api_key, secret_key = _get_keys()
        _stock_data = StockHistoricalDataClient(api_key=api_key, secret_key=secret_key)
    return _stock_data


def get_option_data_client() -> OptionHistoricalDataClient:
    global _option_data
    if _option_data is None:
        api_key, secret_key = _get_keys()
        _option_data = OptionHistoricalDataClient(api_key=api_key, secret_key=secret_key)
    return _option_data
