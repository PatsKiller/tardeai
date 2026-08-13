-- 2026-08-13_two_way_reliability_n.sql
-- Phase 5 increment 2: persist per-factor sample size (n) for the reverse-learning
-- reliability gate. The scorer (hermes_watchlist_scorer) reads `<factor>_n` and damps
-- a reverse factor below its n_min (thesis_outcome=3, options_edge=5, hermes_research=5).
--
-- ADDITIVE ONLY. No DROP / rename / destructive DDL.

BEGIN;

ALTER TABLE watchlist_items
    ADD COLUMN IF NOT EXISTS thesis_outcome_n   INTEGER,
    ADD COLUMN IF NOT EXISTS options_edge_n     INTEGER,
    ADD COLUMN IF NOT EXISTS hermes_research_n  INTEGER;

COMMIT;
