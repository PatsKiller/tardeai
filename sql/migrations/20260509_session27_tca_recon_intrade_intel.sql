-- Migration: Session 27 — TCA, Broker Reconciliation, In-Trade Intelligence
-- Date: 2026-05-09
-- Idempotent: safe to re-run

-- A. Paper Broker Reconciliation Runs
CREATE TABLE IF NOT EXISTS paper_broker_reconciliation_runs (
    id bigserial PRIMARY KEY,
    run_id text UNIQUE NOT NULL,
    started_at timestamptz DEFAULT now(),
    finished_at timestamptz,
    status text NOT NULL DEFAULT 'running',
    alpaca_mode text,
    broker_account_id_masked text,
    db_open_trades integer DEFAULT 0,
    broker_open_positions integer DEFAULT 0,
    broker_open_orders integer DEFAULT 0,
    matched_positions integer DEFAULT 0,
    unmatched_db_trades integer DEFAULT 0,
    unmatched_broker_positions integer DEFAULT 0,
    unmatched_orders integer DEFAULT 0,
    errors jsonb DEFAULT '[]'::jsonb,
    summary jsonb,
    created_at timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_pbr_runs_status ON paper_broker_reconciliation_runs(status);

-- B. Paper Broker Reconciliation Items
CREATE TABLE IF NOT EXISTS paper_broker_reconciliation_items (
    id bigserial PRIMARY KEY,
    run_id text NOT NULL,
    symbol text,
    paper_trade_id bigint,
    broker_position_id text,
    broker_order_id text,
    item_type text NOT NULL,
    severity text DEFAULT 'info',
    status text DEFAULT 'open',
    db_snapshot jsonb,
    broker_snapshot jsonb,
    difference jsonb,
    recommended_action text,
    resolved_at timestamptz,
    created_at timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_pbr_items_run ON paper_broker_reconciliation_items(run_id);
CREATE INDEX IF NOT EXISTS idx_pbr_items_symbol ON paper_broker_reconciliation_items(symbol);
CREATE INDEX IF NOT EXISTS idx_pbr_items_status ON paper_broker_reconciliation_items(status);

-- C. Paper Execution Quality Events
CREATE TABLE IF NOT EXISTS paper_execution_quality_events (
    id bigserial PRIMARY KEY,
    paper_trade_id bigint,
    symbol text NOT NULL,
    event_type text NOT NULL,
    broker_order_id text,
    expected_price numeric,
    actual_price numeric,
    slippage_abs numeric,
    slippage_bps numeric,
    expected_qty numeric,
    actual_qty numeric,
    fill_latency_seconds numeric,
    spread_bps numeric,
    quote_source text,
    quote_freshness_seconds numeric,
    market_session text,
    quality_grade text,
    result jsonb,
    created_at timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_peqe_trade ON paper_execution_quality_events(paper_trade_id);
CREATE INDEX IF NOT EXISTS idx_peqe_symbol ON paper_execution_quality_events(symbol);

-- D. Open Trade Intelligence Snapshots
CREATE TABLE IF NOT EXISTS open_trade_intelligence_snapshots (
    id bigserial PRIMARY KEY,
    paper_trade_id bigint,
    symbol text NOT NULL,
    snapshot_time timestamptz DEFAULT now(),
    current_price numeric,
    entry_price numeric,
    stop_price numeric,
    limit_price numeric,
    unrealized_pnl numeric,
    unrealized_pnl_pct numeric,
    r_multiple numeric,
    max_favorable_excursion numeric,
    max_adverse_excursion numeric,
    distance_to_stop_pct numeric,
    distance_to_target_pct numeric,
    atr numeric,
    rsi numeric,
    volume_ratio numeric,
    vwap numeric,
    trend_state text,
    catalyst_status text,
    news_risk_score numeric,
    technical_risk_score numeric,
    broker_order_state jsonb,
    quote_snapshot jsonb,
    intelligence_summary text,
    created_at timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_otis_trade ON open_trade_intelligence_snapshots(paper_trade_id);
CREATE INDEX IF NOT EXISTS idx_otis_symbol ON open_trade_intelligence_snapshots(symbol);

-- E. Open Trade Due Diligence Events
CREATE TABLE IF NOT EXISTS open_trade_due_diligence_events (
    id bigserial PRIMARY KEY,
    paper_trade_id bigint,
    symbol text NOT NULL,
    event_type text NOT NULL,
    severity text DEFAULT 'normal',
    detected_at timestamptz DEFAULT now(),
    source text,
    payload jsonb,
    requires_review boolean DEFAULT true,
    review_status text DEFAULT 'pending',
    created_at timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_otdde_trade ON open_trade_due_diligence_events(paper_trade_id);
CREATE INDEX IF NOT EXISTS idx_otdde_type ON open_trade_due_diligence_events(event_type);
CREATE INDEX IF NOT EXISTS idx_otdde_review ON open_trade_due_diligence_events(review_status);

-- F. Paper Order Modification Proposals
CREATE TABLE IF NOT EXISTS paper_order_modification_proposals (
    id bigserial PRIMARY KEY,
    proposal_id text UNIQUE NOT NULL,
    paper_trade_id bigint,
    symbol text NOT NULL,
    action text NOT NULL,
    current_stop numeric,
    proposed_stop numeric,
    current_limit numeric,
    proposed_limit numeric,
    current_qty numeric,
    proposed_qty numeric,
    current_order_ids jsonb,
    proposed_order_payload jsonb,
    reason text,
    evidence jsonb,
    risk_gate_result text,
    due_diligence_score numeric,
    confidence numeric,
    created_by text DEFAULT 'open_trade_manager',
    status text DEFAULT 'proposed',
    admin_decision text,
    admin_reason text,
    approved_by text,
    approved_at timestamptz,
    rejected_at timestamptz,
    executed_at timestamptz,
    broker_response jsonb,
    error_message text,
    expires_at timestamptz,
    created_at timestamptz DEFAULT now(),
    updated_at timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_pomp_status ON paper_order_modification_proposals(status);
CREATE INDEX IF NOT EXISTS idx_pomp_trade ON paper_order_modification_proposals(paper_trade_id);
CREATE INDEX IF NOT EXISTS idx_pomp_symbol ON paper_order_modification_proposals(symbol);

-- G. Paper Trade Outcome Analytics
CREATE TABLE IF NOT EXISTS paper_trade_outcome_analytics (
    id bigserial PRIMARY KEY,
    paper_trade_id bigint UNIQUE,
    symbol text NOT NULL,
    strategy_id text,
    opened_at timestamptz,
    closed_at timestamptz,
    hold_minutes numeric,
    entry_price numeric,
    exit_price numeric,
    stop_price numeric,
    target_price numeric,
    pnl numeric,
    pnl_pct numeric,
    r_multiple numeric,
    max_favorable_excursion numeric,
    max_adverse_excursion numeric,
    exit_reason text,
    planned_r numeric,
    realized_r numeric,
    followed_plan boolean,
    stop_adjusted_count integer DEFAULT 0,
    limit_adjusted_count integer DEFAULT 0,
    modification_proposals_count integer DEFAULT 0,
    approved_modifications_count integer DEFAULT 0,
    rejected_modifications_count integer DEFAULT 0,
    tca_grade text,
    outcome_verdict text,
    lessons jsonb,
    created_at timestamptz DEFAULT now(),
    updated_at timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_ptoa_symbol ON paper_trade_outcome_analytics(symbol);
CREATE INDEX IF NOT EXISTS idx_ptoa_strategy ON paper_trade_outcome_analytics(strategy_id);
