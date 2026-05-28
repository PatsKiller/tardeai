# Trade Inspector API Design

## GET /api/v2/lifecycle/trade-inspector

Query: symbol, paper_trade_id, trace_id, proposal_id, strategy_id (any one)

Returns aggregated view:
- resolved_identity: { paper_trade_id, trace_id, proposal_id, symbol, strategy_id }
- overview: entry, exit, pnl, R, account, status
- prospect: signal source, score, grade
- proposal: proposal record, gates, decision
- execution: fill price, timing, slippage
- stop_trailing: db_stop, broker_proof, trailing_tier, time_stop, change_audit
- reconciliation: matched/unmatched status
- journal: win/loss, lesson
- learning: strategy rollup
- backtest: comparison if available
- data_quality_gaps: missing fields per section
- safe_actions / blocked_actions
- safety block (read-only)

- llm_review: { close_analysis, delayed_review, monthly_meta, status, data_quality_gaps, safety }
  - status: not_configured | pending | complete | missing_data | error
  - safety.model_calls_executed_by_endpoint: false (endpoint only reads stored results)

Implementation: call existing endpoints/helpers internally, aggregate response.
The trade-inspector endpoint must NOT call any LLM directly.
