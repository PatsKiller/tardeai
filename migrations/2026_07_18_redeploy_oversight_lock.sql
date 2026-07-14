-- PR-4/PR-5 — plan lock, operator status, oversight audit (advisory only)

ALTER TABLE deploy_events
  ADD COLUMN IF NOT EXISTS plan_locked_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS locked_plan_id BIGINT REFERENCES deploy_plans(id),
  ADD COLUMN IF NOT EXISTS locked_plan_version INT,
  ADD COLUMN IF NOT EXISTS operator_status TEXT NOT NULL DEFAULT 'open',
  ADD COLUMN IF NOT EXISTS reconciliation_status TEXT;

DO $$ BEGIN
  ALTER TABLE deploy_events ADD CONSTRAINT chk_deploy_event_operator_status
    CHECK (operator_status IN ('open', 'reviewing', 'executing', 'completed', 'dismissed'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE INDEX IF NOT EXISTS idx_deploy_events_operator_status
  ON deploy_events(operator_status, sold_at DESC);