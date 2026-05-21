# Overnight Activity Repair

**Status:** COMPLETE
**Date:** 2026-05-21

## Summary

Multiple scheduled pipeline jobs were silently failing in cron context due to two root causes:
1. `db_adapter.py` did not auto-load DB credentials from `.env` — cron jobs lack inherited env vars
2. `incubator_proposal_promoter.py` used integer indexing on `RealDictRow` results, causing `KeyError(0)` silently caught

## Impact

All pipeline jobs that rely on `db_adapter._get_conn()` without their own `load_dotenv()` call were affected. Jobs with `load_dotenv()` (e.g., `trade_ai_orchestrator.py`) continued working.

**Affected jobs (not producing output since May 21 morning):**
- incubator_proposal_promoter (hourly 7am-5pm)
- finviz_screener_runner (5x daily)
- portfolio_orchestrator (7:15am daily)
- market_regime_classifier (6:35am daily)
- paper_trade_monitor (every 2min market hours)

**Not affected (have own dotenv or shell wrapper):**
- trade_ai_orchestrator (screener_pm) — has `load_dotenv()`
- send_telegram_proposal_alert — cron entry sources `.env`
- run_deep_overnight_llm_window — shell wrapper

## Files Changed
- `scripts/db_adapter.py` — auto-loads DB_* vars from `.env` at module init
- `scripts/incubator_proposal_promoter.py` — fixes RealDictRow parsing, adds market_quote_snapshots as quote source

## Verification
All pipeline jobs manually executed and verified after fix. NEE promoted to PENDING proposal #111.
