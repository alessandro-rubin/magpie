#!/usr/bin/env python
"""Start the Magpie HTTP API server (OpenClaw skill backend).

Usage:
    uv run python scripts/run_api.py
    # or via entry point:
    uv run magpie-api
"""

from dotenv import load_dotenv

load_dotenv()

from magpie.agent.api import main  # noqa: E402

if __name__ == "__main__":
    main()
