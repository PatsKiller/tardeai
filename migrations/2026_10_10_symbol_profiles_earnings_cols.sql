-- symbol_profiles earnings columns (2026-10-10, refactor wave 2 of the cron -> n8n program; cron:L551).
--
-- These six columns were added by scripts/earnings_enrich.py itself, as an
-- ALTER TABLE ... ADD COLUMN IF NOT EXISTS on EVERY run (ensure_columns, also on --dry). That ALTER
-- takes an ACCESS EXCLUSIVE lock on symbol_profiles, and at 06:35-06:45 it contends with the other
-- symbol_profiles writers (L552 fund_technicals_enrich, L553, L508 build_symbol_profiles, L502):
-- logs/earnings_enrich.log carries 2 LockNotAvailable failures. The script now only checks that these
-- columns exist (information_schema SELECT) and exits 2 naming this file if one is missing.
--
-- Measured 2026-10-10 (read-only information_schema query): all six columns already exist in
-- production, so applying this is a no-op there. Additive and idempotent.

ALTER TABLE symbol_profiles
    ADD COLUMN IF NOT EXISTS next_earnings_date date,
    ADD COLUMN IF NOT EXISTS last_earnings_date date,
    ADD COLUMN IF NOT EXISTS last_eps_estimate numeric,
    ADD COLUMN IF NOT EXISTS last_eps_actual numeric,
    ADD COLUMN IF NOT EXISTS last_eps_surprise_pct numeric,
    ADD COLUMN IF NOT EXISTS earnings_updated_at timestamptz;
