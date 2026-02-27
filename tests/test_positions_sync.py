"""Tests for Alpaca positions sync."""

from dataclasses import dataclass

import pytest

import magpie.db.connection as conn_mod
import magpie.tracking.journal as journal_mod
import magpie.tracking.positions as pos_mod


@dataclass
class FakePosition:
    symbol: str
    qty: str
    avg_entry_price: str
    unrealized_pl: str
    asset_class: str = "us_option"


class FakeTradingClient:
    def __init__(self, positions: list[FakePosition]):
        self._positions = positions

    def get_all_positions(self) -> list[FakePosition]:
        return self._positions


@pytest.fixture
def _patch_db(db, monkeypatch):
    """Patch all get_connection calls to use the in-memory test DB."""
    monkeypatch.setattr(conn_mod, "get_connection", lambda: db)
    monkeypatch.setattr(journal_mod, "get_connection", lambda: db)


def _patch_alpaca(monkeypatch, positions: list[FakePosition]):
    monkeypatch.setattr(pos_mod, "get_trading_client", lambda: FakeTradingClient(positions))


class TestSyncMatchesByContract:
    def test_spread_pnl_aggregated(self, _patch_db, monkeypatch):
        """Sync should match legs by contract_symbol and aggregate P&L."""
        trade_id = journal_mod.create_trade(
            trade_mode="paper",
            underlying_symbol="AAPL",
            asset_class="option",
            quantity=10,
            status="open",
            legs=[
                {"contract_symbol": "AAPL260320C00275000", "option_type": "call",
                 "strike_price": 275, "quantity": 10, "premium": 5.85},
                {"contract_symbol": "AAPL260320C00285000", "option_type": "call",
                 "strike_price": 285, "quantity": -10, "premium": 2.15},
            ],
        )

        _patch_alpaca(monkeypatch, [
            FakePosition("AAPL260320C00275000", "10", "5.85", "-2850.00"),
            FakePosition("AAPL260320C00285000", "-10", "2.15", "1290.00"),
        ])

        result = pos_mod.sync_from_alpaca()
        assert result["updated"] == 1
        assert result["auto_closed"] == 0
        assert result["imported"] == 0

        trade = journal_mod.get_trade(trade_id)
        assert trade.unrealized_pnl == pytest.approx(-1560.0)

    def test_single_leg_match(self, _patch_db, monkeypatch):
        """Single-leg trades should also match by contract_symbol."""
        trade_id = journal_mod.create_trade(
            trade_mode="paper",
            underlying_symbol="AAPL",
            asset_class="option",
            quantity=5,
            status="open",
            legs=[
                {"contract_symbol": "AAPL260320C00275000", "option_type": "call",
                 "strike_price": 275, "quantity": 5, "premium": 5.85},
            ],
        )

        _patch_alpaca(monkeypatch, [
            FakePosition("AAPL260320C00275000", "5", "5.85", "250.00"),
        ])

        result = pos_mod.sync_from_alpaca()
        assert result["updated"] == 1

        trade = journal_mod.get_trade(trade_id)
        assert trade.unrealized_pnl == pytest.approx(250.0)


class TestSyncAutoClose:
    def test_closes_when_gone(self, _patch_db, monkeypatch):
        """Trades whose legs are all gone from Alpaca should be auto-closed."""
        trade_id = journal_mod.create_trade(
            trade_mode="paper",
            underlying_symbol="AAPL",
            asset_class="option",
            quantity=1,
            status="open",
            legs=[
                {"contract_symbol": "AAPL260320C00275000", "option_type": "call",
                 "strike_price": 275, "quantity": 1, "premium": 5.85},
            ],
        )

        _patch_alpaca(monkeypatch, [])  # All positions gone

        result = pos_mod.sync_from_alpaca()
        assert result["auto_closed"] == 1

        trade = journal_mod.get_trade(trade_id)
        assert trade.status == "closed"
        assert trade.exit_reason == "auto_detected_close"


class TestSyncImport:
    def test_imports_vertical_spread(self, _patch_db, monkeypatch):
        """Unmatched options on same underlying+expiry should import as one spread."""
        _patch_alpaca(monkeypatch, [
            FakePosition("AAPL260320C00275000", "10", "5.85", "-2850.00"),
            FakePosition("AAPL260320C00285000", "-10", "2.15", "1290.00"),
        ])

        result = pos_mod.sync_from_alpaca()
        assert result["imported"] == 1

        trades = journal_mod.list_trades(status="open")
        assert len(trades) == 1
        assert trades[0].underlying_symbol == "AAPL"
        assert trades[0].strategy_type == "vertical_spread"
        assert len(trades[0].legs) == 2

    def test_imports_single_leg(self, _patch_db, monkeypatch):
        """Single unmatched option should import as long/short call/put."""
        _patch_alpaca(monkeypatch, [
            FakePosition("TSLA260320P00400000", "3", "17.45", "-570.00"),
        ])

        result = pos_mod.sync_from_alpaca()
        assert result["imported"] == 1

        trades = journal_mod.list_trades(status="open")
        assert len(trades) == 1
        assert trades[0].underlying_symbol == "TSLA"
        assert trades[0].strategy_type == "long_put"

    def test_imports_stock_position(self, _patch_db, monkeypatch):
        """Stock positions (non-OCC symbols) should import individually."""
        _patch_alpaca(monkeypatch, [
            FakePosition("AAPL", "50", "180.00", "500.00", asset_class="us_equity"),
        ])

        result = pos_mod.sync_from_alpaca()
        assert result["imported"] == 1

        trades = journal_mod.list_trades(status="open")
        assert len(trades) == 1
        assert trades[0].asset_class == "stock"
        assert trades[0].underlying_symbol == "AAPL"

    def test_groups_by_underlying_and_expiry(self, _patch_db, monkeypatch):
        """Options on different underlyings should create separate trades."""
        _patch_alpaca(monkeypatch, [
            FakePosition("AAPL260320C00275000", "10", "5.85", "100.00"),
            FakePosition("NVDA260320C00195000", "10", "8.90", "-200.00"),
        ])

        result = pos_mod.sync_from_alpaca()
        assert result["imported"] == 2

        trades = journal_mod.list_trades(status="open")
        assert len(trades) == 2
        symbols = {t.underlying_symbol for t in trades}
        assert symbols == {"AAPL", "NVDA"}
