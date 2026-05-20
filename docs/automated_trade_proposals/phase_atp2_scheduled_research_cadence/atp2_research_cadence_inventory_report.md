# ATP-2 Research Cadence Inventory
Generated: 2026-05-19T21:38:56.488441

**Total cron jobs:** 118
**ATP-2 coverage:** 71.4% (5/7 slots)

## Missing ATP-2 Cadence Slots
- **overnight**: needs agent, catalyst_news, technical in overnight
- **proposal_revalidation_30min**: needs proposal_revalidation in market_hours, premarket, market_open

## Covered ATP-2 Cadence Slots
- **eod**: finviz_screener_runner.py, send_alert_digest.py, closed_trade_digest_cron.log 2>&1
- **evening**: news_ingestion.py
- **premarket_4am**: finviz_screener_runner.py
- **premarket_7am**: finviz_enrichment.py, llm_intelligence_enrichment.py
- **premarket_9am**: proactive_quote_refresh_cron.log 2>&1, proactive_quote_refresh_cron.log 2>&1

## Jobs by Category

### agent (6 jobs)
- `agent_router_cron.sh full` [premarket] 15 6
- `agent_intelligence_cron.sh daily` [premarket] 25 6
- `agent_router_cron.sh light` [market_hours] 0 10-15
- `agent_intelligence_cron.sh intraday` [market_hours] 30 11,14
- `agent_router_cron.sh deep` [premarket] 30 7
- `agent_intelligence_cron.sh deep` [market_open] 0 8

### catalyst_news (3 jobs)
- `news_ingestion.py` [premarket] 30 6
- `news_ingestion.py` [market_hours] 30 12
- `news_ingestion.py` [evening] 30 18

### digest (3 jobs)
- `send_alert_digest.py` [market_open] 0 8
- `send_alert_digest.py` [after_close] 0 16
- `closed_trade_digest_cron.log 2>&1` [after_close] 30 16

### enrichment (3 jobs)
- `finviz_enrichment.py` [premarket] 10 7
- `finviz_enrichment.py` [market_hours] 0 13
- `llm_intelligence_enrichment.py` [premarket] 20 7

### governance (8 jobs)
- `gemma3_calibration_scorer.py` [overnight] 30 21
- `paper_performance_governance.py` [market_open] 0 8,20
- `governance_system_facts.log 2>&1` [premarket] 40 7
- `governance_a1a_check.log 2>&1` [premarket] 45 7
- `report_governance_status.py` [premarket] 50 7
- `governance_system_facts.log 2>&1` [evening] 0 18
- `governance_a1a_check.log 2>&1` [evening] 5 18
- `report_governance_status.py` [evening] 10 18

### incubator (1 jobs)
- `incubator_proposal_promoter.py` [premarket] 0 7,8,9,10,11,12,13,14,15,16,17

### morning_packet (2 jobs)
- `aegis_morning_brief_delivery.py` [market_open] 5 8
- `send_morning_brief.py` [market_open] 0 8

