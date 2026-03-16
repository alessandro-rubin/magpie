"""Tests for pre-trade risk checks (execution/risk.py)."""

from unittest.mock import patch

from magpie.execution.risk import (
    RiskCheckResult,
    check_daily_loss,
    check_position_size,
    run_all_checks,
)


class _MockSettings:
    """Minimal settings mock for risk check tests."""

    def __init__(self, max_position_pct=0.10, max_daily_loss_pct=0.02):
        self.magpie_max_position_pct = max_position_pct
        self.magpie_max_daily_loss_pct = max_daily_loss_pct


SETTINGS_PATH = "magpie.execution.risk.settings"


# ── check_position_size ──────────────────────────────────────────────────


@patch("magpie.config.settings", _MockSettings(max_position_pct=0.10))
def test_position_size_under_limit():
    result = check_position_size(trade_cost=5_000, account_equity=100_000)
    assert result.passed
    assert result.violations == []


@patch("magpie.config.settings", _MockSettings(max_position_pct=0.10))
def test_position_size_at_limit():
    result = check_position_size(trade_cost=10_000, account_equity=100_000)
    assert result.passed


@patch("magpie.config.settings", _MockSettings(max_position_pct=0.10))
def test_position_size_over_limit():
    result = check_position_size(trade_cost=15_000, account_equity=100_000)
    assert not result.passed
    assert len(result.violations) == 1
    assert "exceeds max" in result.violations[0].lower()


@patch("magpie.config.settings", _MockSettings(max_position_pct=0.05))
def test_position_size_custom_limit():
    result = check_position_size(trade_cost=6_000, account_equity=100_000)
    assert not result.passed  # 6k > 5k (5% of 100k)


# ── check_daily_loss ─────────────────────────────────────────────────────


@patch("magpie.config.settings", _MockSettings(max_daily_loss_pct=0.02))
def test_daily_loss_within_limit():
    result = check_daily_loss(current_daily_pnl=-1_000, account_equity=100_000)
    assert result.passed


@patch("magpie.config.settings", _MockSettings(max_daily_loss_pct=0.02))
def test_daily_loss_exceeded():
    result = check_daily_loss(current_daily_pnl=-3_000, account_equity=100_000)
    assert not result.passed
    assert "daily loss" in result.violations[0].lower()


@patch("magpie.config.settings", _MockSettings(max_daily_loss_pct=0.02))
def test_daily_loss_positive_pnl():
    """Positive daily P&L should always pass."""
    result = check_daily_loss(current_daily_pnl=500, account_equity=100_000)
    assert result.passed


@patch("magpie.config.settings", _MockSettings(max_daily_loss_pct=0.02))
def test_daily_loss_zero_pnl():
    result = check_daily_loss(current_daily_pnl=0, account_equity=100_000)
    assert result.passed


# ── run_all_checks ───────────────────────────────────────────────────────


@patch("magpie.config.settings", _MockSettings(max_position_pct=0.10, max_daily_loss_pct=0.02))
def test_all_checks_pass():
    result = run_all_checks(trade_cost=5_000, account_equity=100_000, current_daily_pnl=-500)
    assert result.passed
    assert result.violations == []


@patch("magpie.config.settings", _MockSettings(max_position_pct=0.10, max_daily_loss_pct=0.02))
def test_all_checks_position_fails():
    result = run_all_checks(trade_cost=20_000, account_equity=100_000, current_daily_pnl=0)
    assert not result.passed
    assert len(result.violations) == 1


@patch("magpie.config.settings", _MockSettings(max_position_pct=0.10, max_daily_loss_pct=0.02))
def test_all_checks_both_fail():
    result = run_all_checks(trade_cost=20_000, account_equity=100_000, current_daily_pnl=-5_000)
    assert not result.passed
    assert len(result.violations) == 2


def test_risk_check_result_bool():
    assert bool(RiskCheckResult(passed=True)) is True
    assert bool(RiskCheckResult(passed=False, violations=["test"])) is False
