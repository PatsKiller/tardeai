-- Rollback of migrations/2026_11_07_watchlist_price_capture.sql (LQ-20261107-273).
--
-- Drops the three price-capture columns. The sweep detects their absence and falls back to its pre-LQ-273 UPDATE,
-- so this rollback leaves the enrichment lane working; what it loses is the price's own observation time, the rung
-- that supplied it, and the record of a failed lookup (the LQ-56 "price stale (last good price kept)" advisory text
-- is unaffected because it lives in setup_advisory).

ALTER TABLE watchlist_items
    DROP COLUMN IF EXISTS price_lookup_failed_at,
    DROP COLUMN IF EXISTS price_observed_source,
    DROP COLUMN IF EXISTS price_observed_at;