### other (65 jobs)
- `run_alex_daily.py` [premarket] 0 5
- `telegram_smart_alerts.py` [premarket] 0 6
- `classify_candidates.py` [premarket] 35 6
- `materialize_income_engine.py` [premarket] 55 6
- `cio_decision_engine.py` [premarket] 0 7
- `sync_dividend_data.py` [premarket] 5 7
- `write_state_freshness_history.py` [premarket] 15 7
- `price_db_sync.py` [premarket] 20 7
- `system_health_alerts.py` [premarket] 25 7
- `recovery_watch_daily.py` [premarket] 30 7
- `portfolio_level_qa.py` [premarket] 40 7
- `record_decision_outcome.py` [premarket] 50 7
- `iterate_research_topics.py` [market_open] 0 8
- `system_health_alerts.py` [market_hours] 10 12,15
- `run_alex_daily.py` [market_open] 0 8
- `generate_weekly_docx.py` [overnight] 0 21
- `run_alex_daily.py` [market_open] 0 9
- `overnight_batch.py` [overnight] 0 20
- `paper_execution_sweep.py` [market_open] */5 9-16 (frequent)
- `paper_trade_monitor.py` [market_open] */5 9-16 (frequent)
- `market_regime_collector.py` [premarket] 30 6
- `market_regime_classifier.py` [premarket] 35 6
- `market_regime_collector.py` [after_close] 5 16
- `open_trade_monitor.py` [market_open] */15 9-16 (frequent)
- `portfolio_orchestrator.py` [premarket] 15 7
- `alert_missing_conditions.py` [premarket] 30 7
- `feedback_loop_processor.py` [overnight] 30 20
- `auto_research.py` [overnight] 0 21
- `youtube_transcript_ingest.py` [evening] 0 19
- `intel_auto_discovery.py` [premarket] 40 6
- `intel_auto_discovery.py` [market_hours] 40 12
- `sec_data_ingest.py` [overnight] 0 20
- `external_market_data_ingest.py` [premarket] 15 7
- `external_market_data_ingest.py` [market_open] 0 8
- `youtube_channel_discovery.py` [market_hours] 0 10
- `transcript_purge.log 2>&1` [overnight] 0 3
- `alpaca_paper_adapter.py` [market_hours] 0 10-16
- `multi_tier_trade_reviewer.py` [market_hours] 0 10
- `multi_tier_trade_reviewer.py` [market_hours] 0 11
- `deep_overnight_llm_window.log 2>&1` [overnight] 0 23
- `trade_ai_orchestrator.py` [market_hours] 0 12
- `trade_ai_orchestrator.py` [market_hours] 0 14
- `trade_ai_orchestrator.py` [after_close] 0 16
- `trade_ai_orchestrator.py` [after_close] 30 17
- `rebalance_verifier.py` [market_hours] 30 10
- `rescan_tickets.py` [evening] 0 18
- `populate_performance_context.py` [overnight] 30 2
- `deep_llm_friday_extended.log 2>&1` [after_close] 0 16
- `data_gap_resolver.py` [market_hours] 0 10-16
- `data_gap_resolver.py` [evening] 0 18
- `data_gap_resolver.py` [market_open] 0 8
- `alpaca_paper_reconciler.py` [market_open] 35 9
- `alpaca_paper_reconciler.py` [after_close] 5 16
- `run_pipeline.py` [overnight] 0 20
- `stale_proposal_sweeper.log 2>&1` [market_open] 15 8
- `stale_proposal_sweeper.log 2>&1` [market_open] 25 8
- `stale_proposal_sweeper.log 2>&1` [after_close] 10 16
- `strategy_config_loader.py` [overnight] 0 3
- `sync-docs-to-drive.py` [unknown] 5 *
- `telegram_command_handler.py` [unknown] */2 * (frequent)
- `maturity_control_board.log 2>&1` [premarket] 55 7
- `report_operator_readiness_summary.py` [market_open] 0 8
- `maturity_control_board.log 2>&1` [evening] 15 18
- `report_operator_readiness_summary.py` [evening] 20 18
- `afterhours_candidate_preparation.log 2>&1` [after_close] 30 17

### quote_refresh (4 jobs)
- `proactive_quote_refresh_cron.log 2>&1` [market_open] */5 9-15 (frequent)
- `proactive_quote_refresh_cron.log 2>&1` [market_open] 20 9
- `proactive_quote_refresh_cron.log 2>&1` [market_hours] 0 12
- `proactive_quote_refresh_cron.log 2>&1` [market_hours] 30 15

### screener (7 jobs)
- `finviz_screener_runner.py` [market_hours] 0 10
- `finviz_screener_runner.py` [after_close] 0 16
- `finviz_screener_runner.py` [premarket] 0 7
- `finviz_screener_runner.py` [market_open] 0 8
- `finviz_screener_runner.py` [market_hours] 0 12
- `finviz_screener_runner.py` [market_hours] 0 14
- `finviz_screener_runner.py` [evening] 0 18

### system (4 jobs)
- `backup_verify.py` [premarket] 0 6
- `cleanup_stale_proposals.py` [market_hours] 0 10
- `cleanup_stale_proposals.py` [market_hours] 0 15
- `classifier_health_check.py` [premarket] 55 7

