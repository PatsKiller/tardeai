# PHASE 214D — Coordinator Repoint (2026-06-07)

Status:      HISTORICAL
as_of:       2026-06-07T17:19:21-04:00
Measured at: efcc51365 / not measured

`hermes_coordinator.py`: removed the inline `KILL_FILES` list; `kill_switch_active()` now calls
`hermes_killswitch.is_hermes_disabled(extra=[COORDINATOR_DISABLED])`. Semantics preserved: aborts when
`data/runtime/HERMES_DISABLED` (or COORDINATOR_DISABLED) exists; never consults the retired `.hermes/DISABLED`.
Other active jobs already use the canonical inline path (no change needed; documented). Cadence unchanged
(cron */15). Status (`/api/v2/hermes/health`) reports the canonical path + retired-ignored list.
