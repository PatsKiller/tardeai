-- 2026-08-13_two_way_curation_sources.sql
-- Phase 5 increment: make `rotation` and `reentry` first-class two-way curation sources.
--
-- ADDITIVE ONLY (CREATE TABLE IF NOT EXISTS + expand surfaced_by CHECK). No DROP of
-- columns, no rename, no destructive DDL. Firewall preserved: rotation/reentry write ONLY
-- their own staging tables; the app role drains them through promote_directive_lead() — they
-- never touch watch_directives / watch_directive_hits / watchlist_items / strategy_watchpool.

BEGIN;

CREATE TABLE IF NOT EXISTS rotation_directive_hits_staging (
    id            BIGSERIAL PRIMARY KEY,
    directive_id  BIGINT,
    symbol        TEXT,
    thesis        TEXT,
    source_detail JSONB,
    proposed_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    drained       BOOLEAN NOT NULL DEFAULT false,
    drained_at    TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_rotation_dir_staging_undrained
    ON rotation_directive_hits_staging (drained) WHERE drained = false;

CREATE TABLE IF NOT EXISTS reentry_directive_hits_staging (
    id            BIGSERIAL PRIMARY KEY,
    directive_id  BIGINT,
    symbol        TEXT,
    thesis        TEXT,
    source_detail JSONB,
    proposed_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    drained       BOOLEAN NOT NULL DEFAULT false,
    drained_at    TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_reentry_dir_staging_undrained
    ON reentry_directive_hits_staging (drained) WHERE drained = false;

-- Expand surfaced_by provenance to the two new sources (supersedes the p0 CHECK).
ALTER TABLE watch_directive_hits
    DROP CONSTRAINT IF EXISTS watch_directive_hits_surfaced_by_check;

ALTER TABLE watch_directive_hits
    ADD CONSTRAINT watch_directive_hits_surfaced_by_check
    CHECK (surfaced_by = ANY (ARRAY[
        'trade_ai'::text,
        'hermes'::text,
        'operator'::text,
        'cio'::text,
        'advisory'::text,
        'defense'::text,
        'rotation'::text,
        'reentry'::text
    ]));

COMMIT;

