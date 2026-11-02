#!/usr/bin/env python3
"""Claude Code PostToolUse hook: an approved ExitPlanMode plan goes into the plan registry.

Wired by the operator in `~/.claude/settings.json` (the snippet lives in docs/ops/PLAN_REGISTRY.md;
the repository never edits that file). Claude Code posts one JSON document on stdin:

    {"session_id": "...", "tool_name": "ExitPlanMode", "tool_input": {"plan": "..."}}

The plan text is read from ``tool_input.plan`` (falling back to a plain string ``tool_input``), and
written as an approved plan with vendor ``claude`` and the session id as its author. The SAME plan
produces the same plan id, so a retried hook never duplicates a plan.

Never fails the tool: a registry problem is reported on stderr and the exit status is 0, because a
hook that blocks ExitPlanMode would stop the operator's own planning.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import plan_registry as pr  # noqa: E402


def plan_from_payload(payload: dict) -> str:
    tool_input = payload.get("tool_input")
    if isinstance(tool_input, str):
        return tool_input
    if isinstance(tool_input, dict):
        for key in ("plan", "content", "text"):
            value = tool_input.get(key)
            if isinstance(value, str) and value.strip():
                return value
    return ""


def title_from_plan(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip()[:120] or "Approved plan"
        if stripped:
            return stripped[:120]
    return "Approved plan"


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except ValueError as exc:
        print(f"plan_registry_hook: unreadable payload ({exc})", file=sys.stderr)
        return 0
    if str(payload.get("tool_name") or "") != "ExitPlanMode":
        return 0
    text = plan_from_payload(payload)
    if not text.strip():
        print("plan_registry_hook: ExitPlanMode payload carried no plan text", file=sys.stderr)
        return 0
    session = str(payload.get("session_id") or "unknown-session")
    try:
        pid = pr.Registry().add(title=title_from_plan(text), body=text, author=session,
                                vendor="claude", approved_at=pr._utc())
        print(f"plan_registry_hook: {pid}", file=sys.stderr)
    except Exception as exc:  # noqa: BLE001 - the hook must never block the planner
        print(f"plan_registry_hook: {type(exc).__name__}: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
