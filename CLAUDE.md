# Magpie — Claude Code Guide

## Project purpose

LLM-powered options trading system. Uses Alpaca paper trading to test predictions, tracks outcomes, and feeds past performance back into future analyses to self-correct over time.

Primary goal: paper trade options strategies, measure prediction accuracy, iterate.

---

## MCP Servers

This project has two MCP servers configured in `.mcp.json`:

### Alpaca MCP Server (market data & orders)

- Check paper account balance and buying power
- View open positions and P&L
- Fetch options chains with Greeks (delta, theta, vega, IV)
- Place and cancel paper orders
- Search option contracts by symbol, strike, expiry, delta

**Always use paper mode.** `ALPACA_PAPER=true` must be set in `.env`.

### Magpie MCP Server (journal, rules, sync, analysis)

Run via entry point `magpie-mcp`. Exposes these tools:

| Tool | Purpose |
|---|---|
| `journal_list` | List trades (filter by status, symbol) |
| `journal_show` | Full trade details by ID |
| `journal_create` | Create a new trade journal entry |
| `journal_close` | Close a trade with exit details |
| `sync_positions` | Sync Alpaca positions with local journal |
| `sync_portfolio_snapshot` | Save daily equity snapshot |
| `manage_positions` | Scan for profit/stop/DTE triggers |
| `get_feedback` | Combined performance feedback + rules |
| `get_analysis_context` | Build market context for a symbol |
| `rules_list` | List active trading rules |
| `rules_add` | Add a new trading rule |
| `rules_remove` | Deactivate or delete a rule |
| `rules_formatted` | Get rules formatted for prompt injection |

Use the Magpie MCP instead of `uv run python -c "..."` one-liners for journal and rule operations.

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
│   ├── occ.py          OCC option symbol parser (e.g. AAPL260320C00275000)
│   └── snapshots.py    Assembles full context dict for LLM analysis
├── analysis/
│   ├── prompts.py      Versioned prompt templates — bump PROMPT_VERSION on changes
│   ├── llm.py          Claude API integration (optional — requires ANTHROPIC_API_KEY)
│   ├── feedback.py     Queries DB → computes win rates → formats for prompt injection
│   └── regime.py       Market regime: VIX (Yahoo Finance), SPY trend, classification
├── tracking/
│   ├── journal.py      CRUD for trade_journal table + contract leg mapping
│   ├── positions.py    Sync Alpaca positions → local DB (contract-level matching)
│   ├── rules.py        Trading rules CRUD — lessons learned, injected into prompts
│   └── pnl.py          Rolling P&L summaries
├── execution/
│   ├── risk.py         Pre-trade checks: position size, daily loss limit
│   ├── review.py       Rich confirmation panel — human gate before any order
│   └── orders.py       alpaca-py order placement (paper only)
├── dashboard/
│   ├── app.py          Streamlit multipage root
│   ├── data.py         Cached DB queries returning DataFrames for charts
│   ├── payoff.py       Payoff diagram math (P&L at expiry, breakevens)
│   └── pages/          equity, payoff_page, greeks, winrate
├── mcp/
│   └── server.py       FastMCP server — exposes magpie tools for Claude Code
└── cli/
    ├── app.py          Typer root; runs DB migrations on startup
    ├── display.py      Shared Rich helpers (tables, panels, color styles)
    └── commands/       analyze, journal, positions, report, rules, dashboard
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
| `market_regime_snapshots` | Daily market regime (VIX, SPY trend, classification) |
| `trading_rules` | Lessons learned from past trades — injected into analysis prompts |
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
    legs=[
        {"contract_symbol": "AAPL260320C00275000", "option_type": "call", "strike_price": 275.0, "quantity": 1, "premium": 5.85, "side": "buy"},
        {"contract_symbol": "AAPL260320C00285000", "option_type": "call", "strike_price": 285.0, "quantity": -1, "premium": 2.15, "side": "sell"},
    ],
    entry_rationale="Bullish momentum after earnings beat; rolled up from $270/$280 to match price move.",
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
    exit_rationale="Spread hit 80% of max profit with 10 DTE remaining; closing to lock in gains.",
)

# Mark linked LLM analysis outcome (auto-done during sync auto-close)
from magpie.analysis.llm import mark_outcome
mark_outcome(analysis_id, was_correct=True)
```

### Auto-linking analyses to trades

```python
from magpie.tracking.journal import find_unlinked_analysis, link_analysis
# Find most recent unlinked analysis for a symbol
analysis_id = find_unlinked_analysis("AAPL")
if analysis_id:
    link_analysis(analysis_id, trade_id)
