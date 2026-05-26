# Direct Telegram Sender Audit

**Generated:** 2026-05-26T19:17:19.280941+00:00
**Total files with Telegram references:** 81
**Approved central components:** 10
**Bypass risk files:** 4
**Direct API (non-central):** 34
**Migration candidates:** 35

## Bypass Risk Files

- `scripts/api_v2.py` — 4 refs, recommendation: review_bypass_usage
- `scripts/audit_direct_telegram_senders.py` — 7 refs, recommendation: review_bypass_usage
- `scripts/send_closed_trade_digest.py` — 6 refs, recommendation: review_bypass_usage
- `scripts/system_health_agent.py` — 2 refs, recommendation: review_bypass_usage

## Direct API (Non-Central)

- `scripts/agent_event_router.py` — 6 refs, recommendation: review_for_migration
- `scripts/alert_dispatcher_unified.py` — 4 refs, recommendation: review_for_migration
- `scripts/atm_auto_approver.py` — 3 refs, recommendation: migrate_to_send_telegram
- `scripts/audit_direct_telegram_senders.py` — 7 refs, recommendation: review_bypass_usage
- `scripts/eod_open_trade_alert.py` — 3 refs, recommendation: migrate_to_send_telegram
- `scripts/full_system_backup.py` — 2 refs, recommendation: migrate_to_send_telegram
- `scripts/iris_taxonomy_agent.py` — 2 refs, recommendation: migrate_to_send_telegram
- `scripts/morning_digest.py` — 4 refs, recommendation: review_for_migration
- `scripts/open_trade_monitor.py` — 16 refs, recommendation: review_for_migration
- `scripts/overnight_batch.py` — 3 refs, recommendation: review_for_migration
- `scripts/phase3_lookthrough_fetcher.py` — 2 refs, recommendation: migrate_to_send_telegram
- `scripts/pipeline_alert.py` — 2 refs, recommendation: migrate_to_send_telegram
- `scripts/pipeline_health_monitor.py` — 6 refs, recommendation: review_for_migration
- `scripts/pipeline_watchdog.py` — 7 refs, recommendation: review_for_migration
- `scripts/portfolio_alerts.py` — 12 refs, recommendation: review_for_migration
- `scripts/portfolio_monthly_report.py` — 6 refs, recommendation: review_for_migration
- `scripts/portfolio_monthly_synthesis.py` — 4 refs, recommendation: review_for_migration
- `scripts/portfolio_technical.py` — 4 refs, recommendation: review_for_migration
- `scripts/portfolio_weekly_report.py` — 6 refs, recommendation: review_for_migration
- `scripts/premarket_watcher.py` — 6 refs, recommendation: review_for_migration
- `scripts/previously_traded_watchlist.py` — 4 refs, recommendation: migrate_to_send_telegram
- `scripts/proposal_alerter.py` — 8 refs, recommendation: review_for_migration
- `scripts/scalp_critic_agent.py` — 4 refs, recommendation: migrate_to_send_telegram
- `scripts/send_morning_brief.py` — 6 refs, recommendation: review_for_migration
- `scripts/send_no_leads_diagnostic_alert.py` — 5 refs, recommendation: migrate_to_send_telegram
- `scripts/send_telegram_proposal_alert.py` — 7 refs, recommendation: review_for_migration
- `scripts/send_watchpool_maturity_alerts.py` — 5 refs, recommendation: migrate_to_send_telegram
- `scripts/stop_decision_brief.py` — 2 refs, recommendation: migrate_to_send_telegram
- `scripts/system_health_alerts.py` — 5 refs, recommendation: review_for_migration
- `scripts/topic_curator.py` — 4 refs, recommendation: review_for_migration
- `scripts/topic_ingestion.py` — 4 refs, recommendation: review_for_migration
- `scripts/trade_ai_news_monitor.py` — 3 refs, recommendation: migrate_to_send_telegram
- `scripts/weekly_summary_local.py` — 6 refs, recommendation: review_for_migration
- `scripts/cron_wrapper.sh` — 3 refs, recommendation: migrate_to_send_telegram

## Migration Candidates

