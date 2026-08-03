-- 0004_pipeline_health_approvals
-- Pipeline health agent Telegram-approval table.
-- Stores pending operator-approval records for pipeline remediations
-- that exceed the agent's auto-fix safety boundary.
CREATE TABLE IF NOT EXISTS pipeline_health_approvals (
    id              SERIAL PRIMARY KEY,
    pipeline_key    TEXT NOT NULL,
    diagnosis       JSONB NOT NULL DEFAULT '{}'::jsonb,
    actions         JSONB NOT NULL DEFAULT '[]'::jsonb,
    status          VARCHAR(20) NOT NULL DEFAULT 'pending',  -- pending | approved | denied
    message_id      VARCHAR(80),
    resolved_by     VARCHAR(80),
    resolved_at     TIMESTAMPTZ,
    resolution_note TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pl_health_approvals_status
    ON pipeline_health_approvals (status, created_at);
CREATE INDEX IF NOT EXISTS idx_pl_health_approvals_key
    ON pipeline_health_approvals (pipeline_key);
