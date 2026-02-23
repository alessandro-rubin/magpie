"""Human-in-the-loop review gate. Nothing executes without passing through here."""

from __future__ import annotations

from enum import Enum
from typing import Literal

import typer
from rich.panel import Panel
from rich.table import Table

from magpie.cli.display import console, format_currency, format_pct
from magpie.db.models import LLMAnalysis


class ReviewDecision(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"
    HYPOTHETICAL = "hypothetical"


def present_and_confirm(
    analysis: LLMAnalysis,
    account_equity: float,
    daily_pnl: float = 0.0,
    risk_violations: list[str] | None = None,
) -> ReviewDecision:
    """
    Display a Rich panel summarizing the LLM recommendation and ask for confirmation.

    Returns the user's decision: approve, reject, or log as hypothetical only.
    """
    _display_panel(analysis, account_equity, daily_pnl, risk_violations or [])

    if risk_violations:
        console.print(
            "\n[bold red]Risk check FAILED.[/bold red] You can still log this as hypothetical."
        )

    choice = typer.prompt(
        "\nDecision",
        type=typer.Choice(["approve", "reject", "hypothetical"], case_sensitive=False),
        default="hypothetical",
        show_choices=True,
    )
    return ReviewDecision(choice.lower())


def _display_panel(
    analysis: LLMAnalysis,
    account_equity: float,
    daily_pnl: float,
    risk_violations: list[str],
) -> None:
    rec = (analysis.recommendation or "—").upper()
    rec_style = {
        "ENTER": "bold green",
        "AVOID": "bold red",
        "EXIT": "bold yellow",
        "HOLD": "dim white",
        "REDUCE": "yellow",
    }.get(rec, "white")

    table = Table.grid(padding=(0, 2))
    table.add_column(style="dim", min_width=20)
    table.add_column()

    rows = [
        ("Symbol", analysis.underlying_symbol),
        ("Recommendation", f"[{rec_style}]{rec}[/{rec_style}]"),
        ("Strategy", analysis.strategy_suggested or "—"),
        ("Confidence", f"{(analysis.confidence_score or 0) * 100:.0f}%"),
        ("Entry Price", format_currency(analysis.suggested_entry)),
        ("Stop Loss", format_currency(analysis.suggested_stop)),
        ("Target", format_currency(analysis.suggested_target)),
        ("", ""),
        ("Account Equity", format_currency(account_equity)),
        ("Today's P&L", format_pct(daily_pnl / account_equity if account_equity else None)),
        ("", ""),
        ("Reasoning", analysis.reasoning_summary or "—"),
    ]

    for label, value in rows:
        table.add_row(label, value)

    if risk_violations:
        table.add_row("", "")
        for v in risk_violations:
            table.add_row("[bold red]RISK[/bold red]", v)

    console.print(Panel(table, title="[bold]Trade Review[/bold]", border_style="blue"))
