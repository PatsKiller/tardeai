# PHASE 214B — Coordinator Kill-Switch Root Cause (2026-06-07)

Status:      HISTORICAL
as_of:       2026-06-07T17:19:21-04:00
Measured at: efcc51365 / not measured

- Checker: `hermes_coordinator.py::kill_switch_active()` (was an inline list of canonical paths).
- Retired path hard-coded? **No** (active code never referenced `.hermes/DISABLED`).
- Configured via env? Now optionally yes (`HERMES_KILL_SWITCH_PATH`); default canonical.
- Other agents checking retired path? **No** — all `hermes_*.py` use `data/runtime/HERMES_DISABLED` inline.
- Multiple kill-switches? Coordinator extra `COORDINATOR_DISABLED`; unrelated `HIGH_LLM_SCHEDULER_DISABLED`; librarian extra `LIBRARIAN_DISABLED` — all canonical project paths.
- v3 displays it: `/api/v2/hermes/health` (kill_switch_path). SIEM/Queue: no retired path shown.
- Desired behavior on touch: Coordinator aborts next tick (preserved).
- Safe to centralize via helper without semantic change: **YES** (verified by tests, Phase 214F).
- Root cause: historical concern; resolved in code already — this phase locks it in via a shared helper.
- Affected files: hermes_coordinator.py, api_v2.py (status enrich), new scripts/hermes_killswitch.py.
- Rollback: revert the 3 files (no data/schema/cadence change). Test: Phase 214F.
