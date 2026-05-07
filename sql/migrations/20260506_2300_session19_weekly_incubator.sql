-- Session 19: Weekly Incubator + Roll-On/Roll-Off + Proposal Quality Review
-- 2026-05-06

CREATE TABLE IF NOT EXISTS incubator_universe (
    id SERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    strategy_id TEXT,
    first_seen_at TIMESTAMPTZ DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ DEFAULT NOW(),
    status TEXT DEFAULT 'ACTIVE',
    lifecycle_state TEXT DEFAULT 'ROLLED_ON',
    source_first_seen TEXT,
    source_latest TEXT,
    source_run_label TEXT,
    baseline_score NUMERIC,
    latest_score NUMERIC,
    best_score NUMERIC,
    score_delta NUMERIC,
    rvol_baseline NUMERIC,
    rvol_latest NUMERIC,
    gap_baseline NUMERIC,
    gap_latest NUMERIC,
    catalyst TEXT,
    catalyst_verified BOOLEAN,
    sector TEXT,
    industry TEXT,
    days_active INTEGER DEFAULT 0,
    promoted_to_signal_at TIMESTAMPTZ,
    promoted_to_proposal_at TIMESTAMPTZ,
    last_paper_trade_id INTEGER,
    last_outcome TEXT,
    rolloff_reason TEXT,
    notes TEXT,
    evidence_payload JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(symbol, strategy_id)
);

CREATE INDEX IF NOT EXISTS idx_incubator_universe_status
ON incubator_universe(status, lifecycle_state, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_incubator_universe_symbol
ON incubator_universe(symbol, updated_at DESC);

CREATE TABLE IF NOT EXISTS incubator_events (
    id SERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    strategy_id TEXT,
    event_type TEXT NOT NULL,
    reason_codes JSONB,
    old_score NUMERIC,
    new_score NUMERIC,
    payload JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_incubator_events_symbol
ON incubator_events(symbol, created_at DESC);

CREATE TABLE IF NOT EXISTS proposal_quality_reviews (
    id SERIAL PRIMARY KEY,
    proposal_id INTEGER,
    symbol TEXT NOT NULL,
    strategy_id TEXT,
    review_state TEXT,
    quality_score NUMERIC,
    approve_case TEXT,
    reject_case TEXT,
    missing_data JSONB,
    source_evidence JSONB,
    llm_model TEXT,
    narrative_source TEXT,
    payload JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pqr_proposal
ON proposal_quality_reviews(proposal_id, created_at DESC);
