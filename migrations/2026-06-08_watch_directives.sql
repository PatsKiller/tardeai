-- 2026-06-08_watch_directives.sql
-- Operator Watch Directives + unified provenance + Hermes->Trade AI promotion hand-off.
-- ADDITIVE ONLY (CREATE/ADD IF NOT EXISTS). No DROP, no rename, no destructive migration.
-- Firewall: watch_directives is OPERATOR-OWNED (app role). Hermes gets SELECT only, and
-- proposes leads via hermes_directive_hits_staging (hermes_* family); the app role drains it.
--
-- Adapted to Phase-0 findings:
--   * watch_directives / watch_directive_hits: ABSENT -> create fresh.
--   * watchlist_symbol_master: provenance cols absent -> ADD.
--   * strategy_watchpool: origin_system/directive_id absent -> ADD.
--   * No hermes_directive_hits_staging exists -> create in hermes_* family (per 0.8 decision tree).

BEGIN;

-- ─────────────────────────────────────────────────────────────────────────────
-- A. Operator Watch Directives (standing instructions honored by Trade AI + Hermes)
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS watch_directives (
    id                BIGSERIAL PRIMARY KEY,
    kind              TEXT NOT NULL CHECK (kind IN ('ticker','sector','trend')),
    label             TEXT NOT NULL,
    spec              JSONB NOT NULL,            -- ticker:{symbol} | sector:{gics_sector,finviz_sector,etf,universe[]} | trend:{keywords[],seed_symbols[],screener_hints[]}
    rationale         TEXT,
    created_by        TEXT NOT NULL DEFAULT 'operator',
    status            TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','paused','archived','needs_review')),
    priority          TEXT NOT NULL DEFAULT 'normal',
    ttl_days          INT,                       -- NULL = standing
    trade_ai_enabled  BOOLEAN NOT NULL DEFAULT true,
    hermes_enabled    BOOLEAN NOT NULL DEFAULT true,
    last_confirmed_at TIMESTAMPTZ,               -- trend cold-detector reference
    cold_since        TIMESTAMPTZ,               -- set when narrative goes cold; auto-pause trigger
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_serviced_at  TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS watch_directive_hits (
    id                   BIGSERIAL PRIMARY KEY,
    directive_id         BIGINT NOT NULL REFERENCES watch_directives(id) ON DELETE CASCADE,
    symbol               TEXT NOT NULL,
    surfaced_by          TEXT NOT NULL CHECK (surfaced_by IN ('trade_ai','hermes','operator')),
    source_tier          TEXT,                   -- core|trusted|probationary|candidate|demoted at time of hit
    hit_reason           TEXT,
    divergence           TEXT,                   -- aligned|mixed|divergent|unavailable at time of hit
    promoted             BOOLEAN NOT NULL DEFAULT false,   -- true once it crossed into Trade AI evaluation
    promotion_status     TEXT,                   -- PROMOTED|MONITORED_NO_QUALIFY|STAGED_FOR_REVIEW|REGISTERED_NO_TECH
    qualified_strategies TEXT[],
    surfaced_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    promoted_at          TIMESTAMPTZ,
    UNIQUE (directive_id, symbol, surfaced_at)
);
CREATE INDEX IF NOT EXISTS idx_directive_hits_pending
    ON watch_directive_hits (directive_id, promoted) WHERE promoted = false;

-- ─────────────────────────────────────────────────────────────────────────────
-- B. Unified provenance on the curated master (all additive)
--    NOTE (Phase-0 correction): watchlist_symbol_master is a VIEW over watchlist_items
--    (+ card tables). Provenance columns therefore go on the BASE table watchlist_items.
--    first_seen_at already exists there -> IF NOT EXISTS makes this idempotent.
--    The view is extended to expose these in D-3 (or the provenance API reads the base directly).
-- ─────────────────────────────────────────────────────────────────────────────
ALTER TABLE watchlist_items
    ADD COLUMN IF NOT EXISTS origin_system      TEXT,        -- trade_ai_screener|hermes_rag|agent_discovery|operator|portfolio|event_detector
    ADD COLUMN IF NOT EXISTS origin_detail      JSONB,       -- screener_id|strategy_id|hermes research_id|agent|directive_id
    ADD COLUMN IF NOT EXISTS directive_id       BIGINT REFERENCES watch_directives(id),
    ADD COLUMN IF NOT EXISTS in_directive_watch BOOLEAN DEFAULT false,
    ADD COLUMN IF NOT EXISTS source_tier        TEXT,
    ADD COLUMN IF NOT EXISTS first_seen_at      TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS last_validated_at  TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS seen_count         INT DEFAULT 1,
    ADD COLUMN IF NOT EXISTS provenance_reason  TEXT;

-- Tag watchpool rows with origin so pills are consistent there too
ALTER TABLE strategy_watchpool
    ADD COLUMN IF NOT EXISTS origin_system TEXT,
    ADD COLUMN IF NOT EXISTS directive_id  BIGINT REFERENCES watch_directives(id);

-- ─────────────────────────────────────────────────────────────────────────────
-- C. Hermes proposal staging (FIREWALL): Hermes writes proposed leads HERE only.
--    The app role drains this -> watch_directive_hits -> promote_directive_lead().
--    Hermes never touches watch_directives / watch_directive_hits / watchlist_symbol_master /
--    strategy_watchpool directly.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS hermes_directive_hits_staging (
    id                 BIGSERIAL PRIMARY KEY,
    directive_id       BIGINT,                   -- not FK: hermes validates nothing; app checks on drain
    symbol             TEXT NOT NULL,
    thesis             TEXT,
    narrative_strength NUMERIC,
    source_detail      JSONB,
    proposed_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    drained            BOOLEAN NOT NULL DEFAULT false,
    drained_at         TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_hermes_dir_staging_undrained
    ON hermes_directive_hits_staging (drained) WHERE drained = false;

COMMIT;

-- ─────────────────────────────────────────────────────────────────────────────
-- D. Grants (least privilege — the firewall)
-- ─────────────────────────────────────────────────────────────────────────────
-- Hermes may READ directives (to honor them) but NEVER write any operator/production table.
GRANT SELECT ON watch_directives      TO hermes_readonly;
GRANT SELECT ON watch_directive_hits  TO hermes_readonly;
-- Hermes proposes leads ONLY into its staging table.
GRANT SELECT, INSERT ON hermes_directive_hits_staging TO hermes_staging_writer;
GRANT USAGE, SELECT ON SEQUENCE hermes_directive_hits_staging_id_seq TO hermes_staging_writer;
-- (Deliberately NO grant of INSERT/UPDATE on watch_directives, watch_directive_hits,
--  watchlist_symbol_master, or strategy_watchpool to any hermes_* role.)
