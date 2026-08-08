-- 20260808_strategy_signals_unique.sql
-- strategy_signals has no uniqueness constraint — duplicate signals are possible
-- from concurrent syncs or re-runs.  Pre-checked 2026-08-08: zero duplicates exist.
-- The writer (strategy_signal_sync.py) now uses ON CONFLICT DO NOTHING.
CREATE UNIQUE INDEX IF NOT EXISTS uq_strategy_signals_fire
    ON strategy_signals (strategy_id, symbol, signal_type, fired_at);
