# Session 18 — Pipeline Wiring + Signal Flow Integrity

## Date: 2026-05-06

## Live Audit Findings

- Trade AI page: 1 GO signal today (SMX)
- Strategy Desk: 0 signals — root cause: no code writes GO scans into `strategy_signals`
- Paper Proposals: stale SEAT WAIT/DOWNGRADE manual proposals still pending
- Prospects: timestamp showing yesterday's scan, stop/entry inverted for some tickers

## Root Cause

The `trade_ai_orchestrator.py` writes scored tickers to `trade_ai_scans` and generates trade plans, but **never writes GO/A+ signals into `strategy_signals`**. The `symbol_discovery_engine.py` referenced in prior sessions does not exist. Strategy Desk reads from `strategy_signals`, so it was always empty.

## Files Created

- `scripts/strategy_signal_sync.py` — GO/A+ scan → strategy_signals sync with validation
- `scripts/session18_signal_flow_health.py` — Signal flow health monitor + alerting
- `scripts/session18_validate.py` — Session validation
- `sql/migrations/20260506_1800_session18_signal_flow_integrity.sql`

## Files Changed

- `scripts/trade_ai_orchestrator.py` — Added step 18d: strategy_signal_sync call after DB persist
- `scripts/api_v2.py` — Prospects timestamp fix (last_scan, scan_freshness_label, run_label)
- `scripts/paper_trade_logger.py` — WAIT/DOWNGRADE guard for manual proposals
- `apps/command-center-v2/src/pages/Prospects.tsx` — Inverted stop display warning

## strategy_signal_sync.py Behavior

1. Queries today's GO/A+ rows from `trade_ai_scans`
2. Infers `strategy_id` (gap_and_go for high-gap, momentum_scalp default)
3. Finds matching trade plan from `trade_plans`
4. Validates long trade plan (stop < entry, target > entry) — auto-fixes inverted
5. Schema-adaptive insert (reads columns from information_schema)
6. Idempotent — checks for existing signal before inserting
7. Writes `signal_flow_audit` row for every sync run
8. Preserves source lineage (source_table, source_record_id, scan_run_label, etc.)

## Orchestrator Integration

- Direct import: `from strategy_signal_sync import sync_strategy_signals`
- Fallback: subprocess call if import fails
- Non-fatal: orchestrator continues if sync fails
- Health alert: sends Telegram warning if GO scans exist but 0 signals written

## Backfill Results

- GO/A+ scans found: 1 (SMX)
- strategy_signals before: 0
- Inserted: 1 (SMX as gap_and_go, A-grade, 42pts)
- strategy_signals after: 1

## Prospects Timestamp Fix

- Added `last_scan`, `scan_date`, `run_label`, `scan_freshness_label` to response
- Uses timezone-safe query for current NY trading date
- Shows "stale_no_scan_today" if no scans found for today

## Stop/Entry Invariant

- FTRE confluence cache had stop_price ($14.71) > scan price (~$14.10)
- Root cause: indicator_confluence_cache stop_price is ATR-derived, not trade-plan-derived
- Fix: Prospects UI now shows "(inverted)" warning when stop >= entry
- strategy_signal_sync auto-fixes inverted stops before inserting

## SEAT Proposal Cleanup

- 2 SEAT PENDING proposals expired/rejected with audit trail
- Added WAIT/DOWNGRADE guard: manual proposals for WAIT/AVOID/NO GO symbols get `approval_allowed=false` and warning message

## Signal Flow Health Monitor

- Runs at 07:15 weekdays via cron
- Checks GO/A+ count vs strategy_signals count
- CRITICAL if GO > 0 and signals = 0
- WARN if signals < 50% of GO count
- Writes to signal_flow_audit + sends Telegram alert

## Validation Results

12/12 checks passed.

## Next Session

Session 19: Full paper proposal research-packet quality verification after live signal flow is stable
