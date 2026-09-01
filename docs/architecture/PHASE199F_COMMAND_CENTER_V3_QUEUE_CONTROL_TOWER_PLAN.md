# Phase 199F — Command Center v3 Queue Control Tower Enhancement Plan

Status:      HISTORICAL
as_of:       2026-06-04T22:44:11-04:00
Measured at: efcc51365 / not measured

v3 is canonical. **No v2 UI work.** This plans enhancements to the EXISTING v3 Queue Control Tower
(in `SystemHub`) to add a pipeline-ownership view over the 199C model.

## Inspection findings (current v3)
- The QCT lives in **`apps/command-center-v3/src/pages/SystemHub.tsx`** and already consumes a rich
  read-only API set:
  `/api/v2/system/queue-control-tower`, `/api/v2/system/cron-compression`,
  `/api/v2/system/scheduled-jobs`, `/api/v2/system/pipeline-health`, `/api/v2/local-llm-status`,
  `/api/v2/system/siem`, `/api/v2/live-trading-gate`, `/api/v2/system/broker-connectors`,
  `/api/v2/system/applications`, `/api/v2/admin/audit-log`, `/api/v2/atm/config`, etc.
- So the data plane mostly exists; what's missing is **grouping by the 7 owner pipelines** and a
  **duplicate-cron risk panel** tied to the 199B inventory.

## API namespace clarification (important)
**`/api/v2/*` here is the backend API namespace, not Command Center v2 UI.** v3 consumes these
endpoints. Per this phase's rules they are NOT renamed; they are documented as
**shared/legacy-namespace backend APIs serving the canonical v3 UI**. v2 UI remains frozen/reference.

## Planned QCT enhancements (v3-only, all read-only/operator-gated)
1. **Pipeline ownership section** — the 7 pipelines (199C) as cards: owner, trigger window, current
   state, last run, next due, allowed/prohibited-writes summary, disable command.
2. **Active jobs by pipeline** — map scheduled-jobs/QCT entries to their owner pipeline (199C mapping).
3. **Due-next by pipeline** — next trigger per pipeline (from systemd timers / cron parse).
4. **Failures by pipeline** — recent failures grouped by owner.
5. **Duplicate-cron risk panel** — from the 199B inventory: multi-scheduled scripts + their owner
   pipeline + "compression candidate" flag (visibility only; no disabling from UI).
6. **LLM queue panel** — high/deep-overnight queue depth, by status (reuse `local-llm-status` +
   a queue summary).
7. **Telegram / SIEM output panel** — recent SIEM events + Telegram policy per pipeline.
8. **Safety badges** — paper-only badge; **LIVE TRADING PROHIBITED** badge; Level 7 prohibited badge;
   gate progress (from `/api/v2/atm/gate-status`).
9. **Drilldown per job / per failure** — click a job → detail (schedule, script, lock, log, deps);
   click a failure → last error + log tail.
10. **Actions** — requeue/approve only where already operator-gated (via the proven admin_write
    guard); **no enable/disable of crons from the UI in this phase.**

## New backend support needed (199G — read-only only)
- `GET /api/v2/system/runtime-inventory` → serve `data/runtime/runtime_job_inventory_latest.json`.
- `GET /api/v2/system/pipeline-summary` → the 7 pipelines + job counts/due-next/failures mapped by owner.
- (gate-status / siem / cron-compression / scheduled-jobs already exist.)
No destructive runtime controls; no enabling/disabling crons; no job modification; no live trading;
no strategy mutation.

## Out of scope (hard)
- No v2 UI changes. No cron enable/disable from UI. No live arming. No GO/WAIT or strategy mutation.

---
*Plan only. v3 canonical; `/api/v2` = shared backend namespace, not v2 UI. Enhances existing QCT.*
