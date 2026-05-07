-- Session 17v3: Research Packet, Agent Review, Backtest Confidence
-- Paper proposal research intelligence upgrade

-- 2.1 Research packets
CREATE TABLE IF NOT EXISTS proposal_research_packets (
    id SERIAL PRIMARY KEY,
    proposal_id INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    strategy_id TEXT,
    packet_status TEXT DEFAULT 'pending',
    research_score NUMERIC,
    confidence_score NUMERIC,
    live_readiness_score NUMERIC,
    agent_review_complete BOOLEAN DEFAULT false,
    local_llm_review_complete BOOLEAN DEFAULT false,
    technical_review_complete BOOLEAN DEFAULT false,
    backtest_complete BOOLEAN DEFAULT false,
    risk_gate_snapshot JSONB,
    packet JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(proposal_id)
);

CREATE INDEX IF NOT EXISTS idx_prp_symbol_created
ON proposal_research_packets(symbol, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_prp_status
ON proposal_research_packets(packet_status);

-- 2.2 Agent reviews
CREATE TABLE IF NOT EXISTS proposal_agent_reviews (
    id SERIAL PRIMARY KEY,
    proposal_id INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    strategy_id TEXT,
    agent_name TEXT NOT NULL,
    role TEXT,
    status TEXT DEFAULT 'pending',
    vote TEXT,
    confidence NUMERIC,
    summary TEXT,
    concerns JSONB,
    required_followups JSONB,
    reviewed_by_model TEXT,
    reviewed_at TIMESTAMPTZ,
    payload JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(proposal_id, agent_name)
);

CREATE INDEX IF NOT EXISTS idx_par_proposal_agent
ON proposal_agent_reviews(proposal_id, agent_name);

CREATE INDEX IF NOT EXISTS idx_par_vote
ON proposal_agent_reviews(vote, created_at DESC);

-- 2.3 Backtest snapshots
CREATE TABLE IF NOT EXISTS proposal_backtest_snapshots (
    id SERIAL PRIMARY KEY,
    proposal_id INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    strategy_id TEXT,
    setup_type TEXT,
    sample_size INTEGER DEFAULT 0,
    symbol_sample_size INTEGER DEFAULT 0,
    strategy_sample_size INTEGER DEFAULT 0,
    pattern_sample_size INTEGER DEFAULT 0,
    win_rate NUMERIC,
    profit_factor NUMERIC,
    expectancy NUMERIC,
    avg_r NUMERIC,
    median_hold_minutes NUMERIC,
    similar_setup_summary TEXT,
    repeat_pattern_detected BOOLEAN DEFAULT false,
    repeat_pattern_description TEXT,
    backtest_quality TEXT,
    limitations JSONB,
    payload JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(proposal_id)
);

CREATE INDEX IF NOT EXISTS idx_pbs_symbol
ON proposal_backtest_snapshots(symbol, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_pbs_strategy
ON proposal_backtest_snapshots(strategy_id, created_at DESC);

-- 2.4 Enrich paper_trade_proposals
ALTER TABLE paper_trade_proposals
ADD COLUMN IF NOT EXISTS research_packet_id INTEGER,
ADD COLUMN IF NOT EXISTS agent_review_status TEXT,
ADD COLUMN IF NOT EXISTS local_llm_review_status TEXT,
ADD COLUMN IF NOT EXISTS backtest_status TEXT,
ADD COLUMN IF NOT EXISTS research_score NUMERIC,
ADD COLUMN IF NOT EXISTS confidence_score NUMERIC,
ADD COLUMN IF NOT EXISTS live_readiness_score NUMERIC,
ADD COLUMN IF NOT EXISTS approval_blocked_reason TEXT,
ADD COLUMN IF NOT EXISTS approval_allowed BOOLEAN,
ADD COLUMN IF NOT EXISTS required_reviews JSONB,
ADD COLUMN IF NOT EXISTS completed_reviews JSONB,
ADD COLUMN IF NOT EXISTS stock_history_summary TEXT,
ADD COLUMN IF NOT EXISTS technical_context JSONB,
ADD COLUMN IF NOT EXISTS backtest_summary JSONB;

-- 2.5 Enrich paper_trades
ALTER TABLE paper_trades
ADD COLUMN IF NOT EXISTS research_packet_id INTEGER,
ADD COLUMN IF NOT EXISTS decision_state TEXT,
ADD COLUMN IF NOT EXISTS confidence_score NUMERIC,
ADD COLUMN IF NOT EXISTS agent_votes JSONB,
ADD COLUMN IF NOT EXISTS backtest_quality TEXT,
ADD COLUMN IF NOT EXISTS approval_mode TEXT;
