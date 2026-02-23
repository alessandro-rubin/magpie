# Magpie — Claude Code Guide

## Project purpose

LLM-powered options trading system. Uses Alpaca paper trading to test predictions, tracks outcomes, and feeds past performance back into future analyses to self-correct over time.

Primary goal: paper trade options strategies, measure prediction accuracy, iterate.

---

## Alpaca MCP Server

This project has `.mcp.json` configured. When the MCP server is active, you can:

- Check paper account balance and buying power
- View open positions and P&L
- Fetch options chains with Greeks (delta, theta, vega, IV)
- Place and cancel paper orders
- Search option contracts by symbol, strike, expiry, delta

**Always use paper mode.** `ALPACA_PAPER=true` must be set in `.env`.

Verify the MCP is working: ask "what is my Alpaca paper account balance?"

---

## Architecture

```
src/magpie/
├── config.py           Typed settings via pydantic-settings, loaded from .env
├── db/
│   ├── connection.py   DuckDB singleton + migration runner
│   ├── models.py       Python dataclasses mirroring DB tables
│   └── migrations/     SQL DDL files (applied in order on first connect)
├── market/
│   ├── client.py       alpaca-py client factory (TradingClient, DataClients)
│   ├── stocks.py       Stock price, bars, snapshots
│   ├── options.py      Option chains, individual snapshots, Greeks
│   └── snapshots.py    Assembles full context dict for LLM analysis
├── analysis/
│   ├── prompts.py      Versioned prompt templates — bump PROMPT_VERSION on changes
│   ├── llm.py          Claude API integration (optional — requires ANTHROPIC_API_KEY)
│   └── feedback.py     Queries DB → computes win rates → formats for prompt injection
├── tracking/
│   ├── journal.py      CRUD for trade_journal table
│   ├── positions.py    Sync Alpaca positions → local DB
│   └── pnl.py          Rolling P&L summaries
├── execution/
│   ├── risk.py         Pre-trade checks: position size, daily loss limit
│   ├── review.py       Rich confirmation panel — human gate before any order
│   └── orders.py       alpaca-py order placement (paper only)
└── cli/
    ├── app.py          Typer root; runs DB migrations on startup
    ├── display.py      Shared Rich helpers (tables, panels, color styles)
    └── commands/       analyze, journal, positions, report
```

---

## Database (DuckDB)

File: `data/magpie.duckdb` (auto-created, gitignored).

Key tables and their purpose:

| Table | Purpose |
|---|---|
| `trade_journal` | Every trade considered: paper, hypothetical, or live |
| `llm_analyses` | Every LLM recommendation + outcome (`was_correct`) |
| `option_snapshots` | Append-only IV/Greeks history per contract |
| `prediction_accuracy` | Rolled-up win rate by symbol/strategy/prompt version |
| `portfolio_snapshots` | Daily equity curve |
| `watchlist` | Symbols to scan |

Run ad-hoc queries:

```python
from magpie.db.connection import execute_df
execute_df("SELECT * FROM trade_journal WHERE status = 'open'")
```

---

## Key patterns

### Adding a watchlist symbol

```python
from magpie.db.connection import get_connection
conn = get_connection()
conn.execute("INSERT OR IGNORE INTO watchlist (symbol) VALUES ('AAPL')")
```

### Creating a hypothetical trade entry

```python
from magpie.tracking.journal import create_trade
trade_id = create_trade(
    trade_mode="hypothetical",
    underlying_symbol="AAPL",
    asset_class="option",
    quantity=1,
    strategy_type="vertical_spread",
    entry_price=4.50,
    entry_iv=0.35,
    entry_delta=0.40,
    dte_at_entry=30,
)
```

### Closing a trade and recording the outcome

```python
from magpie.tracking.journal import update_trade_status
update_trade_status(
    trade_id,
    status="closed",
    exit_price=8.20,
    exit_reason="target_hit",
    realized_pnl=370.0,       # (8.20 - 4.50) * 100 contracts
    realized_pnl_pct=0.822,   # +82.2%
)

from magpie.analysis.llm import mark_outcome
mark_outcome(analysis_id, was_correct=True)
```

### Building market context for analysis

```python
from magpie.market.snapshots import build_analysis_context
context = build_analysis_context("AAPL")
# context contains: underlying price/change, options chain with Greeks, IV metrics
```

---

## Feedback loop

The self-correction mechanism lives in `src/magpie/analysis/feedback.py`.

Every LLM prompt receives a paragraph like:
> "In the last 30 days: 8/12 vertical spread calls were profitable (avg +22% return). Straddle entries within 48h of earnings: 2/8 profitable — avoid."

This is computed from `llm_analyses` joined with `trade_journal` via `compute_accuracy_stats()`.

After each trade closes, call `mark_prediction_outcome(analysis_id, was_correct)` to close the loop.

---

## Risk controls

Configured in `.env`:

```ini
MAGPIE_MAX_POSITION_PCT=0.10   # max 10% of equity per trade
MAGPIE_MAX_DAILY_LOSS_PCT=0.02 # halt new trades if down 2% on the day
```

Always run `execution/risk.py:run_all_checks()` before placing any order.
The `execution/review.py` confirmation panel shows risk check results.

---

## Prompt versioning

`analysis/prompts.py` contains `PROMPT_VERSION = "v1.0"`. Bump this whenever the system prompt or analysis template changes. This allows you to compare prediction accuracy before and after prompt changes using:

```sql
SELECT prompt_version, AVG(CASE WHEN was_correct THEN 1.0 ELSE 0.0 END) as win_rate
FROM llm_analyses
WHERE was_correct IS NOT NULL
GROUP BY prompt_version;
```

---

## Scripts

Run on a schedule during trading hours:

```bash
# Every 15 minutes during market hours
uv run python scripts/sync_positions.py

# Once per day at ~9:45 AM ET
uv run python scripts/morning_scan.py
```

---

## What requires ANTHROPIC_API_KEY

The `analysis/llm.py` module calls the Claude API directly for standalone (non-interactive) analysis. This is **optional** — if the key is not set, the `magpie analyze` command will display the market context and prompt text so you can paste it into Claude Code instead.

All other CLI commands (journal, positions, report, sync) work without any API key.

---

## Development

```bash
uv run pytest          # run tests
uv run ruff check .    # lint
uv run ruff format .   # format
```

Tests use an in-memory DuckDB fixture (`tests/conftest.py`) — no real API calls.
