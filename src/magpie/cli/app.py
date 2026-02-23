"""Magpie CLI root application."""

from __future__ import annotations

import typer
from rich import print as rprint

from magpie import __version__
from magpie.cli.display import console

app = typer.Typer(
    name="magpie",
    help="LLM-powered options trading system using Alpaca paper trading.",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)


def _init_db() -> None:
    """Run migrations on startup (lazy import to keep --help fast)."""
    from magpie.db.connection import get_connection

    get_connection()


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: bool = typer.Option(False, "--version", "-v", help="Show version and exit."),
) -> None:
    if version:
        rprint(f"magpie [bold]{__version__}[/bold]")
        raise typer.Exit()

    if ctx.invoked_subcommand is not None:
        _init_db()


# ── Sub-command groups ──────────────────────────────────────────────────────

from magpie.cli.commands import analyze, journal, positions, report  # noqa: E402

app.add_typer(analyze.app, name="analyze", help="LLM analysis of a symbol.")
app.add_typer(journal.app, name="journal", help="View and manage the trade journal.")
app.add_typer(positions.app, name="positions", help="View and sync Alpaca positions.")
app.add_typer(report.app, name="report", help="P&L and LLM accuracy reports.")


if __name__ == "__main__":
    app()