```

### Building market context for analysis

```python
from magpie.market.snapshots import build_analysis_context
context = build_analysis_context("AAPL")
# context contains: underlying price/change, options chain with Greeks, IV metrics
```

---

## Positions sync & OCC symbols

### OCC symbol format

`market/occ.py` parses standard OCC option symbols like `AAPL260320C00275000`:
- Root symbol (1-6 chars) + expiry `YYMMDD` + `C`/`P` + strike×1000 (8 digits)

```python
from magpie.market.occ import parse_occ, is_occ_symbol
parsed = parse_occ("AAPL260320C00275000")
# OCCComponents(underlying="AAPL", expiry=date(2026,3,20), option_type="call", strike=275.0)
```

### How sync works

`tracking/positions.py:sync_from_alpaca()` reconciles Alpaca positions with `trade_journal`:

1. **Match by contract symbol** — each leg in `trade_journal.legs` has a `contract_symbol` field (OCC symbol). The sync matches these against Alpaca position symbols.
2. **Aggregate P&L** — unrealized P&L is summed across all legs of a spread into one `trade_journal.unrealized_pnl`.
3. **Backfill Greeks** — open trades missing `entry_delta` get live Greeks fetched from Alpaca and stored. Net spread Greeks are computed sign-aware (long legs add, short legs subtract).
4. **Auto-close** — trades whose legs are all gone from Alpaca are marked `status='closed'`. Realized P&L is computed from the last synced `unrealized_pnl`. Any linked LLM analyses are automatically marked with outcomes (see Feedback loop section).
5. **Auto-import** — unmatched Alpaca positions are imported as new trades. Options on the same underlying+expiry are grouped into a single spread entry. Strategy type is inferred from leg structure. Greeks are fetched at import time via `_fetch_spread_greeks()`.

### Legs JSON format

Every trade should include `legs` with `contract_symbol` for sync to work:

```json
[
  {"contract_symbol": "AAPL260320C00275000", "option_type": "call", "strike_price": 275.0, "quantity": 1, "premium": 5.85, "side": "buy"},
  {"contract_symbol": "AAPL260320C00285000", "option_type": "call", "strike_price": 285.0, "quantity": -1, "premium": 2.15, "side": "sell"}
]
```

Fields: `contract_symbol` (OCC or ticker for stocks), `option_type`, `strike_price`, `quantity` (positive=long, negative=short), `premium`, `side` (`"buy"`/`"sell"`). The `payoff.py` module uses `option_type`, `strike_price`, `quantity`, and `premium`.

---

## Greeks on trades

`trade_journal` stores net spread Greeks at entry time: `entry_delta`, `entry_theta`, `entry_vega`, `entry_gamma`, `entry_iv`.

**Sign convention:** net spread Greeks are computed **sign-aware** — long legs (positive quantity) add their raw Greeks, short legs (negative quantity) subtract. This means:
- A bull call spread with long delta 0.21 and short delta 0.07 stores `entry_delta = 0.14` (not 0.28)
- A bear put spread with long delta -0.55 and short delta -0.39 stores `entry_delta = -0.16`

The dashboard exposure formula is `entry_delta * quantity * 100` (per-lot net delta × number of lots × multiplier).

Greeks are populated:
- At **auto-import** time (`_fetch_spread_greeks()` in `positions.py`)
- During **sync backfill** (Phase 2.5) for any open trade with NULL `entry_delta`
- Manually via `create_trade(entry_delta=..., ...)` kwargs

If Greeks can't be fetched (market closed, API error), the trade is still created — Greeks are just NULL and will be backfilled on the next sync.

---

## Trade rationale

Every trade should capture **why** it was entered and exited. Two TEXT columns on `trade_journal`:

- `entry_rationale` — thesis, market context, why this strike/expiry/strategy was chosen
- `exit_rationale` — why the trade was closed (target hit reasoning, stop logic, roll decision)

These are passed via `entry_rationale=` kwarg on `create_trade()` and `exit_rationale=` kwarg on `update_trade_status()`.

For LLM-driven trades, `llm_analyses.reasoning_summary` captures the model's reasoning. The feedback query in `feedback.py` uses `COALESCE(t.entry_rationale, a.reasoning_summary)` so that interactive/MCP trade reasoning and LLM reasoning are both available for retrospective analysis.

---

## Feedback loop

The self-correction mechanism lives in `src/magpie/analysis/feedback.py`.

Every LLM prompt receives a performance summary injected via `get_combined_feedback()`, which merges two data sources:

1. **Trade journal performance** (`compute_trade_performance()`) — win rates, avg P&L, per-symbol and per-strategy stats computed directly from `trade_journal`. Works without any `llm_analyses` records, so the feedback loop functions even when trades are placed interactively via Claude Code + MCP.

2. **LLM prediction accuracy** (`compute_accuracy_stats()`) — win rates from `llm_analyses` joined with `trade_journal`. Only populated when trades are linked to LLM analyses.

Example injected text:
> "In the last 30 days: 3 trades closed, 1 win / 2 losses (33% win rate, avg return -42%). Vertical spreads: 1/2 profitable. AAPL: 0/1 — avoid repeating."

### Outcome marking

When a trade is auto-closed during sync (legs gone from Alpaca), `_mark_analysis_outcomes()` in `positions.py` automatically:
- Finds all linked `llm_analyses` records via `find_linked_analyses(trade_id)`
- Marks each as `was_correct=True` (positive P&L) or `was_correct=False` (negative P&L)
- Refreshes the `prediction_accuracy` rollup table

For manual closes, call `mark_outcome(analysis_id, was_correct)` from `analysis/llm.py`.

---

## Trading rules

`tracking/rules.py` manages a `trading_rules` table where lessons learned from past trades are stored. Active rules are automatically injected into every LLM analysis prompt via `feedback.py:get_combined_feedback()`.

### Categories

| Category | Purpose |
|---|---|
| `sizing` | Position sizing limits and allocation rules |
| `risk` | Stop losses, DTE thresholds, cushion minimums |
| `entry` | Entry criteria, directional bias checks |
| `macro` | Market regime awareness, geopolitical considerations |
| `execution` | Order placement, MCP quirks, fill verification |

### Usage

```python
from magpie.tracking.rules import add_rule, list_rules, format_rules_for_prompt

