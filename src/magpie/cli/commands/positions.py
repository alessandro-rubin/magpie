"""magpie positions — view and sync Alpaca paper positions."""

from __future__ import annotations

import typer

from magpie.cli.display import console, format_currency, format_pct, make_table, pnl_style

app = typer.Typer()


@app.callback(invoke_without_command=True)
def show(
    ctx: typer.Context,
    sync: bool = typer.Option(False, "--sync", help="Sync from Alpaca before displaying."),
) -> None:
    """Display current open positions."""
    if ctx.invoked_subcommand is not None:
        return

    if sync:
        console.print("[info]Syncing positions from Alpaca...[/info]")
        from magpie.tracking.positions import sync_from_alpaca

        sync_from_alpaca()
        console.print("[success]Sync complete.[/success]")

    from magpie.tracking.journal import list_trades

    open_trades = list_trades(status="open")

    if not open_trades:
        console.print("[dim]No open positions.[/dim]")
        return

    table = make_table(
        "Open Positions",
        "Symbol", "Strategy", "Mode", "Qty", "Entry", "Unrealized P&L", "Delta", "DTE",
    )
    for t in open_trades:
        style = pnl_style(t.unrealized_pnl or 0)
        table.add_row(
            t.underlying_symbol,
            t.strategy_type or "—",
            t.trade_mode,
            str(t.quantity),
            format_currency(t.entry_price),
            f"[{style}]{format_currency(t.unrealized_pnl)}[/{style}]",
            f"{t.entry_delta:.3f}" if t.entry_delta else "—",
            str(t.dte_at_entry) if t.dte_at_entry else "—",
        )
    console.print(table)
