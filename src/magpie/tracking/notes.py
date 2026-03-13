"""Trading notes — persistent memory for strategic context across sessions.

Notes capture deadlines, strategy decisions, observations, and portfolio-level
context. Active notes are injected into the feedback loop so every new
conversation starts with full awareness of what's going on.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from magpie.db.connection import get_connection
from magpie.db.models import TradingNote

VALID_CATEGORIES = ("deadline", "strategy", "observation", "portfolio")


def add_note(
    category: str,
    title: str,
    content: str,
    source_trade_id: str | None = None,
    expires_at: str | None = None,
) -> str:
    """Insert a new trading note. Returns the generated note ID.

    Args:
        expires_at: ISO timestamp string (e.g. '2026-03-19T00:00:00') for
                    auto-expiry. Especially useful for deadline notes.
    """
    if category not in VALID_CATEGORIES:
        raise ValueError(f"Category must be one of {VALID_CATEGORIES}, got '{category}'")

    conn = get_connection()
    note_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    conn.execute(
        """
        INSERT INTO trading_notes
            (id, category, title, content, source_trade_id, expires_at, resolved, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)
        """,
        [note_id, category, title, content, source_trade_id, expires_at, now, now],
    )
    conn.commit()
    return note_id


def list_notes(
    category: str | None = None,
    active_only: bool = True,
) -> list[TradingNote]:
    """Fetch trading notes with optional filters.

    When active_only=True (default), excludes resolved notes and notes
    whose expires_at has passed.
    """
    conn = get_connection()
    filters: list[str] = []
    params: list = []

    if active_only:
        filters.append("resolved = 0")
        # Exclude expired notes (but keep notes with no expiry)
        filters.append("(expires_at IS NULL OR expires_at > datetime('now'))")
    if category:
        filters.append("category = ?")
        params.append(category)

    where = f"WHERE {' AND '.join(filters)}" if filters else ""

    rows = conn.execute(
        f"""
        SELECT id, category, title, content, source_trade_id,
               expires_at, resolved, created_at, updated_at
        FROM trading_notes {where}
        ORDER BY
            CASE category
                WHEN 'deadline' THEN 0
                WHEN 'portfolio' THEN 1
                WHEN 'strategy' THEN 2
                WHEN 'observation' THEN 3
            END,
            created_at DESC
        """,
        params,
    ).fetchall()

    return [_row_to_note(r) for r in rows]


def resolve_note(note_id: str) -> bool:
    """Mark a note as resolved. Returns True if a row was updated."""
    conn = get_connection()
    count = conn.execute(
        "SELECT COUNT(*) FROM trading_notes WHERE id LIKE ?", [f"{note_id}%"]
    ).fetchone()[0]
    if count == 0:
        return False
    conn.execute(
        "UPDATE trading_notes SET resolved = 1, updated_at = datetime('now') WHERE id LIKE ?",
        [f"{note_id}%"],
    )
    conn.commit()
    return True


def update_note(note_id: str, content: str | None = None, title: str | None = None) -> bool:
    """Update a note's content and/or title. Returns True if a row was updated."""
    conn = get_connection()
    count = conn.execute(
        "SELECT COUNT(*) FROM trading_notes WHERE id LIKE ?", [f"{note_id}%"]
    ).fetchone()[0]
    if count == 0:
        return False

    updates = []
    params: list = []
    if content is not None:
        updates.append("content = ?")
        params.append(content)
    if title is not None:
        updates.append("title = ?")
        params.append(title)

    if not updates:
        return True

    updates.append("updated_at = datetime('now')")
    params.append(f"{note_id}%")

    conn.execute(
        f"UPDATE trading_notes SET {', '.join(updates)} WHERE id LIKE ?",
        params,
    )
    conn.commit()
    return True


def delete_note(note_id: str) -> bool:
    """Permanently delete a note. Returns True if a row was deleted."""
    conn = get_connection()
    count = conn.execute(
        "SELECT COUNT(*) FROM trading_notes WHERE id LIKE ?", [f"{note_id}%"]
    ).fetchone()[0]
    if count == 0:
        return False
    conn.execute("DELETE FROM trading_notes WHERE id LIKE ?", [f"{note_id}%"])
    conn.commit()
    return True


def format_notes_for_prompt() -> str:
    """Format all active notes as a text block for prompt injection.

    Deadlines that are approaching (within 3 days) are marked as URGENT.
    Returns empty string if no active notes exist.
    """
    notes = list_notes(active_only=True)
    if not notes:
        return ""

    lines = ["## Active Trading Notes"]

    by_category: dict[str, list[TradingNote]] = {}
    for n in notes:
        by_category.setdefault(n.category, []).append(n)

    # Render in priority order
    for cat in VALID_CATEGORIES:
        if cat not in by_category:
            continue
        lines.append(f"\n### {cat.title()}")
        for note in by_category[cat]:
            prefix = ""
            if note.expires_at:
                try:
                    exp = note.expires_at if isinstance(note.expires_at, datetime) else datetime.fromisoformat(str(note.expires_at))
                    now = datetime.now(timezone.utc)
                    days_left = (exp - now).days
                    if days_left <= 3:
                        prefix = "URGENT: "
                    prefix += f"[due {exp.strftime('%Y-%m-%d')}] "
                except Exception:
                    pass
            lines.append(f"- {prefix}**{note.title}**: {note.content}")

    return "\n".join(lines)


def _row_to_note(row: tuple) -> TradingNote:
    return TradingNote(
        id=row[0],
        category=row[1],
        title=row[2],
        content=row[3],
        source_trade_id=row[4],
        expires_at=row[5],
        resolved=bool(row[6]),
        created_at=row[7],
        updated_at=row[8],
    )
