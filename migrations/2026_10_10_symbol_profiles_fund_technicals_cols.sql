-- symbol_profiles fund-technicals columns (2026-10-10, refactor wave 1 of the cron -> n8n program).
--
-- These five columns were added by scripts/fund_technicals_enrich.py itself, as an
-- ALTER TABLE ... ADD COLUMN IF NOT EXISTS on EVERY run. That ALTER takes an ACCESS EXCLUSIVE lock
-- on symbol_profiles, and at 06:3x-06:4x it collided with the other symbol_profiles writers:
-- logs/fund_technicals.log shows 9 LockNotAvailable failures against 2 successful outputs, and the
-- 2026-10-09 06:38 run died on the ALTER itself. The script now only checks that these columns
-- exist (information_schema SELECT) and exits 2 naming this file if one is missing.
--
-- Measured 2026-10-10: all five columns already exist in production, so applying this is a no-op
-- there. Additive and idempotent.

ALTER TABLE symbol_profiles
    ADD COLUMN IF NOT EXISTS rsi14 numeric,
    ADD COLUMN IF NOT EXISTS perf_week_pct numeric,
    ADD COLUMN IF NOT EXISTS perf_month_pct numeric,
    ADD COLUMN IF NOT EXISTS sma50_pct numeric,
    ADD COLUMN IF NOT EXISTS technicals_updated_at timestamptz;