# Add a rule (optionally linked to the trade that taught the lesson)
add_rule("sizing", "Max 2-3 lots per spread on a $100K account", source_trade_id="abc123")

# List active rules
rules = list_rules(category="risk")

# Get formatted text for prompt injection (called automatically by get_combined_feedback)
text = format_rules_for_prompt()
```

**CLI:**

```bash
uv run magpie rules list                           # show active rules
uv run magpie rules list --all                     # include deactivated
uv run magpie rules add sizing "Max 3 lots"        # add a rule
uv run magpie rules remove <rule-id>               # deactivate (soft delete)
uv run magpie rules remove <rule-id> --permanent   # hard delete
```

**MCP tools:** `rules_list`, `rules_add`, `rules_remove`, `rules_formatted`

### How it integrates

`get_combined_feedback()` calls `format_rules_for_prompt()` and appends the rules block to the combined narrative. The analysis prompt template renders this in the feedback section, so the LLM sees rules alongside performance stats. Rules are flagged if a recommendation would violate them.

---

## Market regime

`analysis/regime.py` classifies the current market environment so the LLM sees the macro picture alongside symbol-specific data.

### Data sources

| Signal | Source | Fallback |
|---|---|---|
| VIX level | Yahoo Finance chart API (free, no auth) | SPY 20-day realized vol |
| SPY trend | Alpaca bars (SMA-50, SMA-200, 20d momentum) | Fewer signals if bars insufficient |
| Put/call ratio | SPY options chain open interest | None (skipped) |

### Classification

**Trend regime** — score-based: SPY > SMA-50 (+1/-1), SPY > SMA-200 (+1/-1), 20d momentum > +1% (+1) or < -1% (-1). Score ≥2 = bullish, ≤-2 = bearish, else neutral.

**Volatility regime** — VIX < 15 = low, 15-25 = normal, > 25 = high.

**Composite** — `"{trend}_{vol}_vol"`, e.g. `bearish_normal_vol`.

### How it integrates

`build_analysis_context()` calls `get_market_regime()` and adds a `market_regime` key to the context dict. The prompt template renders it as a `## Market Regime & Sentiment` section. The system prompt instructs the LLM to factor regime into recommendations and explain if a directional trade conflicts with the macro signal.

Daily regime snapshots are saved to `market_regime_snapshots` table for historical tracking.

```python
from magpie.analysis.regime import get_market_regime, save_regime_snapshot
regime = get_market_regime()
# {'trend_regime': 'bearish', 'volatility_regime': 'normal', 'vix_level': 22.7, ...}
save_regime_snapshot(regime)
```

---

