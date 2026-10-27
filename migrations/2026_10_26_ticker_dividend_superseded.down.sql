-- Reverse of 2026_10_26_ticker_dividend_superseded.sql: clear the superseded marker. The columns are KEPT (dropping
-- them would destroy the audit history, AGENTS.md section 0 rule 6); readers keep ignoring retired-provider rows by
-- source (scripts/lib/dividend_source_trust.py) until that code is reverted. Apply (operator only):
--     psql "$DB" -v ON_ERROR_STOP=1 -f migrations/2026_10_26_ticker_dividend_superseded.down.sql

BEGIN;

UPDATE ticker_dividend_data SET superseded_at = NULL, superseded_reason = NULL WHERE superseded_at IS NOT NULL;

COMMIT;
