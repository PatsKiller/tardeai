-- ticker_dividend_data: mark rows written by the retired dividend provider SUPERSEDED (operator decision 2026-10-26,
-- verbatim: "widen the dividend refresh to cover everything you hold or watch; Yahoo Finance feed … switched on:
-- yes"). The prospectus accuracy audit (2026-10-26, finding A2) measured the retired vendor's fund rows at 3-5x the
-- real annual distribution; that vendor was retired 2026-09-13 (config/data_source_authority.json dividends.retired).
--
-- NEEDS OPERATOR. Written, not applied. Readers already ignore these rows by their source column
-- (scripts/lib/dividend_source_trust.py), so nothing waits on this file; it adds the durable audit marker.
-- Adds two nullable columns and stamps the retired-provider rows. No row is deleted and no value is changed
-- (AGENTS.md section 0 rule 6). sync_dividend_data.py clears the marker when a yfinance refresh replaces the row.
-- Idempotent: ADD COLUMN IF NOT EXISTS; only rows not yet stamped are stamped.
-- Plan (dry run):     psql "$DB" -c "SELECT source, count(*) FROM ticker_dividend_data GROUP BY 1 ORDER BY 2 DESC"
-- Apply (operator):   psql "$DB" -v ON_ERROR_STOP=1 -f migrations/2026_10_26_ticker_dividend_superseded.sql
-- Verify (operator):  psql "$DB" -c "SELECT source, count(*) FILTER (WHERE superseded_at IS NOT NULL) AS superseded,
--                                    count(*) AS total FROM ticker_dividend_data GROUP BY 1"
-- Reverse (operator): migrations/2026_10_26_ticker_dividend_superseded.down.sql

BEGIN;

ALTER TABLE ticker_dividend_data ADD COLUMN IF NOT EXISTS superseded_at timestamptz;
ALTER TABLE ticker_dividend_data ADD COLUMN IF NOT EXISTS superseded_reason text;

UPDATE ticker_dividend_data
   SET superseded_at = now(),
       superseded_reason = 'retired provider (fmp, retired 2026-09-13); prospectus accuracy audit 2026-10-26 A2: '
                           || 'fund annual dividends 3-5x real; superseded by yfinance refresh'
 WHERE superseded_at IS NULL
   AND COALESCE(source, '') ~* '^(fmp)([_-]|$)';

COMMIT;
