-- Gap 3: Outcome provenance write-back to paper_trade_proposals
-- Links trade result back to the originating proposal for proposal-quality analytics.
-- Safe to run repeatedly (IF NOT EXISTS).
-- Does NOT touch broker, holdings, execution, or trading behavior.

ALTER TABLE paper_trade_proposals
    ADD COLUMN IF NOT EXISTS outcome_trade_id         INTEGER,
    ADD COLUMN IF NOT EXISTS outcome_r_multiple       NUMERIC(6,3),
    ADD COLUMN IF NOT EXISTS outcome_pnl              NUMERIC(14,2),
    ADD COLUMN IF NOT EXISTS outcome_pnl_pct          NUMERIC(8,2),
    ADD COLUMN IF NOT EXISTS outcome_verdict          VARCHAR(20),
    ADD COLUMN IF NOT EXISTS outcome_thesis_confirmed  BOOLEAN,
    ADD COLUMN IF NOT EXISTS outcome_closed_at         TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS outcome_hold_hours        INTEGER;

CREATE INDEX IF NOT EXISTS idx_ptp_outcome_verdict
    ON paper_trade_proposals (outcome_verdict)
    WHERE outcome_verdict IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_ptp_outcome_trade_id
    ON paper_trade_proposals (outcome_trade_id)
    WHERE outcome_trade_id IS NOT NULL;
