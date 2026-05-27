-- v3.1/v3.2 Lifecycle Trace Tables

CREATE TABLE IF NOT EXISTS lifecycle_trace (
    trace_id TEXT PRIMARY KEY,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    symbol TEXT NOT NULL,
    strategy_id TEXT,
    strategy_family TEXT,
    source_stage TEXT,
    current_stage TEXT,
    source_system TEXT,
    prospect_id TEXT,
    research_id TEXT,
    signal_id TEXT,
    proposal_id TEXT,
    paper_trade_id BIGINT,
    broker_order_id TEXT,
    status TEXT DEFAULT 'active',
    confidence NUMERIC,
    score NUMERIC,
    reason TEXT,
    payload JSONB
);
CREATE INDEX IF NOT EXISTS idx_lt_symbol ON lifecycle_trace(symbol);
CREATE INDEX IF NOT EXISTS idx_lt_strategy ON lifecycle_trace(strategy_id);
CREATE INDEX IF NOT EXISTS idx_lt_stage ON lifecycle_trace(current_stage);
CREATE INDEX IF NOT EXISTS idx_lt_proposal ON lifecycle_trace(proposal_id);
CREATE INDEX IF NOT EXISTS idx_lt_trade ON lifecycle_trace(paper_trade_id);

CREATE TABLE IF NOT EXISTS lifecycle_trace_events (
    id BIGSERIAL PRIMARY KEY,
    trace_id TEXT REFERENCES lifecycle_trace(trace_id),
    event_time TIMESTAMPTZ DEFAULT now(),
    stage TEXT NOT NULL,
    event_type TEXT NOT NULL,
    source_script TEXT,
    source_table TEXT,
    source_id TEXT,
    status TEXT,
    message TEXT,
    payload JSONB
);
CREATE INDEX IF NOT EXISTS idx_lte_trace ON lifecycle_trace_events(trace_id);
CREATE INDEX IF NOT EXISTS idx_lte_time ON lifecycle_trace_events(event_time DESC);

CREATE TABLE IF NOT EXISTS proposal_dedup_audit (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ DEFAULT now(),
    duplicate_key TEXT NOT NULL,
    symbol TEXT,
    strategy_id TEXT,
    canonical_proposal_id TEXT,
    duplicate_proposal_ids JSONB,
    duplicate_count INTEGER,
    recommended_action TEXT,
    payload JSONB
);
CREATE INDEX IF NOT EXISTS idx_pda_key ON proposal_dedup_audit(duplicate_key);
