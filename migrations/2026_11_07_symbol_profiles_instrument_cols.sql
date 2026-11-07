-- symbol_profiles instrument-classification columns (2026-11-07, queue item 1 / cc-deepseek-5).
--
-- These four columns were added by scripts/classify_instruments.py itself, as four separate
-- ALTER TABLE ... ADD COLUMN IF NOT EXISTS statements on EVERY live run. Each one needs an ACCESS
-- EXCLUSIVE lock on symbol_profiles — a whole-table lock, held against every reader and writer of the
-- one row per symbol the dashboard serves — while db_adapter sets lock_timeout = 3s on every
-- connection. This is the same defect that killed etf-analyst-enrich on 2026-11-07 07:00 ET (see
-- migrations/2026_11_07_symbol_profiles_analyst_cols.sql and LQ-20261107-105):
--
--   $ pg log, 2026-11-07 07:00:09.375 EST [731183] trade_ai@trade_ai
--   ERROR:  canceling statement due to lock timeout
--   STATEMENT:  ALTER TABLE symbol_profiles ADD COLUMN IF NOT EXISTS analyst_look_through_pct numeric
--
-- classify-instruments had not been killed by it yet — it runs on Saturday mornings (30 6 * * 6) when
-- the table is quiet — but the lock was taken four times per run and the window is a matter of luck,
-- not design. "IF NOT EXISTS" makes the statement idempotent, not instant.
--
-- The script now only CHECKS that these columns exist (information_schema SELECT) and exits 2 naming
-- this file if one is missing; it never asks for a table lock.
--
-- Measured 2026-11-07 (read-only psql): all four columns already exist in production and 3,459 of
-- 3,459 symbol_profiles rows carry instrument_type, so applying this is a no-op there.
-- Additive and idempotent.

ALTER TABLE symbol_profiles
    ADD COLUMN IF NOT EXISTS instrument_type text,
    ADD COLUMN IF NOT EXISTS direction_hint text,
    ADD COLUMN IF NOT EXISTS expense_ratio numeric,
    ADD COLUMN IF NOT EXISTS quote_type text;
