# Pipeline Stage Actionability Audit

**Generated:** 2026-05-20T13:08:37.811405+00:00
**Total stages:** 31

## Classification Summary

| Classification | Count |
|---|---|
| ACTIONABLE | 6 |
| ON_DEMAND | 2 |
| PARTIALLY_ACTIONABLE | 23 |

## Never-Run Subtypes

| Subtype | Count |
|---|---|
| never_run_cron_missing | 16 |
| never_run_on_demand | 2 |
| never_run_waiting_for_schedule | 13 |

## By Category

| Category | Total | Actionable | Partial | Not Actionable | On-Demand |
|---|---|---|---|---|---|
| Data Collection | 5 | 2 | 3 | 0 | 0 |
| Enrichment | 4 | 1 | 3 | 0 | 0 |
| Scoring | 4 | 0 | 4 | 0 | 0 |
| Intelligence | 4 | 2 | 2 | 0 | 0 |
| Proposal Pipeline | 6 | 0 | 6 | 0 | 0 |
| Execution | 4 | 0 | 2 | 0 | 2 |
| Overnight | 4 | 1 | 3 | 0 | 0 |

## Per-Stage Details

### [OK] Finviz Screener (`finviz_screener_runner`)
- **Category:** Data Collection
- **Score:** 80/100 -- ACTIONABLE
- **Owner:** `scripts/finviz_screener_runner.py` | owner_known=True
- **Cron:** 6:35 AM M-F (via classify pipeline) | cron_found=True
- **Telemetry:** run_count=0 | last_status=None | last_run=None
- **Log on disk:** True
- **Safe action:** True
- **Never-run subtype:** never_run_waiting_for_schedule

### [PARTIAL] Social Ingest (`social_ingest`)
- **Category:** Data Collection
- **Score:** 60/100 -- PARTIALLY_ACTIONABLE
- **Owner:** `scripts/social_ingest.py` | owner_known=True
- **Cron:** 7:15 AM M-F | cron_found=False
- **Telemetry:** run_count=0 | last_status=None | last_run=None
- **Log on disk:** True
- **Safe action:** True
- **Never-run subtype:** never_run_cron_missing

### [OK] News Ingestion (`news_ingestion`)
- **Category:** Data Collection
- **Score:** 80/100 -- ACTIONABLE
- **Owner:** `scripts/news_ingestion.py` | owner_known=True
- **Cron:** 6:30 AM M-F | cron_found=True
- **Telemetry:** run_count=0 | last_status=None | last_run=None
- **Log on disk:** True
- **Safe action:** True
- **Never-run subtype:** never_run_waiting_for_schedule

### [PARTIAL] FRED Data Ingest (`fred_data_ingest`)
- **Category:** Data Collection
- **Score:** 40/100 -- PARTIALLY_ACTIONABLE
- **Owner:** `scripts/fred_data_ingest.py` | owner_known=True
- **Cron:** 7:20 AM M-F | cron_found=False
- **Telemetry:** run_count=0 | last_status=None | last_run=None
- **Log on disk:** False
- **Safe action:** True
- **Never-run subtype:** never_run_cron_missing

### [PARTIAL] SEC Data Ingest (`sec_data_ingest`)
- **Category:** Data Collection
- **Score:** 60/100 -- PARTIALLY_ACTIONABLE
- **Owner:** `scripts/sec_data_ingest.py` | owner_known=True
- **Cron:** 7:25 AM M-F | cron_found=True
- **Telemetry:** run_count=0 | last_status=None | last_run=None
- **Log on disk:** False
- **Safe action:** True
- **Never-run subtype:** never_run_waiting_for_schedule

### [OK] Finviz Enrichment (`finviz_enrichment`)
- **Category:** Enrichment
- **Score:** 80/100 -- ACTIONABLE
- **Owner:** `scripts/finviz_enrichment.py` | owner_known=True
- **Cron:** 7:10 AM M-F | cron_found=True
- **Telemetry:** run_count=0 | last_status=None | last_run=None
- **Log on disk:** True
- **Safe action:** True
- **Never-run subtype:** never_run_waiting_for_schedule

