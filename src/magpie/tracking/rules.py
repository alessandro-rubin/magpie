"""Trading rules — CRUD operations on the trading_rules DuckDB table.

Rules capture lessons learned from past trades and are injected into
LLM analysis prompts so the system avoids repeating mistakes.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from magpie.db.connection import get_connection
from magpie.db.models import TradingRule

VALID_CATEGORIES = ("sizing", "risk", "entry", "macro", "execution")


def add_rule(
    category: str,
    rule: str,
    source_trade_id: str | None = None,
) -> str:
    """Insert a new trading rule. Returns the generated rule ID."""
    if category not in VALID_CATEGORIES:
        raise ValueError(f"Category must be one of {VALID_CATEGORIES}, got '{category}'")

    conn = get_connection()
    rule_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    conn.execute(
        """
        INSERT INTO trading_rules (id, category, rule, source_trade_id, active, created_at, updated_at)
        VALUES (?, ?, ?, ?, TRUE, ?, ?)
        """,
        [rule_id, category, rule, source_trade_id, now, now],
    )
    return rule_id


def list_rules(
    category: str | None = None,
    active_only: bool = True,
) -> list[TradingRule]:
    """Fetch trading rules with optional filters."""
    conn = get_connection()
    filters: list[str] = []
    params: list = []

    if active_only:
        filters.append("active = TRUE")
    if category:
        filters.append("category = ?")
        params.append(category)

    where = f"WHERE {' AND '.join(filters)}" if filters else ""

    rows = conn.execute(
        f"""
        SELECT id, category, rule, source_trade_id, active, created_at, updated_at
        FROM trading_rules {where}
        ORDER BY category, created_at
        """,
        params,
    ).fetchall()

    return [_row_to_rule(r) for r in rows]


def deactivate_rule(rule_id: str) -> bool:
    """Deactivate a rule (soft delete). Returns True if a row was updated."""
    conn = get_connection()
    count = conn.execute(
        "SELECT COUNT(*) FROM trading_rules WHERE id LIKE ?", [f"{rule_id}%"]
    ).fetchone()[0]
    if count == 0:
        return False
    conn.execute(
        "UPDATE trading_rules SET active = FALSE, updated_at = NOW() WHERE id LIKE ?",
        [f"{rule_id}%"],
    )
    return True


def activate_rule(rule_id: str) -> bool:
    """Re-activate a previously deactivated rule."""
    conn = get_connection()
    count = conn.execute(
        "SELECT COUNT(*) FROM trading_rules WHERE id LIKE ?", [f"{rule_id}%"]
    ).fetchone()[0]
    if count == 0:
        return False
    conn.execute(
        "UPDATE trading_rules SET active = TRUE, updated_at = NOW() WHERE id LIKE ?",
        [f"{rule_id}%"],
    )
    return True


def delete_rule(rule_id: str) -> bool:
    """Permanently delete a rule. Returns True if a row was deleted."""
    conn = get_connection()
    count = conn.execute(
        "SELECT COUNT(*) FROM trading_rules WHERE id LIKE ?", [f"{rule_id}%"]
    ).fetchone()[0]
    if count == 0:
        return False
    conn.execute(
        "DELETE FROM trading_rules WHERE id LIKE ?",
        [f"{rule_id}%"],
    )
    return True


def format_rules_for_prompt() -> str:
    """Format all active rules as a text block for prompt injection.

    Returns empty string if no rules exist.
    """
    rules = list_rules(active_only=True)
    if not rules:
        return ""

    by_category: dict[str, list[str]] = {}
    for r in rules:
        by_category.setdefault(r.category, []).append(r.rule)

    lines = ["## Trading Rules (learned from past trades)"]
    for cat in VALID_CATEGORIES:
        if cat not in by_category:
            continue
        lines.append(f"\n### {cat.title()}")
        for rule_text in by_category[cat]:
            lines.append(f"- {rule_text}")

    lines.append(
        "\nApply these rules when making recommendations. "
        "Flag any recommendation that would violate a rule."
    )
    return "\n".join(lines)


def _row_to_rule(row: tuple) -> TradingRule:
    return TradingRule(
        id=row[0],
        category=row[1],
        rule=row[2],
        source_trade_id=row[3],
        active=row[4],
        created_at=row[5],
        updated_at=row[6],
    )
