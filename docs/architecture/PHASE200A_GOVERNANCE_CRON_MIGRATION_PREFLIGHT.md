# Phase 200A — Governance Cron Migration Pilot: Preflight

Status:      HISTORICAL
as_of:       2026-06-04T23:11:24-04:00
Measured at: efcc51365 / not measured

P0 cron migration pilot, **governance pipeline ONLY**. Parallel-run + diff-first; no cron retired
until diff passes (operator approval for governance-only retirement is granted in the Phase 200 prompt).

## Repo state
- Branch: **main** · Head: `09d17c0 docs: index Phase 199 runtime control plane + v3 governance`
- Dirty (non-runtime): 2 files (doc index / memory) — runtime artifacts excluded.

## Safety baseline (verified)
- `ALPACA_MODE=paper` · `LIVE_TRADING_ENABLED` absent (**live OFF**) · Level 7 **PROHIBITED** (no flag).
- No broker-facing / trading / proposal / protection / Hermes / LLM / portfolio job is in scope.

## Backups (pre-migration)
- `/tmp/crontab_before_phase200.txt` (435 lines)
- `/tmp/user_timers_before_phase200.txt`, `/tmp/user_services_before_phase200.txt`
- `/tmp/system_timers_before_phase200.txt`, `/tmp/system_services_before_phase200.txt`

## Governance jobs identified
**Active cron (migratable in this pilot):**
- `run_scheduled_a1a_check.sh` — line ~226 `45 7 * * 1-5` (weekday) and ~232 `5 18 * * 0` (Sunday).

**Already migrated to systemd by prior PHASE41 (commented `# PHASE41-MIGRATED` in cron):**
- `run_scheduled_system_facts.sh`, `report_operator_readiness_summary.py`,
  `report_governance_status.py`, `run_scheduled_maturity_control_board.sh`.
- These are NOT active cron lines (nothing to retire); the controller will *also* orchestrate them
  (single owner going forward) and they remain on their systemd timers as parallel observation.

**Unscheduled (to add to controller):** `generate_state_of_repo_snapshot.py` (no current schedule).

## Explicitly EXCLUDED (not migrated, left untouched)
- **Safety net (NEVER migrate):** `system_freshness_monitor.py` (`*/20`), `freshness_watchdog_heartbeat.py` (`*/30`) — 3 active cron lines kept.
- `system_health_agent.py` (has broker read dependency — conservative exclude), `system_health_alerts.py` (Telegram alert path — keep separate).
- All trading / proposal / ATM / protection / broker / Hermes research+advisory / LLM queue / portfolio / data-feed jobs.

## Rollback plan
- Crontab: restore `/tmp/crontab_before_phase200.txt` via `crontab /tmp/crontab_before_phase200.txt`.
- Controller schedule: `systemctl --user disable --now <timer>` (or remove the added cron line).
- No legacy line is deleted — only commented with a dated `# PHASE200_MIGRATED_TO_GOVERNANCE_PIPELINE`
  marker, reversible by uncommenting.

---
*Preflight complete. Scope = governance reporting only; safety net + all trading/broker jobs excluded.*
