-- Migration: 20260512_execution_safety_overhaul.sql
-- Adds execution safety audit trail columns and risk action tracking table

-- Proposal eligibility tracking
ALTER TABLE paper_trade_proposals ADD COLUMN IF NOT EXISTS execution_eligibility_status TEXT;
ALTER TABLE paper_trade_proposals ADD COLUMN IF NOT EXISTS execution_eligibility_reason TEXT;
ALTER TABLE paper_trade_proposals ADD COLUMN IF NOT EXISTS live_price_at_execution NUMERIC;
ALTER TABLE paper_trade_proposals ADD COLUMN IF NOT EXISTS live_price_timestamp TIMESTAMPTZ;

-- Trade risk snapshot at fill + lifecycle state
ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS risk_params_at_fill JSONB;
ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS lifecycle_state TEXT DEFAULT 'open';

-- Risk action tracking (stop adjustments, auto-closes, trailing stops)
CREATE TABLE IF NOT EXISTS paper_trade_risk_actions (
    id SERIAL PRIMARY KEY,
    paper_trade_id INTEGER REFERENCES paper_trades(id),
    symbol TEXT NOT NULL,
    action_type TEXT NOT NULL,
    old_value NUMERIC,
    new_value NUMERIC,
    trigger_price NUMERIC,
    trigger_reason TEXT,
    broker_order_updated BOOLEAN DEFAULT false,
    action_result JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_risk_actions_trade ON paper_trade_risk_actions(paper_trade_id);
CREATE INDEX IF NOT EXISTS idx_risk_actions_symbol ON paper_trade_risk_actions(symbol);
