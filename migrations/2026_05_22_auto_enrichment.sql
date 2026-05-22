-- Auto-enrichment tracking schema (2026-05-22)

ALTER TABLE paper_trade_proposals
    ADD COLUMN IF NOT EXISTS enrichment_failures INT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS enrichment_status TEXT,
    ADD COLUMN IF NOT EXISTS enrichment_last_attempt_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS enrichment_last_error TEXT;

CREATE INDEX IF NOT EXISTS idx_proposals_enrichment_pending
    ON paper_trade_proposals (enrichment_status)
    WHERE enrichment_status IN ('PENDING', 'IN_PROGRESS');

CREATE TABLE IF NOT EXISTS enrichment_log (
    id BIGSERIAL PRIMARY KEY,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    proposal_id BIGINT NOT NULL,
    step TEXT NOT NULL,
    success BOOLEAN NOT NULL,
    duration_seconds NUMERIC(6,2),
    error_message TEXT,
    output JSONB
);
CREATE INDEX IF NOT EXISTS idx_enrichment_log_recent
    ON enrichment_log (started_at DESC);

ALTER TABLE atm_state
    ADD COLUMN IF NOT EXISTS last_enrichment_at TIMESTAMPTZ;
