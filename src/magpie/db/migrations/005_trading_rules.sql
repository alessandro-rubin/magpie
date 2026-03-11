-- Trading rules: lessons learned from past trades, injected into analysis prompts.

CREATE TABLE IF NOT EXISTS trading_rules (
    id              TEXT PRIMARY KEY,    -- UUID generated in Python
    category        TEXT NOT NULL,       -- 'sizing' | 'risk' | 'entry' | 'macro' | 'execution'
    rule            TEXT NOT NULL,
    source_trade_id TEXT,                -- optional: the trade that taught us this
    active          INTEGER NOT NULL DEFAULT 1,
    created_at      TIMESTAMP NOT NULL DEFAULT (datetime('now')),
    updated_at      TIMESTAMP NOT NULL DEFAULT (datetime('now')),

    FOREIGN KEY (source_trade_id) REFERENCES trade_journal(id)
);

CREATE INDEX IF NOT EXISTS idx_trading_rules_category ON trading_rules(category);
CREATE INDEX IF NOT EXISTS idx_trading_rules_active   ON trading_rules(active);
