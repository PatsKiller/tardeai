-- 010_income_engine.sql — Phase 13: Retirement Income Engine
-- Run: PGPASSWORD=... psql -h localhost -U trade_ai -d trade_ai -f linux_port_v2/linux/migrations/010_income_engine.sql

BEGIN;

-- 1. Portfolio income goals
CREATE TABLE IF NOT EXISTS portfolio_income_goals (
    id                      SERIAL PRIMARY KEY,
    minimum_income_target   NUMERIC NOT NULL DEFAULT 37500,   -- $35K-$40K floor
    target_income           NUMERIC NOT NULL DEFAULT 55000,   -- $55K primary
    stretch_income_target   NUMERIC NOT NULL DEFAULT 67500,   -- $65K-$70K stretch
    timeline_years          INTEGER NOT NULL DEFAULT 6,       -- 4-8 year range, midpoint
    risk_tolerance          TEXT DEFAULT 'moderate_aggressive',
    strategy_notes          TEXT,
    updated_at              TIMESTAMPTZ DEFAULT NOW()
);

-- Seed the mandate
INSERT INTO portfolio_income_goals (minimum_income_target, target_income, stretch_income_target, timeline_years, risk_tolerance, strategy_notes)
VALUES (37500, 55000, 67500, 6, 'moderate_aggressive',
        'Blended dividend growth + yield. NOT pure high-yield chasing. NOT pure growth-only. IRA + Roth prioritized for tax-efficient compounding.')
ON CONFLICT DO NOTHING;

-- 2. Portfolio layer definitions
CREATE TABLE IF NOT EXISTS portfolio_layers (
    layer_id        TEXT PRIMARY KEY,
    layer_name      TEXT NOT NULL,
    target_min_pct  NUMERIC NOT NULL,
    target_max_pct  NUMERIC NOT NULL,
    purpose         TEXT,
    examples        TEXT[]
);

INSERT INTO portfolio_layers VALUES
    ('core_compounders',    'Core Compounders',     40, 60, 'Dividend growth + capital appreciation + long-term compounding', ARRAY['SCHD','DGRO','VIG','SCHG','V']),
    ('income_generators',   'Income Generators',    25, 40, 'Current income + yield support + cash flow. Prioritize IRA placement.', ARRAY['JEPI','JEPQ','BND','HTGC','PFLT','MAIN','ARCC']),
    ('tactical',            'Tactical / Opportunistic', 0, 20, 'Alpha + rotation + opportunistic gains', ARRAY['LMT','RTX','NOC','PLTR','RKLB','ARKQ'])
ON CONFLICT (layer_id) DO NOTHING;

-- 3. Per-symbol income profile
CREATE TABLE IF NOT EXISTS income_asset_profiles (
    symbol                  TEXT PRIMARY KEY,
    layer_id                TEXT REFERENCES portfolio_layers(layer_id),
    annual_dividend_per_share NUMERIC,     -- latest annual dividend
    dividend_yield_pct      NUMERIC,       -- current yield
    forward_yield_pct       NUMERIC,       -- estimated forward yield
    yield_on_cost_pct       NUMERIC,       -- yield based on cost basis
    dividend_growth_5yr_pct NUMERIC,       -- 5-year dividend CAGR
    payout_ratio_pct        NUMERIC,       -- payout ratio
    payout_safety           TEXT CHECK (payout_safety IN ('safe','moderate','at_risk','unsafe','unknown')),
    income_reliability      TEXT CHECK (income_reliability IN ('high','medium','low','unknown')),
    expense_ratio_pct       NUMERIC,       -- for ETFs/funds
    preferred_account       TEXT,          -- IRA, Roth, Taxable
    -- Computed from holdings
    annual_income           NUMERIC,       -- shares * annual_dividend
    portfolio_income_pct    NUMERIC,       -- % of total portfolio income
    income_goal_contribution_pct NUMERIC,  -- % of target income this provides
    reinvestment_effect     TEXT,          -- description of DRIP impact
    updated_at              TIMESTAMPTZ DEFAULT NOW()
);

-- 4. Income projection snapshots
CREATE TABLE IF NOT EXISTS income_projection_history (
    id                      BIGSERIAL PRIMARY KEY,
    snapshot_date           DATE NOT NULL,
    total_annual_income     NUMERIC,
    forward_annual_income   NUMERIC,
    minimum_goal_pct        NUMERIC,       -- % of minimum target achieved
    target_goal_pct         NUMERIC,       -- % of target achieved
    stretch_goal_pct        NUMERIC,       -- % of stretch achieved
    income_gap_to_minimum   NUMERIC,       -- $ needed to reach minimum
    income_gap_to_target    NUMERIC,       -- $ needed to reach target
    top_contributors        JSONB,         -- [{symbol, income, pct}]
    layer_breakdown         JSONB,         -- {core: $X, income: $Y, tactical: $Z}
    created_at              TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_income_proj_date ON income_projection_history (snapshot_date DESC);

-- 5. Account placement rules
CREATE TABLE IF NOT EXISTS account_placement_rules (
    account_type    TEXT PRIMARY KEY,
    preferred_for   TEXT[],
    avoid           TEXT[],
    rationale       TEXT
);

INSERT INTO account_placement_rules VALUES
    ('IRA',     ARRAY['high_yield','tax_inefficient_income','BDCs','REITs','bonds'], ARRAY['growth_only'], 'Tax-deferred: maximize tax-inefficient income here'),
    ('Roth',    ARRAY['high_growth_compounders','SCHG','growth_ETFs'], ARRAY['high_yield_only'], 'Tax-free growth: maximize long-term compounding'),
    ('Taxable', ARRAY['qualified_dividends','tax_efficient_ETFs','SCHD','VIG'], ARRAY['BDCs','REITs','frequent_distributions'], 'Tax-efficient: qualified dividends taxed at lower rate')
ON CONFLICT (account_type) DO NOTHING;

COMMIT;
