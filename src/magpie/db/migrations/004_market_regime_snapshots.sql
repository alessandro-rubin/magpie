-- ============================================================
-- MARKET REGIME SNAPSHOTS: daily regime classification
-- Tracks VIX, SPY trend, and composite regime for each day.
-- Used by the analysis pipeline to inject macro context into
-- LLM prompts and for regime-conditional win rate analysis.
-- ============================================================
CREATE SEQUENCE IF NOT EXISTS market_regime_snapshots_seq;

CREATE TABLE IF NOT EXISTS market_regime_snapshots (
    id                  BIGINT PRIMARY KEY DEFAULT nextval('market_regime_snapshots_seq'),
    snapshot_date       DATE NOT NULL,
    -- VIX
    vix_level           DECIMAL(8,4),
    vix_source          VARCHAR,            -- 'yahoo_finance' | 'spy_realized_vol'
    -- SPY trend
    spy_price           DECIMAL(12,4),
    spy_sma_50          DECIMAL(12,4),
    spy_sma_200         DECIMAL(12,4),
    spy_momentum_20d    DECIMAL(8,6),       -- 20-day return
    -- Regime classification
    trend_regime        VARCHAR NOT NULL,    -- 'bullish' | 'neutral' | 'bearish'
    volatility_regime   VARCHAR NOT NULL,    -- 'low' | 'normal' | 'high'
    composite_regime    VARCHAR NOT NULL,    -- e.g. 'bullish_low_vol', 'bearish_high_vol'
    -- Breadth proxy
    spy_put_call_ratio  DECIMAL(8,4),
    -- Metadata
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_regime_snapshot_date
    ON market_regime_snapshots(snapshot_date);
