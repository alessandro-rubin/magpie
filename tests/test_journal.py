"""Basic smoke tests for the trade journal."""

import pytest


def test_create_and_retrieve_trade(db, monkeypatch):
    """Creating a trade and fetching it back should return matching data."""
    # Patch get_connection to use the test DB
    import magpie.tracking.journal as journal_mod
    import magpie.db.connection as conn_mod

    monkeypatch.setattr(conn_mod, "get_connection", lambda: db)
    monkeypatch.setattr(journal_mod, "get_connection", lambda: db)

    trade_id = journal_mod.create_trade(
        trade_mode="hypothetical",
        underlying_symbol="AAPL",
        asset_class="option",
        quantity=1,
        strategy_type="vertical_spread",
        entry_price=4.50,
        entry_iv=0.35,
        entry_delta=0.40,
        dte_at_entry=30,
    )

    assert trade_id  # UUID was generated

    trade = journal_mod.get_trade(trade_id)
    assert trade is not None
    assert trade.underlying_symbol == "AAPL"
    assert trade.trade_mode == "hypothetical"
    assert trade.entry_price == pytest.approx(4.50)
    assert trade.entry_delta == pytest.approx(0.40)
    assert trade.dte_at_entry == 30


def test_trade_rationale(db, monkeypatch):
    """Entry and exit rationale should be stored and retrieved."""
    import magpie.tracking.journal as journal_mod

    monkeypatch.setattr(journal_mod, "get_connection", lambda: db)

    trade_id = journal_mod.create_trade(
        trade_mode="paper",
        underlying_symbol="AAPL",
        asset_class="option",
        quantity=10,
        status="open",
        strategy_type="vertical_spread",
        entry_rationale="Rolled up from $270/$280 to $275/$285 after AAPL rallied +2.2%.",
    )

    trade = journal_mod.get_trade(trade_id)
    assert trade is not None
    assert trade.entry_rationale == "Rolled up from $270/$280 to $275/$285 after AAPL rallied +2.2%."
    assert trade.exit_rationale is None

    journal_mod.update_trade_status(
        trade_id,
        status="closed",
        exit_price=6.50,
        exit_reason="target_hit",
        exit_rationale="Spread hit 80% of max profit with 10 DTE; closing to lock in gains.",
    )

    trade = journal_mod.get_trade(trade_id)
    assert trade.status == "closed"
    assert trade.exit_rationale == "Spread hit 80% of max profit with 10 DTE; closing to lock in gains."


def test_list_trades_filter(db, monkeypatch):
    """Filtering by status and symbol should work correctly."""
    import magpie.tracking.journal as journal_mod

    monkeypatch.setattr(journal_mod, "get_connection", lambda: db)

    journal_mod.create_trade("paper", "AAPL", "option", 1, status="open")
    journal_mod.create_trade("hypothetical", "TSLA", "option", 2, status="closed")

    open_trades = journal_mod.list_trades(status="open")
    assert len(open_trades) == 1
    assert open_trades[0].underlying_symbol == "AAPL"

    tsla_trades = journal_mod.list_trades(symbol="TSLA")
    assert len(tsla_trades) == 1
    assert tsla_trades[0].trade_mode == "hypothetical"
