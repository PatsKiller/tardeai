# Direct Telegram Sender Audit

Status:      HISTORICAL
as_of:       2026-08-11T09:45:10-04:00
Measured at: efcc51365 / not measured

**Generated:** 2026-08-10T22:33:38.136997+00:00
**Total files with Telegram references:** 161
**Approved central components:** 10
**Bypass risk files:** 36
**Direct API (non-central):** 48
**Migration candidates:** 51

## Bypass Risk Files

- `scripts/alert_daily_digest.py` — 2 refs, recommendation: review_bypass_usage
- `scripts/alert_outbox.py` — 3 refs, recommendation: review_bypass_usage
- `scripts/alpaca_live_read_sync.py` — 2 refs, recommendation: review_bypass_usage
- `scripts/alpaca_stop_manager.py` — 6 refs, recommendation: review_bypass_usage
- `scripts/api_v2.py` — 5 refs, recommendation: review_bypass_usage
- `scripts/audit_direct_telegram_senders.py` — 7 refs, recommendation: review_bypass_usage
- `scripts/defense_execution.py` — 2 refs, recommendation: review_bypass_usage
- `scripts/defense_weekly_paid_review.py` — 2 refs, recommendation: review_bypass_usage
- `scripts/eod_open_trade_alert.py` — 5 refs, recommendation: review_bypass_usage
- `scripts/finviz_industry_groups.py` — 2 refs, recommendation: review_bypass_usage
- `scripts/hermes_backlog_drain.py` — 2 refs, recommendation: review_bypass_usage
- `scripts/interlock_parity_monitor.py` — 2 refs, recommendation: review_bypass_usage
- `scripts/lib/hermes_outcome_bus/alert_notifications.py` — 5 refs, recommendation: review_bypass_usage
- `scripts/moomoo/opend_health.py` — 2 refs, recommendation: review_bypass_usage
- `scripts/morning_command_digest.py` — 2 refs, recommendation: review_bypass_usage
- `scripts/morning_digest.py` — 4 refs, recommendation: review_bypass_usage
- `scripts/oversight_weekly_digest.py` — 2 refs, recommendation: review_bypass_usage
- `scripts/portfolio_monthly_report.py` — 6 refs, recommendation: review_bypass_usage
- `scripts/portfolio_monthly_synthesis.py` — 4 refs, recommendation: review_bypass_usage
- `scripts/portfolio_weekly_report.py` — 6 refs, recommendation: review_bypass_usage
- `scripts/schwab_auto_reauth.py` — 2 refs, recommendation: review_bypass_usage
- `scripts/secrets/render_env.py` — 2 refs, recommendation: review_bypass_usage
- `scripts/secrets/rotation_daemon.py` — 2 refs, recommendation: review_bypass_usage
- `scripts/secrets_admin.py` — 3 refs, recommendation: review_bypass_usage
- `scripts/sector_momentum_engine.py` — 2 refs, recommendation: review_bypass_usage
- `scripts/send_closed_trade_digest.py` — 6 refs, recommendation: review_bypass_usage
- `scripts/send_morning_brief.py` — 4 refs, recommendation: review_bypass_usage
- `scripts/send_operator_alert.py` — 2 refs, recommendation: review_bypass_usage
- `scripts/stop_decision_brief.py` — 2 refs, recommendation: review_bypass_usage
- `scripts/system_health_agent.py` — 4 refs, recommendation: review_bypass_usage
- `scripts/system_rollup_snapshot.py` — 2 refs, recommendation: review_bypass_usage
- `scripts/verify_fib_proposals.py` — 2 refs, recommendation: review_bypass_usage
- `scripts/verify_hermes_daily.py` — 2 refs, recommendation: review_bypass_usage
- `scripts/warrior_weekly_audit_cron.py` — 2 refs, recommendation: review_bypass_usage
- `scripts/watch_alerts_eval.py` — 2 refs, recommendation: review_bypass_usage
- `scripts/weekly_summary_local.py` — 4 refs, recommendation: review_bypass_usage

## Direct API (Non-Central)

