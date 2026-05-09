-- Migration: Paper Validation Gate
-- Date: 2026-05-09
-- Idempotent: safe to re-run

CREATE TABLE IF NOT EXISTS paper_validation_policy (
    id bigserial PRIMARY KEY,
    policy_key text UNIQUE NOT NULL,
    active boolean DEFAULT true,
    validation_start_date date,
    minimum_validation_days integer DEFAULT 183,
    minimum_closed_trades integer DEFAULT 100,
    minimum_win_rate numeric DEFAULT 0.55,
    minimum_profit_factor numeric DEFAULT 1.30,
    requires_governance_approval boolean DEFAULT true,
    live_trading_allowed boolean DEFAULT false,
    notes text,
    created_at timestamptz DEFAULT now(),
    updated_at timestamptz DEFAULT now()
);

CREATE TABLE IF NOT EXISTS paper_validation_daily_metrics (
    id bigserial PRIMARY KEY,
    metric_date date UNIQUE NOT NULL,
    closed_trades integer DEFAULT 0,
    wins integer DEFAULT 0,
    losses integer DEFAULT 0,
    win_rate numeric,
    gross_profit numeric,
    gross_loss numeric,
    profit_factor numeric,
    max_drawdown numeric,
    open_paper_trades integer,
    generated_at timestamptz DEFAULT now(),
    payload jsonb
);

CREATE TABLE IF NOT EXISTS governance_approvals (
    id bigserial PRIMARY KEY,
    approval_key text UNIQUE NOT NULL,
    approval_type text NOT NULL,
    approved boolean DEFAULT false,
    approved_by text,
    approved_at timestamptz,
    rationale text,
    payload jsonb,
    created_at timestamptz DEFAULT now()
);

-- Seed default policy (idempotent)
INSERT INTO paper_validation_policy (policy_key, active, validation_start_date, minimum_validation_days,
    minimum_closed_trades, minimum_win_rate, minimum_profit_factor, requires_governance_approval,
    live_trading_allowed, notes)
VALUES ('live_trading_gate_v1', true, CURRENT_DATE, 183, 100, 0.55, 1.30, true, false,
    'Default paper validation policy — live trading blocked until all gates pass')
ON CONFLICT (policy_key) DO NOTHING;
