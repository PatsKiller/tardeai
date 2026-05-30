-- Hermes Phase 1: Staging Tables and Roles
-- Date: 2026-05-30
-- Purpose: Create Hermes-owned staging tables for research intelligence,
--          validation findings, alerts, embedding queue, memory events,
--          and promotion audit. No production table modifications.
-- Rollback: 20260530_hermes_phase1_staging_tables_rollback.sql

BEGIN;

-- ============================================================
-- 1. ROLES (group roles only, no passwords, no login)
-- ============================================================

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'hermes_readonly') THEN
        CREATE ROLE hermes_readonly NOLOGIN;
        RAISE NOTICE 'Created role: hermes_readonly';
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'hermes_staging_writer') THEN
        CREATE ROLE hermes_staging_writer NOLOGIN;
        RAISE NOTICE 'Created role: hermes_staging_writer';
    END IF;
END
$$;

-- ============================================================
-- 2. hermes_research_intelligence
-- ============================================================

CREATE TABLE IF NOT EXISTS hermes_research_intelligence (
    id                    BIGSERIAL PRIMARY KEY,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ,
    source                TEXT NOT NULL DEFAULT 'hermes' CHECK (source = 'hermes'),
    hermes_agent_name     TEXT NOT NULL,
    research_type         TEXT NOT NULL,
    symbol                TEXT,
    related_trade_id      BIGINT,
    related_proposal_id   BIGINT,
    topic                 TEXT NOT NULL,
    summary               TEXT NOT NULL,
    thesis                TEXT,
    thesis_type           TEXT CHECK (thesis_type IN ('bullish','bearish','neutral','mixed')),
    evidence_json         JSONB NOT NULL DEFAULT '[]',
    confidence_score      REAL CHECK (confidence_score >= 0 AND confidence_score <= 1),
    freshness_date        DATE NOT NULL,
    source_urls_json      JSONB DEFAULT '[]',
    model_used            TEXT NOT NULL,
    prompt_hash           TEXT,
    context_type_used     TEXT,
    status                TEXT NOT NULL DEFAULT 'staged'
                          CHECK (status IN ('staged','reviewed','promoted','rejected','archived')),
    promoted_to_table     TEXT,
    promoted_to_id        BIGINT,
    reviewed_by           TEXT,
    reviewed_at           TIMESTAMPTZ,
    quality_score         REAL,
    tags                  TEXT[] DEFAULT '{}',
    strategy_tags         TEXT[] DEFAULT '{}',
    agent_tags            TEXT[] DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_hri_status ON hermes_research_intelligence(status);
CREATE INDEX IF NOT EXISTS idx_hri_symbol ON hermes_research_intelligence(symbol);
CREATE INDEX IF NOT EXISTS idx_hri_type ON hermes_research_intelligence(research_type);
CREATE INDEX IF NOT EXISTS idx_hri_agent ON hermes_research_intelligence(hermes_agent_name);
CREATE INDEX IF NOT EXISTS idx_hri_created ON hermes_research_intelligence(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_hri_confidence ON hermes_research_intelligence(confidence_score DESC);
CREATE INDEX IF NOT EXISTS idx_hri_trade ON hermes_research_intelligence(related_trade_id) WHERE related_trade_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_hri_proposal ON hermes_research_intelligence(related_proposal_id) WHERE related_proposal_id IS NOT NULL;

-- ============================================================
-- 3. hermes_validation_findings
-- ============================================================

CREATE TABLE IF NOT EXISTS hermes_validation_findings (
    id                    BIGSERIAL PRIMARY KEY,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ,
    source                TEXT NOT NULL DEFAULT 'hermes' CHECK (source = 'hermes'),
    hermes_agent_name     TEXT NOT NULL,
    finding_type          TEXT NOT NULL CHECK (finding_type IN (
        'stale_data',
        'conflicting_agents',
        'weak_evidence',
        'scoring_inconsistency',
        'missing_source_link',
        'stale_proposal',
        'outdated_rag',
        'unsupported_thesis',
        'broken_pipeline',
        'missing_data',
        'hallucination_risk',
        'confidence_drift'
    )),
    severity              TEXT NOT NULL CHECK (severity IN ('info','warning','urgent','critical')),
    symbol                TEXT,
    affected_table        TEXT,
    affected_id           BIGINT,
    description           TEXT NOT NULL,
    evidence_json         JSONB NOT NULL DEFAULT '{}',
    recommended_action    TEXT,
    auto_fixable          BOOLEAN DEFAULT FALSE,
    status                TEXT NOT NULL DEFAULT 'open'
                          CHECK (status IN ('open','acknowledged','resolved','dismissed','promoted')),
    resolved_by           TEXT,
    resolved_at           TIMESTAMPTZ,
    promoted_to_alert_id  BIGINT
);

CREATE INDEX IF NOT EXISTS idx_hvf_status ON hermes_validation_findings(status);
CREATE INDEX IF NOT EXISTS idx_hvf_severity ON hermes_validation_findings(severity);
CREATE INDEX IF NOT EXISTS idx_hvf_symbol ON hermes_validation_findings(symbol);
CREATE INDEX IF NOT EXISTS idx_hvf_type ON hermes_validation_findings(finding_type);
CREATE INDEX IF NOT EXISTS idx_hvf_created ON hermes_validation_findings(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_hvf_affected ON hermes_validation_findings(affected_table, affected_id);

-- ============================================================
-- 4. hermes_alerts
-- ============================================================

CREATE TABLE IF NOT EXISTS hermes_alerts (
    id                    BIGSERIAL PRIMARY KEY,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ,
    source                TEXT NOT NULL DEFAULT 'hermes' CHECK (source = 'hermes'),
    hermes_agent_name     TEXT NOT NULL,
    alert_type            TEXT NOT NULL CHECK (alert_type IN (
        'research_finding',
        'validation_warning',
        'thesis_decay',
        'data_staleness',
        'missing_evidence',
        'scoring_drift',
        'regime_change',
        'incubator_signal',
        'trade_lesson',
        'portfolio_risk',
        'opportunity_alert'
    )),
    severity              TEXT NOT NULL CHECK (severity IN ('info','warning','urgent')),
    symbol                TEXT,
    title                 TEXT NOT NULL,
    description           TEXT NOT NULL,
    evidence_json         JSONB DEFAULT '{}',
    recommended_action    TEXT,
    confidence_score      REAL,
    related_research_id   BIGINT REFERENCES hermes_research_intelligence(id),
    related_finding_id    BIGINT REFERENCES hermes_validation_findings(id),
    status                TEXT NOT NULL DEFAULT 'active'
                          CHECK (status IN ('active','read','dismissed','promoted')),
    read_at               TIMESTAMPTZ,
    dismissed_by          TEXT,
    promoted_to_alert_id  BIGINT
);

CREATE INDEX IF NOT EXISTS idx_ha_status ON hermes_alerts(status);
CREATE INDEX IF NOT EXISTS idx_ha_severity ON hermes_alerts(severity);
CREATE INDEX IF NOT EXISTS idx_ha_symbol ON hermes_alerts(symbol);
CREATE INDEX IF NOT EXISTS idx_ha_type ON hermes_alerts(alert_type);
CREATE INDEX IF NOT EXISTS idx_ha_created ON hermes_alerts(created_at DESC);

-- ============================================================
-- 5. hermes_embedding_queue
-- ============================================================

CREATE TABLE IF NOT EXISTS hermes_embedding_queue (
    id                    BIGSERIAL PRIMARY KEY,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    source                TEXT NOT NULL DEFAULT 'hermes' CHECK (source = 'hermes'),
    source_research_id    BIGINT NOT NULL REFERENCES hermes_research_intelligence(id),
    title                 TEXT NOT NULL,
    content               TEXT NOT NULL,
    source_type_target    TEXT NOT NULL DEFAULT 'hermes_research',
    embedding_status      TEXT NOT NULL DEFAULT 'pending'
                          CHECK (embedding_status IN ('pending','processing','completed','failed','skipped')),
    embedded_id           BIGINT,
    embedded_at           TIMESTAMPTZ,
    error_message         TEXT
);

CREATE INDEX IF NOT EXISTS idx_heq_status ON hermes_embedding_queue(embedding_status);
CREATE INDEX IF NOT EXISTS idx_heq_created ON hermes_embedding_queue(created_at);

-- ============================================================
-- 6. hermes_memory_events
-- ============================================================

CREATE TABLE IF NOT EXISTS hermes_memory_events (
    id                    BIGSERIAL PRIMARY KEY,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ,
    source                TEXT NOT NULL DEFAULT 'hermes' CHECK (source = 'hermes'),
    hermes_agent_name     TEXT NOT NULL,
    event_type            TEXT NOT NULL CHECK (event_type IN (
        'recommendation_issued',
        'operator_decision',
        'outcome_observed',
        'lesson_learned',
        'confidence_adjustment',
        'agent_state_change',
        'research_debt_logged',
        'do_not_repeat'
    )),
    symbol                TEXT,
    topic                 TEXT NOT NULL,
    content               TEXT NOT NULL,
    metadata_json         JSONB DEFAULT '{}',
    related_research_id   BIGINT REFERENCES hermes_research_intelligence(id),
    expires_at            TIMESTAMPTZ,
    status                TEXT NOT NULL DEFAULT 'active'
                          CHECK (status IN ('active','expired','archived'))
);

CREATE INDEX IF NOT EXISTS idx_hme_type ON hermes_memory_events(event_type);
CREATE INDEX IF NOT EXISTS idx_hme_symbol ON hermes_memory_events(symbol);
CREATE INDEX IF NOT EXISTS idx_hme_status ON hermes_memory_events(status);
CREATE INDEX IF NOT EXISTS idx_hme_created ON hermes_memory_events(created_at DESC);

-- ============================================================
-- 7. hermes_promotion_audit
-- ============================================================

CREATE TABLE IF NOT EXISTS hermes_promotion_audit (
    id                    BIGSERIAL PRIMARY KEY,
    promoted_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    source_table          TEXT NOT NULL,
    source_id             BIGINT NOT NULL,
    target_table          TEXT NOT NULL,
    target_id             BIGINT,
    promotion_type        TEXT NOT NULL CHECK (promotion_type IN (
        'research_to_insight',
        'research_to_embedding',
        'research_to_rule',
        'research_to_cache',
        'finding_to_alert',
        'alert_to_alert_event'
    )),
    dry_run               BOOLEAN NOT NULL DEFAULT TRUE,
    approved_by           TEXT,
    approved_at           TIMESTAMPTZ,
    rollback_sql          TEXT,
    notes                 TEXT
);

CREATE INDEX IF NOT EXISTS idx_hpa_source ON hermes_promotion_audit(source_table, source_id);
CREATE INDEX IF NOT EXISTS idx_hpa_target ON hermes_promotion_audit(target_table, target_id);
CREATE INDEX IF NOT EXISTS idx_hpa_promoted ON hermes_promotion_audit(promoted_at DESC);

-- ============================================================
-- 8. GRANTS — hermes_staging_writer: INSERT/UPDATE on hermes_* only
-- ============================================================

GRANT INSERT, UPDATE ON hermes_research_intelligence TO hermes_staging_writer;
GRANT INSERT, UPDATE ON hermes_validation_findings TO hermes_staging_writer;
GRANT INSERT, UPDATE ON hermes_alerts TO hermes_staging_writer;
GRANT INSERT, UPDATE ON hermes_embedding_queue TO hermes_staging_writer;
GRANT INSERT, UPDATE ON hermes_memory_events TO hermes_staging_writer;
-- promotion_audit is written by promotion script, not Hermes agent
-- hermes_staging_writer does NOT get access to hermes_promotion_audit

GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO hermes_staging_writer;

-- ============================================================
-- 9. GRANTS — hermes_readonly: SELECT on hermes_* tables only
--    (broad production read grants deferred to separate approval)
-- ============================================================

GRANT SELECT ON hermes_research_intelligence TO hermes_readonly;
GRANT SELECT ON hermes_validation_findings TO hermes_readonly;
GRANT SELECT ON hermes_alerts TO hermes_readonly;
GRANT SELECT ON hermes_embedding_queue TO hermes_readonly;
GRANT SELECT ON hermes_memory_events TO hermes_readonly;
GRANT SELECT ON hermes_promotion_audit TO hermes_readonly;

COMMIT;
