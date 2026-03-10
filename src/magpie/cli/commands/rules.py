"""magpie rules — manage trading rules (lessons learned)."""

from __future__ import annotations

from typing import Optional

import typer

from magpie.cli.display import console, make_table, print_error, print_success

app = typer.Typer(no_args_is_help=True)


@app.command("list")
def list_rules(
    category: Optional[str] = typer.Option(None, "--category", "-c", help="Filter by category."),
    all_rules: bool = typer.Option(False, "--all", "-a", help="Include deactivated rules."),
) -> None:
    """List active trading rules."""
    from magpie.tracking.rules import list_rules as _list

    rules = _list(category=category, active_only=not all_rules)
    if not rules:
        console.print("[dim]No trading rules found.[/dim]")
        return

    table = make_table("Trading Rules", "ID", "Category", "Rule", "Active", "Source Trade")
    for r in rules:
        table.add_row(
            r.id[:8],
            r.category,
            r.rule[:80] + ("..." if len(r.rule) > 80 else ""),
            "yes" if r.active else "[dim]no[/dim]",
            r.source_trade_id[:8] if r.source_trade_id else "—",
        )
    console.print(table)


@app.command("add")
def add_rule(
    category: str = typer.Argument(..., help="Category: sizing, risk, entry, macro, execution."),
    rule: str = typer.Argument(..., help="The rule text."),
    source_trade: Optional[str] = typer.Option(None, "--trade", "-t", help="Source trade ID."),
) -> None:
    """Add a new trading rule."""
    from magpie.tracking.rules import add_rule as _add

    try:
        rule_id = _add(category=category, rule=rule, source_trade_id=source_trade)
    except ValueError as e:
        print_error(str(e))
        raise typer.Exit(1)

    print_success(f"Rule added: {rule_id[:8]}")


@app.command("remove")
def remove_rule(
    rule_id: str = typer.Argument(..., help="Rule ID (or prefix) to deactivate."),
    permanent: bool = typer.Option(False, "--permanent", help="Permanently delete instead."),
) -> None:
    """Deactivate (or permanently delete) a trading rule."""
    from magpie.tracking.rules import deactivate_rule, delete_rule

    if permanent:
        ok = delete_rule(rule_id)
    else:
        ok = deactivate_rule(rule_id)

    if ok:
        action = "Deleted" if permanent else "Deactivated"
        print_success(f"{action} rule {rule_id[:8]}")
    else:
        print_error(f"Rule '{rule_id}' not found.")
        raise typer.Exit(1)
