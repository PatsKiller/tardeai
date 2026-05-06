# Session 18B: Screener Universe + Freshness + Signal Sync Repair

## Root Cause

The 07:00 run scanned only 10 tickers because:
1. **Only 2 narrow screeners** in screeners.yaml (RVOL>5x+gap>10%, RVOL>3x+gap>5%)
2. **Pre-score filter at min_pre_score=8** eliminated most candidates before enrichment
3. Pre-market/early market conditions with these strict filters naturally yield few results

## Fixes Applied

### Screener Universe (Phase 3)
- Added 3 new broader screeners to `assets/screeners.yaml`:
  - `unusual_volume`: RVOL>2x, price $1-50, avg vol>200k (no gap requirement)
  - `gap_momentum`: Gap>3%, price $1-30, avg vol>100k (lower RVOL threshold)
  - `high_rvol_broad`: RVOL>5x, price $1-100, any cap (catches mid/large cap)
- All 5 screeners active in all run windows (0400/0700/0900/1000)
- Result: **385 tickers** from 5 screeners (up from ~11)

### Pre-Score Filter (Phase 3)
- Lowered `min_pre_score` from 8 to 5 in orchestrator
- Now passes 381/385 candidates through to catalyst enrichment

### Run Health Schema (Phase 2)
- Created `screener_run_health` table to track run completeness
- Status values: RUN_HEALTHY, RUN_PARTIAL, RUN_UNDERFILLED, RUN_FAILED, RUN_STALE
- Reason codes: FINVIZ_AUTH_MISSING, CSV_EMPTY, ROW_LIMIT_10_DETECTED, etc.

### Run Health Helper (Phase 4)
- Created `scripts/screener_run_health.py` with:
  - `classify_run_health(stats)` -> (status, reason_codes)
  - `record_screener_run_finish(conn, run_label, stats)`
  - `get_latest_run_health(conn)`

### Orchestrator Enhancements (Phase 5)
- Added `--min-symbols` (default 40) and `--allow-underfilled` CLI args
- Records run health after scoring (stage 18b2)
- Added trade plan backfill step (stage 18e)
- Fixed pre-existing `conn`/`logger` NameError bugs in symbol enrichment

### API Freshness (Phases 7-8)
- `/api/v2/prospects` now returns: `is_stale`, `stale_reason`, `data_age_minutes`, `symbols_scanned`, `go_count`, `wait_count`, `run_health_status`, `run_health_reason_codes`
- `/api/v2/trade-ai` now returns: `ok`, `latest_run_label`, `latest_run_symbols_scanned`, `run_health_status`, `today_strategy_signal_count`

### Pipeline Run Health Endpoint (Phase 13)
- New `GET /api/v2/pipeline-run-health` returns comprehensive status:
  - latest_run (status, symbols, GO/WAIT counts)
  - prospects (count, is_stale)
  - strategy_signals (today_count, by_strategy)
  - trade_plans (proposal_worthy, planned, coverage_pct)
  - paper_proposals (pending, blocked_reasons)

### Trade Plan Backfill (Phase 10)
- Created `scripts/backfill_trade_plans_for_signals.py`
- Sources: existing trade_plans > confluence cache > ATR-based > conservative fallback
- Quality labels: PLAN, CONFLUENCE, FALLBACK
- Integrated into orchestrator as stage 18e

### UI Banners (Phase 12)
- Prospects, TradeAI, StrategyDesk, PaperProposals all show run health banners
- Color-coded: green=HEALTHY, amber=PARTIAL, red=UNDERFILLED
- Shows: run label, symbols scanned, status, data age, signal count

## Files Created
- `sql/migrations/20260506_2000_session18b_screener_run_health.sql`
- `scripts/screener_run_health.py`
- `scripts/backfill_trade_plans_for_signals.py`
- `scripts/session18_screener_validate.py`
- `docs/project/SESSION_18B_SCREENER_UNIVERSE_FRESHNESS_SIGNAL_SYNC.md`

## Files Changed
- `assets/screeners.yaml` - added 3 screeners, version 12.2
- `scripts/trade_ai_orchestrator.py` - min-symbols, run health, plan backfill, bug fixes
- `scripts/api_v2.py` - freshness fields, pipeline-run-health endpoint
- `apps/command-center-v2/src/pages/Prospects.tsx` - run health banner
- `apps/command-center-v2/src/pages/TradeAI.tsx` - run health banner
- `apps/command-center-v2/src/pages/StrategyDesk.tsx` - run health banner
- `apps/command-center-v2/src/pages/PaperProposals.tsx` - run health banner + empty state

## Remaining / Deferred
- Weekly incubator model (user feedback: screeners run weekly, curate candidates for the week, track roll-off)
- DOCX reference architecture update (separate step)
- Cron additions (orchestrator runs handled by continuous_runner.py)
