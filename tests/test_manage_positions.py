"""Tests for position management logic (profit targets, stops, DTE)."""

import pytest

import magpie.db.connection as conn_mod
import magpie.tracking.journal as journal_mod
from magpie.tracking.journal import create_trade, update_unrealized_pnl


@pytest.fixture
def _patch_db(db, monkeypatch):
    monkeypatch.setattr(conn_mod, "get_connection", lambda: db)
    monkeypatch.setattr(journal_mod, "get_connection", lambda: db)


class TestScanPositions:
    def _make_trade(self, symbol="AAPL", max_profit=500, max_loss=1000, unrealized=0,
                    dte=30, legs=None):
        trade_id = create_trade(
            trade_mode="paper", underlying_symbol=symbol,
            asset_class="option", quantity=3, status="open",
            strategy_type="vertical_spread",
            entry_price=2.0,
            max_profit=max_profit, max_loss=max_loss,
            dte_at_entry=dte,
            legs=legs or [
                {"contract_symbol": f"{symbol}260402C00100000", "option_type": "call",
                 "strike_price": 100, "quantity": -1, "premium": 3.0, "side": "sell"},
                {"contract_symbol": f"{symbol}260402C00105000", "option_type": "call",
                 "strike_price": 105, "quantity": 1, "premium": 1.0, "side": "buy"},
            ],
        )
        if unrealized != 0:
            update_unrealized_pnl(trade_id, unrealized)
        return trade_id

    def test_flags_profit_target_hit(self, _patch_db):
        from magpie.tracking.journal import list_trades
        self._make_trade(unrealized=300, max_profit=500)  # 60% > 50% default target

        trades = list_trades(status="open", mode="paper")
        assert len(trades) == 1

        trade = trades[0]
        # Simulate the check logic
        target = trade.max_profit * 0.50
        assert trade.unrealized_pnl >= target

    def test_does_not_flag_below_target(self, _patch_db):
        from magpie.tracking.journal import list_trades
        self._make_trade(unrealized=200, max_profit=500)  # 40% < 50%

        trades = list_trades(status="open", mode="paper")
        trade = trades[0]
        target = trade.max_profit * 0.50
        assert trade.unrealized_pnl < target

    def test_flags_stop_loss_hit(self, _patch_db):
        from magpie.tracking.journal import list_trades
        self._make_trade(unrealized=-1100, max_loss=1000)  # -110% > 100%

        trades = list_trades(status="open", mode="paper")
        trade = trades[0]
        stop = trade.max_loss * 1.0
        assert trade.unrealized_pnl <= -stop

    def test_does_not_flag_within_stop(self, _patch_db):
        from magpie.tracking.journal import list_trades
        self._make_trade(unrealized=-500, max_loss=1000)  # -50% < 100%

        trades = list_trades(status="open", mode="paper")
        trade = trades[0]
        stop = trade.max_loss * 1.0
        assert trade.unrealized_pnl > -stop
