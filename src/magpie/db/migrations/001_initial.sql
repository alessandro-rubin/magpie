-- ============================================================
-- ASSETS: canonical asset reference
-- ============================================================
CREATE TABLE IF NOT EXISTS assets (
    symbol          TEXT PRIMARY KEY,
    asset_class     TEXT NOT NULL,       -- 'us_equity', 'crypto', 'option'
    underlying      TEXT,                -- for options: parent symbol (e.g. 'AAPL')
    exchange        TEXT,
    tradeable       INTEGER DEFAULT 1,
    created_at      TIMESTAMP DEFAULT (datetime('now'))
);

-- ============================================================
-- OPTIONS CONTRACTS: snapshot of contract metadata at analysis time
-- ============================================================
CREATE TABLE IF NOT EXISTS option_contracts (
    contract_id         TEXT PRIMARY KEY,    -- OCC symbol e.g. AAPL250117C00200000
    underlying_symbol   TEXT NOT NULL,
    expiration_date     DATE NOT NULL,
    strike_price        REAL NOT NULL,
    option_type         TEXT NOT NULL,       -- 'call' or 'put'
    multiplier          INTEGER DEFAULT 100,
    style               TEXT DEFAULT 'american',
    created_at          TIMESTAMP DEFAULT (datetime('now'))
);

-- ============================================================
-- MARKET SNAPSHOTS: point-in-time options data with Greeks
-- Append-only — query by time range for IV history
-- ============================================================
CREATE TABLE IF NOT EXISTS option_snapshots (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    contract_id         TEXT NOT NULL,
    snapshot_time       TIMESTAMP NOT NULL,
    -- Price
    bid                 REAL,
    ask                 REAL,
    mid                 REAL,
    last_price          REAL,
    volume              INTEGER,
    open_interest       INTEGER,
    -- Greeks
    implied_volatility  REAL,
    delta               REAL,
    gamma               REAL,
    theta               REAL,
    vega                REAL,
    rho                 REAL,
    -- Underlying at snapshot time
    underlying_price    REAL,
    underlying_iv_rank  REAL,
    -- Source
    data_source         TEXT DEFAULT 'alpaca_mcp'
);

-- ============================================================
-- TRADE JOURNAL: every considered trade (paper or hypothetical)
-- ============================================================
CREATE TABLE IF NOT EXISTS trade_journal (
    id                  TEXT PRIMARY KEY,    -- UUID
    created_at          TIMESTAMP DEFAULT (datetime('now')),
    updated_at          TIMESTAMP DEFAULT (datetime('now')),

    -- Classification
    trade_mode          TEXT NOT NULL,       -- 'paper', 'hypothetical', 'live'
    status              TEXT NOT NULL,       -- 'pending_review', 'approved', 'rejected',
                                            --  'open', 'closed', 'expired'

    -- Asset
    underlying_symbol   TEXT NOT NULL,
    asset_class         TEXT NOT NULL,       -- 'option', 'stock', 'crypto'
    strategy_type       TEXT,               -- 'single_leg_call', 'vertical_spread',
                                            --  'iron_condor', 'straddle', 'calendar_spread', ...

    -- Entry
    entry_time          TIMESTAMP,
    entry_price         REAL,
    quantity            INTEGER NOT NULL,
    entry_commission    REAL DEFAULT 0,
    legs                TEXT,               -- JSON array of leg objects for multi-leg strategies

    -- Exit
    exit_time           TIMESTAMP,
    exit_price          REAL,
    exit_commission     REAL DEFAULT 0,
    exit_reason         TEXT,               -- 'target_hit', 'stop_loss', 'expiry', 'manual'

    -- P&L
    realized_pnl        REAL,
    realized_pnl_pct    REAL,
    unrealized_pnl      REAL,

    -- Greeks at entry
    entry_iv            REAL,
    entry_delta         REAL,
    entry_theta         REAL,
    entry_vega          REAL,
    entry_gamma         REAL,
    entry_underlying_price  REAL,
    dte_at_entry        INTEGER,

    -- Risk parameters
    max_profit          REAL,
    max_loss            REAL,
    breakeven_price     REAL,

    -- Alpaca tracking
    alpaca_order_id     TEXT,
    alpaca_position_id  TEXT,

    -- Metadata
    tags                TEXT,               -- JSON array (was VARCHAR[] in DuckDB)
    notes               TEXT,

    -- Rationale
    entry_rationale     TEXT,
    exit_rationale      TEXT
);

-- ============================================================
-- LLM ANALYSES: every recommendation + outcome
-- ============================================================
CREATE TABLE IF NOT EXISTS llm_analyses (
    id                  TEXT PRIMARY KEY,    -- UUID
    created_at          TIMESTAMP DEFAULT (datetime('now')),

    underlying_symbol   TEXT NOT NULL,
    analysis_type       TEXT NOT NULL,       -- 'entry_recommendation', 'exit_recommendation', 'market_scan'

    -- LLM inputs
    model               TEXT NOT NULL,
    prompt_version      TEXT NOT NULL,
    context_snapshot    TEXT NOT NULL,       -- JSON
    past_performance_summary TEXT,           -- JSON

    -- LLM outputs
    raw_response        TEXT NOT NULL,
    recommendation      TEXT,               -- 'enter', 'avoid', 'exit', 'hold', 'reduce'
    confidence_score    REAL,
    strategy_suggested  TEXT,
    reasoning_summary   TEXT,
    suggested_entry     REAL,
    suggested_stop      REAL,
    suggested_target    REAL,

    -- Outcome (filled after trade closes)
    linked_trade_id     TEXT,
    was_correct         INTEGER,            -- 0/1 boolean
    outcome_notes       TEXT,
    outcome_recorded_at TIMESTAMP
);

-- ============================================================
-- PREDICTION ACCURACY: rolled-up stats
-- ============================================================
CREATE TABLE IF NOT EXISTS prediction_accuracy (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    computed_at         TIMESTAMP DEFAULT (datetime('now')),
    window_days         INTEGER NOT NULL,
    underlying_symbol   TEXT,               -- NULL = aggregate
    strategy_type       TEXT,               -- NULL = aggregate
    prompt_version      TEXT,
    model               TEXT,

    total_analyses      INTEGER NOT NULL,
    entered_trades      INTEGER,
    wins                INTEGER,
    losses              INTEGER,
    win_rate            REAL,
    avg_return_pct      REAL,
    avg_days_held       REAL,
    total_pnl           REAL,
    sharpe_approx       REAL
);

-- ============================================================
-- PORTFOLIO SNAPSHOTS: daily equity curve
-- ============================================================
CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    snapshot_date           DATE PRIMARY KEY,
    equity                  REAL NOT NULL,
    cash                    REAL,
    buying_power            REAL,
    open_positions_count    INTEGER,
    unrealized_pnl          REAL,
    realized_pnl_today      REAL,
    source                  TEXT DEFAULT 'alpaca'
);

-- ============================================================
-- WATCHLIST: symbols actively monitored
-- ============================================================
CREATE TABLE IF NOT EXISTS watchlist (
    symbol              TEXT PRIMARY KEY,
    added_at            TIMESTAMP DEFAULT (datetime('now')),
    priority            INTEGER DEFAULT 5,
    notes               TEXT,
    alpaca_watchlist_id TEXT
);
