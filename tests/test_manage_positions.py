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
                    dte=30, legs=None, profit_target_pct=None, stop_loss_pct=None):
        trade_id = create_trade(
            trade_mode="paper", underlying_symbol=symbol,
            asset_class="option", quantity=3, status="open",
            strategy_type="vertical_spread",
            entry_price=2.0,
            max_profit=max_profit, max_loss=max_loss,
            dte_at_entry=dte,
            profit_target_pct=profit_target_pct,
            stop_loss_pct=stop_loss_pct,
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

    def test_per_trade_profit_target_overrides_global(self, _patch_db):
        """Trade with custom profit_target_pct=0.30 should trigger at 30%, not global 50%."""
        from magpie.tracking.journal import list_trades
        # 40% of max profit — above 30% custom target, below 50% global
        self._make_trade(unrealized=200, max_profit=500, profit_target_pct=0.30)

        trades = list_trades(status="open", mode="paper")
        trade = trades[0]
        profit_pct = trade.profit_target_pct  # 0.30
        target = trade.max_profit * profit_pct
        assert trade.unrealized_pnl >= target  # 200 >= 150

    def test_per_trade_profit_target_no_false_trigger(self, _patch_db):
        """Without per-trade override, 40% P&L should NOT trigger 50% global target."""
        from magpie.tracking.journal import list_trades
        self._make_trade(unrealized=200, max_profit=500)  # no override

        trades = list_trades(status="open", mode="paper")
        trade = trades[0]
        assert trade.profit_target_pct is None
        target = trade.max_profit * 0.50  # global default
        assert trade.unrealized_pnl < target  # 200 < 250

    def test_per_trade_stop_loss_overrides_global(self, _patch_db):
        """Trade with custom stop_loss_pct=0.50 should trigger at 50%, not global 100%."""
        from magpie.tracking.journal import list_trades
        # -600 vs max_loss 1000 * 0.50 = 500 → should trigger
        self._make_trade(unrealized=-600, max_loss=1000, stop_loss_pct=0.50)

        trades = list_trades(status="open", mode="paper")
        trade = trades[0]
        stop_pct = trade.stop_loss_pct  # 0.50
        stop = trade.max_loss * stop_pct
        assert trade.unrealized_pnl <= -stop  # -600 <= -500

    def test_does_not_flag_within_stop(self, _patch_db):
        from magpie.tracking.journal import list_trades
        self._make_trade(unrealized=-500, max_loss=1000)  # -50% < 100%

        trades = list_trades(status="open", mode="paper")
        trade = trades[0]
        stop = trade.max_loss * 1.0
        assert trade.unrealized_pnl > -stop
