"""magpie positions — view, sync, and manage Alpaca paper positions."""

from __future__ import annotations

import typer

from magpie.cli.display import console, format_currency, make_table, pnl_style

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


@app.command()
def sync(
    snapshot: bool = typer.Option(True, help="Also save a portfolio equity snapshot."),
) -> None:
    """Sync positions from Alpaca and update the trade journal."""
    from magpie.tracking.positions import sync_from_alpaca, sync_portfolio_snapshot

    console.print("[bold]Syncing positions from Alpaca...[/bold]")
    result = sync_from_alpaca()
    console.print(
        f"  Updated: {result['updated']} | "
        f"Auto-closed: {result['auto_closed']} | "
        f"Imported: {result['imported']}"
    )

    if snapshot:
        sync_portfolio_snapshot()
        console.print("  Portfolio snapshot saved.")

    console.print("[success]Sync complete.[/success]")


@app.command()
def manage(
    execute: bool = typer.Option(False, "--execute", help="Actually close positions (default: dry-run)."),
    sync_first: bool = typer.Option(True, "--sync/--no-sync", help="Sync from Alpaca first."),
) -> None:
    """Scan open positions for profit targets, stop losses, and DTE limits."""
    from datetime import date

    from magpie.config import settings
    from magpie.market.occ import parse_occ
    from magpie.tracking.journal import list_trades, update_trade_status
    from magpie.tracking.positions import _mark_analysis_outcomes

    if sync_first:
        from magpie.tracking.positions import sync_from_alpaca

        console.print("[dim]Syncing positions...[/dim]")
        sync_from_alpaca()

    console.print(
        f"[bold]Position Management[/bold] "
        f"(target: {settings.magpie_profit_target_pct*100:.0f}% profit, "
        f"stop: {settings.magpie_stop_loss_pct*100:.0f}% loss, "
        f"min DTE: {settings.magpie_min_dte_close})"
    )

    open_trades = list_trades(status="open", mode="paper")
    actions: list[dict] = []

    for trade in open_trades:
        unrealized = trade.unrealized_pnl
        # Compute current DTE from OCC symbol
        current_dte = trade.dte_at_entry
        if trade.legs:
            for leg in trade.legs:
                try:
                    parsed = parse_occ(leg.get("contract_symbol", ""))
                    current_dte = (parsed.expiry - date.today()).days
                    break
                except Exception:
                    continue

        # Profit target
        if trade.max_profit and unrealized is not None:
            target = trade.max_profit * settings.magpie_profit_target_pct
            if unrealized >= target:
                actions.append({
                    "trade": trade, "action": "close_profit", "reason": "target_hit",
                    "details": f"P&L ${unrealized:+,.0f} >= {settings.magpie_profit_target_pct*100:.0f}% of max ${trade.max_profit:,.0f}",
                })
                continue

        # Stop loss
        if trade.max_loss and unrealized is not None:
            stop = trade.max_loss * settings.magpie_stop_loss_pct
            if unrealized <= -stop:
                actions.append({
                    "trade": trade, "action": "close_stop", "reason": "stop_loss",
                    "details": f"P&L ${unrealized:+,.0f} hit stop -${stop:,.0f}",
                })
                continue

        # DTE
        if current_dte is not None and current_dte <= settings.magpie_min_dte_close:
            actions.append({
                "trade": trade, "action": "close_dte", "reason": "low_dte",
                "details": f"DTE={current_dte} <= {settings.magpie_min_dte_close} (gamma risk)",
            })

    if not actions:
        console.print("[dim]No positions need attention.[/dim]")
        return

    action_table = make_table("Position Alerts", "Symbol", "Action", "Details")
    styles = {"close_profit": "green", "close_stop": "red", "close_dte": "yellow"}
    for a in actions:
        s = styles.get(a["action"], "white")
        action_table.add_row(a["trade"].underlying_symbol, f"[{s}]{a['action']}[/{s}]", a["details"])
    console.print(action_table)

    if execute:
        from datetime import datetime, timezone

        for a in actions:
            t = a["trade"]
            realized_pnl = t.unrealized_pnl
            realized_pnl_pct = None
            exit_price = None
            if realized_pnl is not None and t.entry_price and t.quantity:
                cost = t.entry_price * t.quantity * 100
                if cost != 0:
                    realized_pnl_pct = realized_pnl / cost
                exit_price = t.entry_price + realized_pnl / (t.quantity * 100)

            update_trade_status(
                t.id, status="closed", exit_price=exit_price,
                exit_time=datetime.now(timezone.utc),
                exit_reason=a["reason"], realized_pnl=realized_pnl,
                realized_pnl_pct=realized_pnl_pct,
                exit_rationale=f"Auto-managed: {a['details']}",
            )
            _mark_analysis_outcomes(t.id, realized_pnl)
            console.print(f"  [bold]Closed[/bold] {t.underlying_symbol} ({a['reason']})")

        console.print("\n[yellow]NOTE: Close Alpaca positions separately via MCP or API.[/yellow]")
    else:
        console.print(f"\n[dim]{len(actions)} action(s). Run with --execute to close.[/dim]")
