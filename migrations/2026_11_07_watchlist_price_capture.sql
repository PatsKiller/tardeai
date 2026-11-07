-- LQ-20261107-273 — a stored price carries the time it was actually OBSERVED, and a failed lookup is its own fact.
--
-- watchlist_items.price is a snapshot whose only timestamp was last_enriched_at, which the enrichment sweep moves on
-- EVERY attempt — including a failed price lookup (LQ-20261107-56 keeps the last good price but still stamps the
-- attempt). api_v2 derives the card's price_as_of from last_enriched_at, so after a failed lookup the card presented
-- an older price with the timestamp of the attempt that could not replace it: measured on 2026-11-07, 8 rows carried
-- "price stale (last good price kept)" with a price last observed at an unknown, earlier time.
--
-- Only scripts/watchlist_enrichment_sweep.py writes these columns; it detects them and keeps its pre-LQ-273 UPDATE
-- until this migration is applied, so applying it before or after the code ships is safe either way.
--
--   price_observed_at       when the stored price was actually taken. NULL = unknown; never guessed.
--   price_observed_source   which rung of the price ladder supplied it: market_quotes | finviz.
--   price_lookup_failed_at  the latest failed price lookup; NULL once a lookup succeeds again.
--
-- Rollback: migrations/2026_11_07_watchlist_price_capture.down.sql.

ALTER TABLE watchlist_items
    ADD COLUMN IF NOT EXISTS price_observed_at      timestamp with time zone,
    ADD COLUMN IF NOT EXISTS price_observed_source  text,
    ADD COLUMN IF NOT EXISTS price_lookup_failed_at timestamp with time zone;

COMMENT ON COLUMN watchlist_items.price_observed_at IS
    'When watchlist_items.price was actually observed by the enrichment sweep. NULL = unknown, never back-filled by guess.';
COMMENT ON COLUMN watchlist_items.price_observed_source IS
    'Price ladder rung that supplied watchlist_items.price: market_quotes | finviz.';
COMMENT ON COLUMN watchlist_items.price_lookup_failed_at IS
    'Latest failed price lookup for this row (kept the last good price); NULL when the last lookup succeeded.';

-- Backfill what is knowable. Before LQ-56 (2026-11-07) a failed lookup wrote NULL, so a non-NULL price came from a
-- successful lookup at last_enriched_at. Rows the fixed sweep marked "price stale" were KEPT across a failed lookup,
-- so their price predates last_enriched_at and its real time is unknown — those stay NULL on purpose.
UPDATE watchlist_items
   SET price_observed_at = last_enriched_at
 WHERE price IS NOT NULL
   AND price_observed_at IS NULL
   AND last_enriched_at IS NOT NULL
   AND COALESCE(setup_advisory, '') NOT LIKE '%price stale%';
