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

    filters = [f"a.created_at >= datetime('now', '-{int(window_days)} days')", "a.was_correct IS NOT NULL"]
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
            t.entry_time,
            COALESCE(t.entry_rationale, a.reasoning_summary) AS rationale,
            t.exit_rationale
        FROM llm_analyses a
        LEFT JOIN trade_journal t ON a.linked_trade_id = t.id
        WHERE {where}
        """,
        params,
    ).fetchall()

    if not rows:
        return {}

    total = len(rows)
    wins = sum(1 for r in rows if r[0])
    losses = sum(1 for r in rows if not r[0])
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
        if r[0]:
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
        parts.append(f"Best performing strategy: {best}.")

    if worst and worst != best:
        parts.append(f"Worst performing strategy: {worst} — consider reducing position size or avoiding.")

    if win_rate_pct < 40:
        parts.append("Overall win rate is below 40% — be more selective and consider tightening criteria.")
    elif win_rate_pct >= 70:
        parts.append("Win rate is strong — current strategy approach is working well.")

    return " ".join(parts)


def compute_trade_performance(
    symbol: str | None = None,
    window_days: int = 30,
    strategy_type: str | None = None,
) -> dict:
    """Compute performance stats directly from trade_journal (no llm_analyses needed).

    This is the primary feedback source when using Claude Code interactively
    (no ANTHROPIC_API_KEY), since trades are placed via MCP without llm_analyses records.
    """
    conn = get_connection()

    filters = [
        f"exit_time >= datetime('now', '-{int(window_days)} days')",
        "status = 'closed'",
        "realized_pnl IS NOT NULL",
    ]
    params: list = []

    if symbol:
        filters.append("underlying_symbol = ?")
        params.append(symbol)
    if strategy_type:
        filters.append("strategy_type = ?")
        params.append(strategy_type)

    where = " AND ".join(filters)

    rows = conn.execute(
        f"""
        SELECT
            CAST(realized_pnl AS REAL) AS realized_pnl,
            CAST(realized_pnl_pct AS REAL) AS realized_pnl_pct,
            strategy_type,
            exit_time,
            entry_time,
            underlying_symbol,
            COALESCE(entry_rationale, '') AS rationale,
            exit_rationale,
            exit_reason
        FROM trade_journal
        WHERE {where}
        ORDER BY exit_time ASC
        """,
        params,
    ).fetchall()

    if not rows:
        return {}

    total = len(rows)
    wins = sum(1 for r in rows if r[0] > 0)
    losses = total - wins
    win_rate = wins / total if total > 0 else 0

    returns = [r[1] for r in rows if r[1] is not None]
    avg_return = sum(returns) / len(returns) if returns else None

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

    # Strategy breakdown
    strategy_stats: dict[str, dict] = {}
    for r in rows:
        strat = r[2] or "unknown"
        if strat not in strategy_stats:
            strategy_stats[strat] = {"wins": 0, "total": 0, "returns": []}
        strategy_stats[strat]["total"] += 1
        if r[0] > 0:
            strategy_stats[strat]["wins"] += 1
        if r[1] is not None:
            strategy_stats[strat]["returns"].append(r[1])

    best_strategy = None
    worst_strategy = None
    if strategy_stats:
        ranked = sorted(
            strategy_stats.items(),
            key=lambda x: x[1]["wins"] / x[1]["total"] if x[1]["total"] > 0 else 0,
        )
        worst_strategy = ranked[0][0] if ranked else None
        best_strategy = ranked[-1][0] if ranked else None

    # Per-symbol breakdown for richer feedback
    symbol_stats: dict[str, dict] = {}
    for r in rows:
        sym = r[5]
        if sym not in symbol_stats:
            symbol_stats[sym] = {"wins": 0, "total": 0, "total_pnl": 0.0}
        symbol_stats[sym]["total"] += 1
        if r[0] > 0:
            symbol_stats[sym]["wins"] += 1
        symbol_stats[sym]["total_pnl"] += r[0]

    # Recent losing pattern detection
    recent_losers = [r for r in rows[-5:] if r[0] <= 0]
    losing_streak = len(recent_losers) >= 3

    total_pnl = sum(r[0] for r in rows)

    stats = {
        "window_days": window_days,
        "symbol": symbol,
        "source": "trade_journal",
        "total_trades": total,
        "wins": wins,
        "losses": losses,
        "win_rate": win_rate,
        "avg_return_pct": avg_return,
        "avg_days_held": avg_days,
        "total_pnl": total_pnl,
        "best_strategy": best_strategy,
        "worst_strategy": worst_strategy,
        "symbol_stats": symbol_stats,
        "losing_streak": losing_streak,
    }

    stats["narrative"] = _build_trade_narrative(stats, symbol)
    return stats


def _build_trade_narrative(stats: dict, symbol: str | None) -> str:
    """Build a performance narrative from trade_journal data."""
    sym = symbol or "all symbols"
    win_rate_pct = stats["win_rate"] * 100
    total = stats["total_trades"]
    wins = stats["wins"]
    total_pnl = stats["total_pnl"]
    avg_ret = stats.get("avg_return_pct")

    parts = [
        f"In the last {stats['window_days']} days on {sym}: "
        f"{wins}/{total} trades were profitable "
        f"({win_rate_pct:.0f}% win rate). "
        f"Total P&L: ${total_pnl:+,.0f}."
    ]

    if avg_ret is not None:
        parts.append(f"Average return per trade: {avg_ret * 100:+.1f}%.")

    # Symbol-specific insights
    sym_stats = stats.get("symbol_stats", {})
    for s, ss in sym_stats.items():
        if ss["total"] >= 2:
            parts.append(f"{s}: {ss['wins']}/{ss['total']} wins (${ss['total_pnl']:+,.0f}).")

    best = stats.get("best_strategy")
    worst = stats.get("worst_strategy")
    if best and best != worst:
        parts.append(f"Best strategy: {best}.")
    if worst and worst != best:
        parts.append(f"Worst strategy: {worst} — reduce exposure or avoid.")

    if stats.get("losing_streak"):
        parts.append("WARNING: 3+ of last 5 trades were losers — tighten entry criteria and reduce position size.")

    if win_rate_pct < 40:
        parts.append("Overall win rate below 40% — be more selective.")
    elif win_rate_pct >= 70:
        parts.append("Win rate strong — current approach is working.")

    return " ".join(parts)


def get_combined_feedback(
    symbol: str | None = None,
    window_days: int = 30,
) -> dict:
    """Get the best available feedback: llm_analyses if available, trade_journal always.

    Merges both sources into a single feedback dict for prompt injection.
    """
    analysis_stats = compute_accuracy_stats(symbol=symbol, window_days=window_days)
    trade_stats = compute_trade_performance(symbol=symbol, window_days=window_days)

    if not analysis_stats and not trade_stats:
        return {}

    # Build combined narrative
    narratives = []
    if analysis_stats and analysis_stats.get("narrative"):
        narratives.append(f"[LLM Analysis Track Record] {analysis_stats['narrative']}")
    if trade_stats and trade_stats.get("narrative"):
        narratives.append(f"[Trade Performance] {trade_stats['narrative']}")

    combined = {
        "window_days": window_days,
        "symbol": symbol,
        "narrative": "\n\n".join(narratives) if narratives else "",
    }

    # Merge stats, preferring trade data for counts
    if trade_stats:
        combined["win_rate"] = trade_stats["win_rate"]
        combined["total_pnl"] = trade_stats.get("total_pnl")
        combined["avg_return_pct"] = trade_stats.get("avg_return_pct")
        combined["losing_streak"] = trade_stats.get("losing_streak", False)
    if analysis_stats:
        combined["llm_win_rate"] = analysis_stats.get("win_rate")
        combined["best_strategy"] = analysis_stats.get("best_strategy")
        combined["worst_strategy"] = analysis_stats.get("worst_strategy")

    # Inject trading rules
    from magpie.tracking.rules import format_rules_for_prompt

    rules_text = format_rules_for_prompt()
    if rules_text:
        combined["rules_text"] = rules_text
        narratives.append(rules_text)

    # Inject trading notes (persistent memory)
    from magpie.tracking.notes import format_notes_for_prompt

    notes_text = format_notes_for_prompt()
    if notes_text:
        combined["notes_text"] = notes_text
        narratives.append(notes_text)

    combined["narrative"] = "\n\n".join(narratives) if narratives else ""

    return combined


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
        ) VALUES (datetime('now'), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
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
    conn.commit()
