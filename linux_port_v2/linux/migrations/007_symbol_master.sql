-- 007_symbol_master.sql — Phase 12: Deduplicated symbol master view
-- Run: PGPASSWORD=... psql -h localhost -U trade_ai -d trade_ai -f linux_port_v2/linux/migrations/007_symbol_master.sql

BEGIN;

-- One row per unique symbol across all sources.
-- Sources are aggregated as arrays/booleans.
CREATE OR REPLACE VIEW watchlist_symbol_master AS
SELECT
    wi.symbol,
    -- Source membership
    array_agg(DISTINCT wi.source ORDER BY wi.source) AS sources,
    bool_or(wi.source = 'portfolio') AS in_portfolio,
    bool_or(wi.source = 'ai_discovered') AS in_ai_discovered,
    bool_or(wi.source = 'ai_watchlist') AS in_ai_watchlist,
    bool_or(wi.source = 'personal_watchlist') AS in_personal_watchlist,
    -- Best asset_type (prefer non-null)
    (array_agg(wi.asset_type ORDER BY wi.asset_type NULLS LAST) FILTER (WHERE wi.asset_type IS NOT NULL))[1] AS asset_type,
    -- Best score
    MAX(wi.score) AS score,
    MAX(wi.backtest_score) AS backtest_score,
    MAX(wi.updated_at) AS updated_at,
    -- Strategy card
    sc.strategy_type,
    sc.latest_price,
    sc.support,
    sc.resistance,
    sc.ideal_entry,
    sc.stop_loss,
    sc.target_price,
    sc.risk_reward,
    sc.account_fit,
    sc.technical_summary,
    -- Maturity
    am.analysis_stage,
    am.maria_status,
    am.steph_status,
    am.risk_status,
    am.tax_status,
    am.full_chain_status,
    am.final_synthesis_status,
    am.required_agents,
    am.completed_agents,
    am.needs_iteration AS maturity_needs_iteration,
    am.escalation_policy,
    -- Research
    rc.latest_recommendation,
    rc.latest_summary AS research_summary,
    rc.confidence AS research_confidence,
    -- Synthesis
    fs.recommendation AS synthesis_recommendation,
    fs.confidence AS synthesis_confidence,
    fs.action AS synthesis_action
FROM watchlist_items wi
LEFT JOIN watchlist_strategy_cards sc ON sc.symbol = wi.symbol
LEFT JOIN watchlist_analysis_maturity am ON am.symbol = wi.symbol
LEFT JOIN watchlist_research_cards rc ON rc.symbol = wi.symbol
LEFT JOIN watchlist_final_synthesis fs ON fs.symbol = wi.symbol
WHERE wi.status <> 'removed'
GROUP BY wi.symbol, sc.strategy_type, sc.latest_price, sc.support, sc.resistance,
         sc.ideal_entry, sc.stop_loss, sc.target_price, sc.risk_reward, sc.account_fit,
         sc.technical_summary,
         am.analysis_stage, am.maria_status, am.steph_status, am.risk_status,
         am.tax_status, am.full_chain_status, am.final_synthesis_status,
         am.required_agents, am.completed_agents, am.needs_iteration, am.escalation_policy,
         rc.latest_recommendation, rc.latest_summary, rc.confidence,
         fs.recommendation, fs.confidence, fs.action;

COMMIT;
