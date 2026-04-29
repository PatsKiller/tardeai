-- 014_closed_loop_intelligence.sql — Blueprint v3: Closed-Loop Intelligence
-- Idempotent.
BEGIN;

-- 1. ticker_dividend_data — replaces in-code KNOWN_DIVIDENDS
CREATE TABLE IF NOT EXISTS ticker_dividend_data (
    symbol                  TEXT PRIMARY KEY,
    dividend_yield_pct      NUMERIC,
    forward_yield_pct       NUMERIC,
    annual_dividend_per_share NUMERIC,
    dividend_growth_1y      NUMERIC,
    dividend_growth_3y      NUMERIC,
    dividend_growth_5y      NUMERIC,
    payout_ratio            NUMERIC,
    payout_safety_score     NUMERIC,
    income_reliability_score NUMERIC,
    ex_div_date             DATE,
    pay_date                DATE,
    frequency               TEXT,
    source                  TEXT DEFAULT 'seed',
    source_payload          JSONB DEFAULT '{}'::jsonb,
    last_updated            TIMESTAMPTZ DEFAULT NOW(),
    updated_at              TIMESTAMPTZ DEFAULT NOW()
);

-- Seed from KNOWN_DIVIDENDS (one-time, idempotent)
INSERT INTO ticker_dividend_data (symbol, annual_dividend_per_share, dividend_yield_pct, dividend_growth_5y, payout_safety_score, income_reliability_score, source) VALUES
('SCHD',  0.98,  3.14, 12.0, 0.9, 0.9, 'seed'),
('DGRO',  1.25,  2.35, 10.5, 0.9, 0.9, 'seed'),
('VIG',   2.90,  1.70,  8.0, 0.9, 0.9, 'seed'),
('SCHG',  0.38,  0.15,  5.0, 0.9, 0.6, 'seed'),
('V',     2.36,  0.72, 16.0, 0.9, 0.9, 'seed'),
('JEPI',  4.50,  7.85, NULL, 0.7, 0.9, 'seed'),
('JEPQ',  4.80,  9.20, NULL, 0.7, 0.6, 'seed'),
('BND',   2.50,  3.40, NULL, 0.9, 0.9, 'seed'),
('HTGC',  1.92, 12.38,  3.0, 0.4, 0.6, 'seed'),
('PFLT',  1.14, 11.50,  0.0, 0.4, 0.6, 'seed'),
('MAIN',  2.76,  5.60,  4.0, 0.9, 0.9, 'seed'),
('ARCC',  1.92,  8.80,  2.0, 0.7, 0.9, 'seed'),
('O',     3.10,  5.50,  3.5, 0.9, 0.9, 'seed'),
('PLTR',  0,     0,    NULL, NULL, NULL, 'seed'),
('RKLB',  0,     0,    NULL, NULL, NULL, 'seed'),
('ARKQ',  0.05,  0.05, NULL, NULL, 0.3, 'seed'),
('ARKG',  0,     0,    NULL, NULL, 0.3, 'seed'),
('LMT',  13.20,  2.57,  7.5, 0.9, 0.9, 'seed'),
('RTX',   2.36,  1.35,  7.0, 0.9, 0.9, 'seed'),
('NOC',   7.40,  1.29,  8.0, 0.9, 0.9, 'seed'),
('GD',    5.68,  1.81,  7.5, 0.9, 0.9, 'seed'),
('NEE',   2.06,  2.80,  10.0, 0.9, 0.9, 'seed'),
('CSWC',  2.56, 10.20,  2.0, 0.5, 0.6, 'seed'),
('DIV',   1.20,  6.50, NULL, 0.7, 0.7, 'seed')
ON CONFLICT (symbol) DO NOTHING;

-- 2. portfolio_level_qa_history
CREATE TABLE IF NOT EXISTS portfolio_level_qa_history (
    id                      BIGSERIAL PRIMARY KEY,
    evaluated_at            TIMESTAMPTZ DEFAULT NOW(),
    portfolio_value         NUMERIC,
    projected_annual_income NUMERIC,
    minimum_income_target   NUMERIC,
    target_income           NUMERIC,
    stretch_income          NUMERIC,
    income_gap              NUMERIC,
    group_allocations       JSONB DEFAULT '{}'::jsonb,
    group_cap_violations    JSONB DEFAULT '[]'::jsonb,
    income_floor_status     TEXT,
    concentration_warnings  JSONB DEFAULT '[]'::jsonb,
    cross_symbol_conflicts  JSONB DEFAULT '[]'::jsonb,
    actionable_allowed      BOOLEAN DEFAULT FALSE,
    human_review_required   BOOLEAN DEFAULT FALSE,
    qa_summary              TEXT,
    created_at              TIMESTAMPTZ DEFAULT NOW()
);

-- 3. decision_outcomes
CREATE TABLE IF NOT EXISTS decision_outcomes (
    id                      BIGSERIAL PRIMARY KEY,
    symbol                  TEXT,
    strategy_type           TEXT,
    decision_id             TEXT,
    recommendation          TEXT,
    action_taken            BOOLEAN DEFAULT FALSE,
    human_decision          TEXT,
    price_at_decision       NUMERIC,
    price_1d                NUMERIC,
    price_7d                NUMERIC,
    price_30d               NUMERIC,
    income_impact           NUMERIC,
    drawdown_after_decision NUMERIC,
    regret_score            NUMERIC,
    outcome_score           NUMERIC,
    notes                   TEXT,
    created_at              TIMESTAMPTZ DEFAULT NOW(),
    evaluated_at            TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_outcomes_symbol ON decision_outcomes (symbol, created_at DESC);

-- 4. portfolio_intelligence_events
CREATE TABLE IF NOT EXISTS portfolio_intelligence_events (
    id                      BIGSERIAL PRIMARY KEY,
    symbol                  TEXT,
    strategy_type           TEXT,
    event_type              TEXT NOT NULL,
    severity                TEXT,
    source                  TEXT,
    linked_alert_id         BIGINT,
    linked_decision_id      TEXT,
    linked_job_id           TEXT,
    impact_score            NUMERIC,
    payload                 JSONB DEFAULT '{}'::jsonb,
    learned                 BOOLEAN DEFAULT FALSE,
    created_at              TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_intel_events_symbol ON portfolio_intelligence_events (symbol, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_intel_events_type ON portfolio_intelligence_events (event_type);

COMMIT;