- `scripts/agent_event_router.py` — review_for_migration
- `scripts/alert_dispatcher_unified.py` — review_for_migration
- `scripts/atm_auto_approver.py` — migrate_to_send_telegram
- `scripts/eod_open_trade_alert.py` — migrate_to_send_telegram
- `scripts/full_system_backup.py` — migrate_to_send_telegram
- `scripts/iris_taxonomy_agent.py` — migrate_to_send_telegram
- `scripts/morning_digest.py` — review_for_migration
- `scripts/open_trade_monitor.py` — review_for_migration
- `scripts/overnight_batch.py` — review_for_migration
- `scripts/phase3_lookthrough_fetcher.py` — migrate_to_send_telegram
- `scripts/pipeline_alert.py` — migrate_to_send_telegram
- `scripts/pipeline_health_monitor.py` — review_for_migration
- `scripts/pipeline_watchdog.py` — review_for_migration
- `scripts/portfolio_alerts.py` — review_for_migration
- `scripts/portfolio_monthly_report.py` — review_for_migration
- `scripts/portfolio_monthly_synthesis.py` — review_for_migration
- `scripts/portfolio_server.py` — review_for_migration
- `scripts/portfolio_technical.py` — review_for_migration
- `scripts/portfolio_weekly_report.py` — review_for_migration
- `scripts/premarket_watcher.py` — review_for_migration
- `scripts/previously_traded_watchlist.py` — migrate_to_send_telegram
- `scripts/proposal_alerter.py` — review_for_migration
- `scripts/scalp_critic_agent.py` — migrate_to_send_telegram
- `scripts/send_morning_brief.py` — review_for_migration
- `scripts/send_no_leads_diagnostic_alert.py` — migrate_to_send_telegram
- `scripts/send_telegram_proposal_alert.py` — review_for_migration
- `scripts/send_watchpool_maturity_alerts.py` — migrate_to_send_telegram
- `scripts/stop_decision_brief.py` — migrate_to_send_telegram
- `scripts/system_health_alerts.py` — review_for_migration
- `scripts/topic_curator.py` — review_for_migration
- `scripts/topic_ingestion.py` — review_for_migration
- `scripts/trade_ai_health.py` — review_for_migration
- `scripts/trade_ai_news_monitor.py` — migrate_to_send_telegram
- `scripts/weekly_summary_local.py` — review_for_migration
- `scripts/cron_wrapper.sh` — migrate_to_send_telegram

## All Files

