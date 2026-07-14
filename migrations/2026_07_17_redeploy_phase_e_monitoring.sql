-- Phase E — redeploy monitoring: manual stage fills, restoration metrics (advisory only)

CREATE TABLE IF NOT EXISTS redeploy_stage_fills (
    id BIGSERIAL PRIMARY KEY,
    deploy_event_id BIGINT NOT NULL REFERENCES deploy_events(id) ON DELETE CASCADE,
    deploy_plan_id BIGINT REFERENCES deploy_plans(id) ON DELETE SET NULL,
    plan_version INT,
    plan_archetype CHAR(1),
    leg_index INT,
    ticker TEXT NOT NULL,
    stage INT NOT NULL CHECK (stage BETWEEN 1 AND 3),
    filled_shares INT NOT NULL CHECK (filled_shares > 0),
    filled_price NUMERIC NOT NULL CHECK (filled_price > 0),
    filled_dollars NUMERIC NOT NULL CHECK (filled_dollars > 0),
    filled_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    account TEXT NOT NULL,
    evidence_source TEXT NOT NULL DEFAULT 'operator_manual',
    evidence_note TEXT,
    idempotency_key TEXT NOT NULL UNIQUE,
    recorded_by TEXT NOT NULL DEFAULT 'operator',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (evidence_source IN ('operator_manual', 'broker_statement', 'manual_ticket'))
);

CREATE INDEX IF NOT EXISTS idx_redeploy_stage_fills_event ON redeploy_stage_fills(deploy_event_id, filled_at DESC);
CREATE INDEX IF NOT EXISTS idx_redeploy_stage_fills_plan ON redeploy_stage_fills(deploy_plan_id, plan_version);

CREATE TABLE IF NOT EXISTS redeploy_monitor_snapshots (
    id BIGSERIAL PRIMARY KEY,
    deploy_event_id BIGINT NOT NULL REFERENCES deploy_events(id) ON DELETE CASCADE,
    plan_version INT,
    plan_archetype CHAR(1),
    snapshot_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    restoration_metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
    fill_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    reeval_flags JSONB NOT NULL DEFAULT '[]'::jsonb,
    hermes_outcome_ids BIGINT[] DEFAULT '{}',
    generator_version TEXT,
    policy_version TEXT
);

CREATE INDEX IF NOT EXISTS idx_redeploy_monitor_event ON redeploy_monitor_snapshots(deploy_event_id, snapshot_at DESC);

CREATE TABLE IF NOT EXISTS redeploy_monitor_audit (
    id BIGSERIAL PRIMARY KEY,
    deploy_event_id BIGINT NOT NULL REFERENCES deploy_events(id) ON DELETE CASCADE,
    action TEXT NOT NULL,
    idempotency_key TEXT,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (action, idempotency_key)
);

CREATE INDEX IF NOT EXISTS idx_redeploy_monitor_audit_event ON redeploy_monitor_audit(deploy_event_id, created_at DESC);