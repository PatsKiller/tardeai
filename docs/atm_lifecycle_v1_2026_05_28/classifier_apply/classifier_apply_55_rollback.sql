-- Rollback SQL for classifier apply batch (commit bbe3d54)
-- Generated 2026-05-28
-- Old strategy_id values were NULL, empty, or "unknown" before this batch
-- This restores them to NULL

BEGIN;

-- ADBE: was NULL -> speculative_growth
UPDATE strategy_backtest_trades SET strategy_id = NULL WHERE symbol = 'ADBE' AND strategy_id = 'speculative_growth';

-- AGMH: was NULL -> speculative_growth
UPDATE strategy_backtest_trades SET strategy_id = NULL WHERE symbol = 'AGMH' AND strategy_id = 'speculative_growth';

-- AMD: was NULL -> core_growth_compounder
UPDATE strategy_backtest_trades SET strategy_id = NULL WHERE symbol = 'AMD' AND strategy_id = 'core_growth_compounder';

-- APAM: was NULL -> speculative_growth
UPDATE strategy_backtest_trades SET strategy_id = NULL WHERE symbol = 'APAM' AND strategy_id = 'speculative_growth';

-- ARKG: was NULL -> speculative_growth
UPDATE strategy_backtest_trades SET strategy_id = NULL WHERE symbol = 'ARKG' AND strategy_id = 'speculative_growth';

-- AXTI: was NULL -> speculative_growth
UPDATE strategy_backtest_trades SET strategy_id = NULL WHERE symbol = 'AXTI' AND strategy_id = 'speculative_growth';

-- BNAI: was NULL -> speculative_growth
UPDATE strategy_backtest_trades SET strategy_id = NULL WHERE symbol = 'BNAI' AND strategy_id = 'speculative_growth';

-- BRO: was NULL -> recovery_watch
UPDATE strategy_backtest_trades SET strategy_id = NULL WHERE symbol = 'BRO' AND strategy_id = 'recovery_watch';

-- DFSC: was NULL -> speculative_growth
UPDATE strategy_backtest_trades SET strategy_id = NULL WHERE symbol = 'DFSC' AND strategy_id = 'speculative_growth';

-- EKSO: was NULL -> speculative_growth
UPDATE strategy_backtest_trades SET strategy_id = NULL WHERE symbol = 'EKSO' AND strategy_id = 'speculative_growth';

-- FATN: was NULL -> swing_trade
UPDATE strategy_backtest_trades SET strategy_id = NULL WHERE symbol = 'FATN' AND strategy_id = 'swing_trade';

-- FUSE: was NULL -> speculative_growth
UPDATE strategy_backtest_trades SET strategy_id = NULL WHERE symbol = 'FUSE' AND strategy_id = 'speculative_growth';

-- GSIT: was NULL -> speculative_growth
UPDATE strategy_backtest_trades SET strategy_id = NULL WHERE symbol = 'GSIT' AND strategy_id = 'speculative_growth';

-- GXAI: was NULL -> speculative_growth
UPDATE strategy_backtest_trades SET strategy_id = NULL WHERE symbol = 'GXAI' AND strategy_id = 'speculative_growth';

-- IBIO: was NULL -> speculative_growth
UPDATE strategy_backtest_trades SET strategy_id = NULL WHERE symbol = 'IBIO' AND strategy_id = 'speculative_growth';

-- IVF: was NULL -> speculative_growth
UPDATE strategy_backtest_trades SET strategy_id = NULL WHERE symbol = 'IVF' AND strategy_id = 'speculative_growth';

-- LASE: was NULL -> swing_breakout
UPDATE strategy_backtest_trades SET strategy_id = NULL WHERE symbol = 'LASE' AND strategy_id = 'swing_breakout';

-- MSGM: was NULL -> speculative_growth
UPDATE strategy_backtest_trades SET strategy_id = NULL WHERE symbol = 'MSGM' AND strategy_id = 'speculative_growth';

-- NERV: was NULL -> speculative_growth
UPDATE strategy_backtest_trades SET strategy_id = NULL WHERE symbol = 'NERV' AND strategy_id = 'speculative_growth';

-- NUWE: was NULL -> recovery_watch
UPDATE strategy_backtest_trades SET strategy_id = NULL WHERE symbol = 'NUWE' AND strategy_id = 'recovery_watch';

-- PFE: was NULL -> dividend_growth_compounder
UPDATE strategy_backtest_trades SET strategy_id = NULL WHERE symbol = 'PFE' AND strategy_id = 'dividend_growth_compounder';

-- PHIO: was NULL -> speculative_growth
UPDATE strategy_backtest_trades SET strategy_id = NULL WHERE symbol = 'PHIO' AND strategy_id = 'speculative_growth';

-- SHPH: was NULL -> speculative_growth
UPDATE strategy_backtest_trades SET strategy_id = NULL WHERE symbol = 'SHPH' AND strategy_id = 'speculative_growth';

-- SOPA: was NULL -> recovery_watch
UPDATE strategy_backtest_trades SET strategy_id = NULL WHERE symbol = 'SOPA' AND strategy_id = 'recovery_watch';

-- SPRC: was NULL -> swing_trade
UPDATE strategy_backtest_trades SET strategy_id = NULL WHERE symbol = 'SPRC' AND strategy_id = 'swing_trade';

-- STI: was NULL -> speculative_growth
UPDATE strategy_backtest_trades SET strategy_id = NULL WHERE symbol = 'STI' AND strategy_id = 'speculative_growth';

-- TRX: was NULL -> speculative_growth
UPDATE strategy_backtest_trades SET strategy_id = NULL WHERE symbol = 'TRX' AND strategy_id = 'speculative_growth';

-- XMTR: was NULL -> sector_rotation
UPDATE strategy_backtest_trades SET strategy_id = NULL WHERE symbol = 'XMTR' AND strategy_id = 'sector_rotation';

COMMIT;