# Pipeline Controller Observation — 2026-05-09

## Summary

Manual observation run comparing the new pipeline controller (25 stages)
against the existing crontab (141 active entries, 77 unique scripts).

No cron changes were made. No code was modified. Observation only.

## Current State

| Metric | Value |
|--------|-------|
| Crontab active entries | 141 |
| Crontab unique scripts | 77 |
| Controller active stages | 25 |
| Controller dry-run result | SUCCESS (25/25) |
| Dependency resolution | Clean topological order |
| Blocked/degraded stages | 0 |

## Overlap: 17 scripts in both controller AND cron

These scripts are already scheduled via cron and also defined as controller
stages. When the controller is adopted, these cron entries become redundant.

| Script | Controller Group |
|--------|-----------------|
| `indicator_cache_refresh.py` | data_collection |
| `finviz_screener_runner.py` | data_collection |
| `news_ingestion.py` | data_collection |
| `topic_ingestion.py` | data_collection |
| `sec_data_ingest.py` | data_collection |
| `fred_data_ingest.py` | data_collection |
| `finviz_enrichment.py` | enrichment |
| `price_db_sync.py` | enrichment |
| `rag_indexer.py` | enrichment |
| `cio_decision_engine.py` | intelligence |
| `topic_curator.py` | intelligence |
| `pipeline_watchdog.py` | intelligence |
| `daily_incubator_refresh.py` | proposals |
| `incubator_proposal_promoter.py` | proposals |
| `proposal_enrichment_loop.py` | proposals |
| `overnight_batch.py` | overnight |
| `agent_outcome_scorer.py` | overnight |

## Controller-only: 8 stages not in cron

These are new stages the controller manages that don't have standalone cron entries:

| Script | Controller Group | Notes |
|--------|-----------------|-------|
| `catalyst_enrichment.py` | enrichment | May be called inline by other scripts currently |
| `trade_ai_orchestrator.py` | scoring | Core orchestrator — currently triggered differently |
| `multi_strategy_classifier.py` | scoring | Currently runs via batch/manual |
| `agent_context_refresh.py` | intelligence | New or manually triggered |
| `risk_gate.py` | execution | Pre-execution safety check |
| `live_trading_gate.py` | execution | Paper validation enforcer |
| `execution_quality_analyzer.py` | execution | Post-execution analysis |
| `generate_system_facts.py` | overnight | New from hardening sprint |

## Cron-only: 60 scripts not in controller

These remain cron-only and should NOT be migrated in the first wave.
Categories:

**Agent/AI jobs (should remain cron for now):**
- `aegis_morning_brief_delivery.py`, `agent_event_router.py`,
  `agent_watchlist_engine.py`, `alex_gov_research.py`,
  `alex_retirement_advisor.py`, `run_alex_daily.py`,
  `iris_taxonomy_agent.py`, `auto_research.py`

**Paper trading lifecycle (critical — do not migrate yet):**
- `alpaca_paper_adapter.py`, `alpaca_paper_reconciler.py`,
  `open_trade_monitor.py`, `paper_execution_quality_analyzer.py`,
  `paper_performance_governance.py`, `paper_trade_analyzer.py`

**Proposal pipeline (many interdependent jobs):**
- `proposal_backtest_engine.py`, `proposal_execution_readiness.py`,
  `proposal_intelligence_analyzer.py`, `proposal_llm_review_worker.py`,
  `proposal_monitor.py`, `proposal_quality_reviewer.py`,
  `proposal_research_packet_builder.py`, `proposal_technical_snapshot.py`,
  `queue_proposal_agent_reviews.py`

**Market data / enrichment:**
- `external_market_data_ingest.py`, `premarket_watcher.py`,
  `social_ingest.py`, `social_scalp_scanner.py`,
  `sync_dividend_data.py`, `event_detector.py`

**Infrastructure / monitoring:**
- `_signal_flow_health.py`, `credential_monitor.py`,
  `full_system_backup.py`, `pipeline_health_monitor.py`,
  `system_health_alerts.py`, `telegram_smart_alerts.py`,
  `write_state_freshness_history.py`

**YouTube / content:**
- `youtube_backfill_manager.py`, `youtube_channel_discovery.py`,
  `youtube_transcript_ingest.py`, `transcript_slow_processor.py`

**Other:**
- `classify_candidates.py`, `holdings_llm_refresh.py`,
  `incubator_llm_screener.py`, `incubator_rolloff_engine.py`,
  `intel_auto_discovery.py`, `iterate_research_topics.py`,
  `materialize_income_engine.py`, `materialize_watchlist_strategy_cards.py`,
  `pattern_extractor.py`, `portfolio_level_qa.py`,
  `previously_traded_watchlist.py`, `process_watchlist_agent_jobs.py`,
  `record_decision_outcome.py`, `recovery_watch_daily.py`,
  `scalp_outcome_scorer.py`, `strategy_weekly_review.py`,
  `sync_watchlist_items_to_db.py`, `watchlist_hygiene.py`,
  `weekly_incubator_builder.py`

## Migration Risk Notes

**Safest to migrate first (low risk, overlap confirmed):**
1. `generate_system_facts.py` — new, no existing cron dependency
2. `indicator_cache_refresh.py` — standalone data pull, no downstream in cron
3. `fred_data_ingest.py` — standalone data pull
4. `sec_data_ingest.py` — standalone data pull
5. `agent_outcome_scorer.py` — end-of-day, no downstream

**Do NOT migrate yet:**
- Paper trading scripts (`alpaca_paper_adapter.py`, `alpaca_paper_reconciler.py`) —
  critical live-cycle jobs, any timing change risks trade state corruption
- Proposal pipeline jobs — heavily interdependent, need full dependency mapping
  before moving to controller
- Agent/AI jobs with specific timing windows (premarket, morning brief)
- Infrastructure monitoring (`credential_monitor.py`, `system_health_alerts.py`) —
  should run independently of pipeline success/failure
- Backup jobs (`full_system_backup.py`) — must remain independent

## Recommendations

1. **Do not install pipeline-controller cron yet.**
2. **Continue manual dry-runs for 2–3 clean days** to build confidence.
3. **Consider installing only system-facts cron** after 2–3 clean manual runs
   (low risk, additive, no overlap with existing jobs).
4. **Migrate pipeline cron gradually**, not all at once:
   - Wave 1: `generate_system_facts.py` only
   - Wave 2: data_collection group (6 stages)
   - Wave 3: enrichment + scoring groups
   - Wave 4: intelligence + proposals groups
   - Wave 5: execution + overnight groups (requires paper trading safety review)
5. **Keep infrastructure/monitoring cron independent** — these should run
   regardless of pipeline state.
6. **Keep paper trading lifecycle cron independent** until paper validation
   window closes and live trading decisions are made.