- `scripts/alert_dispatcher_unified.py` — 4 refs, recommendation: review_for_migration
- `scripts/atm_auto_approver.py` — 4 refs, recommendation: review_for_migration
- `scripts/audit_direct_telegram_senders.py` — 7 refs, recommendation: review_bypass_usage
- `scripts/audit_enrichment_coverage.py` — 4 refs, recommendation: migrate_to_send_telegram
- `scripts/audit_position_basis.py` — 8 refs, recommendation: migrate_to_send_telegram
- `scripts/brokers/approval_service.py` — 5 refs, recommendation: migrate_to_send_telegram
- `scripts/check_telegram_chokepoint.py` — 7 refs, recommendation: review_for_migration
- `scripts/crawl_v3_dashboard.py` — 5 refs, recommendation: review_for_migration
- `scripts/defense_engine_gap_checker.py` — 4 refs, recommendation: migrate_to_send_telegram
- `scripts/freshness_watchdog_heartbeat.py` — 2 refs, recommendation: migrate_to_send_telegram
- `scripts/full_system_backup.py` — 2 refs, recommendation: migrate_to_send_telegram
- `scripts/generate_max_hold_exit_proposals.py` — 4 refs, recommendation: migrate_to_send_telegram
- `scripts/intel_table_staleness_monitor.py` — 2 refs, recommendation: migrate_to_send_telegram
- `scripts/iris_taxonomy_agent.py` — 2 refs, recommendation: migrate_to_send_telegram
- `scripts/lib/cio_notification_delivery.py` — 2 refs, recommendation: migrate_to_send_telegram
- `scripts/open_trade_monitor.py` — 16 refs, recommendation: review_for_migration
- `scripts/options_lifecycle_alerts.py` — 5 refs, recommendation: review_for_migration
- `scripts/overnight_batch.py` — 3 refs, recommendation: review_for_migration
- `scripts/phase3_lookthrough_fetcher.py` — 2 refs, recommendation: migrate_to_send_telegram
- `scripts/pipeline_alert.py` — 2 refs, recommendation: migrate_to_send_telegram
- `scripts/pipeline_health_monitor.py` — 6 refs, recommendation: review_for_migration
- `scripts/pipeline_watchdog.py` — 7 refs, recommendation: review_for_migration
- `scripts/portfolio_alerts.py` — 11 refs, recommendation: review_for_migration
- `scripts/portfolio_monthly_report.py` — 6 refs, recommendation: review_bypass_usage
- `scripts/portfolio_technical.py` — 4 refs, recommendation: review_for_migration
- `scripts/portfolio_weekly_report.py` — 6 refs, recommendation: review_bypass_usage
- `scripts/premarket_watcher.py` — 6 refs, recommendation: review_for_migration
- `scripts/previously_traded_watchlist.py` — 4 refs, recommendation: migrate_to_send_telegram
- `scripts/pro_analyst_monitor.py` — 2 refs, recommendation: migrate_to_send_telegram
- `scripts/proposal_alerter.py` — 8 refs, recommendation: review_for_migration
- `scripts/protection_alerts.py` — 2 refs, recommendation: migrate_to_send_telegram
- `scripts/schwab_position_sync.py` — 4 refs, recommendation: migrate_to_send_telegram
- `scripts/schwab_token_manager.py` — 4 refs, recommendation: migrate_to_send_telegram
- `scripts/secret_validators.py` — 2 refs, recommendation: migrate_to_send_telegram
- `scripts/secrets/rotation_probes.py` — 2 refs, recommendation: migrate_to_send_telegram
- `scripts/send_no_leads_diagnostic_alert.py` — 5 refs, recommendation: migrate_to_send_telegram
- `scripts/send_telegram_proposal_alert.py` — 7 refs, recommendation: review_for_migration
- `scripts/send_watchpool_maturity_alerts.py` — 5 refs, recommendation: migrate_to_send_telegram
- `scripts/system_freshness_monitor.py` — 2 refs, recommendation: migrate_to_send_telegram
- `scripts/system_health_alerts.py` — 5 refs, recommendation: review_for_migration
- `scripts/technicals_gap_backfill.py` — 4 refs, recommendation: migrate_to_send_telegram
- `scripts/telegram_transport.py` — 3 refs, recommendation: migrate_to_send_telegram
- `scripts/topic_ingestion.py` — 4 refs, recommendation: review_for_migration
- `scripts/trade_ai_news_monitor.py` — 3 refs, recommendation: migrate_to_send_telegram
- `scripts/watch_directives_service.py` — 3 refs, recommendation: migrate_to_send_telegram
- `scripts/watchlist_entry_planner.py` — 4 refs, recommendation: migrate_to_send_telegram
- `scripts/youtube_cookie_health_check.py` — 5 refs, recommendation: review_for_migration
- `scripts/morning_eval_check.sh` — 3 refs, recommendation: migrate_to_send_telegram

