-- Phase B — institutional redeploy plans + legs (advisory only)

ALTER TABLE deploy_plans
  ADD COLUMN IF NOT EXISTS version INT NOT NULL DEFAULT 1,
  ADD COLUMN IF NOT EXISTS plan_archetype CHAR(1),
  ADD COLUMN IF NOT EXISTS plan_type TEXT,
  ADD COLUMN IF NOT EXISTS tags TEXT[] DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS objective TEXT,
  ADD COLUMN IF NOT EXISTS total_deployable_usd NUMERIC,
  ADD COLUMN IF NOT EXISTS reserve_usd NUMERIC,
  ADD COLUMN IF NOT EXISTS deploy_pct_of_net NUMERIC,
  ADD COLUMN IF NOT EXISTS confidence NUMERIC,
  ADD COLUMN IF NOT EXISTS evidence_factor_count INT DEFAULT 0,
  ADD COLUMN IF NOT EXISTS operator_status TEXT NOT NULL DEFAULT 'draft',
  ADD COLUMN IF NOT EXISTS oversight_status TEXT NOT NULL DEFAULT 'pending',
  ADD COLUMN IF NOT EXISTS composite_rank NUMERIC,
  ADD COLUMN IF NOT EXISTS rejected_alternatives JSONB NOT NULL DEFAULT '[]'::jsonb,
  ADD COLUMN IF NOT EXISTS unmet_exposure JSONB NOT NULL DEFAULT '{}'::jsonb,
  ADD COLUMN IF NOT EXISTS advantages TEXT[] DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS compromises TEXT[] DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS risks TEXT[] DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS hermes_narrative TEXT,
  ADD COLUMN IF NOT EXISTS scenarios JSONB NOT NULL DEFAULT '{}'::jsonb,
  ADD COLUMN IF NOT EXISTS policy_version TEXT,
  ADD COLUMN IF NOT EXISTS generator_version TEXT,
  ADD COLUMN IF NOT EXISTS input_hash TEXT,
  ADD COLUMN IF NOT EXISTS supersedes_plan_id BIGINT REFERENCES deploy_plans(id),
  ADD COLUMN IF NOT EXISTS locked_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS locked_by TEXT,
  ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ;

DO $$ BEGIN
  ALTER TABLE deploy_plans DROP CONSTRAINT IF EXISTS deploy_plans_status_check;
  ALTER TABLE deploy_plans ADD CONSTRAINT deploy_plans_status_check
    CHECK (status IN ('approved', 'draft', 'operator_ready', 'dismissed'));
EXCEPTION WHEN others THEN NULL;
END $$;

DO $$ BEGIN
  ALTER TABLE deploy_plans ADD CONSTRAINT chk_deploy_plan_operator_status
    CHECK (operator_status IN ('draft', 'operator_ready', 'approved', 'dismissed'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
  ALTER TABLE deploy_plans ADD CONSTRAINT chk_deploy_plan_oversight_status
    CHECK (oversight_status IN ('pending', 'passed', 'failed', 'skipped'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS idx_deploy_plans_event_version_archetype
  ON deploy_plans(deploy_event_id, version, plan_archetype);

CREATE TABLE IF NOT EXISTS redeploy_plan_legs (
    id BIGSERIAL PRIMARY KEY,
    deploy_plan_id BIGINT NOT NULL REFERENCES deploy_plans(id) ON DELETE CASCADE,
    leg_index INT NOT NULL,
    ticker TEXT NOT NULL,
    security_name TEXT,
    account TEXT NOT NULL,
    allocation_pct_of_net NUMERIC,
    target_dollars NUMERIC NOT NULL,
    target_shares INT,
    is_reserve BOOLEAN NOT NULL DEFAULT FALSE,
    is_actionable BOOLEAN NOT NULL DEFAULT TRUE,
    current_price NUMERIC,
    price_as_of TEXT,
    price_stale BOOLEAN NOT NULL DEFAULT FALSE,
    preferred_entry NUMERIC,
    entry_range_low NUMERIC,
    entry_range_high NUMERIC,
    do_not_chase NUMERIC,
    stage_1_pct NUMERIC,
    stage_1_price NUMERIC,
    stage_1_shares INT,
    stage_1_dollars NUMERIC,
    stage_2_pct NUMERIC,
    stage_2_price NUMERIC,
    stage_2_shares INT,
    stage_2_dollars NUMERIC,
    stage_3_pct NUMERIC,
    stage_3_price NUMERIC,
    stage_3_shares INT,
    stage_3_dollars NUMERIC,
    expected_yield_pct NUMERIC,
    thesis TEXT,
    invalidation TEXT,
    tax_location_rationale TEXT,
    overlap_note TEXT,
    UNIQUE (deploy_plan_id, leg_index)
);

CREATE INDEX IF NOT EXISTS idx_redeploy_plan_legs_plan ON redeploy_plan_legs(deploy_plan_id);