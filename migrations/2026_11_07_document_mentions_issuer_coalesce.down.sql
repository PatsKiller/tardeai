-- Rollback of migrations/2026_11_07_document_mentions_issuer_coalesce.sql (LQ-20261107-358).
--
-- Drops the coalesced unique index and nothing else. uq_docmentions was never removed by the up
-- migration, so identity/upsert behaviour is unchanged by this rollback; what is lost is the
-- protection against a NULL-issuer duplicate. scripts/lib/document_mentions.py probes pg_indexes and
-- falls back to its pre-migration ON CONFLICT clause, so the backfill keeps working either way.

DROP INDEX IF EXISTS uq_docmentions_issuer_coalesce;