## Position management

Automated scanning of open positions for profit targets, stop losses, and DTE limits.

Configured in `.env` (defaults shown):

```ini
MAGPIE_PROFIT_TARGET_PCT=0.50  # close at 50% of max profit
MAGPIE_STOP_LOSS_PCT=1.0       # close at 100% of max loss
MAGPIE_MIN_DTE_CLOSE=3         # close when DTE <= 3 (gamma risk)
```

**CLI:**

```bash
uv run magpie positions manage              # dry-run: show what would be closed
uv run magpie positions manage --execute    # actually close (journal only — close Alpaca separately)
uv run magpie positions manage --no-sync    # skip Alpaca sync before scanning
```

**Script (for scheduling):**

```bash
uv run python scripts/manage_positions.py              # dry-run
uv run python scripts/manage_positions.py --execute     # close positions
```

When `--execute` is used, each closed trade records `exit_reason` (`target_hit`, `stop_loss`, or `low_dte`), computes `realized_pnl` from the last synced unrealized P&L, and marks linked LLM analysis outcomes.

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

`analysis/prompts.py` contains `PROMPT_VERSION = "v1.1"`. Bump this whenever the system prompt or analysis template changes. This allows you to compare prediction accuracy before and after prompt changes using:

```sql
SELECT prompt_version, AVG(CASE WHEN was_correct THEN 1.0 ELSE 0.0 END) as win_rate
FROM llm_analyses
WHERE was_correct IS NOT NULL
GROUP BY prompt_version;
```

---

## Dashboard

Streamlit-based web frontend for interactive visualization. Launch with:

```bash
uv run magpie dashboard           # opens http://localhost:8501
uv run magpie dashboard --port 9000  # custom port
```

Four pages:

| Page | Data source | Charts |
|---|---|---|
| Equity & Drawdown | `portfolio_snapshots` | Equity line, drawdown %, daily P&L bars |
| Payoff Diagrams | `trade_journal.legs` JSON | P&L at expiry with breakevens, per-leg overlay |
| Greeks Dashboard | `trade_journal` (entry Greeks from sync) + `option_snapshots` | Portfolio Greeks exposure, IV history, per-contract Greeks |
| Win Rates | `trade_journal` + `llm_analyses` | Win rate by strategy/symbol/prompt, rolling win rate, P&L histogram |

All queries live in `dashboard/data.py` with `@st.cache_data(ttl=60)`. Payoff math is in `dashboard/payoff.py` (pure functions, unit tested). Each page handles empty data gracefully.

---

## Scripts

Run on a schedule during trading hours:

```bash
# Every 15 minutes during market hours — sync positions, update P&L, auto-close
uv run python scripts/sync_positions.py

# Once per day at ~9:45 AM ET — analyze watchlist symbols
uv run python scripts/morning_scan.py

# Every 30 minutes or at market close — check profit/stop/DTE targets
uv run python scripts/manage_positions.py

# Once per day near market close — auto-close positions hitting Monday expiry risk
uv run python scripts/monday_close_losers.py
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

---

## Roadmap / TODOs

### Medium priority

- **Slippage tracking** — compare `entry_price` on journal to actual Alpaca fill price. Add `fill_price` column to `trade_journal`, compute slippage at sync time. Useful to measure execution quality.
- **Regime snapshot at analysis time** — store the `market_regime` dict in `llm_analyses.context_snapshot` so retrospective analysis can see what regime the LLM saw when it made the recommendation.
- **Trade timeline / decision audit page** — new dashboard page showing a timeline per trade: analysis → entry → P&L updates → exit, with rationale at each step. Data already exists across `llm_analyses` + `trade_journal`.

### Low priority

- **Watchlist CLI management** — `magpie watchlist add/remove/list` commands. Table exists, just needs CLI wiring.
- **Prompt A/B testing infrastructure** — run two prompt versions in parallel on the same symbols, compare outcomes. Requires splitting `PROMPT_VERSION` into concurrent tracks.
- **Test coverage gaps** — add tests for LLM response parsing edge cases (`_parse_response` in `llm.py`) and risk check logic (`execution/risk.py`).

### Done

- **Trading rules system** — `trading_rules` table, CRUD in `tracking/rules.py`, CLI commands (`magpie rules`), injected into feedback loop and analysis prompts. See "Trading rules" section above.
- **Magpie MCP server** — FastMCP server exposing journal, rules, sync, and analysis tools. Entry point `magpie-mcp`, registered in `.mcp.json`. See "MCP Servers" section above.
