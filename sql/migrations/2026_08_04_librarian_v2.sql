-- Hermes Phase 3: Librarian Agent v2 — additive schema changes
-- Run: psql trade_ai < migrations/2026_08_04_librarian_v2.sql

-- 1. Content-subject taxonomy tags on research rows
DO $$ BEGIN
    ALTER TABLE hermes_research_intelligence ADD COLUMN content_tags TEXT[];
EXCEPTION WHEN duplicate_column THEN NULL;
END $$;
CREATE INDEX IF NOT EXISTS idx_hri_content_tags ON hermes_research_intelligence USING GIN (content_tags);

-- 2. Entity alias map
CREATE TABLE IF NOT EXISTS hermes_entity_alias_map (
    canonical_value TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL,
    aliases TEXT[] NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 3. Entity co-occurrence graph
CREATE TABLE IF NOT EXISTS hermes_entity_cooccurrence (
    entity_a TEXT NOT NULL,
    entity_b TEXT NOT NULL,
    entity_type_a TEXT NOT NULL,
    entity_type_b TEXT NOT NULL,
    weight INT NOT NULL DEFAULT 1,
    window_days INT NOT NULL DEFAULT 30,
    last_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (entity_a, entity_b)
);
CREATE INDEX IF NOT EXISTS idx_hec_entity_a ON hermes_entity_cooccurrence (entity_a);
CREATE INDEX IF NOT EXISTS idx_hec_entity_b ON hermes_entity_cooccurrence (entity_b);

-- 4. Librarian audit table
CREATE TABLE IF NOT EXISTS hermes_librarian_audit (
    id BIGSERIAL PRIMARY KEY,
    run_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    scope TEXT NOT NULL,
    action TEXT,
    detail JSONB,
    rows_affected INT DEFAULT 0,
    rollback_sql TEXT
);
CREATE INDEX IF NOT EXISTS idx_librarian_audit_scope ON hermes_librarian_audit (scope, run_at);
