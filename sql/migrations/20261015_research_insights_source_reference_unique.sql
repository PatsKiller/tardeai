-- 20261015_research_insights_source_reference_unique.sql
-- UNIQUE index on research_insights(source_reference). NOT APPLIED: operator packet
-- docs/ops/packets/research-insights-unique-index-20261015/ (PREFERRED there: the CONCURRENTLY variant,
-- 20261015_research_insights_source_reference_unique_concurrently.sql, which does not block writers).
--
-- Why (CANARY_DOUBLE_EFFECT_AUDIT.md 2026-10-14, finding 2): scripts/research_insight_extractor.py guards its
-- INSERT with NOT EXISTS on source_reference ('news:<id>' / 'catalyst:<id>'). That stops a SEQUENTIAL second run
-- from duplicating, not two CONCURRENT runs (cron + n8n in the same slot). The index makes a concurrent duplicate
-- fail instead of landing.
-- Pre-checked 2026-10-15 (read-only SELECT, READ ONLY session, trade_ai@localhost:5432): 52,684 rows,
-- 52,684 distinct source_reference, 0 NULL, 0 duplicate groups; table 63 MB.
--
-- Idempotent: re-running is a no-op once the index exists. It never deletes or rewrites a row: if duplicates
-- exist it RAISES and changes nothing; if an INVALID index of the same name exists (a failed CONCURRENTLY build)
-- it RAISES so the operator drops it first (IF NOT EXISTS would otherwise keep the invalid index silently).
-- NULL source_reference values stay allowed (NULLs are distinct in a PostgreSQL unique index).
-- Locking: CREATE INDEX (non-concurrent) takes a SHARE lock, blocking INSERT/UPDATE/DELETE on research_insights
-- for the build (seconds at 63 MB). lock_timeout bounds the wait behind an open transaction.

BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '300s';

DO $$
DECLARE
    dup_groups bigint;
    idx_valid boolean;
BEGIN
    SELECT count(*) INTO dup_groups FROM (
        SELECT 1 FROM research_insights
        WHERE source_reference IS NOT NULL
        GROUP BY source_reference
        HAVING count(*) > 1
    ) d;
    IF dup_groups > 0 THEN
        RAISE EXCEPTION 'research_insights has % duplicate source_reference groups; resolve them first (this migration deletes nothing)', dup_groups;
    END IF;

    SELECT i.indisvalid INTO idx_valid
    FROM pg_index i
    WHERE i.indexrelid = to_regclass('public.uq_research_insights_source_reference');
    IF idx_valid IS FALSE THEN
        RAISE EXCEPTION 'uq_research_insights_source_reference exists but is INVALID (failed CONCURRENTLY build); DROP INDEX CONCURRENTLY it, then re-run';
    END IF;
END
$$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_research_insights_source_reference
    ON research_insights (source_reference);

COMMIT;
