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


def remaining(count: int) -> int:
    left = MAX_WITHOUT_OVERRIDE - int(count or 0)
    return left if left > 0 else 0


def decide(*, authorized: bool, override: bool, count: int) -> dict[str, Any]:
    if not authorized:
        return {
            "allow": False,
            "reason": "UNAUTHORIZED",
            "count": count,
            "remaining": remaining(count),
        }
    if count >= MAX_WITHOUT_OVERRIDE and not override:
        return {
            "allow": False,
            "reason": "BUDGET_EXCEEDED",
            "count": count,
            "remaining": 0,
        }
    return {
        "allow": True,
        "reason": "OVERRIDE" if (count >= MAX_WITHOUT_OVERRIDE and override) else "AUTHORIZED",
        "count": count,
        "remaining": remaining(count) if count < MAX_WITHOUT_OVERRIDE else 0,
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
