-- Add current_underlying_price to trade_journal
-- Updated during position sync so the dashboard can show it on payoff diagrams.
ALTER TABLE trade_journal ADD COLUMN current_underlying_price REAL;
