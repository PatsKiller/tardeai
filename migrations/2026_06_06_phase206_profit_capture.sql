-- Phase 206 — Canonical all-trades profit-capture analysis layer (ADVISORY / SHADOW ONLY).
--
-- Upgrades the paper-only, open-trade-only protection advisory model to the canonical
-- trade_instances all-trades model. These tables are ANALYTICS ONLY:
--   * no broker writes, no order/stop mutation, no GO/WAIT or strategy mutation.
--   * shadow recommendations are evidence for operator review, never auto-grafted.
--
-- Additive + idempotent: safe to re-run. Does NOT alter any existing table.

-- ---------------------------------------------------------------------------
-- Part 2: canonical all-trades profit-capture outcome table
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS trade_profit_capture_analysis (
  id BIGSERIAL PRIMARY KEY,
  trade_instance_id BIGINT REFERENCES trade_instances(id),
  source_system TEXT,
  source_table TEXT,
  source_trade_id TEXT,
  symbol TEXT,
  execution_account TEXT,
  execution_broker TEXT,
  execution_environment TEXT,
  strategy_id TEXT,

  entry_time TIMESTAMPTZ,
  exit_time TIMESTAMPTZ,
  entry_price NUMERIC,
  exit_price NUMERIC,
  shares NUMERIC,
  realized_pnl NUMERIC,
  realized_pnl_pct NUMERIC,
  realized_r NUMERIC,

  mfe_price NUMERIC,
  mfe_pct NUMERIC,
  mfe_r NUMERIC,
  mae_pct NUMERIC,
  max_profit_usd NUMERIC,
  captured_profit_usd NUMERIC,
  money_left_usd NUMERIC,
  giveback_usd NUMERIC,
  giveback_pct_of_mfe NUMERIC,
  capture_ratio NUMERIC,

  winner BOOLEAN,
  measurable BOOLEAN,
  protection_needed BOOLEAN,
  protection_missed BOOLEAN,
  advisory_existed BOOLEAN,
  advisory_action TEXT,
  advisory_created_at TIMESTAMPTZ,
  operator_acted BOOLEAN,
  operator_decision TEXT,

  failure_class TEXT,
  failure_reason TEXT,
  data_quality TEXT,
  data_quality_notes JSONB DEFAULT '{}'::jsonb,

  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now(),

  UNIQUE(trade_instance_id)
);
CREATE INDEX IF NOT EXISTS idx_tpca_source_system ON trade_profit_capture_analysis(source_system);
CREATE INDEX IF NOT EXISTS idx_tpca_failure_class ON trade_profit_capture_analysis(failure_class);
CREATE INDEX IF NOT EXISTS idx_tpca_strategy ON trade_profit_capture_analysis(strategy_id);

-- ---------------------------------------------------------------------------
-- Part 5: profit-protection rule backtests (evidence only)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS profit_protection_rule_backtests (
  id BIGSERIAL PRIMARY KEY,
  run_id TEXT,
  rule_name TEXT,
  strategy_family TEXT,
  source_system TEXT,
  sample_size INTEGER,
  baseline_money_left NUMERIC,
  simulated_money_left NUMERIC,
  avoided_giveback NUMERIC,
  premature_exit_cost NUMERIC,
  net_improvement NUMERIC,
  win_rate_delta NUMERIC,
  profit_factor_delta NUMERIC,
  recommended BOOLEAN,
  recommendation_confidence TEXT,
  data_quality TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_pprb_run ON profit_protection_rule_backtests(run_id);
CREATE INDEX IF NOT EXISTS idx_pprb_rule ON profit_protection_rule_backtests(rule_name);

-- ---------------------------------------------------------------------------
-- Part 6: shadow advisory threshold recommendations (advisory only, never grafted)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS profit_protection_shadow_recommendations (
  id BIGSERIAL PRIMARY KEY,
  run_id TEXT,
  strategy_family TEXT,
  current_thresholds JSONB DEFAULT '{}'::jsonb,
  proposed_thresholds JSONB DEFAULT '{}'::jsonb,
  evidence_sample_size INTEGER,
  expected_giveback_reduction NUMERIC,
  expected_premature_exit_cost NUMERIC,
  confidence TEXT,
  graft_verdict TEXT,
  notes TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_ppsr_run ON profit_protection_shadow_recommendations(run_id);
CREATE INDEX IF NOT EXISTS idx_ppsr_family ON profit_protection_shadow_recommendations(strategy_family);
