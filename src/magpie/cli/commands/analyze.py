"""magpie analyze — LLM analysis for a given symbol."""

from __future__ import annotations

import typer

from magpie.cli.display import console, print_error, print_warning

app = typer.Typer(no_args_is_help=True)


@app.command()
def run(
    symbol: str = typer.Argument(..., help="Ticker symbol to analyze (e.g. AAPL)."),
    hypothetical: bool = typer.Option(
        False, "--hypothetical", "-h", help="Log as hypothetical trade only; do not place order."
    ),
    context_only: bool = typer.Option(
        False, "--context", "-c",
        help="Print the formatted market context and prompt text without calling the LLM.",
    ),
) -> None:
    """Build market context for SYMBOL and run LLM analysis.

    If ANTHROPIC_API_KEY is not set, prints the formatted prompt for use
    in Claude Code (paste it into the chat alongside the Alpaca MCP server).
    """
    symbol = symbol.upper()
    console.print(f"[info]Fetching market data for[/info] [bold]{symbol}[/bold]...")

    try:
        from magpie.market.snapshots import build_analysis_context
        from magpie.analysis.llm import AnthropicKeyMissing, build_prompt, run_analysis

        context = build_analysis_context(symbol)

        if context_only:
            prompt = build_prompt(symbol, context)
            _display_prompt(symbol, prompt)
            return

        try:
            analysis = run_analysis(symbol, context, hypothetical_only=hypothetical)
            _display_analysis(analysis)
        except AnthropicKeyMissing:
            print_warning(
                "ANTHROPIC_API_KEY is not set — printing prompt for use in Claude Code instead."
            )
            console.print(
                "\n[dim]Copy the prompt below and paste it into Claude Code. "
                "The Alpaca MCP server is already connected, so Claude can also "
                "look up live data directly.[/dim]\n"
            )
            prompt = build_prompt(symbol, context)
            _display_prompt(symbol, prompt)

    except Exception as exc:
        print_error(str(exc))
        raise typer.Exit(1) from exc


def _display_prompt(symbol: str, prompt: str) -> None:
    """Display the formatted analysis prompt in a scrollable panel."""
    from rich.panel import Panel
    from rich.syntax import Syntax

    console.print(
        Panel(
            prompt,
            title=f"[bold]{symbol}[/bold] — Analysis Prompt (paste into Claude Code)",
            border_style="dim",
            expand=False,
        )
    )


def _display_analysis(analysis: object) -> None:
    """Display an LLMAnalysis in a Rich panel."""
    from rich.panel import Panel
    from rich.table import Table

    a = analysis  # type: ignore[assignment]

    rec_style = {
        "enter": "bold green",
        "avoid": "bold red",
        "exit": "bold yellow",
        "hold": "dim white",
        "reduce": "yellow",
    }.get(getattr(a, "recommendation", "") or "", "white")

    table = Table.grid(padding=(0, 2))
    table.add_column(style="dim")
    table.add_column()

    rows = [
        ("Recommendation", f"[{rec_style}]{(a.recommendation or '—').upper()}[/{rec_style}]"),
        ("Strategy", a.strategy_suggested or "—"),
        ("Confidence", f"{(a.confidence_score or 0) * 100:.0f}%"),
        ("Entry", f"${a.suggested_entry:.2f}" if a.suggested_entry else "—"),
        ("Stop", f"${a.suggested_stop:.2f}" if a.suggested_stop else "—"),
        ("Target", f"${a.suggested_target:.2f}" if a.suggested_target else "—"),
        ("Reasoning", a.reasoning_summary or "—"),
    ]
    for label, value in rows:
        table.add_row(label, value)

    console.print(Panel(table, title=f"[bold]{a.underlying_symbol}[/bold] — LLM Analysis", expand=False))
