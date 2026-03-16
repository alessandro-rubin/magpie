"""magpie watchlist — manage symbols on the watchlist."""

from __future__ import annotations

from typing import Optional

import typer

from magpie.cli.display import console, make_table, print_error, print_success

app = typer.Typer(no_args_is_help=True)


@app.command("list")
def list_watchlist() -> None:
    """List all symbols on the watchlist."""
    from magpie.db.connection import get_connection

    conn = get_connection()
    rows = conn.execute(
        "SELECT symbol, priority, notes, added_at FROM watchlist ORDER BY priority DESC, symbol ASC"
    ).fetchall()

    if not rows:
        console.print("[dim]Watchlist is empty.[/dim]")
        return

    table = make_table("Watchlist", "Symbol", "Priority", "Notes", "Added")
    for r in rows:
        table.add_row(
            r[0],
            str(r[1]),
            r[2] or "—",
            str(r[3])[:10] if r[3] else "—",
        )
    console.print(table)


@app.command("add")
def add_symbol(
    symbol: str = typer.Argument(..., help="Ticker symbol to add (e.g. AAPL)."),
    priority: int = typer.Option(
        5, "--priority", "-p", help="Priority 1-10 (higher = scanned first)."
    ),
    notes: Optional[str] = typer.Option(None, "--notes", "-n", help="Optional notes."),
) -> None:
    """Add a symbol to the watchlist."""
    from magpie.db.connection import get_connection

    conn = get_connection()
    symbol = symbol.upper()

    existing = conn.execute("SELECT symbol FROM watchlist WHERE symbol = ?", [symbol]).fetchone()
    if existing:
        print_error(f"{symbol} is already on the watchlist.")
        raise typer.Exit(1)

    conn.execute(
        "INSERT INTO watchlist (symbol, priority, notes) VALUES (?, ?, ?)",
        [symbol, priority, notes],
    )
    conn.commit()
    print_success(f"Added {symbol} to watchlist (priority={priority})")


@app.command("remove")
def remove_symbol(
    symbol: str = typer.Argument(..., help="Ticker symbol to remove."),
) -> None:
    """Remove a symbol from the watchlist."""
    from magpie.db.connection import get_connection

    conn = get_connection()
    symbol = symbol.upper()

    cursor = conn.execute("DELETE FROM watchlist WHERE symbol = ?", [symbol])
    conn.commit()

    if cursor.rowcount:
        print_success(f"Removed {symbol} from watchlist")
    else:
        print_error(f"{symbol} not found on watchlist.")
        raise typer.Exit(1)
