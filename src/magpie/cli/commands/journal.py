"""magpie journal — view and manage the trade journal."""

from __future__ import annotations

from typing import Optional

import typer

from magpie.cli.display import console, format_currency, format_pct, make_table, pnl_style

app = typer.Typer(no_args_is_help=True)


@app.command("list")
def list_trades(
    status: Optional[str] = typer.Option(None, "--status", "-s", help="Filter by status."),
    symbol: Optional[str] = typer.Option(None, "--symbol", help="Filter by underlying symbol."),
    mode: Optional[str] = typer.Option(None, "--mode", "-m", help="'paper' or 'hypothetical'."),
    limit: int = typer.Option(20, "--limit", "-n", help="Max rows to show."),
) -> None:
    """List trade journal entries."""
    from magpie.tracking.journal import list_trades as _list

    trades = _list(status=status, symbol=symbol.upper() if symbol else None, mode=mode, limit=limit)

    if not trades:
        console.print("[dim]No trades found.[/dim]")
        return

    table = make_table(
        "Trade Journal",
        "ID", "Symbol", "Mode", "Strategy", "Status", "Entry", "P&L", "P&L %",
    )
    for t in trades:
        style = pnl_style(t.realized_pnl or 0)
        table.add_row(
            t.id[:8],
            t.underlying_symbol,
            t.trade_mode,
            t.strategy_type or "—",
            t.status,
            format_currency(t.entry_price),
            f"[{style}]{format_currency(t.realized_pnl)}[/{style}]",
            f"[{style}]{format_pct(t.realized_pnl_pct)}[/{style}]",
        )
    console.print(table)


@app.command("show")
def show_trade(trade_id: str = typer.Argument(..., help="Trade ID (or prefix).")) -> None:
    """Show full details for a single trade."""
    from magpie.tracking.journal import get_trade

    trade = get_trade(trade_id)
    if trade is None:
        console.print(f"[error]Trade '{trade_id}' not found.[/error]")
        raise typer.Exit(1)

    from rich.panel import Panel
    from rich.table import Table

    table = Table.grid(padding=(0, 2))
    table.add_column(style="dim")
    table.add_column()

    rows = [
        ("ID", trade.id),
        ("Symbol", trade.underlying_symbol),
        ("Mode", trade.trade_mode),
        ("Status", trade.status),
        ("Strategy", trade.strategy_type or "—"),
        ("Entry Price", format_currency(trade.entry_price)),
        ("Exit Price", format_currency(trade.exit_price)),
        ("Quantity", str(trade.quantity)),
        ("Realized P&L", format_currency(trade.realized_pnl)),
        ("Realized P&L %", format_pct(trade.realized_pnl_pct)),
        ("Entry IV", f"{(trade.entry_iv or 0) * 100:.1f}%" if trade.entry_iv else "—"),
        ("Entry Delta", f"{trade.entry_delta:.3f}" if trade.entry_delta else "—"),
        ("DTE at Entry", str(trade.dte_at_entry) if trade.dte_at_entry else "—"),
        ("Max Profit", format_currency(trade.max_profit)),
        ("Max Loss", format_currency(trade.max_loss)),
        ("Notes", trade.notes or "—"),
    ]
    for label, value in rows:
        table.add_row(label, value)

    console.print(Panel(table, title=f"[bold]Trade {trade.id[:8]}[/bold]", expand=False))
