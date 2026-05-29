-- Rollback SHFS id=860 manual classification
-- Applied 2026-05-29 by operator approval (Option A direct SQL)
UPDATE strategy_backtest_trades
SET strategy_id = NULL
WHERE id = 860
  AND symbol = 'SHFS'
  AND strategy_id = 'speculative_growth';
