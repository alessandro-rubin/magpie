"""Shared Rich display helpers used across CLI commands."""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.theme import Theme

THEME = Theme(
    {
        "info": "cyan",
        "warning": "yellow",
        "error": "bold red",
        "success": "bold green",
        "profit": "green",
        "loss": "red",
        "neutral": "dim white",
        "header": "bold blue",
    }
)

console = Console(theme=THEME)


def print_error(message: str) -> None:
    console.print(f"[error]Error:[/error] {message}")


def print_success(message: str) -> None:
    console.print(f"[success]{message}[/success]")


def print_warning(message: str) -> None:
    console.print(f"[warning]Warning:[/warning] {message}")


def pnl_style(value: float) -> str:
    """Return Rich markup color for a P&L value."""
    if value > 0:
        return "profit"
    if value < 0:
        return "loss"
    return "neutral"


def format_pct(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value * 100:+.2f}%"


def format_currency(value: float | None) -> str:
    if value is None:
        return "—"
    return f"${value:,.2f}"


def make_table(title: str, *columns: str) -> Table:
    """Create a pre-styled Rich table."""
    table = Table(title=title, header_style="header", show_lines=True)
    for col in columns:
        table.add_column(col)
    return table


def banner(text: str) -> Panel:
    """Create a titled panel banner."""
    return Panel(text, style="header", expand=False)
