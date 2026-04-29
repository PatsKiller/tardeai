-- 013_classification_rule_engine.sql — Classification-First Strategy Rule Engine
-- Idempotent. Run: PGPASSWORD=... psql -h localhost -U trade_ai -d trade_ai -f ...
BEGIN;

-- ══════════════════════════════════════════════════════════════
-- 1. STRATEGY REGISTRY — upgrade existing table with new columns
-- ══════════════════════════════════════════════════════════════
ALTER TABLE strategy_registry
    ADD COLUMN IF NOT EXISTS layer_id TEXT,
    ADD COLUMN IF NOT EXISTS is_income_strategy BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS is_tactical BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS requires_catalyst BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS target_min_pct NUMERIC,
    ADD COLUMN IF NOT EXISTS target_max_pct NUMERIC,
    ADD COLUMN IF NOT EXISTS preferred_accounts JSONB DEFAULT '[]',
    ADD COLUMN IF NOT EXISTS human_review_thresholds JSONB DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS active BOOLEAN DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS version INTEGER DEFAULT 1,
    ADD COLUMN IF NOT EXISTS active_from TIMESTAMPTZ DEFAULT NOW(),
    ADD COLUMN IF NOT EXISTS active_to TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}';

-- Add 3 new strategy types not in original 12
INSERT INTO strategy_registry (strategy_type, display_name, objective, target_accounts, max_position_pct, max_group_alloc_pct, required_agents, rsi_rule_set, synthesis_weights, if_then_rules)
VALUES
('reit_income', 'REIT Income', 'Rate-sensitive income via REITs. Evaluate AFFO/payout/debt/rate regime.', '{IRA}', 8, 20, '{maria,risk,steph}', 'high_yield', '{"allocation":0.25,"account_location":0.25,"fundamentals":0.30,"technicals":0.10,"alerts":0.10}', '[]'),
('international_dividend', 'International Dividend', 'Currency-diversified dividend income. Evaluate FX risk, withholding tax.', '{IRA,Taxable}', 8, 15, '{maria,tax,steph}', 'dividend_growth', '{"allocation":0.25,"account_location":0.20,"fundamentals":0.30,"technicals":0.10,"alerts":0.15}', '[]'),
('invalid_non_security', 'Invalid / Non-Security', 'Rejected from trading workflow. Not a valid security.', '{}', 0, 0, '{}', 'dividend_growth', '{}', '[]')
ON CONFLICT (strategy_type) DO NOTHING;

-- Update classification metadata on all types
UPDATE strategy_registry SET layer_id='core_compounders', is_income_strategy=TRUE WHERE strategy_type='dividend_growth_compounder';
UPDATE strategy_registry SET layer_id='income_generators', is_income_strategy=TRUE WHERE strategy_type='covered_call_income';
UPDATE strategy_registry SET layer_id='income_generators', is_income_strategy=TRUE WHERE strategy_type='high_yield_income_bdc';
UPDATE strategy_registry SET layer_id='income_generators', is_income_strategy=TRUE WHERE strategy_type='bond_income';
UPDATE strategy_registry SET layer_id='core_compounders', is_income_strategy=FALSE WHERE strategy_type='core_growth_compounder';
UPDATE strategy_registry SET layer_id='core_compounders', is_income_strategy=FALSE WHERE strategy_type='core_index';
UPDATE strategy_registry SET layer_id='tactical', is_tactical=TRUE WHERE strategy_type='defense_thesis';
UPDATE strategy_registry SET layer_id='tactical', is_tactical=TRUE, requires_catalyst=TRUE WHERE strategy_type='speculative_growth';
UPDATE strategy_registry SET layer_id='tactical', is_tactical=TRUE, requires_catalyst=TRUE WHERE strategy_type='swing_trade';
UPDATE strategy_registry SET layer_id='tactical', is_tactical=TRUE WHERE strategy_type='recovery_watch';
UPDATE strategy_registry SET layer_id=NULL WHERE strategy_type='cash_or_stable';
UPDATE strategy_registry SET layer_id=NULL WHERE strategy_type='tax_loss_harvest';
UPDATE strategy_registry SET layer_id='income_generators', is_income_strategy=TRUE WHERE strategy_type='reit_income';
UPDATE strategy_registry SET layer_id='core_compounders', is_income_strategy=TRUE WHERE strategy_type='international_dividend';
UPDATE strategy_registry SET layer_id=NULL, active=FALSE WHERE strategy_type='invalid_non_security';

