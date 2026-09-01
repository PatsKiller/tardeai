# Phase 200J — v3 Governance Pipeline Visibility

Status:      HISTORICAL
as_of:       2026-06-04T23:25:21-04:00
Measured at: efcc51365 / not measured

v3 Queue Control Tower (SystemHub → Control Plane) now shows the governance controller status.
Read-only; **no v2 UI changed**.

## Backend (read-only, added)
`GET /api/v2/system/governance-pipeline-status` (`_governance_pipeline_status`) returns:
- `controller` (run_governance_pipeline.sh) + `timer` (tradeai-governance-pipeline.timer)
- `last_run` — run_ts, overall status, dry_run, per-step status (from `governance_pipeline_last_run.json`)
- `failures` — failed steps (currently 0)
- `next_run` — from the user timer
- `retired_legacy_cron` — count of `PHASE200_MIGRATED` markers (**2**)
- `active_legacy_governance_cron` — active legacy governance cron lines (**0**)
- `safety` — paper_only / live_trading=false / level7=prohibited

Verified live: `last_run overall=ok`, failures=0, retired=2, active-legacy=0.

## v3 UI (Control Plane tab)
`PipelineControlTower.tsx` adds a **"Governance Pipeline — migrated to controller (Phase 200)"**
card showing: controller, last-run status, failures, retired-legacy-cron count, active-legacy-gov-cron
count, next run, and per-step statuses. Rendered (screenshot `/tmp/gov_control_plane.png`):
> last run: ok · failures: 0 · retired legacy cron: 2 · active legacy gov cron: 0 ·
> steps: a1a_docs_audit:ok · system_facts:ok · governance_status:ok · maturity_control_board:ok ·
> operator_readiness:ok · state_of_repo:ok

Plus the existing safety badges (PAPER-ONLY / LIVE TRADING PROHIBITED / LEVEL 7 PROHIBITED / gate).

## Required fields coverage
governance controller ✓ · last run status ✓ · next run ✓ · failures ✓ · retired legacy cron count ✓
· active legacy governance cron count ✓ · safety badges ✓.

## No v2 UI
`git status | grep command-center-v2` → empty. All changes under `apps/command-center-v3/` + `api_v2.py`
(shared backend namespace). v2 frozen.

---
*v3 governance visibility complete; read-only; no v2 UI changed.*
