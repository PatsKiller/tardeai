-- Reverse of 2026_10_21_learning_loop_pr1.sql. Archives by RENAME; never drops (AGENTS.md §0 rule 6).
-- After this runs the writers find no table and skip (SAVEPOINT-guarded), and /api/v2/journal reports
-- recommendation_link_status = "unavailable". Anything that still reads the archived names is a finding.
-- Apply (operator only): psql "$DB" -v ON_ERROR_STOP=1 -f migrations/2026_10_21_learning_loop_pr1.down.sql

BEGIN;
ALTER TABLE IF EXISTS trade_recommendation_links RENAME TO trade_recommendation_links_archived_20261021;
ALTER TABLE IF EXISTS recommendation_registry RENAME TO recommendation_registry_archived_20261021;
COMMIT;
