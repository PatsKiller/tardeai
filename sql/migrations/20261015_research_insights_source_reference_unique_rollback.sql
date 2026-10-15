-- 20261015_research_insights_source_reference_unique_rollback.sql
-- Rollback for 20261015_research_insights_source_reference_unique{,_concurrently}.sql. Removes only the index; no
-- row is touched. Run outside a transaction (DROP INDEX CONCURRENTLY):
--     psql -X -v ON_ERROR_STOP=1 -f <this file>
SET lock_timeout = '5s';
DROP INDEX CONCURRENTLY IF EXISTS uq_research_insights_source_reference;
