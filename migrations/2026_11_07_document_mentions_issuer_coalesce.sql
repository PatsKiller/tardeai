-- LQ-20261107-358 — uq_docmentions never fired for a mention with NO issuer, so the backfill could
-- duplicate its own unresolved rows on every run.
--
-- uq_docmentions is UNIQUE (source_table, source_id, issuer_guid, role). PostgreSQL treats every NULL
-- as distinct, so a row whose issuer could not be resolved (issuer_guid IS NULL) matched no existing
-- row and was inserted again by the next backfill pass. Measured on trade_ai 2026-11-07:
--
--   document_mentions rows                     372,344
--   rows with issuer_guid IS NULL               32,550
--   duplicate groups (document, role)            1,599   -- ALL of them in the NULL-issuer rows
--   duplicate rows (extras beyond the first)     1,681
--   duplicate groups with a NON-null issuer          0   -- the old index did its job there
--
-- 1,599 groups is a 17% overcount on the 9,017 unresolved-subject rows. "Unknown issuer" is a real
-- answer and the row must keep its NULL; the uniqueness rule is what needs a value. So the index
-- coalesces the issuer to a sentinel UUID rather than the column storing one.
--
-- ORDER SAFETY. The old index uq_docmentions is LEFT IN PLACE: pre-migration code keeps its
-- (source_table, source_id, issuer_guid, role) ON CONFLICT and keeps working. The new index adds the
-- constraint the old one could not express, and scripts/lib/document_mentions.py probes pg_indexes and
-- switches its ON CONFLICT clause once this index exists (LQ-273's pre/post-migration pattern). Apply
-- this migration before or after the code ships; either order is safe.
--
-- PRECONDITION. The unique build fails on existing duplicates, and a bare "could not create unique
-- index" would not say what to do. This block stops first and names the purge script:
--
--   scripts/purge_document_mentions_false_positives.py --class null_duplicate --apply
--
-- Rollback: migrations/2026_11_07_document_mentions_issuer_coalesce.down.sql.
--
-- Idempotent: re-running creates nothing and changing nothing.

DO $$
DECLARE
    groups  bigint;
    extras  bigint;
BEGIN
    SELECT count(*), coalesce(sum(n - 1), 0)
      INTO groups, extras
      FROM (SELECT count(*) AS n
              FROM document_mentions
             WHERE issuer_guid IS NULL
             GROUP BY source_table, source_id, role
            HAVING count(*) > 1) d;

    IF groups > 0 THEN
        RAISE EXCEPTION
            'document_mentions has % duplicate groups (% extra rows) with a NULL issuer; the unique index cannot be built yet. Run scripts/purge_document_mentions_false_positives.py --class null_duplicate (dry run first, then --apply), then re-run this migration.',
            groups, extras;
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_docmentions_issuer_coalesce
    ON document_mentions (source_table, source_id,
                          COALESCE(issuer_guid, '00000000-0000-0000-0000-000000000000'::uuid),
                          role);

COMMENT ON INDEX uq_docmentions_issuer_coalesce IS
    'One row per (document, issuer-or-unknown, role). COALESCE(issuer_guid, zero-uuid) because PostgreSQL treats every NULL as distinct, which let the backfill re-insert its unresolved rows (LQ-20261107-358).';
