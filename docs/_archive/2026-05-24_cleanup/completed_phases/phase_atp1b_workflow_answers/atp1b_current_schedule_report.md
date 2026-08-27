# Research Pipeline Schedule Report
Generated: 2026-05-20T01:13:14.426602+00:00
Total cron jobs: 118

## Jobs by Session

| Time | Session | Type | Script | Creates Proposals |
|------|---------|------|--------|-------------------|
| 00:05 (dow=1-5) | premarket | other | run_alex_daily.py |  |
| 00:06 (dow=1-5) | premarket | other | telegram_smart_alerts.py |  |
| 15:06 (dow=1-5) | premarket | agent | agent_router_cron.sh |  |
| 25:06 (dow=1-5) | premarket | research | agent_intelligence_cron.sh |  |
| 30:06 (dow=1-5) | premarket | research | news_ingestion.py |  |
| 35:06 (dow=1-5) | premarket | research | classify_candidates.py |  |
| 45:06 (dow=1-5) | premarket | system | sync_watchlist_items_to_db.py |  |
| 50:06 (dow=1-5) | premarket | other | materialize_watchlist_strategy_cards.py |  |
| 55:06 (dow=1-5) | premarket | other | materialize_income_engine.py |  |
| 00:07 (dow=1-5) | premarket | other | cio_decision_engine.py |  |
| 05:07 (dow=1-5) | premarket | system | sync_dividend_data.py |  |
| 10:07 (dow=1-5) | premarket | research | finviz_enrichment.py |  |
| 15:07 (dow=1-5) | premarket | other | write_state_freshness_history.py |  |
| 20:07 (dow=1-5) | premarket | system | price_db_sync.py |  |
| 25:07 (dow=1-5) | premarket | system | system_health_alerts.py |  |
| 30:07 (dow=1-5) | premarket | other | recovery_watch_daily.py |  |
| 40:07 (dow=1-5) | premarket | other | portfolio_level_qa.py |  |
| 50:07 (dow=1-5) | premarket | other | record_decision_outcome.py |  |
| 00:08 (dow=1-5) | market_open | other | iterate_research_topics.py |  |
| 05:08 (dow=1-5) | market_open | digest | aegis_morning_brief_delivery.py |  |
| 00:10 (dow=1-5) | market_hours | research | finviz_screener_runner.py |  |
| 00:10-15 (dow=1-5) | market_hours | agent | agent_router_cron.sh |  |
| 30:12 (dow=1-5) | market_hours | research | news_ingestion.py |  |
| 00:13 (dow=1-5) | market_hours | research | finviz_enrichment.py |  |
| 10:12,15 (dow=1-5) | market_hours | system | system_health_alerts.py |  |
| 30:11,14 (dow=1-5) | market_hours | research | agent_intelligence_cron.sh |  |
| 00:16 (dow=1-5) | after_close | research | finviz_screener_runner.py |  |
| 30:18 | after_close | research | news_ingestion.py |  |
| 30:07 (dow=0) | premarket | agent | agent_router_cron.sh |  |
| 00:08 (dow=0) | market_open | research | agent_intelligence_cron.sh |  |
| 00:08 (dow=0) | market_open | other | run_alex_daily.py |  |
| 00:21 (dow=0) | overnight | other | generate_weekly_docx.py |  |
| 00:09 | market_hours | other | run_alex_daily.py |  |
| 00:20 (dow=1-5) | overnight | other | overnight_batch.py |  |
| every 5 min (hours 9-16) | continuous | execution | paper_execution_sweep.py |  |
| every 5 min (hours 9-16) | continuous | execution | paper_trade_monitor.py |  |
| 30:06 (dow=1-5) | premarket | system | market_regime_collector.py |  |
| 35:06 (dow=1-5) | premarket | system | market_regime_classifier.py |  |
| 05:16 (dow=1-5) | after_close | system | market_regime_classifier.py |  |
| every 15 min (hours 9-16) | continuous | other | open_trade_monitor.py |  |
| every 15 min (hours 6-19) | continuous | agent | process_watchlist_agent_jobs.py |  |
| every 5 min (hours 20-23) | continuous | agent | process_watchlist_agent_jobs.py |  |
| every 5 min (hours 0-5) | continuous | agent | process_watchlist_agent_jobs.py |  |
| every 10 min | continuous | agent | process_watchlist_agent_jobs.py |  |
| 15:07 (dow=1-5) | premarket | other | portfolio_orchestrator.py | YES |
| 20:07 (dow=1-5) | premarket | research | llm_intelligence_enrichment.py |  |
| 30:07 (dow=1-5) | premarket | other | alert_missing_conditions.py |  |
| 30:20 (dow=1-5) | overnight | other | feedback_loop_processor.py |  |
| 00:21 (dow=1-5) | overnight | other | auto_research.py |  |
| 00:19 (dow=1-5) | overnight | other | youtube_transcript_ingest.py |  |
| 40:06 (dow=1-5) | premarket | research | intel_auto_discovery.py |  |
| 40:12 (dow=1-5) | market_hours | research | intel_auto_discovery.py |  |
| 30:09 (dow=0) | market_hours | other | watchlist_hygiene.py |  |
| 00:20 (dow=1-5) | overnight | other | sec_data_ingest.py |  |
| 15:07 (dow=1-5) | premarket | other | external_market_data_ingest.py |  |
| 00:08 (dow=1) | market_open | other | external_market_data_ingest.py |  |
| 00:06 | premarket | system | backup_verify.py |  |
| 00:10 | market_hours | research | youtube_channel_discovery.py |  |
| 00:03 | overnight | other | cd $PROJ && $PY -c "import sys; sys.path.insert(0,'scripts') |  |
| 00:10-16 (dow=1-5) | market_hours | execution | alpaca_paper_adapter.py |  |
| 00:10 (dow=0) | market_hours | other | multi_tier_trade_reviewer.py |  |
| 00:11 | market_hours | other | multi_tier_trade_reviewer.py |  |
| 00:23 | overnight | other | run_deep_overnight_llm_window.sh |  |
| 00:12 (dow=1-5) | market_hours | other | trade_ai_orchestrator.py | YES |
| 00:14 (dow=1-5) | market_hours | other | trade_ai_orchestrator.py | YES |
| 00:16 (dow=1-5) | after_close | other | trade_ai_orchestrator.py | YES |
| 30:17 (dow=1-5) | after_close | other | trade_ai_orchestrator.py | YES |
| 30:10 (dow=0) | market_hours | other | rebalance_verifier.py |  |
| 30:21 (dow=1-5) | overnight | other | gemma3_calibration_scorer.py |  |
| 00:07 (dow=1-5) | premarket | research | finviz_screener_runner.py |  |
| 00:08 (dow=1-5) | market_open | research | finviz_screener_runner.py |  |
| 00:12 (dow=1-5) | market_hours | research | finviz_screener_runner.py |  |
| 00:14 (dow=1-5) | market_hours | research | finviz_screener_runner.py |  |
| 00:18 (dow=1-5) | after_close | research | finviz_screener_runner.py |  |
| 00:7,8,9,10,11,12,13,14,15,16,17 (dow=1-5) | premarket | proposal | incubator_proposal_promoter.py | YES |
| 00:18 | after_close | other | rescan_tickets.py |  |
| 30:02 | overnight | other | populate_performance_context.py |  |
| 00:16 (dow=5) | after_close | other | run_deep_overnight_llm_window.sh |  |
| 00:10-16 (dow=1-5) | market_hours | system | data_gap_resolver.py |  |
| 00:18 (dow=1-5) | after_close | system | data_gap_resolver.py |  |
| 00:08 (dow=0) | market_open | system | data_gap_resolver.py |  |
| 00:08 (dow=1-5) | market_open | digest | send_alert_digest.py |  |
| 00:16 (dow=1-5) | after_close | digest | send_alert_digest.py |  |
| 35:09 (dow=1-5) | market_hours | execution | alpaca_paper_reconciler.py |  |
| 05:16 (dow=1-5) | after_close | execution | alpaca_paper_reconciler.py |  |
| 00:20 (dow=6) | overnight | other | run_pipeline.py |  |
| 00:10 (dow=1-5) | market_hours | proposal | cleanup_stale_proposals.py |  |
| 00:15 (dow=1-5) | market_hours | proposal | cleanup_stale_proposals.py |  |
| 15:08 (dow=1-5) | market_open | proposal | run_scheduled_stale_proposal_sweeper.sh |  |
| 25:08 (dow=1-5) | market_open | proposal | run_scheduled_stale_proposal_sweeper.sh |  |
| 10:16 (dow=1-5) | after_close | proposal | run_scheduled_stale_proposal_sweeper.sh |  |
| 00:08 (dow=1-5) | market_open | digest | send_morning_brief.py |  |
| 55:07 (dow=1-5) | premarket | system | classifier_health_check.py |  |
| 00:8,20 (dow=1-5) | market_open | governance | paper_performance_governance.py |  |
| 00:03 | overnight | system | strategy_config_loader.py |  |
| 05:** | continuous | system | sync-docs-to-drive.py |  |
| every 2 min | continuous | other | telegram_command_handler.py |  |
| 40:07 (dow=1-5) | premarket | governance | run_scheduled_system_facts.sh |  |
| 45:07 (dow=1-5) | premarket | governance | run_scheduled_a1a_check.sh |  |
| 50:07 (dow=1-5) | premarket | governance | report_governance_status.py |  |
| 00:18 (dow=0) | after_close | governance | run_scheduled_system_facts.sh |  |
| 05:18 (dow=0) | after_close | governance | run_scheduled_a1a_check.sh |  |
| 10:18 (dow=0) | after_close | governance | report_governance_status.py |  |
| 55:07 (dow=1-5) | premarket | governance | run_scheduled_maturity_control_board.sh |  |
| 00:08 (dow=1-5) | market_open | other | report_operator_readiness_summary.py |  |
| 15:18 (dow=0) | after_close | governance | run_scheduled_maturity_control_board.sh |  |
| 20:18 (dow=0) | after_close | other | report_operator_readiness_summary.py |  |
| every 5 min (hours 9-15) | continuous | system | run_scheduled_quote_refresh.sh |  |
| 20:09 (dow=1-5) | market_hours | system | run_scheduled_quote_refresh.sh |  |
| 00:12 (dow=1-5) | market_hours | system | run_scheduled_quote_refresh.sh |  |
| 30:15 (dow=1-5) | market_hours | system | run_scheduled_quote_refresh.sh |  |
| 35:09 (dow=1-5) | market_hours | other | run_scheduled_watchpool_alerts.sh |  |
| 05:10 (dow=1-5) | market_hours | other | run_scheduled_watchpool_alerts.sh |  |
| 30:11 (dow=1-5) | market_hours | other | run_scheduled_watchpool_alerts.sh |  |
| 30:13 (dow=1-5) | market_hours | other | run_scheduled_watchpool_alerts.sh |  |
| 30:15 (dow=1-5) | market_hours | other | run_scheduled_watchpool_alerts.sh |  |
| 30:16 (dow=1-5) | after_close | digest | run_closed_trade_digest_cron.sh |  |
| 30:17 (dow=1-5) | after_close | other | run_afterhours_candidate_preparation.sh |  |

## Summary by Session

| Session | Count |
|---------|-------|
| after_close | 19 |
| continuous | 10 |
| market_hours | 30 |
| market_open | 13 |
| overnight | 12 |
| premarket | 34 |

## Summary by Type

| Type | Count |
|------|-------|
| agent | 7 |
| digest | 5 |
| execution | 5 |
| governance | 9 |
| other | 47 |
| proposal | 6 |
| research | 20 |
| system | 19 |

## Proposal-Creating Scripts

- portfolio_orchestrator.py
- trade_ai_orchestrator.py
- trade_ai_orchestrator.py
- trade_ai_orchestrator.py
- trade_ai_orchestrator.py
- incubator_proposal_promoter.py
