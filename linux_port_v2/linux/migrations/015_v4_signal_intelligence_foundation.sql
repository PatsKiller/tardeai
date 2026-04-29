-- 015_v4_signal_intelligence_foundation.sql — V4: Target allocations + signal foundation
-- Idempotent.
BEGIN;

-- 1. Portfolio target allocations — replaces hard-coded caps in synthesis
CREATE TABLE IF NOT EXISTS portfolio_target_allocations (
    allocation_id       TEXT PRIMARY KEY,
    display_name        TEXT NOT NULL,
    target_min_pct      NUMERIC,
    target_max_pct      NUMERIC,
    hard_cap_pct        NUMERIC,
    max_single_pct      NUMERIC,
    human_review_pct    NUMERIC,
    member_strategy_types TEXT[],
    source              TEXT DEFAULT 'system',
    active              BOOLEAN DEFAULT TRUE,
    notes               TEXT,
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

-- Seed from strategy_group_caps
INSERT INTO portfolio_target_allocations (allocation_id, display_name, target_min_pct, target_max_pct, hard_cap_pct, max_single_pct, human_review_pct, member_strategy_types, notes) VALUES
('core_compounders', 'Core Compounders', 40, 60, 65, 20, 15, '{dividend_growth_compounder,core_growth_compounder,core_index,international_dividend}', 'Primary growth + dividend layer'),
('income_generators', 'Income Generators', 25, 40, 45, 15, 12, '{covered_call_income,high_yield_income_bdc,bond_income,reit_income}', 'Primary income layer'),
('tactical_opportunistic', 'Tactical / Opportunistic', 0, 20, 25, 5, 10, '{defense_thesis,speculative_growth,swing_trade,recovery_watch}', 'Alpha + rotation layer'),
('covered_call_group', 'Covered-Call Income', 0, 18, 18, 12, 10, '{covered_call_income}', 'Combined covered-call cap'),
('high_yield_bdc_group', 'High-Yield / BDC', 0, 15, 15, 8, 8, '{high_yield_income_bdc}', 'BDC concentration cap'),
('speculative_satellite', 'Speculative Satellite', 0, 12, 12, 5, 5, '{speculative_growth}', 'Satellite sizing cap'),
('defense_basket', 'Defense Basket', 0, 15, 18, 5, 10, '{defense_thesis}', 'Defense sector basket')
ON CONFLICT (allocation_id) DO NOTHING;

-- 2. Extend strategy_registry with preferred_accounts if missing
ALTER TABLE strategy_registry
    ADD COLUMN IF NOT EXISTS preferred_accounts_json JSONB DEFAULT '[]';

-- Seed preferred accounts by strategy type
UPDATE strategy_registry SET preferred_accounts_json = '["IRA"]' WHERE strategy_type IN ('covered_call_income', 'high_yield_income_bdc', 'reit_income');
UPDATE strategy_registry SET preferred_accounts_json = '["Roth","Taxable"]' WHERE strategy_type IN ('core_growth_compounder', 'speculative_growth');
UPDATE strategy_registry SET preferred_accounts_json = '["Taxable","IRA"]' WHERE strategy_type IN ('dividend_growth_compounder', 'international_dividend');
UPDATE strategy_registry SET preferred_accounts_json = '["IRA","Taxable"]' WHERE strategy_type IN ('bond_income', 'core_index');
UPDATE strategy_registry SET preferred_accounts_json = '["Taxable"]' WHERE strategy_type IN ('defense_thesis', 'swing_trade', 'tax_loss_harvest');

-- 3. Signal history for tracking signal effectiveness
CREATE TABLE IF NOT EXISTS signal_history (
    id                  BIGSERIAL PRIMARY KEY,
    symbol              TEXT,
    strategy_type       TEXT,
    signal_type         TEXT,
    signal_source       TEXT,
    signal_score        NUMERIC,
    signal_confidence   NUMERIC,
    price_at_signal     NUMERIC,
    price_1d_after      NUMERIC,
    price_7d_after      NUMERIC,
    price_30d_after     NUMERIC,
    accuracy_score      NUMERIC,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    evaluated_at        TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_signal_hist_symbol ON signal_history (symbol, created_at DESC);

COMMIT;