### [PARTIAL] Catalyst Enrichment (`catalyst_enrichment`)
- **Category:** Enrichment
- **Score:** 40/100 -- PARTIALLY_ACTIONABLE
- **Owner:** `scripts/catalyst_enrichment.py` | owner_known=True
- **Cron:** 7:30 AM M-F | cron_found=False
- **Telemetry:** run_count=0 | last_status=None | last_run=None
- **Log on disk:** False
- **Safe action:** True
- **Never-run subtype:** never_run_cron_missing

### [PARTIAL] Symbol Enrichment (`symbol_enrichment`)
- **Category:** Enrichment
- **Score:** 40/100 -- PARTIALLY_ACTIONABLE
- **Owner:** `scripts/symbol_enrichment.py` | owner_known=True
- **Cron:** 7:40 AM M-F | cron_found=False
- **Telemetry:** run_count=0 | last_status=None | last_run=None
- **Log on disk:** False
- **Safe action:** True
- **Never-run subtype:** never_run_cron_missing

### [PARTIAL] RAG Indexer (`rag_indexer`)
- **Category:** Enrichment
- **Score:** 60/100 -- PARTIALLY_ACTIONABLE
- **Owner:** `scripts/rag_indexer.py` | owner_known=True
- **Cron:** 7:50 AM M-F | cron_found=False
- **Telemetry:** run_count=0 | last_status=None | last_run=None
- **Log on disk:** True
- **Safe action:** True
- **Never-run subtype:** never_run_cron_missing

### [PARTIAL] Orchestrator (`trade_ai_orchestrator`)
- **Category:** Scoring
- **Score:** 60/100 -- PARTIALLY_ACTIONABLE
- **Owner:** `scripts/trade_ai_orchestrator.py` | owner_known=True
- **Cron:** 8:00 AM M-F | cron_found=True
- **Telemetry:** run_count=0 | last_status=None | last_run=None
- **Log on disk:** False
- **Safe action:** True
- **Never-run subtype:** never_run_waiting_for_schedule

### [PARTIAL] Indicator Engine (`indicator_engine`)
- **Category:** Scoring
- **Score:** 40/100 -- PARTIALLY_ACTIONABLE
- **Owner:** `scripts/indicator_engine.py` | owner_known=True
- **Cron:** 8:10 AM M-F | cron_found=False
- **Telemetry:** run_count=0 | last_status=None | last_run=None
- **Log on disk:** False
- **Safe action:** True
- **Never-run subtype:** never_run_cron_missing

### [PARTIAL] Premarket Watcher (`premarket_watcher`)
- **Category:** Scoring
- **Score:** 60/100 -- PARTIALLY_ACTIONABLE
- **Owner:** `scripts/premarket_watcher.py` | owner_known=True
- **Cron:** every 5m 6:00-9:30 AM M-F | cron_found=False
- **Telemetry:** run_count=0 | last_status=None | last_run=None
- **Log on disk:** True
- **Safe action:** True
- **Never-run subtype:** never_run_cron_missing

### [PARTIAL] Agent Router (`agent_router`)
- **Category:** Scoring
- **Score:** 60/100 -- PARTIALLY_ACTIONABLE
- **Owner:** `scripts/agent_router.py` | owner_known=True
- **Cron:** 6:15 AM M-F (full), intraday refreshes | cron_found=True
- **Telemetry:** run_count=0 | last_status=None | last_run=None
- **Log on disk:** False
- **Safe action:** True
- **Never-run subtype:** never_run_waiting_for_schedule

### [OK] Agent Jobs Processor (`process_watchlist_agent_jobs`)
- **Category:** Intelligence
- **Score:** 80/100 -- ACTIONABLE
- **Owner:** `scripts/process_watchlist_agent_jobs.py` | owner_known=True
- **Cron:** every 15m M-F | cron_found=True
- **Telemetry:** run_count=0 | last_status=None | last_run=None
- **Log on disk:** True
- **Safe action:** True
- **Never-run subtype:** never_run_waiting_for_schedule

