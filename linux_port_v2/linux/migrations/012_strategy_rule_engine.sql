-- 012_strategy_rule_engine.sql — Phase 15: Centralized Strategy Rule Engine
BEGIN;

-- 1. Strategy registry — one row per strategy type with full config
CREATE TABLE IF NOT EXISTS strategy_registry (
    strategy_type       TEXT PRIMARY KEY,
    display_name        TEXT NOT NULL,
    objective           TEXT,
    target_accounts     TEXT[],
    max_position_pct    NUMERIC DEFAULT 10,
    max_group_alloc_pct NUMERIC DEFAULT 30,
    primary_signals     TEXT[],
    secondary_signals   TEXT[],
    prohibited_actions  TEXT[],
    allowed_actions     TEXT[],
    required_data       TEXT[],
    required_agents     TEXT[],
    escalation_triggers TEXT[],
    synthesis_weights   JSONB DEFAULT '{}',
    rsi_rule_set        TEXT,
    if_then_rules       JSONB DEFAULT '[]',
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

-- 2. Per-symbol rule evaluation results
CREATE TABLE IF NOT EXISTS strategy_rule_evaluations (
    symbol              TEXT PRIMARY KEY,
    strategy_type       TEXT,
    baseline_action     TEXT,
    allowed_actions     TEXT[],
    prohibited_actions  TEXT[],
    rule_flags          JSONB DEFAULT '[]',
    required_data_missing TEXT[],
    required_agents_missing TEXT[],
    escalation_required BOOLEAN DEFAULT FALSE,
    human_review_required BOOLEAN DEFAULT FALSE,
    confidence_floor    NUMERIC DEFAULT 0.5,
    rule_narrative      TEXT,
    agent_overlay       JSONB DEFAULT '{}',
    rule_violations     JSONB DEFAULT '[]',
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

-- 3. History
CREATE TABLE IF NOT EXISTS strategy_rule_history (
    id                  BIGSERIAL PRIMARY KEY,
    symbol              TEXT NOT NULL,
    strategy_type       TEXT,
    baseline_action     TEXT,
    rule_flags          JSONB,
    rule_violations     JSONB,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_rule_hist_symbol ON strategy_rule_history (symbol, created_at DESC);

-- Seed all 12 strategy types
INSERT INTO strategy_registry (strategy_type, display_name, objective, target_accounts, max_position_pct, max_group_alloc_pct, primary_signals, secondary_signals, prohibited_actions, allowed_actions, required_data, required_agents, escalation_triggers, synthesis_weights, rsi_rule_set, if_then_rules) VALUES

('dividend_growth_compounder', 'Dividend Growth Compounder', 'Dividend growth + capital appreciation + long-term compounding', '{IRA,Roth,Taxable}', 15, 60,
 '{allocation,dividend_growth,payout_quality,yield_on_cost}', '{RSI,SMA200,valuation}',
 '{SELL_on_RSI,TRIM_on_RSI,AVOID_on_technical}', '{HOLD,ADD_ON_PULLBACK,ADD,REBALANCE_TRIM}',
 '{dividend_yield,dividend_growth_5yr,payout_safety,income_profile}', '{steph,risk}',
 '{dividend_cut,payout_safety_downgrade,allocation_above_max}',
 '{"allocation":0.35,"account_location":0.25,"fundamentals":0.20,"technicals":0.10,"alerts":0.10}',
 'dividend_growth',
 '[{"if":"RSI>70 AND income_asset","then":"HOLD_DO_NOT_CHASE","reason":"RSI timing only for income"},{"if":"income_pct>20 AND rec=TRIM","then":"BLOCK_unless_above_max_alloc","reason":"income protection"},{"if":"dividend_growth_declining","then":"ESCALATE_maria","reason":"fundamental review needed"}]'),

('covered_call_income', 'Covered-Call Income ETF', 'Tactical income via option premium + some upside capture', '{IRA}', 10, 40,
 '{distribution_sustainability,opportunity_cost,yield}', '{RSI,NAV_premium}',
 '{SELL_on_RSI,TRIM_on_RSI}', '{HOLD,ADD_ON_PULLBACK,ADD,REBALANCE_TRIM}',
 '{dividend_yield,expense_ratio,distribution_history}', '{steph,maria,risk}',
 '{distribution_cut,opportunity_cost_spike,NAV_premium_excessive}',
 '{"allocation":0.30,"account_location":0.25,"fundamentals":0.25,"technicals":0.10,"alerts":0.10}',
 'high_yield',
 '[{"if":"RSI>70","then":"DO_NOT_CHASE","reason":"covered-call premium already priced"},{"if":"distribution_cut","then":"ESCALATE_maria_steph","reason":"income quality review"}]'),

('high_yield_income_bdc', 'High-Yield / BDC Income', 'Current income from credit/BDC. Yield >8% requires safety review.', '{IRA}', 5, 20,
 '{payout_safety,NAV_coverage,credit_quality,yield}', '{RSI,price_trend}',
 '{BUY_without_payout_review,ADD_on_RSI_low_without_safety}', '{HOLD,ADD_ON_PULLBACK,ADD,TRIM,RESEARCH_MORE}',
 '{dividend_yield,payout_safety,NAV_book_value}', '{maria,risk,steph}',
 '{dividend_cut,NAV_decline_10pct,credit_downgrade,RSI_below_30}',
 '{"allocation":0.25,"account_location":0.25,"fundamentals":0.30,"technicals":0.05,"alerts":0.15}',
 'high_yield',
 '[{"if":"yield>10 AND payout=at_risk","then":"BLOCK_ADD","reason":"dividend cut risk"},{"if":"RSI<30","then":"STRESS_REVIEW_not_auto_buy","reason":"price stress requires safety check"}]'),

('bond_income', 'Bond / Fixed Income', 'Stable income + capital preservation. Rate/duration/credit dominate.', '{IRA,Taxable}', 15, 40,
 '{rate_trend,duration,credit_risk,yield}', '{RSI}',
 '{}', '{HOLD,ADD,ADD_ON_PULLBACK,TRIM,REBALANCE_TRIM}',
 '{yield,duration,credit_rating}', '{risk,steph}',
 '{rate_spike,credit_downgrade}',
 '{"allocation":0.30,"account_location":0.25,"fundamentals":0.30,"technicals":0.05,"alerts":0.10}',
 'dividend_growth',
 '[{"if":"rate_rising_fast","then":"REVIEW_duration","reason":"duration risk in rising rates"}]'),

('core_growth_compounder', 'Core Growth Compounder', 'Long-term capital appreciation via quality growth companies/ETFs.', '{Roth,Taxable}', 15, 60,
 '{thesis_quality,valuation,earnings_growth}', '{RSI,SMA200,momentum}',
 '{SELL_on_RSI_alone}', '{HOLD,ADD_ON_PULLBACK,ADD,TRIM,REBALANCE_TRIM}',
 '{PE,forward_PE,earnings_growth}', '{maria,risk}',
 '{thesis_break,valuation_extreme,earnings_miss}',
 '{"allocation":0.30,"account_location":0.20,"fundamentals":0.30,"technicals":0.10,"alerts":0.10}',
 'core_growth',
 '[{"if":"RSI>70","then":"DO_NOT_CHASE","reason":"wait for pullback"},{"if":"thesis_intact AND RSI<35","then":"ADD_ON_PULLBACK","reason":"pullback opportunity"}]'),

('core_index', 'Core Index Fund', 'Broad market exposure, low cost. Allocation and rebalancing dominate.', '{401k,Roth,IRA}', 20, 60,
 '{allocation,expense_ratio,tracking_error}', '{market_regime}',
 '{}', '{HOLD,ADD,REBALANCE_TRIM}',
 '{expense_ratio}', '{steph}',
 '{allocation_drift_5pct}',
 '{"allocation":0.40,"account_location":0.25,"fundamentals":0.15,"technicals":0.05,"alerts":0.15}',
 'core_growth',
 '[]'),

('defense_thesis', 'Defense / Aerospace Thesis', 'Geopolitical thesis + sector basket. Evaluate basket, not individual tickers.', '{Taxable,IRA}', 5, 15,
 '{geopolitical_thesis,valuation,contract_pipeline,basket_exposure}', '{RSI,momentum}',
 '{}', '{HOLD,ADD,ADD_ON_PULLBACK,TRIM,SELL}',
 '{sector_exposure,contract_news}', '{maria,risk,steph}',
 '{multiple_stop_failures,thesis_invalidation,basket_overweight}',
 '{"allocation":0.25,"account_location":0.15,"fundamentals":0.25,"technicals":0.15,"alerts":0.20}',
 'defense_thesis',
 '[{"if":"multiple_stops_triggered_in_basket","then":"BASKET_REVIEW","reason":"sector-wide weakness"},{"if":"position_weight<0.5","then":"LOW_PRIORITY","reason":"tiny position"}]'),

('speculative_growth', 'Speculative Growth', 'High-conviction growth with catalyst. Satellite sizing.', '{Roth}', 5, 10,
 '{catalyst,risk_reward,momentum}', '{RSI,volume}',
 '{BUY_without_catalyst,ADD_RSI_above_75}', '{HOLD,BUY,ADD,TRIM,SELL}',
 '{catalyst_thesis,risk_reward_ratio}', '{maria,risk}',
 '{catalyst_expired,stop_triggered,RSI_above_80}',
 '{"allocation":0.15,"account_location":0.10,"fundamentals":0.20,"technicals":0.30,"alerts":0.25}',
 'speculative_growth',
 '[{"if":"no_catalyst","then":"BLOCK_BUY","reason":"catalyst required"},{"if":"position>5pct","then":"TRIM_to_target","reason":"satellite cap"}]'),

('swing_trade', 'Swing Trade', 'Short-term directional trade with defined entry/stop/target.', '{Taxable}', 3, 10,
 '{entry_stop_target,risk_reward,technical_setup}', '{RSI,volume,catalyst}',
 '{TRADE_without_RR}', '{BUY,ADD,HOLD,TRIM,SELL}',
 '{entry_price,stop_price,target_price,risk_reward}', '{maria,risk}',
 '{stop_break,RR_below_2,thesis_expired}',
 '{"allocation":0.10,"account_location":0.05,"fundamentals":0.15,"technicals":0.40,"alerts":0.30}',
 'swing_trade',
 '[{"if":"risk_reward<2","then":"BLOCK_entry","reason":"insufficient R:R"},{"if":"stop_break","then":"EXIT_REVIEW","reason":"stop level violated"}]'),

('recovery_watch', 'Recovery Watch', 'Previously stopped out. Requires reclaim level before re-entry.', '{any}', 3, 10,
 '{reclaim_level,thesis_intact,technical_recovery}', '{RSI,volume,support}',
 '{BUY_without_reclaim}', '{HOLD,BUY,RESEARCH_MORE}',
 '{prior_stop_price,reclaim_level,current_price}', '{risk,maria}',
 '{reclaim_level_hit,volume_confirmation}',
 '{"allocation":0.15,"account_location":0.10,"fundamentals":0.25,"technicals":0.30,"alerts":0.20}',
 'swing_trade',
 '[{"if":"price_below_reclaim","then":"WAIT","reason":"reclaim level not hit"},{"if":"thesis_broken","then":"DO_NOT_REENTER","reason":"original thesis invalidated"}]'),

('cash_or_stable', 'Cash / Stable Value', 'Deployment reserve. Deploy based on opportunity, heat, income gap.', '{any}', 100, 100,
 '{opportunity_score,market_heat,income_gap}', '{}',
 '{}', '{HOLD,DEPLOY}',
 '{income_gap,opportunity_pipeline}', '{steph}',
 '{income_gap_large,opportunity_score_high}',
 '{"allocation":0.50,"account_location":0.20,"fundamentals":0.10,"technicals":0.05,"alerts":0.15}',
 'dividend_growth',
 '[]'),

('tax_loss_harvest', 'Tax-Loss Harvest', 'Realize losses in taxable for tax benefit. Taxable only.', '{Taxable}', 100, 100,
 '{unrealized_loss,wash_sale_window,replacement_candidate}', '{}',
 '{HARVEST_in_IRA,HARVEST_in_Roth}', '{SELL,HOLD}',
 '{unrealized_loss,wash_sale_dates,replacement_ticker}', '{tax}',
 '{loss_threshold_met,year_end_approaching}',
 '{"allocation":0.10,"account_location":0.30,"fundamentals":0.10,"technicals":0.05,"alerts":0.45}',
 'dividend_growth',
 '[{"if":"unrealized_loss>threshold AND taxable","then":"HARVEST_candidate","reason":"tax benefit available"},{"if":"wash_sale_window_active","then":"BLOCK_repurchase","reason":"30-day wash sale rule"}]')

ON CONFLICT (strategy_type) DO NOTHING;

COMMIT;