## Migration Candidates

- `scripts/active_trader/config_read.py` — review_for_migration
- `scripts/alert_dispatcher_unified.py` — review_for_migration
- `scripts/atm_auto_approver.py` — review_for_migration
- `scripts/audit_enrichment_coverage.py` — migrate_to_send_telegram
- `scripts/audit_position_basis.py` — migrate_to_send_telegram
- `scripts/brokers/approval_service.py` — migrate_to_send_telegram
- `scripts/check_telegram_chokepoint.py` — review_for_migration
- `scripts/crawl_v3_dashboard.py` — review_for_migration
- `scripts/defense_engine_gap_checker.py` — migrate_to_send_telegram
- `scripts/freshness_watchdog_heartbeat.py` — migrate_to_send_telegram
- `scripts/full_system_backup.py` — migrate_to_send_telegram
- `scripts/generate_max_hold_exit_proposals.py` — migrate_to_send_telegram
- `scripts/intel_table_staleness_monitor.py` — migrate_to_send_telegram
- `scripts/iris_taxonomy_agent.py` — migrate_to_send_telegram
- `scripts/lib/cio_notification_delivery.py` — migrate_to_send_telegram
- `scripts/open_trade_monitor.py` — review_for_migration
- `scripts/options_lifecycle_alerts.py` — review_for_migration
- `scripts/overnight_batch.py` — review_for_migration
- `scripts/phase3_lookthrough_fetcher.py` — migrate_to_send_telegram
- `scripts/pipeline_alert.py` — migrate_to_send_telegram
- `scripts/pipeline_health_monitor.py` — review_for_migration
- `scripts/pipeline_watchdog.py` — review_for_migration
- `scripts/portfolio_alerts.py` — review_for_migration
- `scripts/portfolio_server.py` — review_for_migration
- `scripts/portfolio_technical.py` — review_for_migration
- `scripts/premarket_watcher.py` — review_for_migration
- `scripts/previously_traded_watchlist.py` — migrate_to_send_telegram
- `scripts/pro_analyst_monitor.py` — migrate_to_send_telegram
- `scripts/proposal_alerter.py` — review_for_migration
- `scripts/protection_alerts.py` — migrate_to_send_telegram
- `scripts/schwab_position_sync.py` — migrate_to_send_telegram
- `scripts/schwab_token_manager.py` — migrate_to_send_telegram
- `scripts/secret_validators.py` — migrate_to_send_telegram
- `scripts/secrets/rotate.py` — review_for_migration
- `scripts/secrets/rotation_probes.py` — migrate_to_send_telegram
- `scripts/send_no_leads_diagnostic_alert.py` — migrate_to_send_telegram
- `scripts/send_telegram_proposal_alert.py` — review_for_migration
- `scripts/send_watchpool_maturity_alerts.py` — migrate_to_send_telegram
- `scripts/system_freshness_monitor.py` — migrate_to_send_telegram
- `scripts/system_health_alerts.py` — review_for_migration
- `scripts/technicals_gap_backfill.py` — migrate_to_send_telegram
- `scripts/telegram_transport.py` — migrate_to_send_telegram
- `scripts/topic_ingestion.py` — review_for_migration
- `scripts/trade_ai_health.py` — review_for_migration
- `scripts/trade_ai_news_monitor.py` — migrate_to_send_telegram
- `scripts/watch_directives_service.py` — migrate_to_send_telegram
- `scripts/watchlist_entry_planner.py` — migrate_to_send_telegram
- `scripts/youtube_cookie_health_check.py` — review_for_migration
- `scripts/check_secret_exposure.sh` — review_for_migration
- `scripts/cron_wrapper.sh` — review_for_migration
- `scripts/morning_eval_check.sh` — migrate_to_send_telegram

