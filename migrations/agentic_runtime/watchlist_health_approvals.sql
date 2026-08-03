-- Watchlist Health Agent — approval tracking table
-- Apply: command psql -d "$LAB_DSN" -v ON_ERROR_STOP=1 -f migrations/agentic_runtime/watchlist_health_approvals.sql

CREATE TABLE IF NOT EXISTS watchlist_health_approvals (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(10) NOT NULL,
    diagnosis JSONB,
    actions JSONB,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    message_id VARCHAR(80),
    resolved_by VARCHAR(80),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    resolved_at TIMESTAMPTZ,
    resolution_note TEXT
);

CREATE INDEX IF NOT EXISTS idx_wl_health_approvals_status ON watchlist_health_approvals(status);
CREATE INDEX IF NOT EXISTS idx_wl_health_approvals_symbol ON watchlist_health_approvals(symbol);
CREATE INDEX IF NOT EXISTS idx_wl_health_approvals_created ON watchlist_health_approvals(created_at DESC);
