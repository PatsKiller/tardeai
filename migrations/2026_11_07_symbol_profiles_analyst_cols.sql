-- symbol_profiles analyst look-through columns (2026-11-07, LQ-20261107-105).
--
-- These two columns were added by scripts/etf_analyst_enrich.py itself, as an
-- ALTER TABLE ... ADD COLUMN IF NOT EXISTS on EVERY run. That ALTER needs an ACCESS EXCLUSIVE lock
-- on symbol_profiles — a whole-table lock, held against every reader and writer of the one row per
-- symbol the dashboard serves — while db_adapter sets lock_timeout = 3s on every connection. The
-- 2026-11-07 07:00 ET run died on it exactly as the 2026-10-10 fund_technicals_enrich.py refactor
-- predicted for this script's sibling:
--
--   $ pg log, 2026-11-07 07:00:09.375 EST [731183] trade_ai@trade_ai
--   ERROR:  canceling statement due to lock timeout
--   STATEMENT:  ALTER TABLE symbol_profiles ADD COLUMN IF NOT EXISTS analyst_look_through_pct numeric
--
-- The script now only CHECKS that these columns exist (information_schema SELECT) and exits 2
-- naming this file if one is missing; it never asks for a table lock.
--
-- Measured 2026-11-07: both columns already exist in production, so applying this is a no-op there.
-- Additive and idempotent.

ALTER TABLE symbol_profiles
    ADD COLUMN IF NOT EXISTS analyst_look_through_pct numeric,
    ADD COLUMN IF NOT EXISTS analyst_basis text;
