"""Named repair services own long work outside health-tick's cgroup.

Acceptance is pending work, never evidence of recovery. No arbitrary command or
shell text crosses this boundary. Unit installation is an operator action.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

KINDS = frozenset({"enrichment", "orchestrator"})


def request_repair(kind: str, *, dry_run: bool = False) -> dict:
    if kind not in KINDS:
        raise ValueError("unknown pipeline repair kind")
    unit = f"tradeai-pipeline-repair@{kind}.service"
    command = ["systemctl", "--user", "start", "--no-block", unit]
    result = {
        "ok": False,
        "accepted": False,
        "recovered": False,
        "unit": unit,
        "outcome": "PENDING",
        "note": "independent repair requested; completion must be verified",
    }
    if dry_run:
        return {**result, "dry_run": True, "command": command}
    try:
        check = subprocess.run(
            ["systemctl", "--user", "show", unit, "--property=LoadState", "--value"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if check.returncode or check.stdout.strip() != "loaded":
            return {
                **result,
                "outcome": "FAILED",
                "exit_code": 1,
                "error": "repair unit not installed/loaded; operator installation required",
            }
        started = subprocess.run(command, capture_output=True, text=True, timeout=5)
        if started.returncode:
            return {
                **result,
                "outcome": "FAILED",
                "exit_code": started.returncode,
                "error": "repair service request failed",
            }
        return {**result, "accepted": True, "exit_code": 0}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {**result, "outcome": "FAILED", "exit_code": 1, "error": type(exc).__name__}


def independently_owned(kind: str) -> bool:
    """Sessions and environment markers do not establish cgroup ownership."""
    unit = f"tradeai-pipeline-repair@{kind}.service"
    try:
        paths = [
            line.split(":", 2)[2].strip().split("/") for line in Path("/proc/self/cgroup").read_text().splitlines()
        ]
    except (OSError, IndexError):
        return False
    return any(unit in parts for parts in paths) and not any("tradeai-health-tick.service" in parts for parts in paths)
