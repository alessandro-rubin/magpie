-- Query performance indexes for the most common access patterns

CREATE INDEX IF NOT EXISTS idx_journal_underlying  ON trade_journal(underlying_symbol);
CREATE INDEX IF NOT EXISTS idx_journal_status      ON trade_journal(status);
CREATE INDEX IF NOT EXISTS idx_journal_entry_time  ON trade_journal(entry_time);
CREATE INDEX IF NOT EXISTS idx_journal_strategy    ON trade_journal(strategy_type);
CREATE INDEX IF NOT EXISTS idx_journal_mode        ON trade_journal(trade_mode);

CREATE INDEX IF NOT EXISTS idx_llm_symbol          ON llm_analyses(underlying_symbol);
CREATE INDEX IF NOT EXISTS idx_llm_linked_trade    ON llm_analyses(linked_trade_id);
CREATE INDEX IF NOT EXISTS idx_llm_created_at      ON llm_analyses(created_at);
CREATE INDEX IF NOT EXISTS idx_llm_prompt_version  ON llm_analyses(prompt_version);

CREATE INDEX IF NOT EXISTS idx_snapshots_contract_time ON option_snapshots(contract_id, snapshot_time);
CREATE INDEX IF NOT EXISTS idx_snapshots_time          ON option_snapshots(snapshot_time);

CREATE INDEX IF NOT EXISTS idx_contracts_underlying ON option_contracts(underlying_symbol);
CREATE INDEX IF NOT EXISTS idx_contracts_expiry     ON option_contracts(expiration_date);
