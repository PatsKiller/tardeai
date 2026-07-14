-- Redeploy data integrity — P0 guards after phase_e test-fixture pollution (2026-07-13).
-- Idempotent; safe to run repeatedly (executed by ensure_monitor_tables on every call).
--
-- 1. environment column: every fill is explicitly production or test.
-- 2. broker_confirmation_id: distinguishes legitimately identical fills.
-- 3. Quarantine: rows already carrying fixture markers are re-labeled environment='test'
--    (reversible — no deletion here; deletion is a separately approved cleanup).
-- 4. Content-level uniqueness for production fills so duplicate manual entries are
--    rejected at the database even if application checks are bypassed.

ALTER TABLE redeploy_stage_fills
    ADD COLUMN IF NOT EXISTS environment TEXT NOT NULL DEFAULT 'production';

ALTER TABLE redeploy_stage_fills
    ADD COLUMN IF NOT EXISTS broker_confirmation_id TEXT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chk_redeploy_fill_environment'
    ) THEN
        ALTER TABLE redeploy_stage_fills
            ADD CONSTRAINT chk_redeploy_fill_environment
            CHECK (environment IN ('production', 'test'));
    END IF;
END $$;

-- Quarantine known fixture rows (marker patterns) so they stop feeding
-- restoration metrics, Hermes learning, and the outcome bus immediately.
UPDATE redeploy_stage_fills
SET environment = 'test'
WHERE environment = 'production'
  AND (
        evidence_note ~* '\m(fixture|synthetic|dummy|fake|test)\m'
     OR idempotency_key LIKE 'test-%'
  );

-- Content-hash idempotency: one production fill per
-- (event, plan, version, ticker, stage, shares, price, broker confirmation).
CREATE UNIQUE INDEX IF NOT EXISTS uq_redeploy_fill_content
    ON redeploy_stage_fills (
        deploy_event_id,
        COALESCE(deploy_plan_id, 0),
        COALESCE(plan_version, 0),
        ticker,
        stage,
        filled_shares,
        filled_price,
        COALESCE(broker_confirmation_id, '')
    )
    WHERE environment = 'production';

CREATE INDEX IF NOT EXISTS idx_redeploy_stage_fills_env
    ON redeploy_stage_fills (environment, deploy_event_id);
