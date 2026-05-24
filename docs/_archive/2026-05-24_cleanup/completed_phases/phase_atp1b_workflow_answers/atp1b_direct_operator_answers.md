# ATP-1B — Direct Operator Answers

## What runs after close (16:00-18:00)?

| Time | Script | Purpose | Creates proposals? |
|------|--------|---------|-------------------|
| 16:00 | finviz_screener_runner.py | Full FinViz screener ingestion | No |
| 16:00 | trade_ai_orchestrator.py --run-label 1600 | Afternoon pipeline (scoring, signals) | No (--no-alerts) |
| 16:00 | send_alert_digest.py evening | Evening digest | No |
| 16:05 | market_regime_collector.py + classifier | EOD regime snapshot | No |
| 16:05 | alpaca_paper_reconciler.py | Broker position reconciliation | No |
| 16:10 | stale_proposal_sweeper.sh --report-only | EOD stale report | No |
| 16:30 | run_closed_trade_digest_cron.sh | Closed trade lesson digest | No |
| 17:30 | trade_ai_orchestrator.py --run-label 1730 --allow-underfilled | Narrow cleanup pass (6 symbols typical) | No |
| 17:30 | run_afterhours_candidate_preparation.sh | Full catalog readiness snapshot (1,311 symbols) | No (snapshot only) |
| 18:00 | finviz_screener_runner.py | Full FinViz screener ingestion | No |
| 18:00 | data_gap_resolver.py --pre-overnight | Data gap sweep | No |
| 18:30 | news_ingestion.py --priority | Evening news ingestion | No |

## What runs overnight (20:00-05:00)?

| Time | Script | Purpose |
|------|--------|---------|
| 20:00 | overnight_batch.py --telegram | Metrics, stale refresh, agent perf | 
| 20:00 | sec_data_ingest.py --all | SEC Form 4 filings |
| 20:00 | paper_performance_governance.py | Governance population |
| 20:30 | feedback_loop_processor.py | Proposal chains, alert scoring |
| 21:00 | auto_research.py | Agent-triggered research |
| 21:30 | gemma3_calibration_scorer.py | Overnight prediction scoring |
| 23:00 | run_deep_overnight_llm_window.sh | Deep LLM queue processing (gemma3) |
| 00:00-05:00 | process_watchlist_agent_jobs.py (every 5m) | Overnight agent job backlog clearing |
| 02:30 | populate_performance_context.py | Strategy YAML performance blocks |
| 03:00 | strategy_config_loader.py --sync-db | Strategy YAML->DB sync |

## What runs premarket (04:00-08:00)?

| Time | Script | Purpose |
|------|--------|---------|
| 05:00 | run_alex_daily.py --daily | Alex daily scan |
| 06:00 | telegram_smart_alerts.py --check-all | Smart proactive alerts |
| 06:15 | agent_router_cron.sh full | Full agent context refresh |
| 06:25 | agent_intelligence_cron.sh daily | Agent discovery |
| 06:30 | news_ingestion.py --priority | Morning news |
| 06:30 | market_regime_collector.py | Pre-market regime |
| 06:35 | classify_candidates.py | Candidate classification |
| 06:40 | intel_auto_discovery.py | Intel-based ticker discovery |
| 06:45 | sync_watchlist_items_to_db.py | Watchlist sync |
| 06:50 | materialize_watchlist_strategy_cards.py | Strategy cards |
| 06:55 | materialize_income_engine.py | Income engine |
| 07:00 | finviz_screener_runner.py | Morning FinViz screener |
| 07:00 | cio_decision_engine.py | CIO decisions |
| 07:00 | incubator_proposal_promoter.py | **Promotes incubator -> proposals** |
| 07:05 | sync_dividend_data.py | Dividend data |
| 07:10 | finviz_enrichment.py | FinViz enrichment |
| 07:15 | external_market_data_ingest.py --quotes | yfinance quotes |
| 07:15 | portfolio_orchestrator.py | Portfolio digest |
| 07:20 | llm_intelligence_enrichment.py | LLM portfolio risk/rebalance |
| 07:25 | system_health_alerts.py | Health check |
| 07:30 | recovery_watch_daily.py | Stop-out detection |
| 07:30 | alert_missing_conditions.py | Missing conditions |
| 07:40 | portfolio_level_qa.py | Portfolio QA |
| 07:50 | record_decision_outcome.py | Decision tracking |

