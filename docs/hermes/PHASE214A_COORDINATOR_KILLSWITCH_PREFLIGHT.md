# PHASE 214A — Coordinator Kill-Switch Preflight (2026-06-07)

Status:      HISTORICAL
as_of:       2026-06-07T17:19:21-04:00
Measured at: efcc51365 / not measured

- Coordinator: `scripts/hermes_coordinator.py`, cron `*/15 * * * *` (flock-guarded); no systemd timer.
- Kill-switch (before): `KILL_FILES = [data/runtime/HERMES_DISABLED, data/runtime/COORDINATOR_DISABLED]` — **already canonical**.
- Retired path `.hermes/DISABLED` references in active code: **NONE** (only docstrings/comments + audit/inventory scanners that list retired dirs read-only).
- Retired DISABLED files on disk: absent (`~/.hermes/DISABLED`, `hermes_sidecar/.hermes*/DISABLED`).
- Intended canonical path: `data/runtime/HERMES_DISABLED`.
- Conclusion: retired path is **not read by active code**; P1 is a hardening/centralization task, not a live bug fix.
