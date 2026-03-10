"""Tests for the trading rules system: CRUD, prompt formatting, and feedback integration."""

import pytest

import magpie.db.connection as conn_mod
import magpie.tracking.rules as rules_mod
import magpie.tracking.journal as journal_mod
import magpie.analysis.feedback as feedback_mod
from magpie.tracking.rules import (
    add_rule,
    list_rules,
    deactivate_rule,
    activate_rule,
    delete_rule,
    format_rules_for_prompt,
    VALID_CATEGORIES,
)


@pytest.fixture
def _patch_db(db, monkeypatch):
    """Patch all get_connection calls to use the in-memory test DB."""
    monkeypatch.setattr(conn_mod, "get_connection", lambda: db)
    monkeypatch.setattr(rules_mod, "get_connection", lambda: db)
    monkeypatch.setattr(journal_mod, "get_connection", lambda: db)
    monkeypatch.setattr(feedback_mod, "get_connection", lambda: db)


class TestAddRule:
    def test_creates_rule(self, _patch_db):
        rule_id = add_rule("sizing", "Max 2-3 lots per spread")
        assert rule_id
        rules = list_rules()
        assert len(rules) == 1
        assert rules[0].category == "sizing"
        assert rules[0].rule == "Max 2-3 lots per spread"
        assert rules[0].active is True

    def test_rejects_invalid_category(self, _patch_db):
        with pytest.raises(ValueError, match="Category must be one of"):
            add_rule("invalid_cat", "Some rule")

    def test_accepts_all_valid_categories(self, _patch_db):
        for cat in VALID_CATEGORIES:
            rule_id = add_rule(cat, f"Rule for {cat}")
            assert rule_id

    def test_links_to_source_trade(self, _patch_db):
        from magpie.tracking.journal import create_trade

        trade_id = create_trade(
            trade_mode="paper", underlying_symbol="AAPL",
            asset_class="option", quantity=1, status="closed",
        )
        rule_id = add_rule("risk", "Close at 14 DTE", source_trade_id=trade_id)
        rules = list_rules()
        assert rules[0].source_trade_id == trade_id


class TestListRules:
    def test_filters_by_category(self, _patch_db):
        add_rule("sizing", "Rule A")
        add_rule("risk", "Rule B")
        add_rule("sizing", "Rule C")

        sizing_rules = list_rules(category="sizing")
        assert len(sizing_rules) == 2
        assert all(r.category == "sizing" for r in sizing_rules)

    def test_active_only_by_default(self, _patch_db):
        rule_id = add_rule("sizing", "Will be deactivated")
        add_rule("sizing", "Stays active")
        deactivate_rule(rule_id)

        rules = list_rules()
        assert len(rules) == 1
        assert rules[0].rule == "Stays active"

    def test_include_inactive(self, _patch_db):
        rule_id = add_rule("sizing", "Deactivated")
        add_rule("sizing", "Active")
        deactivate_rule(rule_id)

        rules = list_rules(active_only=False)
        assert len(rules) == 2


class TestDeactivateActivate:
    def test_deactivate(self, _patch_db):
        rule_id = add_rule("risk", "Close spreads at 14 DTE")
        assert deactivate_rule(rule_id) is True

        rules = list_rules(active_only=False)
        assert rules[0].active is False

    def test_reactivate(self, _patch_db):
        rule_id = add_rule("risk", "Close spreads at 14 DTE")
        deactivate_rule(rule_id)
        assert activate_rule(rule_id) is True

        rules = list_rules()
        assert len(rules) == 1
        assert rules[0].active is True

    def test_deactivate_by_prefix(self, _patch_db):
        rule_id = add_rule("risk", "Some rule")
        prefix = rule_id[:8]
        assert deactivate_rule(prefix) is True

    def test_returns_false_for_missing(self, _patch_db):
        assert deactivate_rule("nonexistent-id") is False


class TestDeleteRule:
    def test_permanent_delete(self, _patch_db):
        rule_id = add_rule("entry", "Don't fight the tape")
        assert delete_rule(rule_id) is True
        assert list_rules(active_only=False) == []

    def test_returns_false_for_missing(self, _patch_db):
        assert delete_rule("nonexistent-id") is False


class TestFormatRulesForPrompt:
    def test_empty_when_no_rules(self, _patch_db):
        assert format_rules_for_prompt() == ""

    def test_formats_by_category(self, _patch_db):
        add_rule("sizing", "Max 2-3 lots per spread")
        add_rule("risk", "Close at 14 DTE for spreads")
        add_rule("macro", "Don't load bearish after a VIX spike selloff")

        text = format_rules_for_prompt()
        assert "## Trading Rules" in text
        assert "### Sizing" in text
        assert "### Risk" in text
        assert "### Macro" in text
        assert "Max 2-3 lots" in text
        assert "Close at 14 DTE" in text

    def test_excludes_inactive(self, _patch_db):
        rule_id = add_rule("sizing", "Old rule")
        add_rule("sizing", "Active rule")
        deactivate_rule(rule_id)

        text = format_rules_for_prompt()
        assert "Old rule" not in text
        assert "Active rule" in text


class TestFeedbackIntegration:
    def test_rules_appear_in_combined_feedback(self, _patch_db, db):
        from datetime import datetime, timezone, timedelta

        add_rule("sizing", "Max 2-3 lots per spread")

        # Create a closed trade so feedback has something
        from magpie.tracking.journal import create_trade
        now = datetime.now(timezone.utc)
        trade_id = create_trade(
            trade_mode="paper", underlying_symbol="AAPL",
            asset_class="option", quantity=1, status="closed",
            entry_price=2.0, entry_time=now - timedelta(days=1),
        )
        db.execute("""
            UPDATE trade_journal
            SET exit_time = NOW(), realized_pnl = 100, realized_pnl_pct = 0.5
            WHERE id = ?
        """, [trade_id])

        combined = feedback_mod.get_combined_feedback(window_days=30)
        assert "Trading Rules" in combined["narrative"]
        assert "Max 2-3 lots" in combined["narrative"]
        assert "rules_text" in combined
