-- Every issuer a document mentions, and whether the document is ABOUT it.
--
-- Existing identity tagging is ONE tag per row, from the row's `symbol` column;
-- it never reads the body. Measured 2026-09-06 over 60 tagged news articles:
-- 58% mention other tickers in the body, 64 additional issuers untagged.
--
-- THE DISTINCTION THIS TABLE EXISTS FOR
--   "Morgan Stanley estimates Apple foldable iPhone could generate…"
-- mentions MS and NDAQ, but the article is ABOUT Apple. Morgan Stanley is the
-- SOURCE of the estimate. Tagging all three as equal subjects attaches the
-- article to issuers it is not about, and every downstream join inherits it.
-- A wrong tag is worse than no tag, because it looks like coverage.

CREATE TABLE IF NOT EXISTS document_mentions (
    id              BIGSERIAL PRIMARY KEY,
    observed_at     TIMESTAMPTZ NOT NULL DEFAULT now(),

    source_table    TEXT   NOT NULL,
    source_id       BIGINT NOT NULL,

    symbol          TEXT,
    subject_guid    UUID,
    issuer_guid     UUID,
    identity_status TEXT,

    -- subject vs passing reference — the point of the table
    role            TEXT NOT NULL CHECK (role IN ('subject','mentioned','unresolved')),

    -- HOW the role was decided. Mandatory: without it a model's guess and a
    -- deterministic fact are indistinguishable a month later, and the model's
    -- output cannot be re-audited separately from the rest.
    role_source     TEXT NOT NULL CHECK (role_source IN ('deterministic','model','operator')),
    role_confidence NUMERIC,          -- NULL when deterministic

    matched_via     TEXT,             -- 'ticker' | 'company_name'
    matched_text    TEXT,             -- the document's own words

    schema_version  TEXT NOT NULL DEFAULT 'DocumentMention@v1',
    authority       TEXT NOT NULL DEFAULT 'READ_ONLY_ADVISORY'
);

-- One row per (document, issuer, role). Re-running the extractor must be a
-- no-op, not a duplicate.
CREATE UNIQUE INDEX IF NOT EXISTS uq_docmentions
    ON document_mentions (source_table, source_id, issuer_guid, role);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_dm_issuer  ON document_mentions (issuer_guid);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_dm_subject ON document_mentions (subject_guid);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_dm_source  ON document_mentions (source_table, source_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_dm_role    ON document_mentions (role, issuer_guid);
