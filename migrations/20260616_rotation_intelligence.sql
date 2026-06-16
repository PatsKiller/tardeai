-- Advisory rotation intelligence schema
-- Date: 2026-06-16
-- Safety: advisory only. No broker order table, no execution trigger, no broker endpoint.

CREATE TABLE IF NOT EXISTS rotation_opportunities (
    id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    account_key TEXT,
    asset_class TEXT,
    sector TEXT,
    strategy_type TEXT,
    current_value NUMERIC,
    target_value NUMERIC,
    over_under_weight NUMERIC,
    trim_score NUMERIC,
    add_score NUMERIC,
    hold_score NUMERIC,
    income_impact NUMERIC,
    tax_sensitivity TEXT,
    risk_impact NUMERIC,
    confidence NUMERIC,
    recommendation TEXT NOT NULL,
    evidence_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '24 hours')
);

CREATE INDEX IF NOT EXISTS idx_rotation_opportunities_run ON rotation_opportunities(run_id);
CREATE INDEX IF NOT EXISTS idx_rotation_opportunities_symbol ON rotation_opportunities(symbol);
CREATE INDEX IF NOT EXISTS idx_rotation_opportunities_rec ON rotation_opportunities(recommendation, confidence DESC);

CREATE TABLE IF NOT EXISTS rotation_pairs (
    id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL,
    source_symbol TEXT NOT NULL,
    destination_symbol TEXT NOT NULL,
    source_account TEXT,
    destination_account TEXT,
    action_class TEXT NOT NULL,
    dollar_amount NUMERIC,
    shares_to_trim NUMERIC,
    shares_to_add_est NUMERIC,
    rotation_score NUMERIC NOT NULL,
    risk_delta NUMERIC,
    income_delta NUMERIC,
    sector_delta JSONB NOT NULL DEFAULT '{}'::jsonb,
    tax_notes TEXT,
    rationale TEXT NOT NULL,
    evidence_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'advisory',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '24 hours'),
    CHECK (status IN ('advisory','reviewed','accepted_for_manual_review','rejected','expired'))
);

CREATE INDEX IF NOT EXISTS idx_rotation_pairs_run ON rotation_pairs(run_id);
CREATE INDEX IF NOT EXISTS idx_rotation_pairs_score ON rotation_pairs(rotation_score DESC);
CREATE INDEX IF NOT EXISTS idx_rotation_pairs_status ON rotation_pairs(status);

CREATE TABLE IF NOT EXISTS rotation_evidence (
    id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    evidence_type TEXT NOT NULL,
    source_name TEXT,
    source_ref TEXT,
    evidence_score NUMERIC,
    summary TEXT,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    observed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_rotation_evidence_run_symbol ON rotation_evidence(run_id, symbol);
CREATE INDEX IF NOT EXISTS idx_rotation_evidence_type ON rotation_evidence(evidence_type);

CREATE TABLE IF NOT EXISTS rotation_decisions (
    id BIGSERIAL PRIMARY KEY,
    rotation_pair_id BIGINT REFERENCES rotation_pairs(id) ON DELETE SET NULL,
    decision TEXT NOT NULL,
    operator_note TEXT,
    decided_by TEXT DEFAULT 'operator',
    decided_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (decision IN ('accept_manual_review','reject','defer','needs_more_research','implemented_outside_system'))
);

COMMENT ON TABLE rotation_opportunities IS 'Advisory trim/add/hold opportunities. No broker execution behavior.';
COMMENT ON TABLE rotation_pairs IS 'Advisory source->destination rotation ideas. Human review required; no broker execution behavior.';
COMMENT ON TABLE rotation_evidence IS 'Evidence ledger for rotation intelligence recommendations.';
COMMENT ON TABLE rotation_decisions IS 'Operator disposition of advisory rotation ideas.';
