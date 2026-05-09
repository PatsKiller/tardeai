-- Unified Self-Improvement Command Center: Session 32
-- 2026-05-09 Idempotent

CREATE TABLE IF NOT EXISTS self_improvement_snapshots (
    id BIGSERIAL PRIMARY KEY, snapshot_id TEXT UNIQUE NOT NULL,
    generated_at TIMESTAMPTZ DEFAULT now(), status TEXT DEFAULT 'generated',
    safety_status JSONB DEFAULT '{}'::jsonb, system_facts JSONB DEFAULT '{}'::jsonb,
    paper_trading_summary JSONB DEFAULT '{}'::jsonb,
    execution_revalidation_summary JSONB DEFAULT '{}'::jsonb,
    open_trade_intelligence_summary JSONB DEFAULT '{}'::jsonb,
    learning_governance_summary JSONB DEFAULT '{}'::jsonb,
    agent_calibration_summary JSONB DEFAULT '{}'::jsonb,
    weekly_digest_summary JSONB DEFAULT '{}'::jsonb,
    backtesting_summary JSONB DEFAULT '{}'::jsonb,
    champion_challenger_summary JSONB DEFAULT '{}'::jsonb,
    pipeline_summary JSONB DEFAULT '{}'::jsonb,
    ingestion_source_summary JSONB DEFAULT '{}'::jsonb,
    documentation_drift_summary JSONB DEFAULT '{}'::jsonb,
    review_queue_summary JSONB DEFAULT '{}'::jsonb,
    warnings JSONB DEFAULT '[]'::jsonb,
    recommended_operator_actions JSONB DEFAULT '[]'::jsonb,
    low_sample_warnings JSONB DEFAULT '[]'::jsonb,
    payload JSONB DEFAULT '{}'::jsonb, created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS operator_review_queue (
    id BIGSERIAL PRIMARY KEY, review_item_id TEXT UNIQUE NOT NULL,
    source_domain TEXT NOT NULL, source_table TEXT, source_id TEXT,
    title TEXT NOT NULL, summary TEXT, severity TEXT DEFAULT 'normal',
    review_type TEXT, status TEXT DEFAULT 'open',
    requires_action BOOLEAN DEFAULT false, action_label TEXT, action_url TEXT,
    linked_dashboard_route TEXT, payload JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT now(), updated_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_orq_status ON operator_review_queue(status);
CREATE INDEX IF NOT EXISTS idx_orq_severity ON operator_review_queue(severity);
CREATE INDEX IF NOT EXISTS idx_orq_domain ON operator_review_queue(source_domain);

CREATE TABLE IF NOT EXISTS self_improvement_component_health (
    id BIGSERIAL PRIMARY KEY, component_key TEXT UNIQUE NOT NULL,
    component_name TEXT, status TEXT DEFAULT 'unknown',
    last_checked_at TIMESTAMPTZ DEFAULT now(), last_success_at TIMESTAMPTZ,
    last_error TEXT, latest_count INTEGER, health_score NUMERIC,
    summary TEXT, payload JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT now(), updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS self_improvement_operator_notes (
    id BIGSERIAL PRIMARY KEY, note_id TEXT UNIQUE NOT NULL,
    review_item_id TEXT, snapshot_id TEXT,
    note_text TEXT NOT NULL, created_by TEXT DEFAULT 'john',
    created_at TIMESTAMPTZ DEFAULT now()
);
