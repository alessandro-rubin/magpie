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

## CLI Commands

### `magpie journal` — Trade Diary

```bash
uv run magpie journal list                    # List all trades
uv run magpie journal list --status open      # Filter by status (pending, open, closed)
uv run magpie journal list --symbol NVDA      # Filter by ticker
uv run magpie journal list --mode paper       # Filter by mode (paper / hypothetical)
uv run magpie journal list --limit 50         # Change row limit (default 20)
uv run magpie journal show <trade-id>         # Full detail on a trade (ID prefix works)
```

### `magpie positions` — Live Position View

```bash
uv run magpie positions                       # Show all open positions from journal
uv run magpie positions --sync                # Sync from Alpaca first, then display
```

The `--sync` flag pulls live data from Alpaca, updates unrealized P&L, backfills Greeks (delta, theta, vega, gamma, IV) on trades missing them, and auto-closes positions that no longer exist on Alpaca's side.

### `magpie report` — P&L + LLM Accuracy

```bash
uv run magpie report                          # 30-day P&L summary + LLM win rate
uv run magpie report --symbol TSLA            # Filter to one ticker
uv run magpie report --window 7               # Change rolling window (days)
```

Shows closed trade stats (wins, losses, win rate, avg return) and LLM prediction accuracy by strategy and prompt version.

### `magpie analyze` — Market Analysis

```bash
uv run magpie analyze run AAPL                # Build context + run LLM analysis
uv run magpie analyze run AAPL --context      # Print market context/prompt only (no LLM call)
uv run magpie analyze run AAPL --hypothetical # Log as hypothetical trade (no order placed)
```

If `ANTHROPIC_API_KEY` is not set, the command prints the formatted prompt so you can paste it into Claude Code for interactive analysis via the Alpaca MCP server.

### General

```bash
uv run magpie --help                          # Show all available commands
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
   Each analysis automatically fetches market regime context:
   - VIX level (Yahoo Finance, with realized-vol fallback)
   - SPY trend (price vs SMA-50/200, 20-day momentum)
   - SPY put/call ratio
   - Composite classification (e.g. bullish_low_vol, bearish_high_vol)
   The regime is saved daily and injected into the LLM prompt.

3. Review recommendations in the trade journal
   uv run magpie journal list

4. Approve  → paper order placed via Alpaca
   Reject   → entry logged as "rejected" (still tracked for feedback)
   Hypothetical → logged but no order placed

5. Sync positions during the day
   uv run python scripts/sync_positions.py
   - Updates unrealized P&L from Alpaca
   - Backfills Greeks (delta, theta, vega, gamma, IV) on any open trade missing them
   - Auto-imports new Alpaca positions with Greeks fetched at import time
   - Auto-closes trades whose positions no longer exist on Alpaca

6. View performance and Greeks exposure
   uv run magpie report              # P&L and win rates
   uv run magpie dashboard           # Streamlit UI with Greeks charts
```

---

## Project Structure

```
src/magpie/
├── config.py           Settings from .env (pydantic-settings)
├── db/                 DuckDB connection, migrations, dataclass models
├── market/             Alpaca-py wrappers (stocks, options, context assembly)
├── analysis/           LLM prompts, feedback loop, market regime, accuracy tracking
├── tracking/           Trade journal, position sync (with Greeks), P&L calculations
├── execution/          Risk checks, human review gate, order placement
├── dashboard/          Streamlit UI: equity, payoff, Greeks exposure, win rates
└── cli/                Typer commands: analyze, journal, positions, report, dashboard

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
- `market_regime_snapshots` — daily market regime (VIX, SPY trend, composite classification)
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
- Every trade can store `entry_rationale` and `exit_rationale` — free-text reasoning captured at decision time. This powers retrospective analysis: review *why* a trade was made, not just *what* happened.
- Position sync fetches live Greeks from Alpaca and stores net spread Greeks (sign-aware: long legs add, short legs subtract) on `trade_journal`. The Greeks dashboard uses these to show portfolio-level exposure.
- Every analysis includes a market regime section (VIX level, SPY trend, put/call ratio) so the LLM sees the macro picture. Regime is classified as bullish/neutral/bearish + low/normal/high vol. VIX is fetched from Yahoo Finance with a realized-vol fallback.
