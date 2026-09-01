# Phase 201B — PHASE41 Governance Timer Overlap Inventory

Status:      HISTORICAL
as_of:       2026-06-05T10:06:29-04:00
Measured at: efcc51365 / not measured

Redundant PHASE41 governance **systemd user timers** now covered by the governance controller. No
timer stopped/disabled in this phase (inventory only).

## Redundant timers (covered by controller steps)
| Timer | Service script | Schedule (last fire) | Output/log | Controller step | Diff evidence | Safe to retire | Rollback |
|-------|----------------|----------------------|------------|-----------------|---------------|----------------|----------|
| `tradeai-governance-facts.timer` | `run_scheduled_system_facts.sh` | weekday 07:40 / Sun 18:00 | `logs/governance_system_facts.log` | `system_facts` | 200F PASS | **YES** | `systemctl --user enable --now tradeai-governance-facts.timer` |
| `tradeai-governance-status.timer` | `report_governance_status.py` | weekday 07:50 / Sun 18:10 | `docs/governance/governance_status_latest.*` | `governance_status` | 200F PASS | **YES** | `systemctl --user enable --now tradeai-governance-status.timer` |
| `tradeai-maturity-board.timer` | `run_scheduled_maturity_control_board.sh` | weekday 07:55 / Sun 18:15 | `docs/maturity*` | `maturity_control_board` | 200F PASS | **YES** | `systemctl --user enable --now tradeai-maturity-board.timer` |
| `tradeai-operator-readiness.timer` | `report_operator_readiness_summary.py` | weekday 08:00 / Sun 18:20 | `docs/maturity_hardening/operator_readiness_latest.*` | `operator_readiness` | 200F PASS | **YES** | `systemctl --user enable --now tradeai-operator-readiness.timer` |

All four ran at ~07:40–08:00 Fri 2026-06-05 **alongside** the controller's 07:40 run — duplication
confirmed (each report regenerated twice; idempotent, harmless, but redundant).

## Keep (NOT retired)
- `tradeai-governance-pipeline.timer` — the **controller itself** (this is the owner going forward).
- A1A — already migrated in Phase 200 (cron, commented). No remaining a1a timer.

## Out of scope / never touched
- Safety net: `system_freshness_monitor` (`*/20`), `freshness_watchdog_heartbeat` (`*/30`) — cron, untouched.
- `heartbeat-receiver.service` — kept. All trading/proposal/protection/broker/Hermes/LLM/portfolio units.

## Coverage check
Each retire-candidate's script == the exact command in the matching controller `gov_step` (same args).
The Phase 200F diff already proved controller output == legacy output (modulo timestamp/audit-state).

---
*Inventory only; nothing disabled. 4 redundant governance timers identified; all controller-covered;
each with a one-line rollback.*
