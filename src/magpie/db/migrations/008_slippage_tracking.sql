-- Add fill_price column for slippage tracking.
-- fill_price = actual Alpaca avg_entry_price, populated during sync.
-- slippage = fill_price - entry_price (positive = worse fill than expected).
ALTER TABLE trade_journal ADD COLUMN fill_price REAL;
