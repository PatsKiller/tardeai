-- Hermes Phase 1C: Safe View Drafts
-- DRAFT ONLY — DO NOT APPLY until operator approves
-- Date: 2026-05-30
-- Purpose: Read-only views for Hermes that exclude sensitive columns

-- ============================================================
-- 1. hermes_v_ticker_context
-- ============================================================
CREATE OR REPLACE VIEW hermes_v_ticker_context AS
SELECT
    t.id, t.snapshot_date, t.symbol, t.source,
    t.rsi, t.beta, t.sma20_pct, t.sma50_pct, t.sma200_pct,
    t.perf_week_pct, t.perf_month_pct, t.perf_ytd_pct,
    t.week52_high_pct, t.week52_low_pct, t.analyst_recom,
    t.data, t.created_at,
    ie.intelligence_score, ie.intelligence_grade, ie.signal_count,
    ie.pipeline_sources, ie.last_enriched, ie.sector, ie.industry,
    ie.current_price, ie.price_updated_at,
    fs.fused_score, fs.catalyst_score, fs.news_score,
    fs.social_score, fs.confidence AS fused_confidence,
    fs.direction, fs.contradictions
FROM ticker_snapshot_daily t
LEFT JOIN intelligence_entities ie ON ie.entity_id = t.symbol AND ie.entity_type = 'market'
LEFT JOIN LATERAL (
    SELECT * FROM fused_signals WHERE symbol = t.symbol ORDER BY created_at DESC LIMIT 1
) fs ON true;

-- ============================================================
-- 2. hermes_v_proposal_context
-- ============================================================
CREATE OR REPLACE VIEW hermes_v_proposal_context AS
SELECT
    p.id, p.symbol, p.strategy_id, p.setup_type,
    p.signal_score, p.signal_grade, p.signal_decision,
    p.rvol, p.float_m, p.gap_pct, p.catalyst, p.catalyst_verified,
    p.source_quality_score, p.data_quality_score, p.intel_readiness,
    p.vix_at_proposal, p.market_regime,
    -- Account masked to type only
    CASE
        WHEN p.proposed_account ILIKE '%ira%' THEN 'IRA'
        WHEN p.proposed_account ILIKE '%roth%' THEN 'Roth'
        WHEN p.proposed_account ILIKE '%401%' THEN '401k'
        ELSE 'Taxable'
    END AS account_type,
    p.proposed_entry, p.proposed_stop, p.proposed_target1, p.proposed_target2,
    p.proposed_shares, p.proposed_dollar_size, p.proposed_dollar_risk,
    p.proposed_stop_pct, p.proposed_rr,
    p.status, p.created_at, p.enrichment_status
FROM paper_trade_proposals p;

-- ============================================================
-- 3. hermes_v_trade_reflection_context
-- ============================================================
CREATE OR REPLACE VIEW hermes_v_trade_reflection_context AS
SELECT
    pt.id, pt.symbol, pt.strategy_id,
    CASE
        WHEN pt.account ILIKE '%ira%' THEN 'IRA'
        WHEN pt.account ILIKE '%roth%' THEN 'Roth'
        WHEN pt.account ILIKE '%401%' THEN '401k'
        ELSE 'Taxable'
    END AS account_type,
    pt.entry_price, pt.entry_time, pt.shares, pt.dollar_size,
    pt.stop_loss, pt.target_1, pt.target_2, pt.dollar_risk,
    pt.score_at_entry, pt.rvol_at_entry, pt.float_m_at_entry,
    pt.catalyst_at_entry, pt.catalyst_verified, pt.intel_readiness,
    pt.vix_at_entry, pt.market_regime,
    pt.exit_price, pt.exit_time, pt.exit_reason,
    pt.pnl, pt.pnl_pct, pt.hold_time_min,
    pt.planned_entry, pt.entry_slippage,
    pt.lifecycle_state, pt.created_at
