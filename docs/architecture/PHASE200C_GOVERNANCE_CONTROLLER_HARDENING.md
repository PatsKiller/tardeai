# Phase 200C — Governance Controller Hardening

Status:      HISTORICAL
as_of:       2026-06-04T23:13:34-04:00
Measured at: efcc51365 / not measured

`scripts/pipelines/run_governance_pipeline.sh` upgraded from a dry-run skeleton (199E) to a real
executor for the **governance reporting** steps. No schedule wired yet (that's 200G).

## Properties
- Strict bash (`set -euo pipefail`); safe env load via `_pipeline_common.sh`.
- **Safety assertions (abort nonzero):** `assert_no_live_trading` (ALPACA_MODE=paper, LIVE off),
  `assert_no_level7`; plus an explicit "governance reporting only — no broker/trading/proposal/
  protection steps" attestation line.
- **DRY_RUN=1 default**; `--apply` required to actually run steps.
- Per-run log → `logs/pipelines/governance/governance_<UTC>.log`.
- `flock` lock (`/tmp/pipeline_governance-pipeline.lock`) — no overlapping controller runs.
- Each step is a named `gov_step` logging START/END/status/duration.
- **Non-cascading:** a failed report sets `overall=degraded` and is recorded, but never aborts the
  other steps or any unrelated trading/protection job (`gov_step` always returns 0).
- **Machine-readable summary** → `data/runtime/governance_pipeline_last_run.json`
  (pipeline, run_ts, dry_run, overall_status, per-step name/status/ms, log path).

## Steps (governance reporting only)
1. `a1a_docs_audit` → `run_scheduled_a1a_check.sh`
2. `system_facts` → `run_scheduled_system_facts.sh`
3. `governance_status` → `report_governance_status.py` (→ docs/governance/governance_status_latest.*)
4. `maturity_control_board` → `run_scheduled_maturity_control_board.sh`
5. `operator_readiness` → `report_operator_readiness_summary.py` (→ docs/maturity_hardening/operator_readiness_latest.*)
6. `state_of_repo` → `generate_state_of_repo_snapshot.py` (→ docs/project/STATE_OF_REPO_LATEST.md)

The underlying scripts keep their own `flock`s, so controller-invoked + legacy-scheduled runs cannot
overlap each other during the parallel-observation window.

## Explicitly NOT in this controller
- Safety net (`system_freshness_monitor`, `freshness_watchdog_heartbeat`) — runs independently, never
  disabled here.
- Any broker / trading / proposal / ATM / protection / Hermes / LLM / portfolio / data-feed step.

---
*Hardened, not scheduled. DRY_RUN default; safety-assert + lock + summary JSON; reporting-only.*
