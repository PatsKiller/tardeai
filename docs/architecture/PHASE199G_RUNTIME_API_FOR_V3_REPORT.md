# Phase 199G — Read-only Runtime Control Plane API for v3

Status:      HISTORICAL
as_of:       2026-06-04T22:46:54-04:00
Measured at: efcc51365 / not measured

Two read-only endpoints added to the shared backend (`scripts/api_v2.py`) for the v3 Queue Control
Tower. **Read-only — no destructive runtime controls, no enable/disable of crons, no job
modification, no live trading, no strategy mutation.**

## Endpoints (GET, read-only)
| Endpoint | Returns |
|----------|---------|
| `GET /api/v2/system/runtime-inventory` | Phase 199B inventory summary (totals, duplicate scripts, category counts) from `data/runtime/runtime_job_inventory_latest.json`; `{available:false}` if not yet generated |
| `GET /api/v2/system/pipeline-summary` | The 7 owner pipelines (199C) mapped over the inventory: per-pipeline cron count, systemd units, compression candidates; standalone services; unknown-triage count; safety flags |

Existing read-only endpoints reused by the QCT (already present): `/api/v2/system/queue-control-tower`,
`/api/v2/system/cron-compression`, `/api/v2/system/scheduled-jobs`, `/api/v2/system/pipeline-health`,
`/api/v2/local-llm-status`, `/api/v2/system/siem`, `/api/v2/atm/gate-status`, `/api/v2/live-trading-gate`.

## Verified
- `GET /api/v2/system/runtime-inventory` → HTTP 200.
- `GET /api/v2/system/pipeline-summary` → HTTP 200, e.g.:
  market 69 cron / after-close 17 / advisory 2 / research 15 / llm 3 / governance 11 / portfolio 6;
  unknown-triage 88; standalone services listed; safety `{live_trading:false, level7:prohibited, paper_only:true}`.

## Namespace note (per phase rule)
`/api/v2/*` is the **backend API namespace serving the canonical v3 UI** — NOT Command Center v2 UI.
These endpoints were added under `/api/v2` for compatibility with the existing v3 client; not renamed.

## Not added (prohibited this phase)
- No endpoint that enables/disables/modifies crons, timers, or jobs.
- No destructive runtime control. No live trading. No strategy/GO-WAIT mutation.

---
*Read-only API only. Shared `/api/v2` namespace = backend for v3, not v2 UI.*
