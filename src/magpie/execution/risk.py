"""Pre-trade risk checks that must pass before any order is placed."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RiskCheckResult:
    passed: bool
    violations: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.passed


def check_position_size(
    trade_cost: float,
    account_equity: float,
) -> RiskCheckResult:
    """Ensure the trade cost doesn't exceed the configured max position size."""
    from magpie.config import settings

    max_allowed = account_equity * settings.magpie_max_position_pct
    if trade_cost > max_allowed:
        return RiskCheckResult(
            passed=False,
            violations=[
                f"Position cost ${trade_cost:,.2f} exceeds max allowed "
                f"${max_allowed:,.2f} ({settings.magpie_max_position_pct * 100:.0f}% of equity)"
            ],
        )
    return RiskCheckResult(passed=True)


def check_daily_loss(
    current_daily_pnl: float,
    account_equity: float,
) -> RiskCheckResult:
    """Refuse new trades if the daily loss limit has already been hit."""
    from magpie.config import settings

    max_loss = account_equity * settings.magpie_max_daily_loss_pct
    if current_daily_pnl < -abs(max_loss):
        return RiskCheckResult(
            passed=False,
            violations=[
                f"Daily loss ${abs(current_daily_pnl):,.2f} exceeds limit "
                f"${abs(max_loss):,.2f} ({settings.magpie_max_daily_loss_pct * 100:.0f}% of equity). "
                "No new trades today."
            ],
        )
    return RiskCheckResult(passed=True)


def run_all_checks(
    trade_cost: float,
    account_equity: float,
    current_daily_pnl: float = 0.0,
) -> RiskCheckResult:
    """Run all risk checks and return a combined result."""
    violations: list[str] = []

    for check_fn, kwargs in [
        (check_position_size, {"trade_cost": trade_cost, "account_equity": account_equity}),
        (check_daily_loss, {"current_daily_pnl": current_daily_pnl, "account_equity": account_equity}),
    ]:
        result = check_fn(**kwargs)  # type: ignore[call-arg]
        if not result.passed:
            violations.extend(result.violations)

    return RiskCheckResult(passed=len(violations) == 0, violations=violations)
