-- Add entry and exit rationale columns to trade_journal.
-- These capture the reasoning behind trade decisions (from interactive sessions,
-- MCP-driven trades, or manual entries) independently of llm_analyses.

ALTER TABLE trade_journal ADD COLUMN IF NOT EXISTS entry_rationale TEXT;
ALTER TABLE trade_journal ADD COLUMN IF NOT EXISTS exit_rationale TEXT;
