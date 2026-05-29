-- Rollback SQL for direct backtest classification of FJSCX
-- Generated 2026-05-28
-- Old values were NULL
BEGIN;
-- FJSCX id=874: NULL -> speculative_growth
UPDATE strategy_backtest_trades SET strategy_id = NULL WHERE id = 874 AND strategy_id = 'speculative_growth';
-- FJSCX id=875: NULL -> speculative_growth
UPDATE strategy_backtest_trades SET strategy_id = NULL WHERE id = 875 AND strategy_id = 'speculative_growth';
-- SHFS id=860: not changed (needs_review skipped)
COMMIT;