-- ══════════════════════════════════════════════════════════════
-- 2. TICKER STRATEGY CLASSIFICATIONS — dynamic symbol→strategy
-- ══════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS ticker_strategy_classifications (
    symbol              TEXT PRIMARY KEY,
    strategy_type       TEXT NOT NULL REFERENCES strategy_registry(strategy_type),
    asset_type          TEXT,
    classification_source TEXT NOT NULL DEFAULT 'manual',
    confidence          NUMERIC DEFAULT 1.0,
    review_required     BOOLEAN DEFAULT FALSE,
    assigned_by_agent   TEXT,
    rationale           TEXT,
    evidence            JSONB DEFAULT '{}',
    effective_from      TIMESTAMPTZ DEFAULT NOW(),
    effective_to        TIMESTAMPTZ,
    active              BOOLEAN DEFAULT TRUE,
    notes               TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

-- Seed classifications (initial data only — rules never reference these symbols)
INSERT INTO ticker_strategy_classifications (symbol, strategy_type, asset_type, classification_source, confidence) VALUES
-- Dividend growth compounders
('SCHD', 'dividend_growth_compounder', 'etf', 'manual', 1.0),
('DGRO', 'dividend_growth_compounder', 'etf', 'manual', 1.0),
('VIG', 'dividend_growth_compounder', 'etf', 'manual', 1.0),
('V', 'dividend_growth_compounder', 'stock', 'manual', 1.0),
('NEE', 'dividend_growth_compounder', 'stock', 'manual', 1.0),
-- Covered-call income
('JEPI', 'covered_call_income', 'etf', 'manual', 1.0),
('JEPQ', 'covered_call_income', 'etf', 'manual', 1.0),
-- High-yield / BDC
('HTGC', 'high_yield_income_bdc', 'stock', 'manual', 1.0),
('PFLT', 'high_yield_income_bdc', 'stock', 'manual', 1.0),
('MAIN', 'high_yield_income_bdc', 'stock', 'manual', 1.0),
('ARCC', 'high_yield_income_bdc', 'stock', 'manual', 1.0),
('O', 'reit_income', 'stock', 'manual', 1.0),
('STAG', 'reit_income', 'stock', 'manual', 1.0),
('DIV', 'high_yield_income_bdc', 'etf', 'manual', 1.0),
-- Bond income
('BND', 'bond_income', 'etf', 'manual', 1.0),
-- Core growth compounders
('SCHG', 'core_growth_compounder', 'etf', 'manual', 1.0),
('MSFT', 'core_growth_compounder', 'stock', 'manual', 1.0),
('XLI', 'core_growth_compounder', 'etf', 'manual', 1.0),
('XLB', 'core_growth_compounder', 'etf', 'manual', 1.0),
-- Core index (Fidelity 401k funds)
('FXAIX', 'core_index', 'mutual_fund', 'manual', 1.0),
('FCNTX', 'core_index', 'mutual_fund', 'manual', 1.0),
('AMANX', 'core_index', 'mutual_fund', 'manual', 1.0),
-- Defense thesis
('LMT', 'defense_thesis', 'stock', 'manual', 1.0),
('RTX', 'defense_thesis', 'stock', 'manual', 1.0),
('NOC', 'defense_thesis', 'stock', 'manual', 1.0),
('GD', 'defense_thesis', 'stock', 'manual', 1.0),
('HII', 'defense_thesis', 'stock', 'manual', 1.0),
('BAH', 'defense_thesis', 'stock', 'manual', 1.0),
('LDOS', 'defense_thesis', 'stock', 'manual', 1.0),
('KTOS', 'defense_thesis', 'stock', 'manual', 1.0),
('DRS', 'defense_thesis', 'stock', 'manual', 1.0),
('KBR', 'defense_thesis', 'stock', 'manual', 1.0),
('LHX', 'defense_thesis', 'stock', 'manual', 1.0),
('AXON', 'defense_thesis', 'stock', 'manual', 1.0),
('AVAV', 'defense_thesis', 'stock', 'manual', 1.0),
('IRDM', 'defense_thesis', 'stock', 'manual', 1.0),
('TDG', 'defense_thesis', 'stock', 'manual', 1.0),
('CACI', 'defense_thesis', 'stock', 'manual', 1.0),
-- Speculative growth
('PLTR', 'speculative_growth', 'stock', 'manual', 1.0),
('RKLB', 'speculative_growth', 'stock', 'manual', 1.0),
('ARKQ', 'speculative_growth', 'etf', 'manual', 1.0),
('ARKG', 'speculative_growth', 'etf', 'manual', 1.0),
('SRNE', 'speculative_growth', 'stock', 'manual', 0.7),
-- Other
('LPIH', 'speculative_growth', 'stock', 'manual', 0.6),
('CSWC', 'high_yield_income_bdc', 'stock', 'manual', 1.0)
ON CONFLICT (symbol) DO NOTHING;

-- ══════════════════════════════════════════════════════════════
-- 3. TICKER CLASSIFICATION HISTORY — append-only audit
-- ══════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS ticker_classification_history (
    id                  BIGSERIAL PRIMARY KEY,
    symbol              TEXT NOT NULL,
    old_strategy_type   TEXT,
    new_strategy_type   TEXT,
    classification_source TEXT,
    confidence          NUMERIC,
    review_required     BOOLEAN,
    assigned_by_agent   TEXT,
    rationale           TEXT,
    evidence            JSONB DEFAULT '{}',
    changed_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_class_hist_symbol ON ticker_classification_history (symbol, changed_at DESC);

-- ══════════════════════════════════════════════════════════════
-- 4. STRATEGY GROUP CAPS
-- ══════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS strategy_group_caps (
    group_id            TEXT PRIMARY KEY,
    group_name          TEXT,
    member_strategy_types JSONB NOT NULL DEFAULT '[]',
    target_min_pct      NUMERIC,
    target_max_pct      NUMERIC,
    hard_cap_pct        NUMERIC,
    max_single_ticker_pct NUMERIC,
    human_review_over_pct NUMERIC,
    active              BOOLEAN DEFAULT TRUE,
    notes               TEXT,
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

INSERT INTO strategy_group_caps VALUES
('income_generators', 'Income Generators', '["covered_call_income","high_yield_income_bdc","bond_income","reit_income"]', 25, 40, 45, 15, 12, TRUE, 'Primary income layer'),
('core_compounders', 'Core Compounders', '["dividend_growth_compounder","core_growth_compounder","core_index","international_dividend"]', 40, 60, 65, 20, 15, TRUE, 'Primary growth + dividend layer'),
('tactical_opportunistic', 'Tactical / Opportunistic', '["defense_thesis","speculative_growth","swing_trade","recovery_watch"]', 0, 20, 25, 5, 10, TRUE, 'Alpha + rotation layer'),
('covered_call_group', 'Covered-Call Income', '["covered_call_income"]', 0, 18, 18, 12, 10, TRUE, 'Combined covered-call cap'),
('high_yield_bdc_group', 'High-Yield / BDC', '["high_yield_income_bdc"]', 0, 15, 15, 8, 8, TRUE, 'BDC concentration cap'),
('speculative_satellite', 'Speculative Satellite', '["speculative_growth"]', 0, 12, 12, 5, 5, TRUE, 'Satellite sizing cap'),
('defense_basket', 'Defense Basket', '["defense_thesis"]', 0, 15, 18, 5, 10, TRUE, 'Defense sector basket')
ON CONFLICT (group_id) DO NOTHING;

-- ══════════════════════════════════════════════════════════════
-- 5. STRATEGY RULE SETS — composite rules by classification
-- ══════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS strategy_rule_sets (
    id                  BIGSERIAL PRIMARY KEY,
    rule_name           TEXT NOT NULL,
    strategy_type       TEXT,
    group_id            TEXT,
    rule_scope          TEXT NOT NULL DEFAULT 'strategy',
    rule_priority       INTEGER DEFAULT 100,
    conditions          JSONB NOT NULL DEFAULT '[]',
    logical_operator    TEXT DEFAULT 'AND',
    then_actions        JSONB NOT NULL DEFAULT '{}',
    prohibited_actions  JSONB DEFAULT '[]',
    allowed_actions     JSONB DEFAULT '[]',
    required_agents     JSONB DEFAULT '[]',
    escalation          JSONB DEFAULT '{}',
    narrative_template  TEXT,
    active              BOOLEAN DEFAULT TRUE,
    version             INTEGER DEFAULT 1,
    active_from         TIMESTAMPTZ DEFAULT NOW(),
    active_to           TIMESTAMPTZ,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

-- Seed composite rules (NO ticker references — all by strategy_type/group_id)
INSERT INTO strategy_rule_sets (rule_name, strategy_type, group_id, rule_scope, rule_priority, conditions, then_actions, prohibited_actions, narrative_template) VALUES
('Income_Floor_Protection', NULL, 'income_generators', 'portfolio', 10,
 '[{"field":"income_pct_of_target","op":"<","value":80},{"field":"rec","op":"IN","value":["TRIM","SELL","AVOID"]},{"field":"is_income_strategy","op":"=","value":true}]',
 '{"action":"BLOCK","override_to":"HOLD","reason":"Income below 80% of target — do not reduce income assets"}',
 '["TRIM","SELL","AVOID"]',
 'Income floor protection: portfolio income is below 80% of target. Reducing income assets is blocked.'),

('High_Heat_Pause', NULL, NULL, 'portfolio', 20,
 '[{"field":"portfolio_heat","op":">","value":0.7},{"field":"rec","op":"IN","value":["BUY","ADD"]}]',
 '{"action":"PAUSE","reason":"Portfolio heat >70% — pause new additions"}',
 '["BUY","ADD"]',
 'High portfolio heat detected. New additions paused until heat normalizes.'),

('Major_Allocation_Breach', NULL, NULL, 'group', 15,
 '[{"field":"group_alloc_pct","op":">","value":"hard_cap_pct"}]',
 '{"action":"TRIM_REQUIRED","escalation":"human_review","reason":"Group allocation exceeds hard cap"}',
 '["ADD","BUY"]',
 'Group allocation exceeds hard cap. Additions blocked; trim required.'),

('Dividend_Growth_RSI_Protection', 'dividend_growth_compounder', NULL, 'strategy', 30,
 '[{"field":"rsi","op":">","value":70},{"field":"rec","op":"IN","value":["TRIM","SELL"]}]',
 '{"action":"BLOCK","override_to":"HOLD","reason":"RSI alone cannot trigger trim on dividend growth asset"}',
 '["TRIM","SELL"]',
 'RSI {rsi} on dividend growth compounder. HOLD — do not chase, do not sell on RSI alone.'),

('BDC_Stress_Block', 'high_yield_income_bdc', NULL, 'strategy', 25,
 '[{"field":"rsi","op":"<","value":30}]',
 '{"action":"BLOCK_ADD","require":"payout_safety_review","reason":"BDC under stress — payout safety review required before adding"}',
 '["BUY","ADD"]',
 'BDC RSI below 30 — stress conditions. Adding blocked until payout safety confirmed.'),

('Covered_Call_RSI_Protection', 'covered_call_income', NULL, 'strategy', 30,
 '[{"field":"rsi","op":">","value":70},{"field":"rec","op":"IN","value":["TRIM","SELL"]}]',
 '{"action":"BLOCK","override_to":"HOLD","reason":"RSI alone cannot trigger trim on covered-call income"}',
 '["TRIM","SELL"]',
 'Covered-call income at extended RSI. HOLD — collect premium, do not sell on RSI alone.'),

('Speculative_Catalyst_Required', 'speculative_growth', NULL, 'strategy', 30,
 '[{"field":"rec","op":"IN","value":["BUY","ADD"]},{"field":"has_catalyst","op":"=","value":false}]',
 '{"action":"BLOCK","reason":"Speculative growth requires catalyst for new additions"}',
 '["BUY","ADD"]',
 'No catalyst identified for speculative growth position. BUY/ADD blocked.'),

('Swing_Trade_RR_Required', 'swing_trade', NULL, 'strategy', 20,
 '[{"field":"risk_reward","op":"<","value":2},{"field":"rec","op":"IN","value":["BUY","ADD"]}]',
 '{"action":"BLOCK","reason":"Swing trade requires R:R >= 2.0"}',
 '["BUY","ADD"]',
 'Risk:reward ratio below 2.0. Swing trade entry blocked.'),

('Defense_Basket_Cohesion', 'defense_thesis', NULL, 'strategy', 40,
 '[{"field":"position_weight","op":"<","value":0.5}]',
 '{"action":"LOW_PRIORITY","reason":"Defense thesis tiny position — evaluate as basket, not individual"}',
 '[]',
 'Defense position <0.5% weight. Evaluate at basket level, not individual.'),

('Recovery_Reclaim_Required', 'recovery_watch', NULL, 'strategy', 20,
 '[{"field":"rec","op":"IN","value":["BUY","ADD"]},{"field":"price_above_reclaim","op":"=","value":false}]',
 '{"action":"BLOCK","reason":"Recovery watch requires price above reclaim level before re-entry"}',
 '["BUY","ADD"]',
 'Price has not reclaimed prior support. Re-entry blocked.'),

('Agent_Conflict_Override', NULL, NULL, 'agent_overlay', 50,
 '[{"field":"has_buy_sell_conflict","op":"=","value":true}]',
 '{"action":"ESCALATE","require":"cio_synthesis","human_review":true,"reason":"Agent BUY vs SELL conflict requires CIO synthesis"}',
 '[]',
 'Agents disagree (BUY vs SELL). Escalating to CIO synthesis with human review.'),

('High_Impact_Income_Move', NULL, 'income_generators', 'qa', 10,
 '[{"field":"income_pct","op":">","value":20},{"field":"rec","op":"IN","value":["TRIM","SELL"]},{"field":"confidence","op":"<","value":0.8}]',
 '{"action":"BLOCK","override_to":"HOLD","human_review":true,"reason":"Position provides >20% of income — confidence must exceed 80% for reduction"}',
 '["TRIM","SELL"]',
 '>20% income concentration. Reduction requires 80%+ confidence and human review.')
ON CONFLICT DO NOTHING;

-- ══════════════════════════════════════════════════════════════
-- 6. STRATEGY RULE EVALUATIONS — upgrade existing table
-- ══════════════════════════════════════════════════════════════
ALTER TABLE strategy_rule_evaluations
    ADD COLUMN IF NOT EXISTS input_context JSONB DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS matched_rules JSONB DEFAULT '[]',
    ADD COLUMN IF NOT EXISTS agent_overlay_action TEXT,
    ADD COLUMN IF NOT EXISTS final_synthesized_action TEXT;

-- Drop old PK if it was symbol-only (now id-based)
-- Keep existing data, just add columns

-- ══════════════════════════════════════════════════════════════
-- 7. AGENT CLASSIFICATION SUGGESTIONS
-- ══════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS agent_classification_suggestions (
    id                  BIGSERIAL PRIMARY KEY,
    symbol              TEXT NOT NULL,
    suggested_strategy_type TEXT REFERENCES strategy_registry(strategy_type),
    suggested_asset_type TEXT,
    agent               TEXT,
    confidence          NUMERIC,
    rationale           TEXT,
    evidence            JSONB DEFAULT '{}',
    status              TEXT DEFAULT 'pending',
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    reviewed_at         TIMESTAMPTZ,
    reviewed_by         TEXT
);

-- ══════════════════════════════════════════════════════════════
-- 8. AGENT CONFLICTS
-- ══════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS agent_conflicts (
    id                  BIGSERIAL PRIMARY KEY,
    symbol              TEXT,
    strategy_type       TEXT,
    conflict_type       TEXT,
    agents              JSONB,
    recommendations     JSONB,
    resolution_method   TEXT,
    winning_agent       TEXT,
    final_action        TEXT,
    rationale           TEXT,
    human_review_required BOOLEAN DEFAULT FALSE,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

-- ══════════════════════════════════════════════════════════════
-- 9. MARL SHADOW MODE TABLES (no live execution)
-- ══════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS marl_policy_versions (
    id                  BIGSERIAL PRIMARY KEY,
    version_tag         TEXT UNIQUE,
    algorithm           TEXT DEFAULT 'MAPPO',
    training_episodes   INTEGER,
    reward_config       JSONB,
    performance_metrics JSONB,
    promoted            BOOLEAN DEFAULT FALSE,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS marl_suggestions (
    id                  BIGSERIAL PRIMARY KEY,
    symbol              TEXT,
    strategy_type       TEXT,
    policy_version      TEXT,
    suggested_action    TEXT,
    confidence          NUMERIC,
    state_snapshot      JSONB,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS marl_training_episodes (
    id                  BIGSERIAL PRIMARY KEY,
    episode_date        DATE,
    state               JSONB,
    actions             JSONB,
    rewards             JSONB,
    outcome             JSONB,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS agent_performance_history (
    id                  BIGSERIAL PRIMARY KEY,
    agent               TEXT,
    period_start        DATE,
    period_end          DATE,
    total_recommendations INTEGER,
    accuracy_pct        NUMERIC,
    avg_confidence      NUMERIC,
    rule_violations     INTEGER,
    human_overrides     INTEGER,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS human_feedback_examples (
    id                  BIGSERIAL PRIMARY KEY,
    symbol              TEXT,
    original_action     TEXT,
    human_action        TEXT,
    rationale           TEXT,
    feedback_type       TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

COMMIT;
