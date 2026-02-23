#!/usr/bin/env python
"""
Morning watchlist scan — build market context for every symbol in the watchlist.

If ANTHROPIC_API_KEY is set, calls the Claude API directly.
Otherwise, prints formatted prompts to paste into Claude Code.

Suggested schedule: 9:45 AM ET on trading days (after market open stabilizes).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from magpie.db.connection import get_connection, run_migrations
from magpie.market.snapshots import build_analysis_context
from magpie.analysis.llm import AnthropicKeyMissing, build_prompt, run_analysis

if __name__ == "__main__":
    conn = get_connection()
    run_migrations(conn)

    watchlist = conn.execute(
        "SELECT symbol FROM watchlist ORDER BY priority ASC"
    ).fetchall()

    if not watchlist:
        print("Watchlist is empty. Add symbols:")
        print("  INSERT INTO watchlist (symbol) VALUES ('AAPL'), ('SPY');")
        sys.exit(0)

    for (symbol,) in watchlist:
        print(f"\n── {symbol} ──")
        try:
            context = build_analysis_context(symbol)

            try:
                analysis = run_analysis(symbol, context, hypothetical_only=True)
                rec = (analysis.recommendation or "—").upper()
                conf = f"{(analysis.confidence_score or 0) * 100:.0f}%"
                strat = analysis.strategy_suggested or "—"
                print(f"  {rec} | {strat} | confidence={conf}")
                print(f"  {analysis.reasoning_summary or '(no reasoning)'}")
            except AnthropicKeyMissing:
                print("  [no API key] Prompt ready for Claude Code:")
                print()
                print(build_prompt(symbol, context))
                print()

        except Exception as e:
            print(f"  ERROR: {e}")

    print("\nScan complete. View results: uv run magpie journal list")
