-- 20261015_research_insights_source_reference_unique_concurrently.sql
-- CONCURRENTLY variant of 20261015_research_insights_source_reference_unique.sql (same index, same name).
-- NOT APPLIED: operator packet docs/ops/packets/research-insights-unique-index-20261015/.
--
-- Run it OUTSIDE a transaction, in autocommit, one statement at a time:
--     psql -X -v ON_ERROR_STOP=1 -f <this file>         (no -1 / --single-transaction, no BEGIN)
-- CREATE INDEX CONCURRENTLY cannot run inside a transaction block. It takes only a SHARE UPDATE EXCLUSIVE lock,
-- so the extractor keeps inserting while the index builds; it waits for transactions older than it to finish.
--
-- Idempotent: every statement is a check or IF NOT EXISTS, so a re-run after success is a no-op. It deletes no
-- row. A failed CONCURRENTLY build leaves an INVALID index behind; the first check refuses in that case (IF NOT
-- EXISTS would skip the build and keep the invalid index), and the operator runs
--     DROP INDEX CONCURRENTLY IF EXISTS uq_research_insights_source_reference;
-- before re-running. The last check refuses unless the index is present and VALID.

SET lock_timeout = '5s';
SET statement_timeout = 0;

-- 1. Preflight: no duplicate source_reference, no INVALID leftover index.
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

-- 2. Build without blocking writers.
CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_research_insights_source_reference
    ON research_insights (source_reference);

-- 3. Postcheck: present, valid, unique, on exactly (source_reference).
DO $$
DECLARE
    r record;
BEGIN
    SELECT i.indisvalid, i.indisunique, pg_get_indexdef(i.indexrelid) AS def INTO r
    FROM pg_index i
    WHERE i.indexrelid = to_regclass('public.uq_research_insights_source_reference');
    IF r IS NULL OR r.indisvalid IS DISTINCT FROM TRUE OR r.indisunique IS DISTINCT FROM TRUE THEN
        RAISE EXCEPTION 'uq_research_insights_source_reference missing, INVALID or not unique after the build';
    END IF;
    IF r.def NOT LIKE '%(source_reference)' THEN
        RAISE EXCEPTION 'uq_research_insights_source_reference has an unexpected definition: %', r.def;
    END IF;
END
$$;
