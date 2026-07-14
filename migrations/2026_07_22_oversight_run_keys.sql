-- Oversight runs must carry the complete immutable key so governance projection
-- can select the newest valid verdict per lane for EXACTLY one plan snapshot
-- (adjudication: old Plan-B/needs_review rows were bleeding into Plan-F packets).
ALTER TABLE deploy_oversight_runs ADD COLUMN IF NOT EXISTS plan_id INTEGER;
ALTER TABLE deploy_oversight_runs ADD COLUMN IF NOT EXISTS plan_version INTEGER;
ALTER TABLE deploy_oversight_runs ADD COLUMN IF NOT EXISTS input_hash TEXT;
ALTER TABLE deploy_oversight_runs ADD COLUMN IF NOT EXISTS oversight_policy_version TEXT;
CREATE INDEX IF NOT EXISTS idx_oversight_runs_plan
    ON deploy_oversight_runs(deploy_event_id, plan_id, plan_version, lane, id DESC);