### watchpool (12 jobs)
- `sync_watchlist_items_to_db.py` [premarket] 45 6
- `materialize_watchlist_strategy_cards.py` [premarket] 50 6
- `process_watchlist_agent_jobs.py` [premarket] */15 6-19 (frequent)
- `process_watchlist_agent_jobs.py` [overnight] */5 20-23 (frequent)
- `process_watchlist_agent_jobs.py` [overnight] */5 0-5 (frequent)
- `process_watchlist_agent_jobs.py` [unknown] */10 * (frequent)
- `watchlist_hygiene.py` [market_open] 30 9
- `watchpool_alerts_cron.log 2>&1` [market_open] 35 9
- `watchpool_alerts_cron.log 2>&1` [market_hours] 5 10
- `watchpool_alerts_cron.log 2>&1` [market_hours] 30 11
- `watchpool_alerts_cron.log 2>&1` [market_hours] 30 13
- `watchpool_alerts_cron.log 2>&1` [market_hours] 30 15

## Jobs by Session Window

### after_close (10 jobs)
- `finviz_screener_runner.py` [screener] 0 16
- `market_regime_collector.py` [other] 5 16
- `trade_ai_orchestrator.py` [other] 0 16
- `trade_ai_orchestrator.py` [other] 30 17
- `deep_llm_friday_extended.log 2>&1` [other] 0 16
- `send_alert_digest.py` [digest] 0 16
- `alpaca_paper_reconciler.py` [other] 5 16
- `stale_proposal_sweeper.log 2>&1` [other] 10 16
- `closed_trade_digest_cron.log 2>&1` [digest] 30 16
- `afterhours_candidate_preparation.log 2>&1` [other] 30 17

### evening (10 jobs)
- `news_ingestion.py` [catalyst_news] 30 18
- `youtube_transcript_ingest.py` [other] 0 19
- `finviz_screener_runner.py` [screener] 0 18
- `rescan_tickets.py` [other] 0 18
- `data_gap_resolver.py` [other] 0 18
- `governance_system_facts.log 2>&1` [governance] 0 18
- `governance_a1a_check.log 2>&1` [governance] 5 18
- `report_governance_status.py` [governance] 10 18
- `maturity_control_board.log 2>&1` [other] 15 18
- `report_operator_readiness_summary.py` [other] 20 18

### market_hours (25 jobs)
- `finviz_screener_runner.py` [screener] 0 10
- `agent_router_cron.sh light` [agent] 0 10-15
- `news_ingestion.py` [catalyst_news] 30 12
- `finviz_enrichment.py` [enrichment] 0 13
- `system_health_alerts.py` [other] 10 12,15
- `agent_intelligence_cron.sh intraday` [agent] 30 11,14
- `intel_auto_discovery.py` [other] 40 12
- `youtube_channel_discovery.py` [other] 0 10
- `alpaca_paper_adapter.py` [other] 0 10-16
- `multi_tier_trade_reviewer.py` [other] 0 10
- `multi_tier_trade_reviewer.py` [other] 0 11
- `trade_ai_orchestrator.py` [other] 0 12
- `trade_ai_orchestrator.py` [other] 0 14
- `rebalance_verifier.py` [other] 30 10
- `finviz_screener_runner.py` [screener] 0 12
- `finviz_screener_runner.py` [screener] 0 14
- `data_gap_resolver.py` [other] 0 10-16
- `cleanup_stale_proposals.py` [system] 0 10
- `cleanup_stale_proposals.py` [system] 0 15
- `proactive_quote_refresh_cron.log 2>&1` [quote_refresh] 0 12
- `proactive_quote_refresh_cron.log 2>&1` [quote_refresh] 30 15
- `watchpool_alerts_cron.log 2>&1` [watchpool] 5 10
- `watchpool_alerts_cron.log 2>&1` [watchpool] 30 11
- `watchpool_alerts_cron.log 2>&1` [watchpool] 30 13
- `watchpool_alerts_cron.log 2>&1` [watchpool] 30 15