| File | Refs | Central | Bypass | Direct API | Recommendation |
|------|------|---------|--------|------------|----------------|
| `scripts/aegis_morning_brief_delivery.py` | 2 |  |  |  | ok_uses_central_api |
| `scripts/aegis_overnight.py` | 3 |  |  |  | ok_uses_central_api |
| `scripts/agent_event_router.py` | 6 |  |  | yes | review_for_migration |
| `scripts/agent_watchlist_engine.py` | 1 |  |  |  | ok_uses_central_api |
| `scripts/alert_dispatcher.py` | 6 |  |  |  | ok_uses_central_api |
| `scripts/alert_dispatcher_unified.py` | 4 |  |  | yes | review_for_migration |
| `scripts/alerting.py` | 1 |  |  |  | ok_uses_central_api |
| `scripts/api_v2.py` | 4 |  | YES |  | review_bypass_usage |
| `scripts/atm_auto_approver.py` | 3 |  |  | yes | migrate_to_send_telegram |
| `scripts/audit_direct_telegram_senders.py` | 7 |  | YES | yes | review_bypass_usage |
| `scripts/auto_research.py` | 1 |  |  |  | ok_uses_central_api |
| `scripts/continuous_runner.py` | 1 |  |  |  | ok_uses_central_api |
| `scripts/credential_monitor.py` | 1 |  |  |  | ok_uses_central_api |
| `scripts/discover_telegram_chat_id.py` | 3 | yes |  | yes | central_component |
| `scripts/eod_open_trade_alert.py` | 3 |  |  | yes | migrate_to_send_telegram |
| `scripts/finviz_health_check.py` | 1 |  |  |  | ok_uses_central_api |
| `scripts/finviz_ingestion.py` | 2 |  |  |  | ok_uses_central_api |
| `scripts/full_system_backup.py` | 2 |  |  | yes | migrate_to_send_telegram |
| `scripts/generate_daily_intelligence_report.py` | 1 |  |  |  | ok_uses_central_api |
| `scripts/generate_weekly_docx.py` | 1 |  |  |  | ok_uses_central_api |
| `scripts/incubator_llm_screener.py` | 1 |  |  |  | ok_uses_central_api |
| `scripts/incubator_proposal_promoter.py` | 2 |  |  |  | ok_uses_central_api |
| `scripts/iris_taxonomy_agent.py` | 2 |  |  | yes | migrate_to_send_telegram |
| `scripts/morning_digest.py` | 4 |  |  | yes | review_for_migration |
| `scripts/open_trade_monitor.py` | 16 |  |  | yes | review_for_migration |
| `scripts/overnight_batch.py` | 3 |  |  | yes | review_for_migration |
| `scripts/overnight_digest_telegram.py` | 1 |  |  |  | ok_uses_central_api |
| `scripts/phase3_lookthrough_fetcher.py` | 2 |  |  | yes | migrate_to_send_telegram |
| `scripts/pipeline_alert.py` | 2 |  |  | yes | migrate_to_send_telegram |
| `scripts/pipeline_health_monitor.py` | 6 |  |  | yes | review_for_migration |
| `scripts/pipeline_watchdog.py` | 7 |  |  | yes | review_for_migration |
| `scripts/portfolio_alerts.py` | 12 |  |  | yes | review_for_migration |
| `scripts/portfolio_live_monitor.py` | 5 |  |  |  | ok_uses_central_api |
| `scripts/portfolio_monthly_report.py` | 6 |  |  | yes | review_for_migration |
| `scripts/portfolio_monthly_synthesis.py` | 4 |  |  | yes | review_for_migration |
| `scripts/portfolio_orchestrator.py` | 1 |  |  |  | ok_uses_central_api |
| `scripts/portfolio_server.py` | 4 |  |  |  | review_for_migration |
| `scripts/portfolio_technical.py` | 4 |  |  | yes | review_for_migration |
| `scripts/portfolio_weekly_report.py` | 6 |  |  | yes | review_for_migration |
| `scripts/premarket_watcher.py` | 6 |  |  | yes | review_for_migration |
| `scripts/previously_traded_watchlist.py` | 4 |  |  | yes | migrate_to_send_telegram |
| `scripts/process_watchlist_agent_jobs.py` | 2 |  |  |  | ok_uses_central_api |
| `scripts/proposal_alerter.py` | 8 |  |  | yes | review_for_migration |
| `scripts/proposal_paper_submitter.py` | 2 |  |  |  | ok_uses_central_api |
| `scripts/rebalance_verifier.py` | 2 |  |  |  | ok_uses_central_api |
| `scripts/recovery_watch_daily.py` | 2 |  |  |  | ok_uses_central_api |
| `scripts/run_alex_daily.py` | 1 |  |  |  | ok_uses_central_api |
| `scripts/run_proactive_quote_refresh.py` | 1 |  |  |  | ok_uses_central_api |
| `scripts/run_telegram_callback_poller.py` | 6 | yes |  | yes | central_component |
| `scripts/scalp_critic_agent.py` | 4 |  |  | yes | migrate_to_send_telegram |
| `scripts/scalp_outcome_scorer.py` | 1 |  |  |  | ok_uses_central_api |
| `scripts/send_alert_digest.py` | 1 |  |  |  | ok_uses_central_api |
| `scripts/send_closed_trade_digest.py` | 6 |  | YES |  | review_bypass_usage |
| `scripts/send_morning_brief.py` | 6 |  |  | yes | review_for_migration |
| `scripts/send_no_leads_diagnostic_alert.py` | 5 |  |  | yes | migrate_to_send_telegram |
| `scripts/send_screener_schedule_health_alert.py` | 1 |  |  |  | ok_uses_central_api |
| `scripts/send_telegram_proposal_alert.py` | 7 |  |  | yes | review_for_migration |
| `scripts/send_watchpool_maturity_alerts.py` | 5 |  |  | yes | migrate_to_send_telegram |
| `scripts/simulate_alert_routing.py` | 1 |  |  |  | ok_uses_central_api |
| `scripts/social_scalp_scanner.py` | 2 |  |  |  | ok_uses_central_api |
| `scripts/stop_decision_brief.py` | 2 |  |  | yes | migrate_to_send_telegram |
| `scripts/strategy_weekly_review.py` | 4 |  |  |  | ok_uses_central_api |
| `scripts/system_health_agent.py` | 2 |  | YES |  | review_bypass_usage |
| `scripts/system_health_alerts.py` | 5 |  |  | yes | review_for_migration |
| `scripts/telegram_alert.py` | 13 | yes |  | yes | central_component |
| `scripts/telegram_alert_router.py` | 2 | yes |  |  | central_component |
| `scripts/telegram_callback_handler.py` | 3 | yes |  | yes | central_component |
| `scripts/telegram_cio_summary.py` | 1 | yes |  |  | central_component |
| `scripts/telegram_command_handler.py` | 6 | yes |  | yes | central_component |
| `scripts/telegram_reply_processor.py` | 3 | yes |  | yes | central_component |
| `scripts/telegram_smart_alerts.py` | 1 | yes |  |  | central_component |
| `scripts/topic_curator.py` | 4 |  |  | yes | review_for_migration |
| `scripts/topic_ingestion.py` | 4 |  |  | yes | review_for_migration |
| `scripts/trade_ai_health.py` | 2 |  |  |  | review_for_migration |
| `scripts/trade_ai_news_monitor.py` | 3 |  |  | yes | migrate_to_send_telegram |
| `scripts/weekly_learning_digest_delivery.py` | 3 |  |  |  | ok_uses_central_api |
| `scripts/weekly_summary_local.py` | 6 |  |  | yes | review_for_migration |
| `scripts/youtube_backfill_manager.py` | 1 |  |  |  | ok_uses_central_api |
| `scripts/youtube_transcript_ingest.py` | 1 |  |  |  | ok_uses_central_api |
| `scripts/cron_wrapper.sh` | 3 |  |  | yes | migrate_to_send_telegram |
| `scripts/telegram_poller_watchdog.sh` | 2 | yes |  | yes | central_component |
