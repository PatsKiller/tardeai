"""lane_registry_drift.py — the registry gate's findings as stable incident items.

Roadmap Phase 2 PR-B (2026-10-08). `check_lane_registry.py --fail-on-new --state-drift` runs in CI and by
hand; between runs a lane that drifts (a NEVER_SCHEDULED row whose line is live, a cron line nobody
declared) is invisible. This module applies the SAME library calls the gate applies — validate_registry,
find_undeclared, lane_state_drift.classify_lanes/conflicts — to inputs the caller supplies, and returns
one finding per violation with an item string that is stable across runs (never the command text).

Consumed by scripts/n8n_incident_fanin.py (source `lane_registry`). Pure: no subprocess, no file write.

AUTHORITY: READ_ONLY_ADVISORY.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Optional

from scripts.lib.lane_registry import discover_cron, find_undeclared, validate_registry
from scripts.lib.lane_state_drift import classify_lanes, conflicts

SCHEMA = "LaneRegistryDriftFindings@v1"
UNDECLARED_CRON = "UNDECLARED_CRON"
UNDECLARED_UNIT = "UNDECLARED_UNIT"
STATE_DRIFT = "STATE_DRIFT"
STRUCTURAL = "STRUCTURAL"
SEVERITY = {UNDECLARED_CRON: "P2", UNDECLARED_UNIT: "P2", STATE_DRIFT: "P2", STRUCTURAL: "P1"}


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _cron_hint(expression: str) -> str:
    """Schedule plus the script basename — enough to find the line, never the full command."""
    parts = expression.split()
    sched = " ".join(parts[:5]) if len(parts) >= 5 else expression[:24]
    script = ""
    for tok in parts[5:]:
        if tok.endswith((".py", ".sh")):
            script = tok.rsplit("/", 1)[-1]
            break
    return f"{sched} {script}".strip()[:80]


def findings(registry: dict[str, Any], crontab_text: str, systemd_units: list[str], *,
             state_root: Optional[Path] = None, host_state: Optional[dict[str, Any]] = None) -> list[dict[str, Any]]:
    """One finding per gate violation: {code, item, severity, detail}.

    ``systemd_units`` are timer unit names (as `systemctl --user list-unit-files --type=timer` lists them);
    without ``host_state`` a systemd lane's drift is NOT_MEASURED, exactly as the gate reports it without
    `--host-state-json`. ``state_root`` is accepted for symmetry with the gate and unused here.
    """
    del state_root
    found = {"cron": discover_cron(crontab_text or ""), "cron_commented": [],
             "systemd": [{"kind": "systemd", "expression": str(u)} for u in (systemd_units or [])]}
    out: list[dict[str, Any]] = []
    for err in validate_registry(registry):
        out.append({"code": STRUCTURAL, "item": f"structural:{_digest(str(err))}", "severity": SEVERITY[STRUCTURAL],
                    "detail": str(err)[:160]})
    for u in find_undeclared(registry, found):
        expr = str(u.get("expression") or "")
        if u.get("kind") == "systemd":
            out.append({"code": UNDECLARED_UNIT, "item": f"unit:{expr}", "severity": SEVERITY[UNDECLARED_UNIT],
                        "detail": f"timer {expr} has no lane row and is not in the baseline"})
        else:
            out.append({"code": UNDECLARED_CRON, "item": f"cron:{_digest(expr)}", "severity": SEVERITY[UNDECLARED_CRON],
                        "detail": f"undeclared cron line {_cron_hint(expr)}"})
    rows = classify_lanes(registry.get("lanes") or [], cron_rows=found["cron"], timer_state_fn=None, host_state=host_state)
    for r in conflicts(rows):
        out.append({"code": STATE_DRIFT, "item": f"drift:{r.get('lane_id')}:{r.get('code')}", "severity": SEVERITY[STATE_DRIFT],
                    "detail": f"{r.get('lane_id')} declared {r.get('declared_state')} but {r.get('code')}"})
    return out
