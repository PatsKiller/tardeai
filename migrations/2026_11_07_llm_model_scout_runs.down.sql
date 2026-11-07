-- Reverse of 2026_11_07_llm_model_scout_runs.sql.
--
-- The table is advisory history only (nothing routes from it); the monthly JSON files under
-- data/runtime/llm_model_scout/ keep a copy of every report, so a rollback loses no decision.

DROP INDEX IF EXISTS llm_model_scout_runs_period_idx;
DROP TABLE IF EXISTS llm_model_scout_runs;
