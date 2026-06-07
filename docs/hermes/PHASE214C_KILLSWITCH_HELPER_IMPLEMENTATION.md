# PHASE 214C — Canonical Kill-Switch Helper (2026-06-07)
`scripts/hermes_killswitch.py`: canonical `data/runtime/HERMES_DISABLED`; env override `HERMES_KILL_SWITCH_PATH`
(never defaults to a retired path). Functions: `is_hermes_disabled(extra=None)->(bool,str)`,
`get_killswitch_path()->Path`, `describe_killswitch()->dict`. Retired sidecar paths (`~/.hermes/DISABLED`,
`hermes_sidecar/.hermes/DISABLED`) are **ignored** (reported as present-but-ignored, never tripped); they are
not deleted. CLI: `python3 scripts/hermes_killswitch.py` prints describe JSON.
