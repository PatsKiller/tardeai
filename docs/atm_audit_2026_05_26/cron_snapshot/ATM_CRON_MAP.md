# ATM Cron Map — Audit 2026-05-26

Status:      HISTORICAL
as_of:       2026-05-26T11:21:21-04:00
Measured at: efcc51365 / not measured

Generated from live crontab. 181 active jobs total.

## Key ATM/Pipeline Jobs

| Schedule | Script | Flock | Log | Max Runtime | Downstream | Critical | Monitored |
|----------|--------|-------|-----|-------------|------------|----------|-----------|
| `45 7,10,12,13,16 * * 1-5` | proactive_quote_refresh | YES | ? | 2min | proposal prices | NO | health_agent |
| `*/2 * * * *` | telegram_command_handler | NO | logs/telegram_commands.log | 1min | operator commands | YES | health_agent |
| `*/5 9-15 * * 1-5` | proactive_quote_refresh | YES | ? | 2min | proposal prices | NO | health_agent |
| `0 10 * * 1-5` | cleanup_stale_proposals | NO | logs/cleanup_stale_proposals.log | 1min | proposal hygiene | NO | health_agent |
| `0 10 * * 1-5` | finviz_screener_runner | NO | logs/finviz_screener.log | 10min | scanner input data | YES | health_agent |
| `0 12 * * 1-5` | proactive_quote_refresh | YES | ? | 2min | proposal prices | NO | health_agent |
| `0 12 * * 1-5` | finviz_screener_runner | YES | logs/finviz_screener.log | 10min | scanner input data | YES | health_agent |
| `0 9 * * 1-5` | trade_ai_orchestrator | YES | logs/screener_pm.log | 10min | strategy_signals, proposals, ATM | YES | health_agent |
| `0 10 * * 1-5` | trade_ai_orchestrator | YES | logs/screener_pm.log | 10min | strategy_signals, proposals, ATM | YES | health_agent |
| `0 12 * * 1-5` | trade_ai_orchestrator | YES | logs/screener_pm.log | 10min | strategy_signals, proposals, ATM | YES | health_agent |
| `0 14 * * 1-5` | finviz_screener_runner | YES | logs/finviz_screener.log | 10min | scanner input data | YES | health_agent |
| `0 14 * * 1-5` | trade_ai_orchestrator | YES | logs/screener_pm.log | 10min | strategy_signals, proposals, ATM | YES | health_agent |
| `0 15 * * 1-5` | cleanup_stale_proposals | NO | logs/cleanup_stale_proposals.log | 1min | proposal hygiene | NO | health_agent |
| `0 16 * * 1-5` | finviz_screener_runner | NO | logs/finviz_screener.log | 10min | scanner input data | YES | health_agent |
| `0 16 * * 1-5` | trade_ai_orchestrator | YES | logs/screener_pm.log | 10min | strategy_signals, proposals, ATM | YES | health_agent |
| `0 18 * * 1-5` | finviz_screener_runner | YES | logs/finviz_screener.log | 10min | scanner input data | YES | health_agent |
| `0 6 * * 1-5` | proactive_quote_refresh | YES | ? | 2min | proposal prices | NO | health_agent |
| `0 7 * * 1-5` | finviz_screener_runner | YES | logs/finviz_screener.log | 10min | scanner input data | YES | health_agent |
| `0 7 * * 1-5` | proactive_quote_refresh | YES | ? | 2min | proposal prices | NO | health_agent |
| `0 7,8,9,10,11,12,13,14,15,16,17 * * 1-5` | incubator_proposal_promoter | YES | logs/incubator_promoter.log | 5min | incubator to proposals | YES | health_agent |
| `0 8 * * 1-5` | finviz_screener_runner | YES | logs/finviz_screener.log | 10min | scanner input data | YES | health_agent |
| `0 8 * * 1-5` | proactive_quote_refresh | YES | ? | 2min | proposal prices | NO | health_agent |
| `20 9 * * 1-5` | proactive_quote_refresh | YES | ? | 2min | proposal prices | NO | health_agent |
| `30 15 * * 1-5` | proactive_quote_refresh | YES | ? | 2min | proposal prices | NO | health_agent |
| `30 17 * * 1-5` | trade_ai_orchestrator | YES | logs/screener_pm.log | 10min | strategy_signals, proposals, ATM | YES | health_agent |
| `30 6 * * 1-5` | proactive_quote_refresh | YES | ? | 2min | proposal prices | NO | health_agent |
| `30 7 * * 1-5` | proactive_quote_refresh | YES | ? | 2min | proposal prices | NO | health_agent |
| `30 8 * * 1-5` | proactive_quote_refresh | YES | ? | 2min | proposal prices | NO | health_agent |
| `*/2 9-16 * * 1-5` | send_telegram_proposal_alert | NO | logs/proposal_alerts.log | 1min | proposal notifications | NO | health_agent |
| `*/3 9-16 * * 1-5` | unified_stop_supervisor | YES | logs/unified_stop_supervisor.log | 2min | trailing stops, target exits | YES | health_agent |
| `*/15 7-9 * * 1-5` | premarket_watcher | NO | logs/premarket_watcher.log | 5min | pre-market catalysts | NO | health_agent |
| `0 */2 * * *` | pipeline_watchdog | NO | logs/pipeline_watchdog.log | 5min | pipeline self-healing | YES | health_agent |
| `30 8,16 * * *` | alert_dispatcher | NO | logs/alert_dispatcher.log | 1min | Telegram alerts | NO | health_agent |
| `*/30 9-16 * * 1-5` | auto_proposal_generator | NO | logs/auto_proposal.log | 5min | proposals, ATM execution | YES | health_agent |
| `30 16 * * 1-5` | paper_execution_quality_analyzer | NO | logs/tca_analyzer.log | 1min | TCA page | NO | health_agent |
| `0 17 * * 1-5` | paper_execution_quality | NO | logs/tca_events.log | 1min | TCA events | NO | health_agent |
| `*/5 9-20 * * 1-5` | system_health_agent | NO | logs/system_health_agent.log | 5min | execution integrity monitoring | YES | health_agent |
| `*/15 * * * 0,6` | system_health_agent | NO | logs/system_health_agent.log | 5min | execution integrity monitoring | YES | health_agent |
| `0 7 * * 1-5` | system_health_agent | NO | logs/system_health_agent.log | 5min | execution integrity monitoring | YES | health_agent |

## Full Crontab Stats
- Active jobs: 181
- Commented-out jobs: 2
- Jobs using safe_flock: 13
- Jobs using flock: 51
- Jobs with market_day_gate: 14