-- Hermes research quality remediation metrics (Learning tab KPI)
ALTER TABLE intelligence_remediation_runs
  ADD COLUMN IF NOT EXISTS external_retries INT NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS proposal_backfills INT NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS s0_refreshes INT NOT NULL DEFAULT 0;
