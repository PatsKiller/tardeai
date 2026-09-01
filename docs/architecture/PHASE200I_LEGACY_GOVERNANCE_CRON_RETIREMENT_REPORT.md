# Phase 200I — Legacy Governance Cron Retirement (comment, not delete)

Status:      HISTORICAL
as_of:       2026-06-04T23:21:53-04:00
Measured at: efcc51365 / not measured

All preconditions passed (dry-run ✓, apply ✓, output diff ✓, scheduled cycle ✓, rollback documented
✓, governance-only ✓, operator approval in the Phase 200 prompt ✓), so the **active legacy A1A cron
lines were commented** (not deleted) with a dated marker.

## What was retired
- **2 active A1A cron lines** (`run_scheduled_a1a_check.sh` — weekday `45 7 * * 1-5` + Sunday
  `5 18 * * 0`) — now prefixed with
  `# PHASE200_MIGRATED_TO_GOVERNANCE_PIPELINE 2026-06-04 scripts/pipelines/run_governance_pipeline.sh`
  and commented (the line is preserved, restorable by uncommenting).
- These were the ONLY active *cron* governance jobs. The PHASE41 governance **systemd timers**
  (facts/status/maturity/readiness) are left running (parallel observation) — retiring systemd units
  is out of scope for a cron-migration pilot.

## Verification (post-edit)
- A1A active cron lines: **0** (was 2).
- Marker lines present: **2**.
- Crontab line count: **437** (435 + 2 markers) — net of commenting 2 + adding 2 marker comments.
- **Safety net UNTOUCHED:** `system_freshness_monitor.py` (`*/20`) + `freshness_watchdog_heartbeat.py`
  (`*/30`) — **2 active, byte-identical to backup** (confirmed by diff). The layer-3
  `heartbeat-receiver` is a systemd service (not cron). **Never migrated/disabled.**
- **Diff backup-vs-now:** ONLY the 2 A1A lines differ; every other cron line identical.
- Controller timer: **active** (next fire Fri 07:40).

## Backups
- `/tmp/crontab_before_phase200.txt` (pre-phase, 435 lines)
- `/tmp/crontab_pre_200I_<ts>.txt` (immediately pre-edit)

## Rollback
`crontab /tmp/crontab_before_phase200.txt` restores the exact pre-migration crontab (re-activates the
2 A1A lines). Or uncomment the 2 marked lines.

## Blockers
- None. All conditions passed; governance-only; no trading/protection/broker/LLM lines touched.

---
*Governance A1A cron retired (commented, reversible). Safety net + all non-governance jobs intact.*
