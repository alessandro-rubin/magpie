-- ============================================================
-- MARKET REGIME SNAPSHOTS: daily regime classification
-- Tracks VIX, SPY trend, and composite regime for each day.
-- Used by the analysis pipeline to inject macro context into
-- LLM prompts and for regime-conditional win rate analysis.
-- ============================================================
CREATE TABLE IF NOT EXISTS market_regime_snapshots (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_date       DATE NOT NULL,
    -- VIX
    vix_level           REAL,
    vix_source          TEXT,            -- 'yahoo_finance' | 'spy_realized_vol'
    -- SPY trend
    spy_price           REAL,
    spy_sma_50          REAL,
    spy_sma_200         REAL,
    spy_momentum_20d    REAL,           -- 20-day return
    -- Regime classification
    trend_regime        TEXT NOT NULL,    -- 'bullish' | 'neutral' | 'bearish'
    volatility_regime   TEXT NOT NULL,    -- 'low' | 'normal' | 'high'
    composite_regime    TEXT NOT NULL,    -- e.g. 'bullish_low_vol', 'bearish_high_vol'
    -- Breadth proxy
    spy_put_call_ratio  REAL,
    -- Metadata
    created_at          TIMESTAMP DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_regime_snapshot_date
    ON market_regime_snapshots(snapshot_date);
