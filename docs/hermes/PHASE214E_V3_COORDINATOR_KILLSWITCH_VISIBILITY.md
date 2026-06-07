# PHASE 214E — v3 Kill-Switch Visibility (2026-06-07)
`/api/v2/hermes/health` now returns a `kill_switch` block from `describe_killswitch()`: canonical_path
(data/runtime/HERMES_DISABLED), active, active_path, env_override, retired_paths_ignored,
retired_present_but_ignored, note. Read-only; no run/enable controls. No v2 UI built. Verified live:
active=false, retired ignored, "canonical kill-switch only; no retired path present".
