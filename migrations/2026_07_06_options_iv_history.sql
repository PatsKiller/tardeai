-- IV-rank context layer (2026-07-06): daily ATM-IV snapshots, one row per
-- symbol per day, powering lib.strategy_research.iv_history.iv_rank().
--
-- ADDITIVE on the EXISTING options_iv_history table (created 2026-06-22 by
-- migrations/2026_06_22_options_iv_history.sql; empty at the time this
-- migration shipped — its legacy writer never captured a row). Existing
-- columns (iv_pct, atm_strike, underlying, source, captured_at) are kept so
-- existing readers (options_engine._iv_rank_from_history,
-- analyst_report_builder, job_coverage_monitor) keep working unchanged:
--   * iv_pct        — ATM IV in percent (e.g. 35.2) = the spec's atm_iv
--   * source        — the spec's iv_source
--   * snapshot_date — NEW: calendar day of capture (upsert key with symbol)
--   * meta_json     — NEW: extraction provenance (contracts used, DTE window,
--                     method, spot)
-- Idempotent: safe to re-run.

ALTER TABLE options_iv_history
    ADD COLUMN IF NOT EXISTS snapshot_date DATE NOT NULL DEFAULT CURRENT_DATE;

ALTER TABLE options_iv_history
    ADD COLUMN IF NOT EXISTS meta_json JSONB NOT NULL DEFAULT '{}'::jsonb;

-- Backfill snapshot_date for any pre-existing rows (no-op on the empty table).
UPDATE options_iv_history
   SET snapshot_date = (captured_at AT TIME ZONE 'America/New_York')::date
 WHERE captured_at IS NOT NULL
   AND snapshot_date <> (captured_at AT TIME ZONE 'America/New_York')::date;

-- De-dupe guard before the unique index (keep the newest row per symbol/day).
DELETE FROM options_iv_history a
 USING options_iv_history b
 WHERE a.symbol = b.symbol
   AND a.snapshot_date = b.snapshot_date
   AND a.id < b.id;

-- One row per symbol per day — snapshot_iv() upserts ON CONFLICT on this.
CREATE UNIQUE INDEX IF NOT EXISTS uq_options_iv_history_symbol_day
    ON options_iv_history (symbol, snapshot_date);
