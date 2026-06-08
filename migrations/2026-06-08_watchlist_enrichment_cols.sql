-- 2026-06-08_watchlist_enrichment_cols.sql
-- Additive enrichment columns on watchlist_items for the standing enrichment sweep (E-1).
-- score + trend already exist. Never touches source/screener output. No destructive change.

ALTER TABLE watchlist_items
    ADD COLUMN IF NOT EXISTS rsi              NUMERIC,
    ADD COLUMN IF NOT EXISTS setup_advisory   TEXT,
    ADD COLUMN IF NOT EXISTS last_enriched_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS price            NUMERIC,
    ADD COLUMN IF NOT EXISTS change_pct       NUMERIC,
    ADD COLUMN IF NOT EXISTS float_m          NUMERIC,
    ADD COLUMN IF NOT EXISTS rvol             NUMERIC,
    ADD COLUMN IF NOT EXISTS watch_score_kind TEXT;   -- 'strategy_qualified' | 'technical' (never a fabricated proposal score)
