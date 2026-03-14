"""CLI commands for the autonomous agent loop and pending trade approvals."""

from __future__ import annotations

import typer
from rich.table import Table

from magpie.cli.display import console

app = typer.Typer(no_args_is_help=True)


@app.command("pending")
def list_pending() -> None:
    """List trades awaiting human approval."""
    from magpie.db.connection import get_connection

    conn = get_connection()
    rows = conn.execute(
        """
        SELECT id, underlying_symbol, strategy_type, entry_price, quantity,
               entry_time, notes, entry_rationale
        FROM trade_journal
        WHERE status = 'pending_approval'
        ORDER BY entry_time DESC
        """
    ).fetchall()

    if not rows:
        console.print("[dim]No pending trades.[/dim]")
        return

    table = Table(title="Pending Approval Trades", show_lines=True)
    table.add_column("ID (prefix)", style="cyan", no_wrap=True)
    table.add_column("Symbol", style="bold")
    table.add_column("Strategy")
    table.add_column("Entry Price", justify="right")
    table.add_column("Qty", justify="right")
    table.add_column("Time")
    table.add_column("Reason / Rationale")

    for row in rows:
        trade_id, symbol, strategy, price, qty, entry_time, notes, rationale = row
        reason = notes or rationale or ""
        table.add_row(
            trade_id[:8],
            symbol,
            strategy or "—",
            f"${price:.2f}" if price else "—",
            str(qty),
            str(entry_time)[:16] if entry_time else "—",
            reason[:80],
        )

    console.print(table)
    console.print("\n[dim]Use [bold]magpie agent approve <id>[/bold] or [bold]reject <id>[/bold][/dim]")


@app.command("approve")
def approve_trade(
    trade_id: str = typer.Argument(help="Trade ID or prefix to approve"),
    limit_price: float | None = typer.Option(None, "--limit", "-l", help="Optional limit price for the order"),
) -> None:
    """Approve a pending trade and place the order via Alpaca."""
    from magpie.db.connection import get_connection
    from magpie.execution.orders import place_multileg_order, place_single_option_order
    from magpie.tracking.journal import update_trade_status
    import json

    conn = get_connection()
    row = conn.execute(
        """
        SELECT id, underlying_symbol, strategy_type, legs, quantity, entry_price
        FROM trade_journal
        WHERE (id = ? OR id LIKE ?) AND status = 'pending_approval'
        LIMIT 1
        """,
        [trade_id, f"{trade_id}%"],
    ).fetchone()

    if not row:
        console.print(f"[red]No pending trade found with ID starting with '{trade_id}'[/red]")
        raise typer.Exit(1)

    full_id, symbol, strategy, legs_json, quantity, entry_price = row
    legs = json.loads(legs_json) if legs_json else []

    price = limit_price or entry_price
    console.print(f"Placing order for [bold]{symbol}[/bold] [{strategy}] qty={quantity} limit={price}")

    try:
        if len(legs) > 1:
            order_legs = [
                {"contract_id": leg["contract_symbol"], "action": leg["side"], "qty": abs(leg.get("quantity", 1))}
                for leg in legs
            ]
            order = place_multileg_order(order_legs, limit_price=price)
        elif len(legs) == 1:
            leg = legs[0]
            order = place_single_option_order(
                leg["contract_symbol"], leg["side"], abs(leg.get("quantity", 1)), limit_price=price
            )
        else:
            console.print("[yellow]No legs defined — marking open without placing Alpaca order.[/yellow]")
            order = {"id": None, "status": "manual"}

        update_trade_status(full_id, status="open")
        if order.get("id"):
            conn.execute(
                "UPDATE trade_journal SET alpaca_order_id = ?, updated_at = datetime('now') WHERE id = ?",
                [order["id"], full_id],
            )
            conn.commit()

        console.print(f"[green]✓ Approved trade {full_id[:8]} — order status: {order.get('status', '?')}[/green]")

    except Exception as exc:
        console.print(f"[red]Order failed: {exc}[/red]")
        raise typer.Exit(1)


@app.command("reject")
def reject_trade(
    trade_id: str = typer.Argument(help="Trade ID or prefix to reject"),
) -> None:
    """Reject a pending trade (cancels without placing an order)."""
    from magpie.db.connection import get_connection
    from magpie.tracking.journal import update_trade_status

    conn = get_connection()
    row = conn.execute(
        "SELECT id FROM trade_journal WHERE (id = ? OR id LIKE ?) AND status = 'pending_approval' LIMIT 1",
        [trade_id, f"{trade_id}%"],
    ).fetchone()

    if not row:
        console.print(f"[red]No pending trade found with ID starting with '{trade_id}'[/red]")
        raise typer.Exit(1)

    full_id = row[0]
    update_trade_status(full_id, status="cancelled")
    console.print(f"[yellow]✗ Rejected trade {full_id[:8]}[/yellow]")


@app.command("start")
def start_loop(
    interval: int = typer.Option(None, "--interval", "-i", help="Scan interval in seconds (overrides config)"),
) -> None:
    """Start the autonomous agent loop (runs until interrupted)."""
    from magpie.agent.loop import AgentLoop
    from magpie.config import settings

    effective_interval = interval or settings.magpie_agent_interval
    console.print(
        f"[bold]Starting agent loop[/bold] — interval: {effective_interval}s, "
        f"auto-trade limit: ${settings.magpie_auto_trade_max_cost:.0f}"
    )
    console.print("[dim]Press Ctrl+C to stop.[/dim]")

    loop = AgentLoop()
    loop.run(interval=effective_interval)
