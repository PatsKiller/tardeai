-- 2026-08-13_two_way_curation.sql
-- Two-way watchlist curation: generalize the Hermes firewall to CIO / advisory / defense
-- sources, and add the reverse-edge (outcome -> watchlist) columns + audit trail.
--
-- ADDITIVE ONLY (CREATE / ADD COLUMN IF NOT EXISTS). No DROP, no rename, no destructive DDL.
-- Firewall preserved: each source writes ONLY its own staging table; watch_directives_service.py
-- drains all sources through promote_directive_lead() under the APP role. Sources never touch
-- watch_directives / watch_directive_hits / watchlist_items / strategy_watchpool directly.

BEGIN;

-- ─────────────────────────────────────────────────────────────────────────────
-- A. Per-source staging tables (mirror hermes_directive_hits_staging)
--    directive_id is deliberately NOT a FK (the source validates nothing; the app
--    checks directive validity on drain, exactly like the Hermes path).
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS cio_directive_hits_staging (
    id            BIGSERIAL PRIMARY KEY,
    directive_id  BIGINT,
    symbol        TEXT,
    thesis        TEXT,
    source_detail JSONB,
    proposed_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    drained       BOOLEAN NOT NULL DEFAULT false,
    drained_at    TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_cio_dir_staging_undrained
    ON cio_directive_hits_staging (drained) WHERE drained = false;

CREATE TABLE IF NOT EXISTS advisory_directive_hits_staging (
    id            BIGSERIAL PRIMARY KEY,
    directive_id  BIGINT,
    symbol        TEXT,
    thesis        TEXT,
    source_detail JSONB,
    proposed_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    drained       BOOLEAN NOT NULL DEFAULT false,
    drained_at    TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_advisory_dir_staging_undrained
    ON advisory_directive_hits_staging (drained) WHERE drained = false;

CREATE TABLE IF NOT EXISTS defense_directive_hits_staging (
    id            BIGSERIAL PRIMARY KEY,
    directive_id  BIGINT,
    symbol        TEXT,
    thesis        TEXT,
    source_detail JSONB,
    proposed_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    drained       BOOLEAN NOT NULL DEFAULT false,
    drained_at    TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_defense_dir_staging_undrained
    ON defense_directive_hits_staging (drained) WHERE drained = false;

-- ─────────────────────────────────────────────────────────────────────────────
-- B. Reverse-edge columns on watchlist_items (outcome -> watchlist learning)
--    realized_outcome       : win | loss | scratch | break_even (from the outcome ledger)
--    thesis_win             : did the watchlist thesis resolve favorably (null = unresolved)
--    options_edge_score     : 0-100 blended IV-rank + prime-rubric edge for the UNDERLYING symbol
--    hermes_research_score  : 0-100 Hermes research intelligence folded into scoring
-- ─────────────────────────────────────────────────────────────────────────────

ALTER TABLE watchlist_items
    ADD COLUMN IF NOT EXISTS realized_outcome       TEXT,
    ADD COLUMN IF NOT EXISTS thesis_win             BOOLEAN,
    ADD COLUMN IF NOT EXISTS options_edge_score     NUMERIC,
    ADD COLUMN IF NOT EXISTS options_edge_detail    JSONB,
    ADD COLUMN IF NOT EXISTS hermes_research_score  NUMERIC,
    ADD COLUMN IF NOT EXISTS hermes_research_detail JSONB;

-- ─────────────────────────────────────────────────────────────────────────────
-- C. Curation loop audit trail (provenance for the two-way loop)
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS curation_loop_audit (
    id         BIGSERIAL PRIMARY KEY,
    source     TEXT NOT NULL,                 -- cio | advisory | defense | outcome | options | hermes_research
    event      TEXT NOT NULL,                 -- staged | drained | written | folded | auto_applied | staged_for_review
    payload    JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_curation_loop_audit_source
    ON curation_loop_audit (source, created_at);

COMMIT;

-- ─────────────────────────────────────────────────────────────────────────────
-- D. Grants (least privilege — the firewall). CIO/advisory/defense run under the
--    app role today, so no new roles are minted here. When a dedicated role is
--    introduced, follow the hermes_directive_hits_staging pattern: GRANT
--    SELECT, INSERT on the staging table only, and USAGE on its sequence — and
--    NEVER on watch_directives / watch_directive_hits / watchlist_items.
-- ─────────────────────────────────────────────────────────────────────────────
