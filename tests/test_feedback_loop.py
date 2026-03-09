"""Tests for the feedback loop: outcome marking, trade performance, and combined feedback."""

from datetime import datetime, timezone, timedelta

import pytest

import magpie.db.connection as conn_mod
import magpie.tracking.journal as journal_mod
import magpie.tracking.positions as pos_mod
import magpie.analysis.feedback as feedback_mod
from magpie.tracking.journal import (
    create_trade,
    find_linked_analyses,
    find_unlinked_analysis,
)


@pytest.fixture
def _patch_db(db, monkeypatch):
    """Patch all get_connection calls to use the in-memory test DB."""
    monkeypatch.setattr(conn_mod, "get_connection", lambda: db)
    monkeypatch.setattr(journal_mod, "get_connection", lambda: db)
    monkeypatch.setattr(feedback_mod, "get_connection", lambda: db)


def _create_analysis(db, analysis_id, symbol, linked_trade_id=None, was_correct=None):
    """Insert a test llm_analyses record."""
    db.execute(
        """
        INSERT INTO llm_analyses (
            id, created_at, underlying_symbol, analysis_type,
            model, prompt_version, context_snapshot, raw_response,
            linked_trade_id, was_correct
        ) VALUES (?, NOW(), ?, 'entry_recommendation', 'test', 'v1.1', '{}', 'test', ?, ?)
        """,
        [analysis_id, symbol, linked_trade_id, was_correct],
    )


class TestFindLinkedAnalyses:
    def test_finds_linked(self, _patch_db, db):
        trade_id = create_trade(
            trade_mode="paper", underlying_symbol="AAPL",
            asset_class="option", quantity=1, status="open",
        )
        _create_analysis(db, "a1", "AAPL", linked_trade_id=trade_id)

        result = find_linked_analyses(trade_id)
        assert len(result) == 1
        assert result[0]["id"] == "a1"

    def test_returns_empty_when_no_links(self, _patch_db, db):
        trade_id = create_trade(
            trade_mode="paper", underlying_symbol="AAPL",
            asset_class="option", quantity=1, status="open",
        )
        assert find_linked_analyses(trade_id) == []


class TestFindUnlinkedAnalysis:
    def test_finds_recent_unlinked(self, _patch_db, db):
        _create_analysis(db, "a1", "AAPL")
        result = find_unlinked_analysis("AAPL")
        assert result == "a1"

    def test_returns_none_when_all_linked(self, _patch_db, db):
        _create_analysis(db, "a1", "AAPL", linked_trade_id="some-trade")
        assert find_unlinked_analysis("AAPL") is None

    def test_returns_none_for_different_symbol(self, _patch_db, db):
        _create_analysis(db, "a1", "NVDA")
        assert find_unlinked_analysis("AAPL") is None


class TestAutoCloseMarksOutcome:
    """Test that _auto_close() marks linked analyses with outcomes."""

    def test_marks_winner(self, _patch_db, db, monkeypatch):
        from dataclasses import dataclass

        @dataclass
        class FakePosition:
            symbol: str
            qty: str
            avg_entry_price: str
            unrealized_pl: str

        class FakeTradingClient:
            def get_all_positions(self):
                return []

        monkeypatch.setattr(pos_mod, "get_trading_client", lambda: FakeTradingClient())

        trade_id = create_trade(
            trade_mode="paper", underlying_symbol="TSLA",
            asset_class="option", quantity=1, status="open",
            entry_price=3.0,
            legs=[{"contract_symbol": "TSLA260320P00400000", "quantity": 1}],
        )

        # Set positive unrealized P&L
        journal_mod.update_unrealized_pnl(trade_id, 500.0)

        # Link an analysis
        _create_analysis(db, "a-win", "TSLA", linked_trade_id=trade_id)

        # Run sync — trade legs are gone so it should auto-close
        pos_mod.sync_from_alpaca()

        # Verify analysis was marked correct
        row = db.execute(
            "SELECT was_correct, outcome_notes FROM llm_analyses WHERE id = 'a-win'"
        ).fetchone()
        assert row[0] is True
        assert "Auto-marked" in row[1]

    def test_marks_loser(self, _patch_db, db, monkeypatch):
        from dataclasses import dataclass

        @dataclass
        class FakePosition:
            symbol: str
            qty: str
            avg_entry_price: str
            unrealized_pl: str

        class FakeTradingClient:
            def get_all_positions(self):
                return []

        monkeypatch.setattr(pos_mod, "get_trading_client", lambda: FakeTradingClient())

        trade_id = create_trade(
            trade_mode="paper", underlying_symbol="NVDA",
            asset_class="option", quantity=1, status="open",
            entry_price=4.0,
            legs=[{"contract_symbol": "NVDA260320C00195000", "quantity": 1}],
        )

        journal_mod.update_unrealized_pnl(trade_id, -300.0)
        _create_analysis(db, "a-loss", "NVDA", linked_trade_id=trade_id)

        pos_mod.sync_from_alpaca()

        row = db.execute(
            "SELECT was_correct, outcome_notes FROM llm_analyses WHERE id = 'a-loss'"
        ).fetchone()
        assert row[0] is False

    def test_no_crash_without_linked_analyses(self, _patch_db, db, monkeypatch):
        """Auto-close should work fine even when no analyses are linked."""
        from dataclasses import dataclass

        @dataclass
        class FakePosition:
            symbol: str
            qty: str
            avg_entry_price: str
            unrealized_pl: str

        class FakeTradingClient:
            def get_all_positions(self):
                return []

        monkeypatch.setattr(pos_mod, "get_trading_client", lambda: FakeTradingClient())

        trade_id = create_trade(
            trade_mode="paper", underlying_symbol="XOM",
            asset_class="option", quantity=1, status="open",
            entry_price=2.0,
            legs=[{"contract_symbol": "XOM260402C00155000", "quantity": -1}],
        )
        journal_mod.update_unrealized_pnl(trade_id, 100.0)

        # Should not raise
        pos_mod.sync_from_alpaca()

        trade = journal_mod.get_trade(trade_id)
        assert trade.status == "closed"


