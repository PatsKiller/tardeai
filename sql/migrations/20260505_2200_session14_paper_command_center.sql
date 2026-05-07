BEGIN;

-- paper_trade_proposals
CREATE TABLE IF NOT EXISTS paper_trade_proposals (
    id SERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    strategy_id TEXT NOT NULL DEFAULT 'momentum_scalp',
    setup_type TEXT,
    signal_score NUMERIC,
    signal_grade TEXT,
    signal_decision TEXT,
    source_signal_id INTEGER,
    source_strategy_card_id INTEGER,
    trade_plan_id INTEGER,
    rvol NUMERIC,
    float_m NUMERIC,
    gap_pct NUMERIC,
    catalyst TEXT,
    catalyst_verified BOOLEAN DEFAULT false,
    source_quality_score NUMERIC,
    data_quality_score INTEGER,
    intel_readiness INTEGER,
    vix_at_proposal NUMERIC,
    market_regime TEXT,
    proposed_account TEXT DEFAULT 'TOS_PAPER',
    proposed_entry NUMERIC NOT NULL,
    proposed_stop NUMERIC NOT NULL,
    proposed_target1 NUMERIC NOT NULL,
    proposed_target2 NUMERIC,
    proposed_shares INTEGER NOT NULL,
    proposed_dollar_size NUMERIC,
    proposed_dollar_risk NUMERIC,
    proposed_stop_pct NUMERIC,
    proposed_rr NUMERIC,
    tos_order_string TEXT,
    final_account TEXT,
    final_entry NUMERIC,
    final_stop NUMERIC,
    final_target1 NUMERIC,
    final_shares INTEGER,
    final_dollar_risk NUMERIC,
    risk_gate_result TEXT,
    risk_gate_codes JSONB,
    proposed_by TEXT DEFAULT 'system',
    status TEXT DEFAULT 'PENDING',
    paper_trade_id INTEGER,
    approved_at TIMESTAMPTZ,
    rejected_at TIMESTAMPTZ,
    rejection_reason TEXT,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_ptp_status ON paper_trade_proposals(status);
CREATE INDEX IF NOT EXISTS idx_ptp_symbol ON paper_trade_proposals(symbol);
CREATE INDEX IF NOT EXISTS idx_ptp_created ON paper_trade_proposals(created_at DESC);

-- Enrich paper_trades (additive only, skip if exists)
ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS proposal_id INTEGER;
ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS setup_type TEXT;
ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS signal_grade TEXT;
ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS automation_source TEXT;
ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS broker_submitted_at TIMESTAMPTZ;
ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS broker_filled_at TIMESTAMPTZ;
ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS broker_closed_at TIMESTAMPTZ;
ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS source_quality_score NUMERIC;
ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS data_quality_score INTEGER;
ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS r_multiple NUMERIC;
ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS planned_vs_actual_entry NUMERIC;

CREATE INDEX IF NOT EXISTS idx_paper_trades_strategy_status ON paper_trades(strategy_id, status);
CREATE INDEX IF NOT EXISTS idx_paper_trades_opened_via ON paper_trades(opened_via);

-- Sync log
CREATE TABLE IF NOT EXISTS paper_system_sync_log (
    id SERIAL PRIMARY KEY,
    component TEXT NOT NULL,
    status TEXT NOT NULL,
    message TEXT,
    payload JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_paper_sync_component ON paper_system_sync_log(component, created_at DESC);

-- paper_trade_commands (may exist from session 13)
CREATE TABLE IF NOT EXISTS paper_trade_commands (
    id SERIAL PRIMARY KEY,
    command_text TEXT,
    command_type TEXT,
    symbol TEXT,
    proposal_id INTEGER,
    paper_trade_id INTEGER,
    result TEXT,
    response_text TEXT,
    chat_id TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_ptc_created ON paper_trade_commands(created_at DESC);

COMMIT;
