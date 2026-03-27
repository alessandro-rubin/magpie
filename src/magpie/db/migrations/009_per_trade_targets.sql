-- Per-trade profit target and stop loss thresholds.
-- NULL means "use global default from settings".
-- Values are fractions (e.g., 0.50 = 50% of max profit).
ALTER TABLE trade_journal ADD COLUMN profit_target_pct REAL;
ALTER TABLE trade_journal ADD COLUMN stop_loss_pct REAL;
