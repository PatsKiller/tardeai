# SP-2 Preflight

**Date:** 2026-05-18
**Safety:** ALPACA_MODE=paper, LLM_DISABLE_LIVE_EXECUTION=true, holdings=$1,193,025

## DB Counts

| Table | Count |
|-------|-------|
| screener_config | 18 |
| finviz_screeners | 27 |
| incubator_universe | 1,139 |
| strategy_setup_matches | 360 |
| paper_trade_proposals | 83 |
| paper_trades | 23 |
| screener_run_health | 83 |

## Proposals by Strategy

| Strategy | Count |
|----------|-------|
| momentum_scalp | 30 |
| gap_and_go | 12 |
| swing_breakout | 10 |
| swing_trade | 6 |
| screener | 6 |
| speculative_growth | 6 |
| recovery_watch | 5 |
| earnings_catalyst | 4 |
| sector_rotation | 2 |
| core_growth_compounder | 1 |

## Screener Configs (18 total, all enabled)

All screeners enabled but none have last_result_count or last_run_at populated in screener_config table.
Run health tracked separately in screener_run_health (83 rows).

## Strategy YAMLs: 23 files (including schema/shared)

## Key Scripts Located

- finviz_screener_runner.py, finviz_ingestion.py, finviz_enrichment.py
- incubator_proposal_promoter.py, daily_incubator_refresh.py, weekly_incubator_builder.py
- multi_setup_router.py, strategy_config_loader.py
- screener_run_health.py
