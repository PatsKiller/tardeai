CREATE OR REPLACE VIEW v_trade_execution_quality_latest AS
SELECT q.*, r.grok_execution_label, r.grok_summary, r.grok_what_to_do_next_time,
       r.grok_strategy_backtest_hypotheses, r.normalized_tags, r.review_status AS grok_status
FROM trade_execution_quality q
LEFT JOIN trade_execution_grok_reviews r ON r.trade_key=q.trade_key AND r.source=q.source;