class TestComputeTradePerformance:
    def test_computes_from_closed_trades(self, _patch_db, db):
        now = datetime.now(timezone.utc)
        create_trade(
            trade_mode="paper", underlying_symbol="AAPL",
            asset_class="option", quantity=10, status="closed",
            strategy_type="vertical_spread",
            entry_price=3.70, entry_time=now - timedelta(days=5),
        )
        # Set exit data
        db.execute("""
            UPDATE trade_journal
            SET exit_time = NOW(), realized_pnl = -3320, realized_pnl_pct = -0.897
            WHERE underlying_symbol = 'AAPL'
        """)

        create_trade(
            trade_mode="paper", underlying_symbol="XOM",
            asset_class="option", quantity=4, status="closed",
            strategy_type="vertical_spread",
            entry_price=1.60, entry_time=now - timedelta(days=3),
        )
        db.execute("""
            UPDATE trade_journal
            SET exit_time = NOW(), realized_pnl = 200, realized_pnl_pct = 0.312
            WHERE underlying_symbol = 'XOM'
        """)

        stats = feedback_mod.compute_trade_performance(window_days=30)
        assert stats["total_trades"] == 2
        assert stats["wins"] == 1
        assert stats["losses"] == 1
        assert stats["win_rate"] == 0.5
        assert stats["source"] == "trade_journal"
        assert "narrative" in stats

    def test_returns_empty_when_no_trades(self, _patch_db, db):
        stats = feedback_mod.compute_trade_performance(window_days=30)
        assert stats == {}

    def test_filters_by_symbol(self, _patch_db, db):
        now = datetime.now(timezone.utc)
        for sym, pnl in [("AAPL", -100), ("NVDA", 200)]:
            create_trade(
                trade_mode="paper", underlying_symbol=sym,
                asset_class="option", quantity=1, status="closed",
                entry_price=1.0, entry_time=now - timedelta(days=2),
            )
            db.execute(f"""
                UPDATE trade_journal
                SET exit_time = NOW(), realized_pnl = {pnl}, realized_pnl_pct = {pnl/100}
                WHERE underlying_symbol = '{sym}'
            """)

        stats = feedback_mod.compute_trade_performance(symbol="NVDA", window_days=30)
        assert stats["total_trades"] == 1
        assert stats["wins"] == 1


class TestCombinedFeedback:
    def test_merges_both_sources(self, _patch_db, db):
        now = datetime.now(timezone.utc)

        # Create a closed trade
        trade_id = create_trade(
            trade_mode="paper", underlying_symbol="AAPL",
            asset_class="option", quantity=1, status="closed",
            entry_price=2.0, entry_time=now - timedelta(days=3),
        )
        db.execute("""
            UPDATE trade_journal
            SET exit_time = NOW(), realized_pnl = 150, realized_pnl_pct = 0.75
            WHERE id = ?
        """, [trade_id])

        # Create a linked analysis with outcome
        _create_analysis(db, "a-combined", "AAPL", linked_trade_id=trade_id, was_correct=True)

        combined = feedback_mod.get_combined_feedback(window_days=30)
        assert "narrative" in combined
        assert "[LLM Analysis Track Record]" in combined["narrative"]
        assert "[Trade Performance]" in combined["narrative"]

    def test_works_without_analyses(self, _patch_db, db):
        now = datetime.now(timezone.utc)
        trade_id = create_trade(
            trade_mode="paper", underlying_symbol="SPY",
            asset_class="option", quantity=2, status="closed",
            entry_price=4.0, entry_time=now - timedelta(days=1),
        )
        db.execute("""
            UPDATE trade_journal
            SET exit_time = NOW(), realized_pnl = -200, realized_pnl_pct = -0.25
            WHERE id = ?
        """, [trade_id])

        combined = feedback_mod.get_combined_feedback(window_days=30)
        assert combined != {}
        assert "[Trade Performance]" in combined["narrative"]
        # No LLM section
        assert "[LLM Analysis Track Record]" not in combined["narrative"]
