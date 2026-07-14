-- Redeploy audit lineage (Phase 15, operator review 2026-07-14).
-- Every governance-relevant action on an event/plan gets a row; historical
-- actions that cannot be proven are backfilled with inferred=TRUE and labeled
-- INFERRED_FROM_CURRENT_STATE — never fabricated precise timestamps.
CREATE TABLE IF NOT EXISTS redeploy_audit_log (
    id              SERIAL PRIMARY KEY,
    deploy_event_id INTEGER NOT NULL,
    plan_id         INTEGER,
    plan_version    INTEGER,
    action          TEXT NOT NULL,
    actor           TEXT NOT NULL DEFAULT 'system',
    prior_value     TEXT,
    new_value       TEXT,
    reason          TEXT,
    correlation_id  TEXT,
    inferred        BOOLEAN NOT NULL DEFAULT FALSE,
    occurred_at     TIMESTAMPTZ,          -- when the action happened (NULL if unknown)
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_redeploy_audit_event ON redeploy_audit_log(deploy_event_id, created_at DESC);
