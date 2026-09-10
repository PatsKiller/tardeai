-- NarrativeSubjectLink@v1 — what a narrative is ABOUT, across every subject type.
-- Phase 1 of the narrative-identity plan. Campaign m2-canary-20260907.
--
-- WHY A NEW TABLE AND NOT COLUMNS ON FIFTEEN EXISTING ONES.
-- Two reasons, both load-bearing.
--
-- 1. Cardinality. A defense thesis is about a theme AND a sector AND several
--    securities. `two_way_curation.rotation_signal_to_feedback` returns None
--    without a sector and sets `symbol` only when an ETF proxy exists — rotation
--    is sector-first by design. A single subject_guid column cannot hold that,
--    and forcing one recreates the sector_move defect (13 of 14 sector_move rows
--    carry a SECURITY guid for a SECTOR event) one table over.
--
-- 2. Safety. This repo's own postmortem, sql/research_identity_tags.sql:
--    `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` takes ACCESS EXCLUSIVE, and a
--    taxonomy_tagger run took a table down on 2026-07-02.
--    agent_recommendation_registry is 462,902 rows with a 30 8 * * 1-5 writer;
--    watchlist_final_synthesis has writers firing every 5-15 minutes nearly
--    around the clock. This migration touches NEITHER — it adds one new table
--    and takes no lock on anything live.
--
-- FORWARD-ONLY. Nothing here backfills. Historical rows acquire links only
-- where identity is derivable from data already in the row; anything else stays
-- UNKNOWN_LEGACY. Inferring a subject from prose would make the ledger look
-- better than the truth, which is the same rule the settlement migration held.

SET lock_timeout = '5s';

CREATE TABLE IF NOT EXISTS narrative_subjects (
    link_guid        TEXT PRIMARY KEY,
    row_guid         TEXT NOT NULL,
    source_table     TEXT NOT NULL,
    source_id        TEXT NOT NULL,
    entity_type      TEXT NOT NULL,
    subject_guid     TEXT NOT NULL,
    semantic_subject TEXT,
    relationship     TEXT NOT NULL DEFAULT 'subject',
    confidence       TEXT NOT NULL DEFAULT 'CANDIDATE',
    author_agent_id  TEXT NOT NULL,
    schema_version   TEXT NOT NULL DEFAULT 'NarrativeSubjectLink@v1',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- The vocabulary is enforced here, not just in Python. tradeai_record_envelope
-- .entity_ref() downgrades an unknown entity_type to "OTHER" — permissive is
-- right for an envelope and wrong for a subject link, where a typo would join to
-- nothing and report no error. NOT VALID so the constraint applies to new rows
-- without scanning; there are no rows yet, but the habit is the point.
ALTER TABLE narrative_subjects
    ADD CONSTRAINT narrative_subjects_entity_type_ck
    CHECK (entity_type IN
           ('SECURITY','SECTOR','INDUSTRY','THEME','PORTFOLIO','STRATEGY')) NOT VALID;

ALTER TABLE narrative_subjects
    ADD CONSTRAINT narrative_subjects_relationship_ck
    CHECK (relationship IN ('subject','mentioned','from','to','peer')) NOT VALID;

ALTER TABLE narrative_subjects
    ADD CONSTRAINT narrative_subjects_confidence_ck
    CHECK (confidence IN ('CONFIRMED','CANDIDATE','UNKNOWN_LEGACY')) NOT VALID;

-- "Everything this narrative is about" — the join the CIO write path uses.
CREATE INDEX IF NOT EXISTS narrative_subjects_row_idx
    ON narrative_subjects (row_guid);

-- "Every narrative about this sector / this strategy / this security" — the
-- rollup that fifteen untagged surfaces made impossible.
CREATE INDEX IF NOT EXISTS narrative_subjects_subject_idx
    ON narrative_subjects (subject_guid, created_at DESC);

-- Coverage measurement per lane, so the gap stays honest rather than assumed.
CREATE INDEX IF NOT EXISTS narrative_subjects_source_idx
    ON narrative_subjects (source_table, entity_type);

-- One link per (row, subject, relationship). link_guid is uuid5 over exactly
-- that triple, so replay and re-ingestion are idempotent by construction and
-- this index is a statement of the same fact in the database.
CREATE UNIQUE INDEX IF NOT EXISTS narrative_subjects_triple_uq
    ON narrative_subjects (row_guid, subject_guid, relationship);

-- ROLLBACK (reversal, under its own authorization):
--   DROP TABLE IF EXISTS narrative_subjects;
-- No existing table is modified by this migration, so reversal is total.
