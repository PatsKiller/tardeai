-- Hermes Phase 2: Research Agenda Engine — additive schema changes
-- Run: psql trade_ai < migrations/2026_08_04_agenda.sql

-- 1. Agenda audit table
CREATE TABLE IF NOT EXISTS hermes_research_agenda_audit (
    id BIGSERIAL PRIMARY KEY,
    run_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    decision TEXT NOT NULL,           -- 'create', 'retire', 'boost'
    topic_id TEXT,
    rationale TEXT,
    rollback_sql TEXT,
    detail JSONB
);
CREATE INDEX IF NOT EXISTS idx_agenda_audit_decision ON hermes_research_agenda_audit (decision);
CREATE INDEX IF NOT EXISTS idx_agenda_audit_run ON hermes_research_agenda_audit (run_at);

-- 2. Auto-created topic provenance
DO $$ BEGIN
    ALTER TABLE topic_monitor ADD COLUMN auto_created BOOLEAN NOT NULL DEFAULT FALSE;
EXCEPTION WHEN duplicate_column THEN NULL;
END $$;
CREATE INDEX IF NOT EXISTS idx_topic_monitor_auto ON topic_monitor (auto_created) WHERE auto_created = true;
