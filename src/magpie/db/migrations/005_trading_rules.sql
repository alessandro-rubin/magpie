-- Trading rules: lessons learned from past trades, injected into analysis prompts.

CREATE TABLE IF NOT EXISTS trading_rules (
    id              VARCHAR PRIMARY KEY DEFAULT uuid(),
    category        VARCHAR NOT NULL,       -- 'sizing' | 'risk' | 'entry' | 'macro' | 'execution'
    rule            TEXT NOT NULL,
    source_trade_id VARCHAR,                -- optional: the trade that taught us this
    active          BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    FOREIGN KEY (source_trade_id) REFERENCES trade_journal(id)
);

CREATE INDEX idx_trading_rules_category ON trading_rules(category);
CREATE INDEX idx_trading_rules_active   ON trading_rules(active);
