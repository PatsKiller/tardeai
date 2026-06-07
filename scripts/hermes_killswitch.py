#!/usr/bin/env python3
"""hermes_killswitch.py — canonical Hermes runtime kill-switch (Phase 214).

Single source of truth so no Hermes job ever depends on the RETIRED sidecar path. The canonical kill-switch
is the project runtime file `data/runtime/HERMES_DISABLED`. The retired sidecar paths (`~/.hermes/DISABLED`,
`hermes_sidecar/.hermes*/DISABLED`) are IGNORED (audit-only) — present-but-ignored is reported, never tripped.

  from hermes_killswitch import is_hermes_disabled, get_killswitch_path, describe_killswitch
  disabled, path = is_hermes_disabled()              # canonical only
  disabled, path = is_hermes_disabled(extra=[...])   # plus per-job extra stop files (e.g. COORDINATOR_DISABLED)

Env override: HERMES_KILL_SWITCH_PATH (absolute path). Never defaults to a retired sidecar path.
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CANONICAL = ROOT / "data" / "runtime" / "HERMES_DISABLED"
# retired sidecar kill-switch locations — IGNORED by active code (kept only to detect+warn, never to trip)
RETIRED_PATHS = [Path.home() / ".hermes" / "DISABLED",
                 ROOT / "hermes_sidecar" / ".hermes" / "DISABLED"]


def get_killswitch_path() -> Path:
    """Canonical kill-switch path (env override allowed; never a retired sidecar path)."""
    env = os.environ.get("HERMES_KILL_SWITCH_PATH")
    return Path(env).expanduser() if env else CANONICAL


def is_hermes_disabled(extra=None):
    """(disabled, path). True if the canonical kill-switch (or any per-job `extra` stop file) exists.
    Retired sidecar paths are NEVER treated as active."""
    candidates = [get_killswitch_path()] + [Path(p) for p in (extra or [])]
    for p in candidates:
        try:
            if p.exists():
                return True, str(p)
        except Exception:
            continue
    return False, ""


def describe_killswitch() -> dict:
    """Read-only status for v3/SIEM: canonical path, active state, retired paths (ignored)."""
    active, path = is_hermes_disabled()
    retired_present = [str(p) for p in RETIRED_PATHS if p.exists()]
    return {
        "canonical_path": "data/runtime/HERMES_DISABLED",
        "resolved_path": str(get_killswitch_path()),
        "active": active,
        "active_path": path or None,
        "env_override": os.environ.get("HERMES_KILL_SWITCH_PATH"),
        "retired_paths_ignored": [str(p) for p in RETIRED_PATHS],
        "retired_present_but_ignored": retired_present,
        "note": ("retired sidecar kill-switch ignored; use data/runtime/HERMES_DISABLED"
                 if retired_present else "canonical kill-switch only; no retired path present"),
    }


if __name__ == "__main__":
    import json
    print(json.dumps(describe_killswitch(), indent=2))
