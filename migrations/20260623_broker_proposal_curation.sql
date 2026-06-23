-- Broker proposal curation metadata (30m trading-hours curator)
-- ADDITIVE ONLY

BEGIN;

ALTER TABLE paper_trade_proposals
    ADD COLUMN IF NOT EXISTS last_curated_at TIMESTAMPTZ;

ALTER TABLE paper_trade_proposals
    ADD COLUMN IF NOT EXISTS curation_status TEXT;

ALTER TABLE paper_trade_proposals
    ADD COLUMN IF NOT EXISTS curation_snapshot JSONB;

CREATE INDEX IF NOT EXISTS idx_ptp_last_curated
    ON paper_trade_proposals (last_curated_at DESC NULLS LAST)
    WHERE status IN ('PENDING', 'APPROVED_FOR_PAPER_TEST');

COMMIT;