-- Session 23C: Institutional Proposal Packet Schema
-- Trade AI v12 — May 2026
-- Additive only: CREATE TABLE IF NOT EXISTS, ALTER TABLE ADD COLUMN IF NOT EXISTS

-- 2.1 Proposal evidence snapshots
CREATE TABLE IF NOT EXISTS proposal_evidence_snapshots (
    id SERIAL PRIMARY KEY,
    proposal_id INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    strategy_id TEXT,
    snapshot_type TEXT DEFAULT 'pre_submit',
    scan_snapshot JSONB,
    indicator_snapshot JSONB,
    quote_snapshot JSONB,
    catalyst_snapshot JSONB,
    agent_snapshot JSONB,
    llm_snapshot JSONB,
    quality_snapshot JSONB,
    backtest_snapshot JSONB,
    risk_snapshot JSONB,
    execution_snapshot JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_pes_proposal_created
ON proposal_evidence_snapshots(proposal_id, created_at DESC);

-- 2.2 Proposal technical snapshots
CREATE TABLE IF NOT EXISTS proposal_technical_snapshots (
    id SERIAL PRIMARY KEY,
    proposal_id INTEGER,
    symbol TEXT NOT NULL,
    timeframe TEXT DEFAULT 'daily',
    rsi_14 NUMERIC,
    atr_14 NUMERIC,
    atr_pct NUMERIC,
    vwap NUMERIC,
    vwap_distance_pct NUMERIC,
    above_vwap BOOLEAN,
    ema_8 NUMERIC,
    ema_21 NUMERIC,
    ema_50 NUMERIC,
    ema_200 NUMERIC,
    ema_alignment TEXT,
    macd_state TEXT,
    bollinger_position TEXT,
    ttm_squeeze BOOLEAN,
    squeeze_state TEXT,
    support_1 NUMERIC,
    support_2 NUMERIC,
    resistance_1 NUMERIC,
    resistance_2 NUMERIC,
    fib_context JSONB,
    opening_range_high NUMERIC,
    opening_range_low NUMERIC,
    premarket_high NUMERIC,
    premarket_low NUMERIC,
    confluence_score NUMERIC,
    technical_grade TEXT,
    missing_data JSONB,
    source TEXT,
    computed_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_pts_proposal
ON proposal_technical_snapshots(proposal_id, computed_at DESC);
CREATE INDEX IF NOT EXISTS idx_pts_symbol
ON proposal_technical_snapshots(symbol, computed_at DESC);

-- 2.3 Strategy backtest results
CREATE TABLE IF NOT EXISTS strategy_backtest_results (
    id SERIAL PRIMARY KEY,
    strategy_id TEXT NOT NULL,
    symbol TEXT,
    setup_type TEXT,
    catalyst_type TEXT,
    market_regime TEXT,
    sector TEXT,
    timeframe TEXT,
    sample_size INTEGER DEFAULT 0,
    wins INTEGER DEFAULT 0,
    losses INTEGER DEFAULT 0,
    win_rate NUMERIC,
    avg_r NUMERIC,
    median_r NUMERIC,
    expectancy_r NUMERIC,
    profit_factor NUMERIC,
    max_drawdown_r NUMERIC,
    avg_hold_minutes NUMERIC,
    best_case_r NUMERIC,
    worst_case_r NUMERIC,
    confidence_level TEXT,
    sample_warning TEXT,
    parameters JSONB,
    result_distribution JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_sbr_strategy_created
ON strategy_backtest_results(strategy_id, created_at DESC);

-- 2.4 Proposal execution readiness
CREATE TABLE IF NOT EXISTS proposal_execution_readiness (
    id SERIAL PRIMARY KEY,
    proposal_id INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    strategy_id TEXT,
    readiness_state TEXT NOT NULL,
    readiness_score NUMERIC,
    quote_price NUMERIC,
    quote_timestamp TIMESTAMPTZ,
    quote_age_seconds NUMERIC,
    bid NUMERIC,
    ask NUMERIC,
    spread NUMERIC,
    spread_pct NUMERIC,
    entry_price NUMERIC,
    price_vs_entry_pct NUMERIC,
    slippage_budget_pct NUMERIC,
    liquidity_ok BOOLEAN,
    spread_ok BOOLEAN,
    quote_fresh BOOLEAN,
    price_ok BOOLEAN,
    risk_gate_ok BOOLEAN,
    duplicate_ok BOOLEAN,
    indicators_ok BOOLEAN,
    backtest_ok BOOLEAN,
    blockers JSONB,
    warnings JSONB,
    execution_plan JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_per_proposal_created
ON proposal_execution_readiness(proposal_id, created_at DESC);

-- 2.5 Proposal event log
CREATE TABLE IF NOT EXISTS proposal_event_log (
    id SERIAL PRIMARY KEY,
    proposal_id INTEGER,
    paper_trade_id INTEGER,
    symbol TEXT,
    event_type TEXT NOT NULL,
    event_source TEXT,
    payload JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_pel_proposal_created
ON proposal_event_log(proposal_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_pel_event_type
ON proposal_event_log(event_type, created_at DESC);

-- 2.6 Add proposal columns if missing
ALTER TABLE paper_trade_proposals
ADD COLUMN IF NOT EXISTS institutional_packet_ready BOOLEAN DEFAULT false;
ALTER TABLE paper_trade_proposals
ADD COLUMN IF NOT EXISTS latest_execution_readiness TEXT;
ALTER TABLE paper_trade_proposals
ADD COLUMN IF NOT EXISTS latest_strategy_edge JSONB;
ALTER TABLE paper_trade_proposals
ADD COLUMN IF NOT EXISTS latest_evidence_snapshot_id INTEGER;
ALTER TABLE paper_trade_proposals
ADD COLUMN IF NOT EXISTS alpaca_paper_submit_enabled BOOLEAN DEFAULT false;
ALTER TABLE paper_trade_proposals
ADD COLUMN IF NOT EXISTS live_submit_blocked_reason TEXT DEFAULT 'Live trading disabled pending six-month paper validation';
