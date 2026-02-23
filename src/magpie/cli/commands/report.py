"""magpie report — P&L summary and LLM accuracy statistics."""

from __future__ import annotations

from typing import Optional

import typer

from magpie.cli.display import console, format_currency, format_pct, make_table

app = typer.Typer()


@app.callback(invoke_without_command=True)
def summary(
    ctx: typer.Context,
    symbol: Optional[str] = typer.Option(None, "--symbol", help="Filter by symbol."),
    window: int = typer.Option(30, "--window", "-w", help="Rolling window in days."),
) -> None:
    """Show P&L summary and LLM prediction accuracy."""
    if ctx.invoked_subcommand is not None:
        return

    from magpie.analysis.feedback import compute_accuracy_stats
    from magpie.tracking.pnl import get_pnl_summary

    sym = symbol.upper() if symbol else None

    console.rule("[header]P&L Summary[/header]")
    pnl = get_pnl_summary(symbol=sym, window_days=window)
    _print_pnl(pnl)

    console.rule("[header]LLM Prediction Accuracy[/header]")
    stats = compute_accuracy_stats(symbol=sym, window_days=window)
    _print_accuracy(stats)


def _print_pnl(pnl: dict) -> None:
    table = make_table(f"P&L ({pnl.get('window_days', '?')}d)", "Metric", "Value")
    table.add_row("Total Realized P&L", format_currency(pnl.get("total_realized_pnl")))
    table.add_row("Closed Trades", str(pnl.get("closed_trades", 0)))
    table.add_row("Winning Trades", str(pnl.get("wins", 0)))
    table.add_row("Losing Trades", str(pnl.get("losses", 0)))
    table.add_row("Win Rate", format_pct(pnl.get("win_rate")))
    table.add_row("Avg Return", format_pct(pnl.get("avg_return_pct")))
    console.print(table)


def _print_accuracy(stats: dict) -> None:
    if not stats.get("total_analyses"):
        console.print("[dim]No LLM analysis history yet.[/dim]")
        return

    table = make_table(f"LLM Accuracy ({stats.get('window_days', '?')}d)", "Metric", "Value")
    table.add_row("Analyses Run", str(stats.get("total_analyses", 0)))
    table.add_row("Trades Entered", str(stats.get("entered_trades", 0)))
    table.add_row("Wins", str(stats.get("wins", 0)))
    table.add_row("Losses", str(stats.get("losses", 0)))
    table.add_row("Win Rate", format_pct(stats.get("win_rate")))
    table.add_row("Avg Return", format_pct(stats.get("avg_return_pct")))
    table.add_row("Best Strategy", stats.get("best_strategy") or "—")
    console.print(table)
