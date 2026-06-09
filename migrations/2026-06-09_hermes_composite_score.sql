-- 2026-06-09_hermes_composite_score.sql — Hermes composite watchlist score (H-1/H-2). Additive.
ALTER TABLE watchlist_items
    ADD COLUMN IF NOT EXISTS hermes_composite_score  NUMERIC,
    ADD COLUMN IF NOT EXISTS hermes_rank             INT,
    ADD COLUMN IF NOT EXISTS hermes_score_components JSONB,   -- per-factor breakdown = the H-2 intel card data
    ADD COLUMN IF NOT EXISTS hermes_scored_at        TIMESTAMPTZ;
