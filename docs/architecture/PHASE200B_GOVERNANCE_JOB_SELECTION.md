# Phase 200B — Governance Job Selection

Status:      HISTORICAL
as_of:       2026-06-04T23:11:56-04:00
Measured at: efcc51365 / not measured

Governance-pipeline jobs selected for the controller. All are **read-only reporting** (produce docs /
JSON); none touch broker, trading, proposals, protection, Hermes, LLM, or portfolio state.

## Selected governance jobs
| Job | Current schedule | Script | Writes_to | Log | Lock | Safety |
|-----|------------------|--------|-----------|-----|------|--------|
| A1A docs audit | **cron** `45 7 * * 1-5` + `5 18 * * 0` | `run_scheduled_a1a_check.sh` | `docs/_audit/*` | `logs/governance_a1a_check.log` | `tradeai_a1a_check.lock` | LOW (read-only) |
| Safety/system facts | systemd (PHASE41) | `run_scheduled_system_facts.sh` | `docs/governance/system_facts*` | `logs/governance_system_facts.log` | `tradeai_system_facts.lock` | LOW |
| Governance status | systemd (PHASE41) | `report_governance_status.py` | `docs/governance/governance_status_latest.{json,md}` | `logs/governance_status.log` | — | LOW |
| Maturity control board | systemd (PHASE41) | `run_scheduled_maturity_control_board.sh` | `docs/maturity*` | `logs/maturity_control_board.log` | `tradeai_maturity_control_board.lock` | LOW |
| Operator readiness | systemd (PHASE41) | `report_operator_readiness_summary.py` | `docs/maturity_hardening/operator_readiness_latest.{json,md}` | `logs/operator_readiness.log` | — | LOW |
| State-of-repo snapshot | **none** (unscheduled) | `generate_state_of_repo_snapshot.py` | `docs/project/STATE_OF_REPO_LATEST.md` | (controller log) | — | LOW |

## Per-job migration detail
- **Proposed controller step:** each becomes a named `gov_step` in `run_governance_pipeline.sh --apply`.
- **Expected output:** the report files above are (re)generated; controller writes a summary to
  `data/runtime/governance_pipeline_last_run.json`.
- **Diff method:** `scripts/compare_governance_pipeline_outputs.py` compares the controller-produced
  report files against the legacy ones (content where deterministic; ignore timestamp/run_id/path).
- **Rollback method:** legacy schedules remain active (parallel observation) until diff passes; the
  only *active cron* retired is A1A (commented with `# PHASE200_MIGRATED...`, restorable from
  `/tmp/crontab_before_phase200.txt`). systemd PHASE41 timers are untouched in this pilot.

## NOT selected (explicit)
- Safety net: `system_freshness_monitor.py`, `freshness_watchdog_heartbeat.py` — **never migrated**.
- `system_health_agent.py` (broker read dep), `system_health_alerts.py` (Telegram path).
- Everything trading / proposal / ATM / protection / broker / Hermes / LLM / portfolio / data-feed.

---
*Governance reporting only. The single active cron to retire is A1A; the rest are already on systemd
(PHASE41) and now also owned by the controller for unified visibility.*
