-- ============================================================
-- ASSETS: canonical asset reference
-- ============================================================
CREATE TABLE IF NOT EXISTS assets (
    symbol          VARCHAR PRIMARY KEY,
    asset_class     VARCHAR NOT NULL,       -- 'us_equity', 'crypto', 'option'
    underlying      VARCHAR,                -- for options: parent symbol (e.g. 'AAPL')
    exchange        VARCHAR,
    tradeable       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- OPTIONS CONTRACTS: snapshot of contract metadata at analysis time
-- ============================================================
CREATE TABLE IF NOT EXISTS option_contracts (
    contract_id         VARCHAR PRIMARY KEY,    -- OCC symbol e.g. AAPL250117C00200000
    underlying_symbol   VARCHAR NOT NULL,
    expiration_date     DATE NOT NULL,
    strike_price        DECIMAL(12,4) NOT NULL,
    option_type         VARCHAR NOT NULL,       -- 'call' or 'put'
    multiplier          INTEGER DEFAULT 100,
    style               VARCHAR DEFAULT 'american',
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- MARKET SNAPSHOTS: point-in-time options data with Greeks
-- Append-only — query by time range for IV history
-- ============================================================
CREATE SEQUENCE IF NOT EXISTS option_snapshots_seq;

CREATE TABLE IF NOT EXISTS option_snapshots (
    id                  BIGINT PRIMARY KEY DEFAULT nextval('option_snapshots_seq'),
    contract_id         VARCHAR NOT NULL,
    snapshot_time       TIMESTAMPTZ NOT NULL,
    -- Price
    bid                 DECIMAL(10,4),
    ask                 DECIMAL(10,4),
    mid                 DECIMAL(10,4),
    last_price          DECIMAL(10,4),
    volume              INTEGER,
    open_interest       INTEGER,
    -- Greeks
    implied_volatility  DECIMAL(10,6),
    delta               DECIMAL(10,6),
    gamma               DECIMAL(10,6),
    theta               DECIMAL(10,6),
    vega                DECIMAL(10,6),
    rho                 DECIMAL(10,6),
    -- Underlying at snapshot time
    underlying_price    DECIMAL(12,4),
    underlying_iv_rank  DECIMAL(6,4),
    -- Source
    data_source         VARCHAR DEFAULT 'alpaca_mcp'
);

-- ============================================================
-- TRADE JOURNAL: every considered trade (paper or hypothetical)
-- ============================================================
CREATE TABLE IF NOT EXISTS trade_journal (
    id                  VARCHAR PRIMARY KEY,    -- UUID
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW(),

    -- Classification
    trade_mode          VARCHAR NOT NULL,       -- 'paper', 'hypothetical', 'live'
    status              VARCHAR NOT NULL,       -- 'pending_review', 'approved', 'rejected',
                                               --  'open', 'closed', 'expired'

    -- Asset
    underlying_symbol   VARCHAR NOT NULL,
    asset_class         VARCHAR NOT NULL,       -- 'option', 'stock', 'crypto'
    strategy_type       VARCHAR,               -- 'single_leg_call', 'vertical_spread',
                                               --  'iron_condor', 'straddle', 'calendar_spread', ...

    -- Entry
    entry_time          TIMESTAMPTZ,
    entry_price         DECIMAL(12,4),
    quantity            INTEGER NOT NULL,
    entry_commission    DECIMAL(8,4) DEFAULT 0,
    legs                JSON,                  -- array of leg objects for multi-leg strategies

    -- Exit
    exit_time           TIMESTAMPTZ,
    exit_price          DECIMAL(12,4),
    exit_commission     DECIMAL(8,4) DEFAULT 0,
    exit_reason         VARCHAR,               -- 'target_hit', 'stop_loss', 'expiry', 'manual'

    -- P&L
    realized_pnl        DECIMAL(12,4),
    realized_pnl_pct    DECIMAL(8,6),
    unrealized_pnl      DECIMAL(12,4),

    -- Greeks at entry
    entry_iv            DECIMAL(10,6),
    entry_delta         DECIMAL(10,6),
    entry_theta         DECIMAL(10,6),
    entry_vega          DECIMAL(10,6),
    entry_gamma         DECIMAL(10,6),
    entry_underlying_price  DECIMAL(12,4),
    dte_at_entry        INTEGER,

    -- Risk parameters
    max_profit          DECIMAL(12,4),
    max_loss            DECIMAL(12,4),
    breakeven_price     DECIMAL(12,4),

    -- Alpaca tracking
    alpaca_order_id     VARCHAR,
    alpaca_position_id  VARCHAR,

    -- Metadata
    tags                VARCHAR[],
    notes               TEXT
);

-- ============================================================
-- LLM ANALYSES: every recommendation + outcome
-- ============================================================
CREATE TABLE IF NOT EXISTS llm_analyses (
    id                  VARCHAR PRIMARY KEY,    -- UUID
    created_at          TIMESTAMPTZ DEFAULT NOW(),

    underlying_symbol   VARCHAR NOT NULL,
    analysis_type       VARCHAR NOT NULL,       -- 'entry_recommendation', 'exit_recommendation', 'market_scan'

    -- LLM inputs
    model               VARCHAR NOT NULL,
    prompt_version      VARCHAR NOT NULL,
    context_snapshot    JSON NOT NULL,
    past_performance_summary JSON,

    -- LLM outputs
    raw_response        TEXT NOT NULL,
    recommendation      VARCHAR,               -- 'enter', 'avoid', 'exit', 'hold', 'reduce'
    confidence_score    DECIMAL(4,3),
    strategy_suggested  VARCHAR,
    reasoning_summary   TEXT,
    suggested_entry     DECIMAL(12,4),
    suggested_stop      DECIMAL(12,4),
    suggested_target    DECIMAL(12,4),

    -- Outcome (filled after trade closes)
    linked_trade_id     VARCHAR,
    was_correct         BOOLEAN,
    outcome_notes       TEXT,
    outcome_recorded_at TIMESTAMPTZ
);

-- ============================================================
-- PREDICTION ACCURACY: rolled-up stats
-- ============================================================
CREATE SEQUENCE IF NOT EXISTS prediction_accuracy_seq;

CREATE TABLE IF NOT EXISTS prediction_accuracy (
    id                  BIGINT PRIMARY KEY DEFAULT nextval('prediction_accuracy_seq'),
    computed_at         TIMESTAMPTZ DEFAULT NOW(),
    window_days         INTEGER NOT NULL,
    underlying_symbol   VARCHAR,               -- NULL = aggregate
    strategy_type       VARCHAR,               -- NULL = aggregate
    prompt_version      VARCHAR,
    model               VARCHAR,

    total_analyses      INTEGER NOT NULL,
    entered_trades      INTEGER,
    wins                INTEGER,
    losses              INTEGER,
    win_rate            DECIMAL(6,4),
    avg_return_pct      DECIMAL(8,6),
    avg_days_held       DECIMAL(8,4),
    total_pnl           DECIMAL(14,4),
    sharpe_approx       DECIMAL(8,6)
);

-- ============================================================
-- PORTFOLIO SNAPSHOTS: daily equity curve
-- ============================================================
CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    snapshot_date           DATE PRIMARY KEY,
    equity                  DECIMAL(14,4) NOT NULL,
    cash                    DECIMAL(14,4),
    buying_power            DECIMAL(14,4),
    open_positions_count    INTEGER,
    unrealized_pnl          DECIMAL(14,4),
    realized_pnl_today      DECIMAL(14,4),
    source                  VARCHAR DEFAULT 'alpaca'
);

-- ============================================================
-- WATCHLIST: symbols actively monitored
-- ============================================================
CREATE TABLE IF NOT EXISTS watchlist (
    symbol              VARCHAR PRIMARY KEY,
    added_at            TIMESTAMPTZ DEFAULT NOW(),
    priority            INTEGER DEFAULT 5,
    notes               TEXT,
    alpaca_watchlist_id VARCHAR
);

-- ============================================================
-- MIGRATIONS TRACKER (internal)
-- ============================================================
CREATE TABLE IF NOT EXISTS magpie_migrations (
    filename    VARCHAR PRIMARY KEY,
    applied_at  TIMESTAMPTZ DEFAULT NOW()
);
