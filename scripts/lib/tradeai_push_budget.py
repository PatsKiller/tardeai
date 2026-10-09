"""Local-only remote-push budget. State lives under the git-dir, never in source."""
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MAX_WITHOUT_OVERRIDE = 2
STATE_NAME = "tradeai-push-budget.json"

# Time-boxed program exceptions to the default budget (AI_WORK_POLICY.md §3/§17).
# A branch gets `budget` authorized pushes only when its name starts with `prefix`
# (exact, case-sensitive, no glob), has at least one character after the prefix,
# and `now` is not later than `ends_at`. Everything else gets MAX_WITHOUT_OVERRIDE.
PROGRAM_WINDOWS: tuple[dict[str, Any], ...] = (
    {
        "prefix": "n8nmat/",
        "budget": 4,
        "ends_at": "2026-10-12T23:59:59-04:00",
        "policy": "AGENTS.md 4.1.0 §23.13",
    },
)


def git_dir() -> Path:
    out = subprocess.check_output(["git", "rev-parse", "--absolute-git-dir"], text=True).strip()
    return Path(out)


def current_branch() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], text=True
        ).strip()
    except subprocess.CalledProcessError:
        return "HEAD"


def state_path() -> Path:
    override = os.environ.get("TRADEAI_PUSH_BUDGET_PATH")
    if override:
        return Path(override)
    return git_dir() / STATE_NAME


def _empty(branch: str) -> dict[str, Any]:
    return {
        "tranche_id": branch,
        "authorized_push_count": 0,
        "last_push_at": None,
        "last_branch": None,
    }


def load_state() -> dict[str, Any]:
    branch = current_branch()
    path = state_path()
    if not path.is_file():
        return _empty(branch)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty(branch)
    if not isinstance(data, dict):
        return _empty(branch)
    if data.get("tranche_id") not in {None, branch}:
        return _empty(branch)
    data.setdefault("tranche_id", branch)
    data.setdefault("authorized_push_count", 0)
    data.setdefault("last_push_at", None)
    data.setdefault("last_branch", None)
    return data


def save_state(data: dict[str, Any]) -> None:
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _now(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    if now.tzinfo is None:
        # Naive datetimes are treated as UTC so the comparison never raises.
        return now.replace(tzinfo=timezone.utc)
    return now


def budget_for(branch: str | None, now: datetime | None = None) -> int:
    """Authorized pushes allowed for `branch` at `now` before an override is needed."""
    if not branch:
        return MAX_WITHOUT_OVERRIDE
    at = _now(now)
    for window in PROGRAM_WINDOWS:
        prefix = str(window["prefix"])
        if not branch.startswith(prefix) or len(branch) <= len(prefix):
            continue
        if at > datetime.fromisoformat(str(window["ends_at"])):
            continue
        return int(window["budget"])
    return MAX_WITHOUT_OVERRIDE


def remaining(count: int, *, branch: str | None = None, now: datetime | None = None) -> int:
    left = budget_for(branch, now) - int(count or 0)
    return left if left > 0 else 0


def decide(
    *,
    authorized: bool,
    override: bool,
    count: int,
    branch: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    budget = budget_for(branch, now)
    if not authorized:
        return {
            "allow": False,
            "reason": "UNAUTHORIZED",
            "count": count,
            "remaining": remaining(count, branch=branch, now=now),
            "budget": budget,
        }
    if count >= budget and not override:
        return {
            "allow": False,
            "reason": "BUDGET_EXCEEDED",
            "count": count,
            "remaining": 0,
            "budget": budget,
        }
    return {
        "allow": True,
        "reason": "OVERRIDE" if (count >= budget and override) else "AUTHORIZED",
        "count": count,
        "remaining": remaining(count, branch=branch, now=now) if count < budget else 0,
        "budget": budget,
    }


def record_authorized_push() -> dict[str, Any]:
    data = load_state()
    branch = current_branch()
    data["tranche_id"] = branch
    data["authorized_push_count"] = int(data.get("authorized_push_count") or 0) + 1
    data["last_push_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    data["last_branch"] = branch
    save_state(data)
    return data
