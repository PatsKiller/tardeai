-- Session 24A: Proposal Lifecycle + Governance Foundation
-- Date: 2026-05-07

-- 2.1 Lifecycle columns on paper_trade_proposals
ALTER TABLE paper_trade_proposals
ADD COLUMN IF NOT EXISTS lifecycle_status TEXT DEFAULT 'ACTIVE',
ADD COLUMN IF NOT EXISTS lifecycle_message TEXT,
ADD COLUMN IF NOT EXISTS entry_zone_status TEXT,
ADD COLUMN IF NOT EXISTS entry_zone_valid BOOLEAN,
ADD COLUMN IF NOT EXISTS current_price NUMERIC,
ADD COLUMN IF NOT EXISTS price_drift_pct NUMERIC,
ADD COLUMN IF NOT EXISTS last_price_source TEXT,
ADD COLUMN IF NOT EXISTS last_price_checked_at TIMESTAMPTZ,
ADD COLUMN IF NOT EXISTS base_expires_at TIMESTAMPTZ,
ADD COLUMN IF NOT EXISTS max_expires_at TIMESTAMPTZ,
ADD COLUMN IF NOT EXISTS expiry_extended_count INTEGER DEFAULT 0,
ADD COLUMN IF NOT EXISTS last_lifecycle_check_at TIMESTAMPTZ,
ADD COLUMN IF NOT EXISTS overnight_monitoring_enabled BOOLEAN DEFAULT false,
ADD COLUMN IF NOT EXISTS proposal_timeframe_class TEXT,
ADD COLUMN IF NOT EXISTS manual_review_required BOOLEAN DEFAULT false,
ADD COLUMN IF NOT EXISTS lifecycle_blockers JSONB,
ADD COLUMN IF NOT EXISTS lifecycle_warnings JSONB;

-- 2.2 Lifecycle events
CREATE TABLE IF NOT EXISTS proposal_lifecycle_events (
    id SERIAL PRIMARY KEY,
    proposal_id INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    strategy_id TEXT,
    event_type TEXT NOT NULL,
    lifecycle_status TEXT,
    current_price NUMERIC,
    entry_price NUMERIC,
    price_drift_pct NUMERIC,
    quote_provider TEXT,
    quote_is_delayed BOOLEAN,
    quote_execution_eligible BOOLEAN,
    news_count INTEGER,
    expiry_before TIMESTAMPTZ,
    expiry_after TIMESTAMPTZ,
    message TEXT,
    payload JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ple_proposal_created
ON proposal_lifecycle_events(proposal_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ple_symbol_created
ON proposal_lifecycle_events(symbol, created_at DESC);

-- 2.3 TCA / execution quality
CREATE TABLE IF NOT EXISTS paper_execution_quality (
    id SERIAL PRIMARY KEY,
    paper_trade_id INTEGER,
    proposal_id INTEGER,
    symbol TEXT NOT NULL,
    strategy_id TEXT,
    order_id TEXT,
    client_order_id TEXT,
    intended_entry NUMERIC,
    submitted_limit_price NUMERIC,
    fill_price NUMERIC,
    arrival_price NUMERIC,
    quote_bid NUMERIC,
    quote_ask NUMERIC,
    spread_pct NUMERIC,
    slippage_pct NUMERIC,
    slippage_dollars NUMERIC,
    fill_quality TEXT,
    liquidity_context JSONB,
    tca_payload JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_peq_trade_created
ON paper_execution_quality(paper_trade_id, created_at DESC);

-- 2.4 Broker reconciliation
CREATE TABLE IF NOT EXISTS broker_reconciliation_runs (
    id SERIAL PRIMARY KEY,
    broker TEXT DEFAULT 'alpaca_paper',
    run_status TEXT,
    orders_seen INTEGER DEFAULT 0,
    positions_seen INTEGER DEFAULT 0,
    trades_matched INTEGER DEFAULT 0,
    unmatched_broker_orders INTEGER DEFAULT 0,
    unmatched_local_trades INTEGER DEFAULT 0,
    issues JSONB,
    started_at TIMESTAMPTZ DEFAULT NOW(),
    finished_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS broker_reconciliation_items (
    id SERIAL PRIMARY KEY,
    run_id INTEGER,
    broker TEXT DEFAULT 'alpaca_paper',
    broker_order_id TEXT,
    client_order_id TEXT,
    paper_trade_id INTEGER,
    proposal_id INTEGER,
    symbol TEXT,
    reconciliation_state TEXT,
    issue_code TEXT,
    payload JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 2.5 Thesis-vs-outcome
CREATE TABLE IF NOT EXISTS trade_thesis_outcomes (
    id SERIAL PRIMARY KEY,
    paper_trade_id INTEGER,
    proposal_id INTEGER,
    symbol TEXT NOT NULL,
    strategy_id TEXT,
    thesis_snapshot_id INTEGER,
    expected_entry NUMERIC,
    expected_stop NUMERIC,
    expected_target NUMERIC,
    expected_r NUMERIC,
    actual_entry NUMERIC,
    actual_exit NUMERIC,
    actual_r NUMERIC,
    thesis_result TEXT,
    invalidation_hit BOOLEAN,
    kill_condition_triggered TEXT,
    llm_review_model TEXT,
    review_payload JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 2.6 Six-month governance
CREATE TABLE IF NOT EXISTS paper_performance_governance (
    id SERIAL PRIMARY KEY,
    strategy_id TEXT,
    window_start DATE,
    window_end DATE,
    calendar_days INTEGER,
    paper_trades INTEGER DEFAULT 0,
    closed_trades INTEGER DEFAULT 0,
    win_rate NUMERIC,
    avg_r NUMERIC,
    expectancy_r NUMERIC,
    profit_factor NUMERIC,
    max_drawdown_r NUMERIC,
    tca_avg_slippage_pct NUMERIC,
    broker_recon_issues INTEGER DEFAULT 0,
    governance_state TEXT DEFAULT 'PAPER_ONLY',
    live_eligible BOOLEAN DEFAULT false,
    live_block_reason TEXT DEFAULT 'Requires six months of validated paper results',
    payload JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
