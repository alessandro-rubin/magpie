-- Trading notes: persistent memory for strategic context, deadlines, and observations.
-- Injected into feedback loop so every session starts with full context.

CREATE TABLE IF NOT EXISTS trading_notes (
    id              TEXT PRIMARY KEY,
    category        TEXT NOT NULL,       -- 'deadline' | 'strategy' | 'observation' | 'portfolio'
    title           TEXT NOT NULL,       -- short label for listing
    content         TEXT NOT NULL,       -- full note body
    source_trade_id TEXT,                -- optional: linked trade
    expires_at      TIMESTAMP,           -- optional: auto-expire (useful for deadlines)
    resolved        INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMP NOT NULL DEFAULT (datetime('now')),
    updated_at      TIMESTAMP NOT NULL DEFAULT (datetime('now')),

    FOREIGN KEY (source_trade_id) REFERENCES trade_journal(id)
);

CREATE INDEX IF NOT EXISTS idx_trading_notes_category ON trading_notes(category);
CREATE INDEX IF NOT EXISTS idx_trading_notes_resolved ON trading_notes(resolved);
CREATE INDEX IF NOT EXISTS idx_trading_notes_expires  ON trading_notes(expires_at);
