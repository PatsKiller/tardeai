-- Phase 206b — additive quality/sample columns on profit_protection_rule_backtests.
-- Evidence-only analytics. No execution/strategy/order/GO-WAIT impact. Idempotent.
ALTER TABLE profit_protection_rule_backtests
  ADD COLUMN IF NOT EXISTS raw_sample_size INTEGER,
  ADD COLUMN IF NOT EXISTS quality_eligible_sample_size INTEGER,
  ADD COLUMN IF NOT EXISTS triggered_sample_size INTEGER,
  ADD COLUMN IF NOT EXISTS winner_sample_size INTEGER,
  ADD COLUMN IF NOT EXISTS reliable_sample_size INTEGER,
  ADD COLUMN IF NOT EXISTS excluded_count INTEGER,
  ADD COLUMN IF NOT EXISTS excluded_reasons JSONB DEFAULT '{}'::jsonb,
  ADD COLUMN IF NOT EXISTS premature_exit_cost_known BOOLEAN,
  ADD COLUMN IF NOT EXISTS premature_exit_cost_method TEXT,
  ADD COLUMN IF NOT EXISTS premature_exit_cost_warning TEXT,
  ADD COLUMN IF NOT EXISTS estimate_quality TEXT,
  ADD COLUMN IF NOT EXISTS result_scope TEXT,
  ADD COLUMN IF NOT EXISTS graft_verdict TEXT;
