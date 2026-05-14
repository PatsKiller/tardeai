# System Facts — Latest

Generated: 2026-05-11T07:15:01.483115

## Runtime
- Hostname: ms01-openclaw
- Python: 3.13.7
- Git: main @ 1808cbe

## Database
- Connected: True
- Tables: 320
- trade_ai_scans: 615
- paper_trade_proposals: 51
- paper_trades: 4
- watchlist_agent_results: 4274
- news_articles: 3022
- topic_monitor: 17
- content_embeddings: 14222
- pipeline_stages: 44
- pipeline_runs: 16
- config_documents: 38
- content_entity_links: 82
- blocked_content: 2

## Codebase
- python_script_count: 358
- sql_migration_count: 35
- yaml_config_count: 34
- json_config_count: 6
- strategy_count: 20
- frontend_page_count: 61
- react_component_count: 97
- cron_job_count: 152

## Safety
- ALPACA_MODE: paper
- Live trading: BLOCKED
- Holdings: $1,189,475
- Holdings guard: PASSED
- Blocked reasons: policy_live_trading_allowed_false, validation_days_insufficient, closed_trade_sample_insufficient, win_rate_below_threshold, profit_factor_below_threshold, governance_not_approved

## Documentation Drift
- **docs/CHEAT_SHEET.md**: table_count claimed=299 actual=320
- **docs/CHEAT_SHEET.md**: python_script_count claimed=3 actual=358
- **docs/CHEAT_SHEET.md**: python_script_count claimed=3 actual=358
- **docs/CHEAT_SHEET.md**: python_script_count claimed=3 actual=358
- **docs/CHEAT_SHEET.md**: python_script_count claimed=3 actual=358
- **docs/ARCHITECTURE_INFOGRAM.md**: table_count claimed=299 actual=320
- **docs/ARCHITECTURE_INFOGRAM.md**: cron_job_count claimed=142 actual=152
- **docs/ARCHITECTURE_INFOGRAM.md**: frontend_page_count claimed=55 actual=61
- **docs/ARCHITECTURE_OVERVIEW.md**: table_count claimed=299 actual=320
- **docs/ARCHITECTURE_OVERVIEW.md**: table_count claimed=299 actual=320
- **docs/ARCHITECTURE_OVERVIEW.md**: cron_job_count claimed=142 actual=152
- **docs/ARCHITECTURE_OVERVIEW.md**: cron_job_count claimed=142 actual=152
- **docs/ARCHITECTURE_OVERVIEW.md**: frontend_page_count claimed=55 actual=61
- **docs/RESTORE_GUIDE.md**: table_count claimed=299 actual=320
- **docs/RESTORE_GUIDE.md**: python_script_count claimed=3 actual=358
- **docs/RESTORE_GUIDE.md**: python_script_count claimed=3 actual=358
- **docs/llm_fleet_strategy_v3_4_1.md**: cron_job_count claimed=2 actual=152
- **docs/llm_fleet_strategy_v3_4_1.md**: cron_job_count claimed=2 actual=152
- **docs/llm_fleet_strategy_v3_4_1.md**: cron_job_count claimed=2 actual=152
- **docs/llm_fleet_strategy_v3_4_1.md**: python_script_count claimed=3 actual=358
- **docs/llm_fleet_strategy_v3_4_1.md**: python_script_count claimed=3 actual=358
- **docs/llm_fleet_strategy_v3_4_1.md**: python_script_count claimed=3 actual=358
- **docs/MASTER_SYSTEM_DOCUMENTATION.md**: table_count claimed=299 actual=320
- **docs/MASTER_SYSTEM_DOCUMENTATION.md**: cron_job_count claimed=142 actual=152
- **docs/MASTER_SYSTEM_DOCUMENTATION.md**: python_script_count claimed=90 actual=358
- **docs/COST_MODEL.md**: table_count claimed=299 actual=320
---

## Session 33 Updates (2026-05-13)

- Strategy count: 22 active + 1 deprecated = 23 total (was 20)
- Schema dialect: all v1.0.0 (no v1.0 TESTING remaining)
- YAML audit issues: ~63 → informational only (all required blocks present)
- New blocks on all YAMLs: vix_rules, technical_indicators_required, performance_context
- Screener count in assets/screeners.yaml: 10 core + 8 new = 18 (DB has 27 total with finviz_screeners)
- New strategies: fib_retracement_bounce, earnings_pre_buildup, earnings_post_momentum
- Deprecated: earnings_catalyst (split into pre/post)

## Session 35 Updates (2026-05-14)

- New table: data_gap_registry (gap tracking from gemma3 outputs)
- New table: gap_resolution_outcomes (feedback measurement)
- New table: overnight_actionable_outcomes (actionable signal tracking)
- New script: scripts/data_gap_resolver.py (self-healing gap resolution)
- New script: scripts/report_deep_overnight_queue_status.py (queue reporter)
- New script: scripts/check_deep_overnight_health.py (11 health checks)
- New script: scripts/overnight_digest_telegram.py (6 AM brief)
- New page: /v2/overnight (Overnight Intelligence Dashboard)
- Cron entries: +3 gap resolver (hourly/pre-overnight/weekly) → ~155 total
- Total DB tables: 333+ (was 330)
- Queue runner: --quota-policy balanced with per-type soft quotas
- Recovery watch prompt: uses llm_context_engine.build_context()
- Queue dedup: per-job-type cooldowns prevent duplicate analysis
- Self-healing loop: detection → resolution → re-queue → verification