### [PARTIAL] Watchlist Engine (`agent_watchlist_engine`)
- **Category:** Intelligence
- **Score:** 60/100 -- PARTIALLY_ACTIONABLE
- **Owner:** `scripts/agent_watchlist_engine.py` | owner_known=True
- **Cron:** 6:25 AM M-F (daily) | cron_found=True
- **Telemetry:** run_count=0 | last_status=None | last_run=None
- **Log on disk:** False
- **Safe action:** True
- **Never-run subtype:** never_run_waiting_for_schedule

### [OK] CIO Decision Engine (`cio_decision_engine`)
- **Category:** Intelligence
- **Score:** 80/100 -- ACTIONABLE
- **Owner:** `scripts/cio_decision_engine.py` | owner_known=True
- **Cron:** 7:00 AM M-F | cron_found=True
- **Telemetry:** run_count=0 | last_status=None | last_run=None
- **Log on disk:** True
- **Safe action:** True
- **Never-run subtype:** never_run_waiting_for_schedule

### [PARTIAL] Pipeline Watchdog (`pipeline_watchdog`)
- **Category:** Intelligence
- **Score:** 60/100 -- PARTIALLY_ACTIONABLE
- **Owner:** `scripts/pipeline_watchdog.py` | owner_known=True
- **Cron:** every 5m M-F | cron_found=False
- **Telemetry:** run_count=0 | last_status=None | last_run=None
- **Log on disk:** True
- **Safe action:** True
- **Never-run subtype:** never_run_cron_missing

### [PARTIAL] Weekly Incubator Builder (`weekly_incubator_builder`)
- **Category:** Proposal Pipeline
- **Score:** 40/100 -- PARTIALLY_ACTIONABLE
- **Owner:** `scripts/weekly_incubator_builder.py` | owner_known=True
- **Cron:** Sunday 8 PM | cron_found=False
- **Telemetry:** run_count=0 | last_status=None | last_run=None
- **Log on disk:** False
- **Safe action:** True
- **Never-run subtype:** never_run_cron_missing

### [PARTIAL] Daily Incubator Refresh (`daily_incubator_refresh`)
- **Category:** Proposal Pipeline
- **Score:** 40/100 -- PARTIALLY_ACTIONABLE
- **Owner:** `scripts/daily_incubator_refresh.py` | owner_known=True
- **Cron:** 8:00 AM M-F | cron_found=False
- **Telemetry:** run_count=0 | last_status=None | last_run=None
- **Log on disk:** False
- **Safe action:** True
- **Never-run subtype:** never_run_cron_missing

### [PARTIAL] Incubator Rolloff Engine (`incubator_rolloff_engine`)
- **Category:** Proposal Pipeline
- **Score:** 40/100 -- PARTIALLY_ACTIONABLE
- **Owner:** `scripts/incubator_rolloff_engine.py` | owner_known=True
- **Cron:** 8:15 AM M-F | cron_found=False
- **Telemetry:** run_count=0 | last_status=None | last_run=None
- **Log on disk:** False
- **Safe action:** True
- **Never-run subtype:** never_run_cron_missing

### [PARTIAL] Proposal Promoter (`incubator_proposal_promoter`)
- **Category:** Proposal Pipeline
- **Score:** 60/100 -- PARTIALLY_ACTIONABLE
- **Owner:** `scripts/incubator_proposal_promoter.py` | owner_known=True
- **Cron:** 8:30 AM M-F | cron_found=True
- **Telemetry:** run_count=0 | last_status=None | last_run=None
- **Log on disk:** False
- **Safe action:** True
- **Never-run subtype:** never_run_waiting_for_schedule

### [PARTIAL] Proposal Enrichment Loop (`proposal_enrichment_loop`)
- **Category:** Proposal Pipeline
- **Score:** 40/100 -- PARTIALLY_ACTIONABLE
- **Owner:** `scripts/proposal_enrichment_loop.py` | owner_known=True
- **Cron:** every 5m 9:00-16:00 M-F | cron_found=False
- **Telemetry:** run_count=0 | last_status=None | last_run=None
- **Log on disk:** False
- **Safe action:** True
- **Never-run subtype:** never_run_cron_missing