### market_open (22 jobs)
- `iterate_research_topics.py` [other] 0 8
- `aegis_morning_brief_delivery.py` [morning_packet] 5 8
- `agent_intelligence_cron.sh deep` [agent] 0 8
- `run_alex_daily.py` [other] 0 8
- `run_alex_daily.py` [other] 0 9
- `paper_execution_sweep.py` [other] */5 9-16
- `paper_trade_monitor.py` [other] */5 9-16
- `open_trade_monitor.py` [other] */15 9-16
- `watchlist_hygiene.py` [watchpool] 30 9
- `external_market_data_ingest.py` [other] 0 8
- `finviz_screener_runner.py` [screener] 0 8
- `data_gap_resolver.py` [other] 0 8
- `send_alert_digest.py` [digest] 0 8
- `alpaca_paper_reconciler.py` [other] 35 9
- `stale_proposal_sweeper.log 2>&1` [other] 15 8
- `stale_proposal_sweeper.log 2>&1` [other] 25 8
- `send_morning_brief.py` [morning_packet] 0 8
- `paper_performance_governance.py` [governance] 0 8,20
- `report_operator_readiness_summary.py` [other] 0 8
- `proactive_quote_refresh_cron.log 2>&1` [quote_refresh] */5 9-15
- `proactive_quote_refresh_cron.log 2>&1` [quote_refresh] 20 9
- `watchpool_alerts_cron.log 2>&1` [watchpool] 35 9

### overnight (13 jobs)
- `generate_weekly_docx.py` [other] 0 21
- `overnight_batch.py` [other] 0 20
- `process_watchlist_agent_jobs.py` [watchpool] */5 20-23
- `process_watchlist_agent_jobs.py` [watchpool] */5 0-5
- `feedback_loop_processor.py` [other] 30 20
- `auto_research.py` [other] 0 21
- `sec_data_ingest.py` [other] 0 20
- `transcript_purge.log 2>&1` [other] 0 3
- `deep_overnight_llm_window.log 2>&1` [other] 0 23
- `gemma3_calibration_scorer.py` [governance] 30 21
- `populate_performance_context.py` [other] 30 2
- `run_pipeline.py` [other] 0 20
- `strategy_config_loader.py` [other] 0 3

### premarket (35 jobs)
- `run_alex_daily.py` [other] 0 5
- `telegram_smart_alerts.py` [other] 0 6
- `agent_router_cron.sh full` [agent] 15 6
- `agent_intelligence_cron.sh daily` [agent] 25 6
- `news_ingestion.py` [catalyst_news] 30 6
- `classify_candidates.py` [other] 35 6
- `sync_watchlist_items_to_db.py` [watchpool] 45 6
- `materialize_watchlist_strategy_cards.py` [watchpool] 50 6
- `materialize_income_engine.py` [other] 55 6
- `cio_decision_engine.py` [other] 0 7
- `sync_dividend_data.py` [other] 5 7
- `finviz_enrichment.py` [enrichment] 10 7
- `write_state_freshness_history.py` [other] 15 7
- `price_db_sync.py` [other] 20 7
- `system_health_alerts.py` [other] 25 7
- `recovery_watch_daily.py` [other] 30 7
- `portfolio_level_qa.py` [other] 40 7
- `record_decision_outcome.py` [other] 50 7
- `agent_router_cron.sh deep` [agent] 30 7
- `market_regime_collector.py` [other] 30 6
- `market_regime_classifier.py` [other] 35 6
- `process_watchlist_agent_jobs.py` [watchpool] */15 6-19
- `portfolio_orchestrator.py` [other] 15 7
- `llm_intelligence_enrichment.py` [enrichment] 20 7
- `alert_missing_conditions.py` [other] 30 7
- `intel_auto_discovery.py` [other] 40 6
- `external_market_data_ingest.py` [other] 15 7
- `backup_verify.py` [system] 0 6
- `finviz_screener_runner.py` [screener] 0 7
- `incubator_proposal_promoter.py` [incubator] 0 7,8,9,10,11,12,13,14,15,16,17
- `classifier_health_check.py` [system] 55 7
- `governance_system_facts.log 2>&1` [governance] 40 7
- `governance_a1a_check.log 2>&1` [governance] 45 7
- `report_governance_status.py` [governance] 50 7
- `maturity_control_board.log 2>&1` [other] 55 7

### unknown (3 jobs)
- `process_watchlist_agent_jobs.py` [watchpool] */10 *
- `sync-docs-to-drive.py` [other] 5 *
- `telegram_command_handler.py` [other] */2 *