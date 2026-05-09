-- Migration: Universal Execution-Time Revalidation
-- Date: 2026-05-09
-- Idempotent: safe to re-run

-- A. Paper Trade Execution Rechecks
CREATE TABLE IF NOT EXISTS paper_trade_execution_rechecks (
    id bigserial PRIMARY KEY,
    recheck_id text UNIQUE NOT NULL,
    paper_trade_proposal_id bigint,
    paper_trade_id bigint,
    symbol text NOT NULL,
    trigger_type text NOT NULL,
    recommendation_created_at timestamptz,
    approval_created_at timestamptz,
    recheck_reason text,
    elapsed_since_recommendation_seconds numeric,
    elapsed_since_approval_seconds numeric,
    status text NOT NULL DEFAULT 'pending',
    original_plan jsonb,
    recalibrated_plan jsonb,
    quote_snapshot jsonb,
    market_session text,
    price_at_recommendation numeric,
    price_at_approval numeric,
    current_price numeric,
    price_drift_pct numeric,
    spread_bps numeric,
    volume_ratio numeric,
    atr numeric,
    rsi numeric,
    risk_gate_result text,
    execution_readiness_score numeric,
    material_change_detected boolean DEFAULT false,
    material_change_reasons jsonb DEFAULT '[]'::jsonb,
    recommendation text,
    reason text,
    requires_reapproval boolean DEFAULT false,
    admin_approval_status text,
    created_at timestamptz DEFAULT now(),
    started_at timestamptz,
    finished_at timestamptz,
    expires_at timestamptz,
    updated_at timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_pter_status ON paper_trade_execution_rechecks(status);
CREATE INDEX IF NOT EXISTS idx_pter_symbol ON paper_trade_execution_rechecks(symbol);
CREATE INDEX IF NOT EXISTS idx_pter_proposal ON paper_trade_execution_rechecks(paper_trade_proposal_id);

-- B. Paper Trade Pre-Execution Events
CREATE TABLE IF NOT EXISTS paper_trade_pre_execution_events (
    id bigserial PRIMARY KEY,
    symbol text NOT NULL,
    proposal_id bigint,
    event_type text NOT NULL,
    severity text DEFAULT 'normal',
    payload jsonb,
    created_at timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_ptpee_symbol ON paper_trade_pre_execution_events(symbol);
CREATE INDEX IF NOT EXISTS idx_ptpee_proposal ON paper_trade_pre_execution_events(proposal_id);

-- C. Guarded ALTER TABLE on paper_trade_proposals (add revalidation columns)
DO $$ BEGIN
    ALTER TABLE paper_trade_proposals ADD COLUMN execution_recheck_required boolean DEFAULT true;
EXCEPTION WHEN duplicate_column THEN NULL; END $$;

DO $$ BEGIN
    ALTER TABLE paper_trade_proposals ADD COLUMN approved_pending_recheck boolean DEFAULT false;
EXCEPTION WHEN duplicate_column THEN NULL; END $$;

DO $$ BEGIN
    ALTER TABLE paper_trade_proposals ADD COLUMN execution_recheck_reason text;
EXCEPTION WHEN duplicate_column THEN NULL; END $$;

DO $$ BEGIN
    ALTER TABLE paper_trade_proposals ADD COLUMN last_recheck_id text;
EXCEPTION WHEN duplicate_column THEN NULL; END $$;

DO $$ BEGIN
    ALTER TABLE paper_trade_proposals ADD COLUMN execution_validated_at timestamptz;
EXCEPTION WHEN duplicate_column THEN NULL; END $$;

DO $$ BEGIN
    ALTER TABLE paper_trade_proposals ADD COLUMN execution_readiness_score numeric;
EXCEPTION WHEN duplicate_column THEN NULL; END $$;

DO $$ BEGIN
    ALTER TABLE paper_trade_proposals ADD COLUMN material_change_pending_approval boolean DEFAULT false;
EXCEPTION WHEN duplicate_column THEN NULL; END $$;

-- D. Guarded ALTER TABLE on paper_trades (add recheck tracking)
DO $$ BEGIN
    ALTER TABLE paper_trades ADD COLUMN entered_after_recheck boolean DEFAULT false;
EXCEPTION WHEN duplicate_column THEN NULL; END $$;

DO $$ BEGIN
    ALTER TABLE paper_trades ADD COLUMN entry_recheck_id text;
EXCEPTION WHEN duplicate_column THEN NULL; END $$;

DO $$ BEGIN
    ALTER TABLE paper_trades ADD COLUMN entry_readiness_score numeric;
EXCEPTION WHEN duplicate_column THEN NULL; END $$;

DO $$ BEGIN
    ALTER TABLE paper_trades ADD COLUMN recommendation_to_entry_seconds numeric;
EXCEPTION WHEN duplicate_column THEN NULL; END $$;

DO $$ BEGIN
    ALTER TABLE paper_trades ADD COLUMN approval_to_entry_seconds numeric;
EXCEPTION WHEN duplicate_column THEN NULL; END $$;

-- E. Paper Trade Execution Windows
CREATE TABLE IF NOT EXISTS paper_trade_execution_windows (
    id              BIGSERIAL PRIMARY KEY,
    symbol          TEXT NOT NULL,
    strategy_id     TEXT,
    proposal_id     BIGINT,
    window_date     DATE NOT NULL,
    window_start    TIMESTAMPTZ,
    window_end      TIMESTAMPTZ,
    window_type     TEXT,
    readiness_score NUMERIC,
    reason          TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_ptew_symbol ON paper_trade_execution_windows(symbol);
CREATE INDEX IF NOT EXISTS idx_ptew_proposal ON paper_trade_execution_windows(proposal_id);

-- F. Additional columns on rechecks table
DO $$ BEGIN ALTER TABLE paper_trade_execution_rechecks ADD COLUMN gap_pct numeric; EXCEPTION WHEN duplicate_column THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE paper_trade_execution_rechecks ADD COLUMN vwap numeric; EXCEPTION WHEN duplicate_column THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE paper_trade_execution_rechecks ADD COLUMN opening_range_state text; EXCEPTION WHEN duplicate_column THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE paper_trade_execution_rechecks ADD COLUMN news_delta jsonb; EXCEPTION WHEN duplicate_column THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE paper_trade_execution_rechecks ADD COLUMN catalyst_delta jsonb; EXCEPTION WHEN duplicate_column THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE paper_trade_execution_rechecks ADD COLUMN market_calendar jsonb; EXCEPTION WHEN duplicate_column THEN NULL; END $$;

-- G. Additional proposal columns
DO $$ BEGIN ALTER TABLE paper_trade_proposals ADD COLUMN next_recheck_at timestamptz; EXCEPTION WHEN duplicate_column THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE paper_trade_proposals ADD COLUMN recommendation_created_at timestamptz; EXCEPTION WHEN duplicate_column THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE paper_trade_proposals ADD COLUMN last_plan_price numeric; EXCEPTION WHEN duplicate_column THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE paper_trade_proposals ADD COLUMN last_plan_updated_at timestamptz; EXCEPTION WHEN duplicate_column THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE paper_trade_proposals ADD COLUMN execution_status text DEFAULT 'not_submitted'; EXCEPTION WHEN duplicate_column THEN NULL; END $$;
