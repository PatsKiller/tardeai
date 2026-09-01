# Phase 207A — Daily Report Cadence Migration: Preflight — 2026-06-07

Status:      HISTORICAL
as_of:       2026-06-07T10:47:32-04:00
Measured at: efcc51365 / not measured

## Verified current state
- **Backup cadence controller active + clean:** `tradeai-portfolio-backup-cadence.timer` enabled, last
  fire 2026-06-07 02:30 `overall=ok` (Phase 204/205 complete). Legacy backup cron retired 2026-06-06.
- **No active portfolio controller process** running.
- **Live trading blocked:** `ALPACA_MODE=paper`, `LLM_DISABLE_LIVE_EXECUTION=true`. Level 7 prohibited.
- **Safety-net watchdog untouched:** `portfolio_server_watchdog.sh` cron present (1 entry).

## Legacy daily report schedule (migration target — still ACTIVE)
- `portfolio-daily.timer` (systemd --user, **active/enabled**) → `linux_launchers/run_portfolio.sh`
  (last 2026-06-05 07:00; next Mon 2026-06-08 07:00). **This is the legacy daily path.**
- (Separate daily cron jobs NOT in scope: `run_alex_daily.py --daily` @05:00, standalone
  `portfolio_orchestrator.py` @07:15, recovery_watch/portfolio_level_qa/agent_intelligence — the
  cadence controller's `run_daily` replaces only the `run_portfolio.sh` path.)

## Cadence controller daily state
The cadence-aware controller `scripts/pipelines/run_portfolio_maintenance_pipeline.sh` **already**
implements `--cadence daily` → `run_daily()` = `bash linux_launchers/run_portfolio.sh`, labeled
**`PORTFOLIO_ADVISORY_DRAFT_REVIEW_ONLY`**, with price_cache + db_retention EXCLUDED and
`assert_no_live_trading`. It has been **dry-run only** (2026-06-05, `dry_run=true`, `overall=ok`,
summary `data/runtime/portfolio_maintenance_daily_last_run.json`). **Never applied, never scheduled.**

## Conclusions
- backup cadence controller active and clean: **YES**
- legacy backup cron retired: **YES** (reversible)
- daily report legacy schedule still active: **YES** (`portfolio-daily.timer`)
- no active portfolio controller process: **YES**
- live trading blocked: **YES**; Level 7 prohibited: **YES**
- safety-net monitor/watchdog untouched: **YES**

Proceed to 207B classification → 207C harden/verify → dry-run → parallel apply → diff → schedule
(parallel) → observe → retire only if clean. **Legacy `portfolio-daily.timer` stays active throughout.**