## All Files

| File | Refs | Central | Bypass | Direct API | Recommendation |
|------|------|---------|--------|------------|----------------|
| `scripts/active_trader/config_read.py` | 1 |  |  |  | review_for_migration |
| `scripts/aegis_morning_brief_delivery.py` | 2 |  |  |  | ok_uses_central_api |
| `scripts/aegis_overnight.py` | 3 |  |  |  | ok_uses_central_api |
| `scripts/agent_event_router.py` | 5 |  |  |  | ok_uses_central_api |
| `scripts/agent_watchlist_engine.py` | 1 |  |  |  | ok_uses_central_api |
| `scripts/alert_daily_digest.py` | 2 |  | YES |  | review_bypass_usage |
| `scripts/alert_dispatcher.py` | 6 |  |  |  | ok_uses_central_api |
| `scripts/alert_dispatcher_unified.py` | 4 |  |  | yes | review_for_migration |
| `scripts/alert_outbox.py` | 3 |  | YES |  | review_bypass_usage |
| `scripts/alerting.py` | 1 |  |  |  | ok_uses_central_api |
| `scripts/alpaca_live_read_sync.py` | 2 |  | YES |  | review_bypass_usage |
| `scripts/alpaca_stop_manager.py` | 6 |  | YES |  | review_bypass_usage |
| `scripts/api_v2.py` | 5 |  | YES |  | review_bypass_usage |
| `scripts/atm_auto_approver.py` | 4 |  |  | yes | review_for_migration |
| `scripts/audit_direct_telegram_senders.py` | 7 |  | YES | yes | review_bypass_usage |
| `scripts/audit_enrichment_coverage.py` | 4 |  |  | yes | migrate_to_send_telegram |
| `scripts/audit_position_basis.py` | 8 |  |  | yes | migrate_to_send_telegram |
| `scripts/auto_research.py` | 1 |  |  |  | ok_uses_central_api |
| `scripts/brokers/approval_service.py` | 5 |  |  | yes | migrate_to_send_telegram |
| `scripts/check_telegram_chokepoint.py` | 7 |  |  | yes | review_for_migration |
| `scripts/claude_escalation_handler.py` | 1 |  |  |  | ok_uses_central_api |
| `scripts/cloud_consensus_verdict.py` | 4 |  |  |  | ok_uses_central_api |
| `scripts/continuous_runner.py` | 1 |  |  |  | ok_uses_central_api |
| `scripts/crawl_v3_dashboard.py` | 5 |  |  | yes | review_for_migration |
| `scripts/credential_monitor.py` | 1 |  |  |  | ok_uses_central_api |
| `scripts/defense_engine_gap_checker.py` | 4 |  |  | yes | migrate_to_send_telegram |
| `scripts/defense_execution.py` | 2 |  | YES |  | review_bypass_usage |
| `scripts/defense_weekly_paid_review.py` | 2 |  | YES |  | review_bypass_usage |
| `scripts/discover_telegram_chat_id.py` | 3 | yes |  | yes | central_component |
| `scripts/eod_open_trade_alert.py` | 5 |  | YES |  | review_bypass_usage |
| `scripts/finviz_health_check.py` | 1 |  |  |  | ok_uses_central_api |
| `scripts/finviz_industry_groups.py` | 2 |  | YES |  | review_bypass_usage |
| `scripts/finviz_ingestion.py` | 2 |  |  |  | ok_uses_central_api |
| `scripts/freshness_watchdog_heartbeat.py` | 2 |  |  | yes | migrate_to_send_telegram |
| `scripts/full_system_backup.py` | 2 |  |  | yes | migrate_to_send_telegram |
| `scripts/generate_daily_intelligence_report.py` | 1 |  |  |  | ok_uses_central_api |
| `scripts/generate_max_hold_exit_proposals.py` | 4 |  |  | yes | migrate_to_send_telegram |
| `scripts/generate_weekly_docx.py` | 1 |  |  |  | ok_uses_central_api |
| `scripts/health_agent.py` | 1 |  |  |  | ok_uses_central_api |
| `scripts/hermes_backlog_drain.py` | 2 |  | YES |  | review_bypass_usage |
| `scripts/hermes_discovery_ingestors.py` | 1 |  |  |  | ok_uses_central_api |
| `scripts/hermes_score_alerts.py` | 1 |  |  |  | ok_uses_central_api |
| `scripts/incubator_llm_screener.py` | 1 |  |  |  | ok_uses_central_api |
| `scripts/incubator_proposal_promoter.py` | 2 |  |  |  | ok_uses_central_api |
| `scripts/inference_telegram.py` | 1 |  |  |  | ok_uses_central_api |
| `scripts/intel_table_staleness_monitor.py` | 2 |  |  | yes | migrate_to_send_telegram |
| `scripts/interlock_parity_monitor.py` | 2 |  | YES |  | review_bypass_usage |
| `scripts/iris_taxonomy_agent.py` | 2 |  |  | yes | migrate_to_send_telegram |
| `scripts/lib/cio_notification_delivery.py` | 2 |  |  | yes | migrate_to_send_telegram |
| `scripts/lib/gain_guardian_publish.py` | 1 |  |  |  | ok_uses_central_api |
| `scripts/lib/hermes_outcome_bus/alert_notifications.py` | 5 |  | YES |  | review_bypass_usage |
| `scripts/lib/options_pipeline/paper_position_alerts.py` | 3 |  |  |  | ok_uses_central_api |
| `scripts/moomoo/opend_health.py` | 2 |  | YES |  | review_bypass_usage |
| `scripts/morning_command_digest.py` | 2 |  | YES |  | review_bypass_usage |
| `scripts/morning_digest.py` | 4 |  | YES |  | review_bypass_usage |
| `scripts/nightly_integrity_sweep.py` | 1 |  |  |  | ok_uses_central_api |
| `scripts/oauth_lane_keepalive.py` | 1 |  |  |  | ok_uses_central_api |
| `scripts/open_trade_monitor.py` | 16 |  |  | yes | review_for_migration |
| `scripts/options_lifecycle_alerts.py` | 5 |  |  | yes | review_for_migration |
| `scripts/overnight_batch.py` | 3 |  |  | yes | review_for_migration |
| `scripts/overnight_digest_telegram.py` | 1 |  |  |  | ok_uses_central_api |
| `scripts/oversight_weekly_digest.py` | 2 |  | YES |  | review_bypass_usage |
| `scripts/paper_performance_governance.py` | 1 |  |  |  | ok_uses_central_api |
| `scripts/paper_trade_monitor.py` | 1 |  |  |  | ok_uses_central_api |
| `scripts/phase3_lookthrough_fetcher.py` | 2 |  |  | yes | migrate_to_send_telegram |
| `scripts/pipeline_alert.py` | 2 |  |  | yes | migrate_to_send_telegram |
| `scripts/pipeline_freshness_slo.py` | 1 |  |  |  | ok_uses_central_api |
| `scripts/pipeline_health_monitor.py` | 6 |  |  | yes | review_for_migration |
| `scripts/pipeline_watchdog.py` | 7 |  |  | yes | review_for_migration |
| `scripts/portfolio_alerts.py` | 11 |  |  | yes | review_for_migration |
| `scripts/portfolio_live_monitor.py` | 5 |  |  |  | ok_uses_central_api |
| `scripts/portfolio_monthly_report.py` | 6 |  | YES | yes | review_bypass_usage |
| `scripts/portfolio_monthly_synthesis.py` | 4 |  | YES |  | review_bypass_usage |
| `scripts/portfolio_orchestrator.py` | 2 |  |  |  | ok_uses_central_api |
| `scripts/portfolio_server.py` | 4 |  |  |  | review_for_migration |
| `scripts/portfolio_technical.py` | 4 |  |  | yes | review_for_migration |
| `scripts/portfolio_weekly_report.py` | 6 |  | YES | yes | review_bypass_usage |
| `scripts/post_deploy_smoke_test.py` | 2 |  |  |  | ok_uses_central_api |
| `scripts/premarket_watcher.py` | 6 |  |  | yes | review_for_migration |
| `scripts/previously_traded_watchlist.py` | 4 |  |  | yes | migrate_to_send_telegram |
| `scripts/pro_analyst_monitor.py` | 2 |  |  | yes | migrate_to_send_telegram |
| `scripts/process_reaper.py` | 1 |  |  |  | ok_uses_central_api |
| `scripts/process_watchlist_agent_jobs.py` | 2 |  |  |  | ok_uses_central_api |
| `scripts/proposal_alerter.py` | 8 |  |  | yes | review_for_migration |
| `scripts/proposal_paper_submitter.py` | 2 |  |  |  | ok_uses_central_api |
| `scripts/protection_alerts.py` | 2 |  |  | yes | migrate_to_send_telegram |
| `scripts/pullback_macd_screener.py` | 2 |  |  |  | ok_uses_central_api |
| `scripts/rebalance_verifier.py` | 2 |  |  |  | ok_uses_central_api |
| `scripts/recovery_watch_daily.py` | 2 |  |  |  | ok_uses_central_api |
| `scripts/remediate_weekly_report_action.py` | 1 |  |  |  | ok_uses_central_api |
| `scripts/rerun_cio_dual_consensus.py` | 1 |  |  |  | ok_uses_central_api |
| `scripts/research_intelligence_queue.py` | 1 |  |  |  | ok_uses_central_api |
| `scripts/research_scheduler.py` | 1 |  |  |  | ok_uses_central_api |
| `scripts/rotation_autopilot.py` | 1 |  |  |  | ok_uses_central_api |
| `scripts/rotation_rebalance_digest.py` | 1 |  |  |  | ok_uses_central_api |
| `scripts/run_alex_daily.py` | 1 |  |  |  | ok_uses_central_api |
| `scripts/run_paper_canary_chain.py` | 1 |  |  |  | ok_uses_central_api |
| `scripts/run_proactive_quote_refresh.py` | 1 |  |  |  | ok_uses_central_api |
| `scripts/run_telegram_callback_poller.py` | 8 | yes |  | yes | central_component |
| `scripts/scalp_critic_agent.py` | 2 |  |  |  | ok_uses_central_api |
| `scripts/scalp_outcome_scorer.py` | 1 |  |  |  | ok_uses_central_api |
| `scripts/schwab_auto_reauth.py` | 2 |  | YES |  | review_bypass_usage |
| `scripts/schwab_position_sync.py` | 4 |  |  | yes | migrate_to_send_telegram |
| `scripts/schwab_token_manager.py` | 4 |  |  | yes | migrate_to_send_telegram |
| `scripts/secret_validators.py` | 2 |  |  | yes | migrate_to_send_telegram |
| `scripts/secrets/render_env.py` | 2 |  | YES |  | review_bypass_usage |
| `scripts/secrets/rotate.py` | 1 |  |  |  | review_for_migration |
| `scripts/secrets/rotation_daemon.py` | 2 |  | YES |  | review_bypass_usage |
| `scripts/secrets/rotation_probes.py` | 2 |  |  | yes | migrate_to_send_telegram |
| `scripts/secrets_admin.py` | 3 |  | YES |  | review_bypass_usage |
| `scripts/sector_momentum_engine.py` | 2 |  | YES |  | review_bypass_usage |
| `scripts/send_alert_digest.py` | 1 |  |  |  | ok_uses_central_api |
| `scripts/send_closed_trade_digest.py` | 6 |  | YES |  | review_bypass_usage |
| `scripts/send_morning_brief.py` | 4 |  | YES |  | review_bypass_usage |
| `scripts/send_no_leads_diagnostic_alert.py` | 5 |  |  | yes | migrate_to_send_telegram |
| `scripts/send_operator_alert.py` | 2 |  | YES |  | review_bypass_usage |
| `scripts/send_screener_schedule_health_alert.py` | 1 |  |  |  | ok_uses_central_api |
| `scripts/send_telegram_proposal_alert.py` | 7 |  |  | yes | review_for_migration |
| `scripts/send_watchpool_maturity_alerts.py` | 5 |  |  | yes | migrate_to_send_telegram |
| `scripts/siem_critical_notify.py` | 1 |  |  |  | ok_uses_central_api |
| `scripts/simulate_alert_routing.py` | 1 |  |  |  | ok_uses_central_api |
| `scripts/social_scalp_scanner.py` | 3 |  |  |  | ok_uses_central_api |
| `scripts/stop_decision_brief.py` | 2 |  | YES |  | review_bypass_usage |
| `scripts/stop_drift_alert.py` | 1 |  |  |  | ok_uses_central_api |
| `scripts/stop_health_check.py` | 4 |  |  |  | ok_uses_central_api |
| `scripts/stop_over_consensus_monitor.py` | 1 |  |  |  | ok_uses_central_api |
| `scripts/strategy_weekly_review.py` | 4 |  |  |  | ok_uses_central_api |
| `scripts/system_freshness_monitor.py` | 2 |  |  | yes | migrate_to_send_telegram |
| `scripts/system_health_agent.py` | 4 |  | YES |  | review_bypass_usage |
| `scripts/system_health_alerts.py` | 5 |  |  | yes | review_for_migration |
| `scripts/system_rollup_snapshot.py` | 2 |  | YES |  | review_bypass_usage |
| `scripts/technicals_gap_backfill.py` | 4 |  |  | yes | migrate_to_send_telegram |
| `scripts/telegram_alert.py` | 19 | yes |  | yes | central_component |
| `scripts/telegram_alert_router.py` | 2 | yes |  |  | central_component |
| `scripts/telegram_callback_handler.py` | 3 | yes |  | yes | central_component |
| `scripts/telegram_cio_summary.py` | 1 | yes |  |  | central_component |
| `scripts/telegram_command_handler.py` | 12 | yes |  | yes | central_component |
| `scripts/telegram_reply_processor.py` | 3 | yes |  | yes | central_component |
| `scripts/telegram_smart_alerts.py` | 1 | yes |  |  | central_component |
| `scripts/telegram_transport.py` | 3 |  |  | yes | migrate_to_send_telegram |
| `scripts/topic_curator.py` | 3 |  |  |  | ok_uses_central_api |
| `scripts/topic_ingestion.py` | 4 |  |  | yes | review_for_migration |
| `scripts/trade_ai_health.py` | 2 |  |  |  | review_for_migration |
| `scripts/trade_ai_news_monitor.py` | 3 |  |  | yes | migrate_to_send_telegram |
| `scripts/update_docx_reports_portal_20260616.py` | 2 |  |  |  | ok_uses_central_api |
| `scripts/verify_fib_proposals.py` | 2 |  | YES |  | review_bypass_usage |
| `scripts/verify_hermes_daily.py` | 2 |  | YES |  | review_bypass_usage |
| `scripts/warrior_weekly_audit_cron.py` | 2 |  | YES |  | review_bypass_usage |
| `scripts/watch_alerts_eval.py` | 2 |  | YES |  | review_bypass_usage |
| `scripts/watch_directive_hygiene.py` | 1 |  |  |  | ok_uses_central_api |
| `scripts/watch_directives_service.py` | 3 |  |  | yes | migrate_to_send_telegram |
| `scripts/watchlist_entry_planner.py` | 4 |  |  | yes | migrate_to_send_telegram |
| `scripts/weekly_learning_digest_delivery.py` | 3 |  |  |  | ok_uses_central_api |
| `scripts/weekly_summary_local.py` | 4 |  | YES |  | review_bypass_usage |
| `scripts/youtube_backfill_manager.py` | 1 |  |  |  | ok_uses_central_api |
| `scripts/youtube_cookie_health_check.py` | 5 |  |  | yes | review_for_migration |
| `scripts/youtube_transcript_ingest.py` | 1 |  |  |  | ok_uses_central_api |
| `scripts/check_secret_exposure.sh` | 1 |  |  |  | review_for_migration |
| `scripts/cron_wrapper.sh` | 1 |  |  |  | review_for_migration |
| `scripts/morning_eval_check.sh` | 3 |  |  | yes | migrate_to_send_telegram |
| `scripts/telegram_poller_watchdog.sh` | 1 | yes |  |  | central_component |
