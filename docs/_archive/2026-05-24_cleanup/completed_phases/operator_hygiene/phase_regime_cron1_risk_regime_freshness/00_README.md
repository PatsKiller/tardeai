# REGIME-CRON-1 — Restore Risk Regime Freshness

**Status:** COMPLETE

## Root Cause

All three risk-regime scripts had the same bug: `save_*` functions defaulted to `dry_run=True`, and the callers in `main()` never passed `dry_run=False` when running in `--apply` mode. The cron ran on schedule, the classifier classified correctly, but no results were ever written to the database.

| Script | Bug | Fix |
|--------|-----|-----|
| `market_regime_collector.py:164` | `save_indicators(conn, indicators)` | Added `dry_run=False` |
| `market_regime_classifier.py:214` | `save_snapshot(conn, snapshot)` | Added `dry_run=False` |
| `strategy_rotation_engine.py:162` | `save_signals(conn, signals, alignments)` | Added `dry_run=False` |

## Before / After

| Metric | Before | After |
|--------|--------|-------|
| Latest snapshot | 2026-05-11 (9 days stale) | 2026-05-20 11:50 (fresh) |
| Run log entries | 0 | 1 (success) |
| Indicators | 13 (stale) | 20 (fresh) |
| Rotation signals | 0 | 0 (correct — no profile matches) |
| API generated_at | 2026-05-11T16:13:38 | 2026-05-20T11:50:02 |

## Changes

1. **3 one-line fixes** — pass `dry_run=False` to save functions in apply mode
2. **Transaction recovery** — `save_snapshot()` tests connection health before write, rolls back poisoned transactions, returns success/failure bool
3. **Run log recording** — `_record_run_log()` writes to `risk_regime_run_log` after each classifier run
4. **Cron wrapper** — `scripts/run_scheduled_risk_regime_classifier.sh` with safety guards, flock, telemetry
5. **Rollback script** — `scripts/rollback_regime_cron1_classifier_cron.sh`
6. **Health report** — `scripts/run_regime_cron1_health.py` (read-only with optional repair flags)
7. **Staleness audit** — `scripts/report_regime_cron1_staleness.py`
8. **Schema contract audit** — `scripts/report_regime_cron1_schema_contract.py`

## Safety Preserved

- ALPACA_MODE=paper
- LLM_DISABLE_LIVE_EXECUTION=true
- No trades, orders, or approvals
- No strategy activation changes
- No auto-rotation (signals are proposal-only, requires_admin_approval=True)
- No YAML/Finviz changes
- No .env modifications
- Transaction failures cannot poison status writes
- Failed classifiers cannot mark stale data as current