FROM paper_trades pt
UNION ALL
SELECT
    tc.id, tc.symbol, tc.strategy_id,
    CASE
        WHEN tc.account ILIKE '%ira%' THEN 'IRA'
        WHEN tc.account ILIKE '%roth%' THEN 'Roth'
        WHEN tc.account ILIKE '%401%' THEN '401k'
        ELSE 'Taxable'
    END AS account_type,
    tc.buy_price, tc.open_date, tc.shares, tc.cost_basis,
    NULL, NULL, NULL, NULL,
    NULL, NULL, NULL,
    NULL, NULL, NULL,
    NULL, NULL,
    tc.sell_price, tc.close_date, tc.note,
    tc.pnl, tc.pnl_pct, tc.hold_days * 60 * 24,
    NULL, NULL,
    'closed', tc.created_at
FROM trade_closed tc;

-- ============================================================
-- 4. hermes_v_news_research_context
-- ============================================================
CREATE OR REPLACE VIEW hermes_v_news_research_context AS
SELECT
    n.id, n.symbol, n.strategy_type, n.title, n.summary,
    n.source, n.source_url, n.published_at,
    n.relevance_score, n.sentiment, n.sentiment_score,
    n.is_attention_spike, n.strategy_tags, n.agent_tags,
    n.hygiene_status, n.is_duplicate,
    n.rag_status, n.deep_curation_verdict, n.deep_curation_weight,
    n.created_at
    -- raw_payload excluded (large, may contain raw HTML)
FROM news_articles n;

-- ============================================================
-- 5. hermes_v_agent_results_context
-- ============================================================
CREATE OR REPLACE VIEW hermes_v_agent_results_context AS
SELECT
    w.id, w.job_id, w.symbol, w.agent, w.request_type,
    w.status, w.confidence, w.summary, w.recommendation,
    w.next_action, w.reason_codes, w.model_used, w.prompt_hash,
    w.started_at, w.completed_at, w.rag_sources_used,
    w.created_at
    -- raw_response excluded (large, may contain prompt content)
    -- input_data_snapshot excluded (large)
    -- full_result excluded (large JSONB)
    -- full_narrative excluded (large text)
FROM watchlist_agent_results w;

-- ============================================================
-- 6. hermes_v_pipeline_health_context
-- ============================================================
CREATE OR REPLACE VIEW hermes_v_pipeline_health_context AS
SELECT
    pr.id, pr.pipeline_id, pr.status, pr.started_at, pr.completed_at,
    pr.duration_seconds, pr.error_message, pr.created_at,
    pd.name AS pipeline_name, pd.description
FROM pipeline_runs pr
LEFT JOIN pipeline_definitions pd ON pd.id = pr.pipeline_id;

-- ============================================================
-- 7. hermes_v_rag_context_metadata
-- ============================================================
CREATE OR REPLACE VIEW hermes_v_rag_context_metadata AS
SELECT
    ce.id, ce.source_type, ce.source_id, ce.title,
    ce.top_keywords, ce.embedding_model, ce.embedding_dim,
    ce.created_at
    -- embedding excluded (large 768-dim JSONB vector)
    -- tfidf_terms excluded (large JSONB)
FROM content_embeddings ce;

-- ============================================================
-- 8. hermes_v_portfolio_context
-- ============================================================
CREATE OR REPLACE VIEW hermes_v_portfolio_context AS
SELECT
    sw.id, sw.symbol,
    CASE
        WHEN sw.account ILIKE '%ira%' THEN 'IRA'
        WHEN sw.account ILIKE '%roth%' THEN 'Roth'
        WHEN sw.account ILIKE '%401%' THEN '401k'
        ELSE 'Taxable'
    END AS account_type,
    sw.stopped_out_at, sw.exit_price, sw.stop_price, sw.reason,
    sw.setup_name, sw.thesis_at_exit, sw.realized_pnl, sw.status,
    sw.analyst_verdict, sw.analyst_confidence, sw.analyst_summary,
    sw.reentry_trigger, sw.invalidated_if, sw.is_active,
    sw.created_at, sw.updated_at
FROM stopped_out_watch sw;
