-- Session 27: TCA, Reconciliation, Outcome schema hardening
-- Date: 2026-05-08

-- paper_execution_quality additions
ALTER TABLE paper_execution_quality
ADD COLUMN IF NOT EXISTS order_submitted_at TIMESTAMPTZ,
ADD COLUMN IF NOT EXISTS order_filled_at TIMESTAMPTZ,
ADD COLUMN IF NOT EXISTS time_to_fill_seconds NUMERIC,
ADD COLUMN IF NOT EXISTS intended_shares NUMERIC,
ADD COLUMN IF NOT EXISTS filled_shares NUMERIC,
ADD COLUMN IF NOT EXISTS partial_fill BOOLEAN DEFAULT false,
ADD COLUMN IF NOT EXISTS price_improvement_pct NUMERIC,
ADD COLUMN IF NOT EXISTS quote_age_seconds NUMERIC,
ADD COLUMN IF NOT EXISTS market_session TEXT,
ADD COLUMN IF NOT EXISTS readiness_state_at_submit TEXT,
ADD COLUMN IF NOT EXISTS lifecycle_state_at_submit TEXT,
ADD COLUMN IF NOT EXISTS action_state_at_submit TEXT,
ADD COLUMN IF NOT EXISTS packet_completion_pct_at_submit NUMERIC,
ADD COLUMN IF NOT EXISTS data_quality_grade TEXT;

-- broker_reconciliation_items additions
ALTER TABLE broker_reconciliation_items
ADD COLUMN IF NOT EXISTS local_status TEXT,
ADD COLUMN IF NOT EXISTS broker_status TEXT,
ADD COLUMN IF NOT EXISTS local_qty NUMERIC,
ADD COLUMN IF NOT EXISTS broker_qty NUMERIC,
ADD COLUMN IF NOT EXISTS local_avg_price NUMERIC,
ADD COLUMN IF NOT EXISTS broker_avg_price NUMERIC,
ADD COLUMN IF NOT EXISTS severity TEXT DEFAULT 'INFO',
ADD COLUMN IF NOT EXISTS recommended_action TEXT;

-- trade_thesis_outcomes additions
ALTER TABLE trade_thesis_outcomes
ADD COLUMN IF NOT EXISTS max_favorable_excursion_pct NUMERIC,
ADD COLUMN IF NOT EXISTS max_adverse_excursion_pct NUMERIC,
ADD COLUMN IF NOT EXISTS time_in_trade_minutes NUMERIC,
ADD COLUMN IF NOT EXISTS exit_reason TEXT,
ADD COLUMN IF NOT EXISTS thesis_followed BOOLEAN,
ADD COLUMN IF NOT EXISTS strategy_fit_score_at_entry NUMERIC,
ADD COLUMN IF NOT EXISTS catalyst_quality_at_entry TEXT,
ADD COLUMN IF NOT EXISTS technical_grade_at_entry TEXT,
ADD COLUMN IF NOT EXISTS agent_consensus_at_entry TEXT,
ADD COLUMN IF NOT EXISTS llm_verdict_at_entry TEXT;

-- paper_dashboard_snapshots
CREATE TABLE IF NOT EXISTS paper_dashboard_snapshots (
    id SERIAL PRIMARY KEY,
    snapshot_type TEXT NOT NULL,
    window_start TIMESTAMPTZ,
    window_end TIMESTAMPTZ,
    payload JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pds_type_created
ON paper_dashboard_snapshots(snapshot_type, created_at DESC);