## What runs at market open (08:00-09:35)?

| Time | Script | Purpose | Creates proposals? |
|------|--------|---------|-------------------|
| 08:00 | finviz_screener_runner.py | Market-open screener | No |
| 08:00 | send_morning_brief.py | **Morning brief to operator** | No |
| 08:00 | iterate_research_topics.py | Research topics | No |
| 08:05 | aegis_morning_brief_delivery.py | Aegis brief | No |
| 08:15-08:25 | stale_proposal_sweeper.sh | Pre-market stale sweep | Cleans old proposals |
| 09:00-15:00 | quote_refresh every 5m | **Execution-eligible quote refresh** | No |
| 09:00-16:00 | paper_execution_sweep.py every 5m | **Executes approved proposals** | Trades from approved |
| 09:00-16:00 | paper_trade_monitor.py every 5m | Trailing stops, profit targets | No |
| 09:00-16:00 | open_trade_monitor.py every 15m | Near-stop/target alerts | No |
| 09:20 | quote_refresh --mode incubator | Incubator quote refresh | No |
| 09:35 | watchpool_alerts --mode maturity | Watchpool maturity check | No |
| 09:35 | alpaca_paper_reconciler.py | Open reconciliation | No |

## What creates Automated Trade Proposals?

| Script | Frequency | Mechanism |
|--------|-----------|-----------|
| incubator_proposal_promoter.py | Hourly 07-17 M-F | Promotes incubator candidates to proposals |
| trade_ai_orchestrator.py | At 12/14/16/17:30 | auto_proposals step creates from GO scans |
| auto_proposal_generator.py | Called by orchestrator | Generates proposals from scored signals |

## What revalidates proposals every 30 minutes?

Currently: **paper_execution_sweep.py (every 5m)** checks approved proposals for execution.
**open_trade_monitor.py (every 15m)** monitors open positions.
**Missing: dedicated 30-minute proposal revalidation** for quote drift, R:R validity, spread checks on pending proposals.

## What requires execution-eligible quotes?

- paper_execution_sweep.py (Alpaca)
- paper_trade_monitor.py (Alpaca)
- alpaca_paper_reconciler.py (Alpaca)
- run_scheduled_quote_refresh.sh (Alpaca/Polygon)
- pre_promotion_readiness_policy.py (PROMOTE-1 gate)

## What uses research-only providers?

- finviz_screener_runner.py (FinViz)
- finviz_enrichment.py (FinViz)
- news_ingestion.py (web)
- external_market_data_ingest.py (yfinance)
- classify_candidates.py (internal scoring)
- strategy-fit audit (internal)
- afterhours_candidate_preparation (internal)

## Why the current "zero pending" state exists

1. The 17:30 run scanned only 6 symbols (narrow cleanup pass with `--allow-underfilled`)
2. Auto proposals are skipped when underfilled
3. The real candidate pipeline runs at 14:00 (827 symbols) and 16:00
4. The incubator_proposal_promoter runs hourly but most candidates fail:
   - Spread too wide (SIF 34.5%, EZGO 32.8%, BCHT 10.9%)
   - Only 1-2 promotions per cycle
5. After-hours readiness shows 39 candidates ready for review, but they need market-open execution check

## Is the current installed cron sufficient?

**No.** Gaps:
1. No dedicated after-close broad research run (the 17:30 orchestrator is narrow)
2. No overnight technical/Fib/context enrichment
3. No 4 AM premarket gap scan
4. No dedicated 30-minute proposal revalidation
5. No pre-open readiness check at 9:20
6. The afterhours_candidate_preparation cron (17:30) is new and covers the readiness snapshot, but doesn't drive screener ingestion
