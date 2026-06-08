-- 2026-06-08_provenance_backfill.sql
-- One-time additive backfill of the NEW provenance columns on watchlist_items (the base table of
-- the watchlist_symbol_master VIEW). Maps the existing coarse `source` to origin_system so the new
-- pill row isn't blank. Touches ONLY the additive provenance columns — never `source`, screener
-- output, or any pre-existing column. Idempotent (WHERE origin_system IS NULL).

BEGIN;

UPDATE watchlist_items SET origin_system = CASE
    WHEN source ILIKE 'portfolio%' OR source ILIKE 'prev_traded%'                 THEN 'portfolio'
    WHEN source ILIKE 'paper_proposal%' OR source ILIKE 'trade_ai%'
         OR source ILIKE 'static_universe%' OR source ILIKE 'screener%'          THEN 'trade_ai_screener'
    WHEN source ILIKE 'ai_discovered%' OR source ILIKE 'ai_watchlist%'           THEN 'agent_discovery'
    WHEN source ILIKE 'personal%' OR source ILIKE 'operator%'                    THEN 'operator'
    WHEN source ILIKE 'hermes%'                                                  THEN 'hermes'
    WHEN source ILIKE 'social%'                                                  THEN 'social'
    ELSE COALESCE(origin_system, 'trade_ai_screener')
END
WHERE origin_system IS NULL;

UPDATE watchlist_items
   SET first_seen_at     = COALESCE(first_seen_at, last_seen_at, updated_at),
       last_validated_at = COALESCE(last_validated_at, updated_at)
 WHERE first_seen_at IS NULL OR last_validated_at IS NULL;

COMMIT;
