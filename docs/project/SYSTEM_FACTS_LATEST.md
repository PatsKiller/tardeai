# System Facts — Latest

Generated: 2026-07-01T07:40:01.109371

## Runtime
- Hostname: ms01-openclaw
- Python: 3.13.7
- Git: runtime/pr33-stop-evidence-deploy @ b632509f

## Database
- Connected: True
- Tables: 550
- trade_ai_scans: 41250
- paper_trade_proposals: 1032
- paper_trades: 87
- watchlist_agent_results: 13438
- news_articles: 25329
- topic_monitor: 362
- content_embeddings: 168871
- pipeline_stages: 44
- pipeline_runs: 20796
- config_documents: 38
- content_entity_links: 8717
- blocked_content: 88

## Codebase
- python_script_count: 1162
- sql_migration_count: 52
- yaml_config_count: 60
- json_config_count: 17
- strategy_count: 26
- frontend_page_count: 94
- react_component_count: 156
- cron_job_count: 367

## Safety
- ALPACA_MODE: paper
- Live trading: BLOCKED
- Holdings: $1,248,865
- Holdings guard: PASSED
- Blocked reasons: policy_live_trading_allowed_false, validation_days_insufficient, closed_trade_sample_insufficient, governance_not_approved

## Documentation Drift
- **docs/MASTER_SYSTEM_DOCUMENTATION.md**: strategy_count claimed=22 actual=26
- **docs/MASTER_SYSTEM_DOCUMENTATION.md**: strategy_count claimed=23 actual=26