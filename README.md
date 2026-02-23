# magpie

LLM-powered options trading system using Alpaca paper trading.

Tracks paper and hypothetical trades, feeds past performance back into LLM analyses, and iterates toward better predictions over time.

---

## Overview

Magpie has two integration modes that work together:

1. **Alpaca MCP in Claude Code** — the Alpaca MCP server is wired into this repo's `.mcp.json`. Once your keys are in `.env`, Claude Code (this assistant) can directly query your paper account, options chains, and place orders conversationally.

2. **`magpie` CLI** — a standalone Python application for data collection, trade tracking, and running analyses programmatically on a schedule.

The LLM (Claude Code) acts as the analysis brain. The CLI acts as the data and record-keeping layer. Both speak to Alpaca.

---

## Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/getting-started/installation/) package manager
- An [Alpaca paper trading account](https://app.alpaca.markets) (free)

---

## Setup

**1. Clone and install dependencies**

```bash
uv sync
```

**2. Configure secrets**

```bash
cp .env.example .env
```

Edit `.env` and fill in your Alpaca paper trading credentials:

```ini
ALPACA_API_KEY=PKxxxxxxxxxxxxxxxxxxxxxxxx
ALPACA_SECRET_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
ALPACA_PAPER=true
```

Get your paper API keys from: `https://app.alpaca.markets` → Paper Account → API Keys

**3. Activate the Alpaca MCP server in Claude Code**

The `.mcp.json` is already in this repo. Claude Code will automatically pick it up once your keys are in `.env`. Reload the Claude Code window after adding your keys.

You can verify the MCP is active by asking in Claude Code:
> "What is my Alpaca paper account balance?"

---

## CLI Usage

```bash
# Show help
uv run magpie --help

# Build market context for a symbol and print it for LLM review
uv run magpie analyze AAPL

# View trade journal
uv run magpie journal list
uv run magpie journal show <trade-id>

# View open positions (use --sync to pull from Alpaca first)
uv run magpie positions
uv run magpie positions --sync

# P&L and LLM accuracy report
uv run magpie report
uv run magpie report --symbol AAPL --window 30
```

**Utility scripts**

```bash
# Sync positions and save a daily portfolio snapshot
uv run python scripts/sync_positions.py

# Run analysis on all watchlist symbols
uv run python scripts/morning_scan.py
```

---

## Workflow

```
1. Add symbols to watchlist
   INSERT INTO watchlist (symbol) VALUES ('AAPL'), ('SPY');

2. Run morning scan or use Claude Code interactively via Alpaca MCP

3. Review recommendations in the trade journal
   uv run magpie journal list

4. Approve  → paper order placed via Alpaca
   Reject   → entry logged as "rejected" (still tracked for feedback)
   Hypothetical → logged but no order placed

5. Sync positions during the day
   uv run python scripts/sync_positions.py

6. View performance
   uv run magpie report
```

---

## Project Structure

```
src/magpie/
├── config.py           Settings from .env (pydantic-settings)
├── db/                 DuckDB connection, migrations, dataclass models
├── market/             Alpaca-py wrappers (stocks, options, context assembly)
├── analysis/           LLM prompts, feedback loop, accuracy tracking
├── tracking/           Trade journal, position sync, P&L calculations
├── execution/          Risk checks, human review gate, order placement
└── cli/                Typer commands: analyze, journal, positions, report

scripts/
├── sync_positions.py   Cron: sync Alpaca positions into DB
└── morning_scan.py     Cron: run analysis on watchlist

data/
└── magpie.duckdb       Local database (gitignored)
```

---

## Database

Magpie uses [DuckDB](https://duckdb.org/) — a local, serverless analytical database. No setup required; the file is created automatically on first run.

Key tables:
- `trade_journal` — every trade considered (paper, hypothetical, or live)
- `llm_analyses` — every LLM recommendation and its outcome
- `option_snapshots` — IV and Greeks history for options contracts
- `prediction_accuracy` — rolling win rate by symbol, strategy, prompt version
- `portfolio_snapshots` — daily equity curve
- `watchlist` — symbols to scan

Query the database directly:

```bash
uv run python -c "
from magpie.db.connection import execute_df
print(execute_df('SELECT * FROM trade_journal ORDER BY created_at DESC LIMIT 10'))
"
```

---

## Running Tests

```bash
uv run pytest
```

---

## Options Strategies Supported

| Strategy | Description |
|---|---|
| `single_leg_call` | Directional call buy |
| `single_leg_put` | Directional put buy |
| `vertical_spread` | Bull call / bear put / bull put / bear call |
| `iron_condor` | Range-bound, sell both sides |
| `straddle` / `strangle` | Volatility plays (earnings, events) |
| `calendar_spread` | Time decay differential |
| `covered_call` | Income on existing stock position |
| `cash_secured_put` | Income with intention to buy |

---

## Notes

- All trading defaults to **paper mode**. Set `ALPACA_PAPER=true` in `.env`.
- The feedback loop improves over time: each closed trade updates `prediction_accuracy`, which is injected into future LLM prompts.
- Prompt versions are tracked in `llm_analyses.prompt_version` so you can measure the impact of prompt changes on accuracy.