### [PARTIAL] Proposal Lifecycle (`proposal_lifecycle`)
- **Category:** Proposal Pipeline
- **Score:** 40/100 -- PARTIALLY_ACTIONABLE
- **Owner:** `scripts/proposal_lifecycle.py` | owner_known=True
- **Cron:** every 30m 9:00-16:00 M-F | cron_found=False
- **Telemetry:** run_count=0 | last_status=None | last_run=None
- **Log on disk:** False
- **Safe action:** True
- **Never-run subtype:** never_run_cron_missing

### [ON-DEMAND] Risk Gate (`risk_gate`)
- **Category:** Execution
- **Score:** 20/100 -- ON_DEMAND
- **Owner:** `scripts/risk_gate.py` | owner_known=True
- **Cron:** N/A | cron_found=False
- **Telemetry:** run_count=0 | last_status=None | last_run=None
- **Log on disk:** False
- **Safe action:** False
- **Never-run subtype:** never_run_on_demand

### [ON-DEMAND] Alpaca Paper Trading (`alpaca_paper`)
- **Category:** Execution
- **Score:** 40/100 -- ON_DEMAND
- **Owner:** `scripts/alpaca_paper_adapter.py` | owner_known=True
- **Cron:** N/A | cron_found=True
- **Telemetry:** run_count=0 | last_status=None | last_run=None
- **Log on disk:** False
- **Safe action:** False
- **Never-run subtype:** never_run_on_demand

### [PARTIAL] Broker Reconciliation (`broker_reconciliation`)
- **Category:** Execution
- **Score:** 60/100 -- PARTIALLY_ACTIONABLE
- **Owner:** `scripts/alpaca_paper_reconciler.py` | owner_known=True
- **Cron:** 4:30 PM M-F | cron_found=True
- **Telemetry:** run_count=0 | last_status=None | last_run=None
- **Log on disk:** False
- **Safe action:** True
- **Never-run subtype:** never_run_waiting_for_schedule

### [PARTIAL] Execution Quality (`execution_quality`)
- **Category:** Execution
- **Score:** 40/100 -- PARTIALLY_ACTIONABLE
- **Owner:** `scripts/paper_execution_quality.py` | owner_known=True
- **Cron:** 5:00 PM M-F | cron_found=False
- **Telemetry:** run_count=0 | last_status=None | last_run=None
- **Log on disk:** False
- **Safe action:** True
- **Never-run subtype:** never_run_cron_missing

### [OK] Overnight Batch (`overnight_batch`)
- **Category:** Overnight
- **Score:** 80/100 -- ACTIONABLE
- **Owner:** `scripts/overnight_batch.py` | owner_known=True
- **Cron:** 8:00 PM M-F | cron_found=True
- **Telemetry:** run_count=0 | last_status=None | last_run=None
- **Log on disk:** True
- **Safe action:** True
- **Never-run subtype:** never_run_waiting_for_schedule

### [PARTIAL] Outcome Scorer (`agent_outcome_scorer`)
- **Category:** Overnight
- **Score:** 40/100 -- PARTIALLY_ACTIONABLE
- **Owner:** `scripts/agent_outcome_scorer.py` | owner_known=True
- **Cron:** 9:00 PM M-F | cron_found=False
- **Telemetry:** run_count=0 | last_status=None | last_run=None
- **Log on disk:** False
- **Safe action:** True
- **Never-run subtype:** never_run_cron_missing

### [PARTIAL] Strategy Weekly Review (`strategy_weekly_review`)
- **Category:** Overnight
- **Score:** 60/100 -- PARTIALLY_ACTIONABLE
- **Owner:** `scripts/strategy_weekly_review.py` | owner_known=True
- **Cron:** Sunday 9 PM | cron_found=False
- **Telemetry:** run_count=0 | last_status=None | last_run=None
- **Log on disk:** True
- **Safe action:** True
- **Never-run subtype:** never_run_cron_missing

### [PARTIAL] Overnight Embeddings (`overnight_batch_embeddings`)
- **Category:** Overnight
- **Score:** 60/100 -- PARTIALLY_ACTIONABLE
- **Owner:** `scripts/overnight_batch.py` | owner_known=True
- **Cron:** 10:00 PM M-F | cron_found=True
- **Telemetry:** run_count=0 | last_status=None | last_run=None
- **Log on disk:** False
- **Safe action:** True
- **Never-run subtype:** never_run_waiting_for_schedule
