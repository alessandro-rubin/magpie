"""
Compute past prediction accuracy from the DB and format it for prompt injection.

This is the self-correction engine: every LLM prompt gets a summary of how
well previous recommendations performed under similar conditions.
"""

from __future__ import annotations

from magpie.db.connection import get_connection


def compute_accuracy_stats(
    symbol: str | None = None,
    window_days: int = 30,
    strategy_type: str | None = None,
) -> dict:
    """
    Query llm_analyses joined with trade_journal to compute rolling accuracy stats.

    Returns a dict with win_rate, avg_return, best/worst strategy, and a narrative.
    Returns an empty dict if there is no history.
    """
    conn = get_connection()

    filters = [f"a.created_at >= NOW() - INTERVAL {int(window_days)} DAY", "a.was_correct IS NOT NULL"]
    params: list = []

    if symbol:
        filters.append("a.underlying_symbol = ?")
        params.append(symbol)
    if strategy_type:
        filters.append("a.strategy_suggested = ?")
        params.append(strategy_type)

    where = " AND ".join(filters)

    rows = conn.execute(
        f"""
        SELECT
            a.was_correct,
            t.realized_pnl_pct,
            a.strategy_suggested,
            t.exit_time,
            t.entry_time
        FROM llm_analyses a
        LEFT JOIN trade_journal t ON a.linked_trade_id = t.id
        WHERE {where}
        """,
        params,
    ).fetchall()

    if not rows:
        return {}

    total = len(rows)
    wins = sum(1 for r in rows if r[0] is True)
    losses = sum(1 for r in rows if r[0] is False)
    win_rate = wins / total if total > 0 else 0

    returns = [r[1] for r in rows if r[1] is not None]
    avg_return = sum(returns) / len(returns) if returns else None

    # Days held
    days_held = []
    for r in rows:
        if r[3] and r[4]:
            try:
                delta = (r[3] - r[4]).days
                if delta >= 0:
                    days_held.append(delta)
            except Exception:
                pass
    avg_days = sum(days_held) / len(days_held) if days_held else None

    # Best/worst strategy
    strategy_stats: dict[str, dict] = {}
    for r in rows:
        strat = r[2] or "unknown"
        if strat not in strategy_stats:
            strategy_stats[strat] = {"wins": 0, "total": 0}
        strategy_stats[strat]["total"] += 1
        if r[0] is True:
            strategy_stats[strat]["wins"] += 1

    best_strategy = None
    worst_strategy = None
    if strategy_stats:
        ranked = sorted(
            strategy_stats.items(),
            key=lambda x: x[1]["wins"] / x[1]["total"] if x[1]["total"] > 0 else 0,
        )
        worst_strategy = ranked[0][0] if ranked else None
        best_strategy = ranked[-1][0] if ranked else None

    stats = {
        "window_days": window_days,
        "symbol": symbol,
        "total_analyses": total,
        "entered_trades": len([r for r in rows if r[1] is not None]),
        "wins": wins,
        "losses": losses,
        "win_rate": win_rate,
        "avg_return_pct": avg_return,
        "avg_days_held": avg_days,
        "best_strategy": best_strategy,
        "worst_strategy": worst_strategy,
    }

    stats["narrative"] = _build_narrative(stats, symbol)
    return stats


def format_feedback_for_prompt(stats: dict) -> dict:
    """Return feedback dict ready for prompt injection (includes narrative key)."""
    if not stats:
        return {}
    return stats


def _build_narrative(stats: dict, symbol: str | None) -> str:
    """Build a human-readable performance summary for prompt injection."""
    sym = symbol or "all symbols"
    win_rate_pct = stats["win_rate"] * 100
    total = stats["total_analyses"]
    wins = stats["wins"]
    avg_ret = stats.get("avg_return_pct")
    avg_days = stats.get("avg_days_held")
    best = stats.get("best_strategy")
    worst = stats.get("worst_strategy")

    parts = [
        f"In the last {stats['window_days']} days on {sym}: "
        f"{wins}/{total} recommendations were profitable "
        f"({win_rate_pct:.0f}% win rate)."
    ]

    if avg_ret is not None:
        parts.append(f"Average return on entered trades: {avg_ret * 100:+.1f}%.")

    if avg_days is not None:
        parts.append(f"Average hold time: {avg_days:.0f} days.")

    if best and best != worst:
        best_stats = None  # Could be enriched
        parts.append(f"Best performing strategy: {best}.")

    if worst and worst != best:
        parts.append(f"Worst performing strategy: {worst} — consider reducing position size or avoiding.")

    if win_rate_pct < 40:
        parts.append("Overall win rate is below 40% — be more selective and consider tightening criteria.")
    elif win_rate_pct >= 70:
        parts.append("Win rate is strong — current strategy approach is working well.")

    return " ".join(parts)


def upsert_prediction_accuracy(
    window_days: int = 30,
    symbol: str | None = None,
    strategy_type: str | None = None,
) -> None:
    """Refresh the prediction_accuracy table with the latest computed stats."""
    stats = compute_accuracy_stats(
        symbol=symbol, window_days=window_days, strategy_type=strategy_type
    )
    if not stats:
        return

    from magpie.config import settings
    from magpie.analysis.prompts import PROMPT_VERSION

    conn = get_connection()
    conn.execute(
        """
        INSERT INTO prediction_accuracy (
            computed_at, window_days, underlying_symbol, strategy_type,
            prompt_version, model,
            total_analyses, entered_trades, wins, losses,
            win_rate, avg_return_pct, avg_days_held, total_pnl
        ) VALUES (NOW(), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
        """,
        [
            window_days,
            symbol,
            strategy_type,
            PROMPT_VERSION,
            settings.anthropic_model,
            stats["total_analyses"],
            stats["entered_trades"],
            stats["wins"],
            stats["losses"],
            stats["win_rate"],
            stats.get("avg_return_pct"),
            stats.get("avg_days_held"),
        ],
    )
