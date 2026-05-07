-- Session 16c: Paper Proposal Intelligence / Decision Packet
-- 2026-05-06

-- 2.1 paper_proposal_analysis
CREATE TABLE IF NOT EXISTS paper_proposal_analysis (
    id SERIAL PRIMARY KEY,
    proposal_id INTEGER,
    symbol TEXT NOT NULL,
    strategy_id TEXT,
    analysis_type TEXT DEFAULT 'proposal_decision_packet',
    model_used TEXT,
    source TEXT DEFAULT 'system',
    narrative_source TEXT,
    summary TEXT,
    approve_case TEXT,
    reject_case TEXT,
    invalidation TEXT,
    missing_data JSONB,
    technical_summary JSONB,
    catalyst_summary JSONB,
    sector_summary JSONB,
    risk_summary JSONB,
    pattern_summary JSONB,
    confidence NUMERIC,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_paper_proposal_analysis_proposal
ON paper_proposal_analysis(proposal_id);

CREATE INDEX IF NOT EXISTS idx_paper_proposal_analysis_symbol
ON paper_proposal_analysis(symbol);

CREATE INDEX IF NOT EXISTS idx_paper_proposal_analysis_created
ON paper_proposal_analysis(created_at DESC);

-- 2.2 Enrich paper_trade_proposals
ALTER TABLE paper_trade_proposals
ADD COLUMN IF NOT EXISTS source_table TEXT,
ADD COLUMN IF NOT EXISTS source_record_id TEXT,
ADD COLUMN IF NOT EXISTS screener_name TEXT,
ADD COLUMN IF NOT EXISTS discovery_source TEXT,
ADD COLUMN IF NOT EXISTS setup_description TEXT,
ADD COLUMN IF NOT EXISTS catalyst_confidence NUMERIC,
ADD COLUMN IF NOT EXISTS critic_verdict TEXT,
ADD COLUMN IF NOT EXISTS critic_confidence NUMERIC,
ADD COLUMN IF NOT EXISTS critic_reasoning TEXT,
ADD COLUMN IF NOT EXISTS sector TEXT,
ADD COLUMN IF NOT EXISTS industry TEXT,
ADD COLUMN IF NOT EXISTS country TEXT,
ADD COLUMN IF NOT EXISTS atr NUMERIC,
ADD COLUMN IF NOT EXISTS atr_pct NUMERIC,
ADD COLUMN IF NOT EXISTS rsi NUMERIC,
ADD COLUMN IF NOT EXISTS vwap_distance NUMERIC,
ADD COLUMN IF NOT EXISTS above_vwap BOOLEAN,
ADD COLUMN IF NOT EXISTS fib_context JSONB,
ADD COLUMN IF NOT EXISTS normal_pattern_summary TEXT,
ADD COLUMN IF NOT EXISTS missing_data JSONB,
ADD COLUMN IF NOT EXISTS risk_pct_portfolio NUMERIC,
ADD COLUMN IF NOT EXISTS target1_dollar_reward NUMERIC,
ADD COLUMN IF NOT EXISTS target2_dollar_reward NUMERIC;
