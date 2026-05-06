-- Session 18c: Auto proposal generation stage 18f

CREATE TABLE IF NOT EXISTS auto_proposal_runs (
    id SERIAL PRIMARY KEY,
    run_label TEXT,
    run_date DATE DEFAULT CURRENT_DATE,
    status TEXT DEFAULT 'UNKNOWN',
    signals_checked INTEGER DEFAULT 0,
    proposals_created INTEGER DEFAULT 0,
    proposals_skipped INTEGER DEFAULT 0,
    duplicates_skipped INTEGER DEFAULT 0,
    risk_rejected INTEGER DEFAULT 0,
    quality_rejected INTEGER DEFAULT 0,
    source_cap_rejected INTEGER DEFAULT 0,
    sizing_adjusted INTEGER DEFAULT 0,
    reason_summary JSONB,
    started_at TIMESTAMPTZ DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_auto_proposal_runs_run
ON auto_proposal_runs(run_date, run_label, created_at DESC);

CREATE TABLE IF NOT EXISTS auto_proposal_decisions (
    id SERIAL PRIMARY KEY,
    run_label TEXT,
    source_signal_id INTEGER,
    symbol TEXT NOT NULL,
    strategy_id TEXT,
    decision TEXT NOT NULL,
    reason_codes JSONB,
    proposal_id INTEGER,
    original_shares INTEGER,
    adjusted_shares INTEGER,
    original_dollar_size NUMERIC,
    adjusted_dollar_size NUMERIC,
    original_dollar_risk NUMERIC,
    adjusted_dollar_risk NUMERIC,
    risk_gate_result TEXT,
    risk_gate_codes JSONB,
    quality_pass BOOLEAN,
    source_cap_pass BOOLEAN,
    payload JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_auto_proposal_decisions_run
ON auto_proposal_decisions(run_label, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_auto_proposal_decisions_signal
ON auto_proposal_decisions(source_signal_id);

CREATE INDEX IF NOT EXISTS idx_auto_proposal_decisions_symbol
ON auto_proposal_decisions(symbol, created_at DESC);

-- Enrich paper_trade_proposals with auto-proposal fields
ALTER TABLE paper_trade_proposals
ADD COLUMN IF NOT EXISTS auto_created BOOLEAN DEFAULT false,
ADD COLUMN IF NOT EXISTS auto_proposal_run_id INTEGER,
ADD COLUMN IF NOT EXISTS sizing_adjusted BOOLEAN DEFAULT false,
ADD COLUMN IF NOT EXISTS original_shares INTEGER,
ADD COLUMN IF NOT EXISTS adjusted_shares INTEGER,
ADD COLUMN IF NOT EXISTS sizing_reason TEXT,
ADD COLUMN IF NOT EXISTS auto_proposal_reason JSONB;

-- Add route tracking to strategy_signals
ALTER TABLE strategy_signals
ADD COLUMN IF NOT EXISTS route_match_reasons JSONB,
ADD COLUMN IF NOT EXISTS route_reject_reasons JSONB,
ADD COLUMN IF NOT EXISTS route_score NUMERIC;
