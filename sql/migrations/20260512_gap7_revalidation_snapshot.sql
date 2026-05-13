-- Gap 7: Revalidation snapshot columns in paper_trades
-- Captures what the revalidator decided at submission time for journal completeness.
-- Safe to run repeatedly (IF NOT EXISTS).
-- Does NOT touch broker, holdings, execution, or trading behavior.

ALTER TABLE paper_trades
    ADD COLUMN IF NOT EXISTS revalidation_verdict      VARCHAR(40),
    ADD COLUMN IF NOT EXISTS revalidation_score        INTEGER,
    ADD COLUMN IF NOT EXISTS revalidation_flags        JSONB,
    ADD COLUMN IF NOT EXISTS price_at_approval         NUMERIC(10,4),
    ADD COLUMN IF NOT EXISTS staleness_at_submit_min   INTEGER;
