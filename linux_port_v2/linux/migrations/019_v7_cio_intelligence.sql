-- Trade AI v12 V7 CIO Intelligence Schema
-- Idempotent schema proposal. Review before applying.

CREATE TABLE IF NOT EXISTS cio_decisions (
    decision_id TEXT PRIMARY KEY,
    symbol TEXT,
    strategy_type TEXT,
    group_id TEXT,
    action TEXT NOT NULL,
    action_class TEXT,
    priority TEXT DEFAULT 'normal',
    confidence_raw NUMERIC,
    confidence_calibrated NUMERIC,
    decision_safety TEXT DEFAULT 'pending',
    human_review_required BOOLEAN DEFAULT false,
    rationale TEXT,
    supporting_signals JSONB DEFAULT '[]',
    supporting_research JSONB DEFAULT '[]',
    agent_votes JSONB DEFAULT '{}',
    rule_flags JSONB DEFAULT '[]',
    qa_flags JSONB DEFAULT '[]',
    expected_income_impact NUMERIC,
    expected_risk_impact NUMERIC,
    expected_allocation_impact NUMERIC,
    status TEXT DEFAULT 'proposed',
    created_at TIMESTAMPTZ DEFAULT now(),
    expires_at TIMESTAMPTZ,
    metadata JSONB DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS strategy_rotation_recommendations (
    rotation_id TEXT PRIMARY KEY,
    source_group_id TEXT,
    target_group_id TEXT,
    source_strategy_type TEXT,
    target_strategy_type TEXT,
    source_symbols JSONB DEFAULT '[]',
    target_symbols JSONB DEFAULT '[]',
    rotation_amount_pct NUMERIC,
    rotation_amount_dollars NUMERIC,
    rationale TEXT,
    signals JSONB DEFAULT '[]',
    research JSONB DEFAULT '[]',
    confidence NUMERIC,
    human_review_required BOOLEAN DEFAULT true,
    status TEXT DEFAULT 'proposed',
    created_at TIMESTAMPTZ DEFAULT now(),
    metadata JSONB DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS rebalance_plans (
    plan_id TEXT PRIMARY KEY,
    generated_at TIMESTAMPTZ DEFAULT now(),
    plan_status TEXT DEFAULT 'draft',
    total_trade_value NUMERIC,
    expected_income_change NUMERIC,
    expected_risk_change NUMERIC,
    expected_allocation_change NUMERIC,
    tax_notes TEXT,
    plan_summary TEXT,
    human_review_required BOOLEAN DEFAULT true,
    metadata JSONB DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS rebalance_plan_actions (
    action_id TEXT PRIMARY KEY,
    plan_id TEXT REFERENCES rebalance_plans(plan_id),
    symbol TEXT,
    account TEXT,
    action TEXT,
    quantity_estimate NUMERIC,
    dollar_amount NUMERIC,
    limit_price_suggestion NUMERIC,
    reason TEXT,
    source_decision_id TEXT,
    source_rotation_id TEXT,
    safety_status TEXT DEFAULT 'pending',
    human_review_required BOOLEAN DEFAULT true,
    metadata JSONB DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS marl_training_datasets (
    dataset_id TEXT PRIMARY KEY,
    generated_at TIMESTAMPTZ DEFAULT now(),
    row_count INTEGER,
    start_date DATE,
    end_date DATE,
    feature_schema JSONB DEFAULT '{}',
    source_tables JSONB DEFAULT '[]',
    status TEXT DEFAULT 'shadow_only',
    metadata JSONB DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS marl_simulation_runs (
    simulation_id TEXT PRIMARY KEY,
    dataset_id TEXT,
    policy_version TEXT,
    started_at TIMESTAMPTZ DEFAULT now(),
    completed_at TIMESTAMPTZ,
    status TEXT DEFAULT 'running',
    metrics JSONB DEFAULT '{}',
    violations JSONB DEFAULT '[]',
    notes TEXT
);

CREATE TABLE IF NOT EXISTS marl_policy_evaluations (
    evaluation_id TEXT PRIMARY KEY,
    policy_version TEXT,
    evaluated_at TIMESTAMPTZ DEFAULT now(),
    dataset_id TEXT,
    metrics JSONB DEFAULT '{}',
    safety_violations JSONB DEFAULT '[]',
    approved_for_live BOOLEAN DEFAULT false,
    human_review_required BOOLEAN DEFAULT true
);

CREATE TABLE IF NOT EXISTS marl_counterfactual_actions (
    id BIGSERIAL PRIMARY KEY,
    symbol TEXT,
    strategy_type TEXT,
    observed_action TEXT,
    marl_action TEXT,
    rule_allowed BOOLEAN,
    decision_qa_allowed BOOLEAN,
    counterfactual_reward NUMERIC,
    created_at TIMESTAMPTZ DEFAULT now(),
    metadata JSONB DEFAULT '{}'
);
