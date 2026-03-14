#!/usr/bin/env python
"""Start the Magpie autonomous agent loop.

Continuously scans the watchlist on a configured interval, runs LLM analysis,
and executes trades within risk guardrails (hybrid autonomy mode).

Usage:
    uv run python scripts/run_agent.py
    # or via entry point:
    uv run magpie-agent

Configuration (in .env):
    MAGPIE_AGENT_INTERVAL=1800        # scan every 30 minutes
    MAGPIE_AUTO_TRADE_MAX_COST=0      # 0 = always require approval
    MAGPIE_AUTO_TRADE_MAX_COST=500    # auto-execute trades up to $500

Pending approvals:
    uv run magpie agent pending       # list queued trades
    uv run magpie agent approve <id>  # approve and place order
    uv run magpie agent reject <id>   # reject without order
"""

from dotenv import load_dotenv

load_dotenv()

from magpie.agent.loop import main  # noqa: E402

if __name__ == "__main__":
    main()
