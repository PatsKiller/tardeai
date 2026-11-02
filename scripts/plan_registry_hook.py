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
import os
import stat
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import plan_registry as pr  # noqa: E402

#: A plan is text. The hook must never copy an arbitrary file into a SHARED registry (review
#: 2026-11-02, B2): a payload naming ``secret.env`` stored its contents as a plan body. The path is
#: constrained to the directories a client actually writes plans in, must be a regular file (not a
#: symlink) and is size-capped.
MAX_PLAN_BYTES = 256 * 1024


def plan_file_roots() -> list[Path]:
    """Where a client may keep a plan file: the state root, ``~/.claude`` and the temp dir."""
    roots = [Path(os.environ.get("TRADEAI_STATE_ROOT")
                  or (Path.home() / "trade-ai-releases" / "persistent-state")),
             Path.home() / ".claude",
             Path(tempfile.gettempdir())]
    out = []
    for r in roots:
        try:
            out.append(r.resolve())
        except OSError:
            continue
    return out


def read_plan_file(raw: str) -> str:
    """The plan text at ``raw``, or ``""`` when it is not a bounded regular file in a plan root."""
    try:
        path = Path(raw)
        st = path.lstat()
    except OSError:
        return ""
    if not stat.S_ISREG(st.st_mode) or st.st_size > MAX_PLAN_BYTES:
        return ""  # symlinks (lstat) and oversize files are never plan input
    try:
        resolved = path.resolve()
    except OSError:
        return ""
    if not any(resolved == root or root in resolved.parents for root in plan_file_roots()):
        return ""
    try:
        data = path.read_bytes()
    except OSError:
        return ""
    if len(data) > MAX_PLAN_BYTES:
        return ""
    return data.decode("utf-8", errors="replace")


def plan_from_payload(payload: dict) -> str:
    """The APPROVED text, in the order Claude Code actually sends it.

    Since 2.1.269 ExitPlanMode arrives with an empty ``tool_input`` and the approved text (including
    the operator's edits) in ``tool_response.plan``, then ``planFilePath``; older builds put it in
    ``tool_input.plan``. Reading only tool_input stored the pre-edit plan.
    """
    response = payload.get("tool_response")
    response = response if isinstance(response, dict) else {}
    value = response.get("plan")
    if isinstance(value, str) and value.strip():
        return value
    for source in (response, payload):
        for key in ("planFilePath", "plan_file_path"):
            path = source.get(key)
            if isinstance(path, str) and path.strip():
                text = read_plan_file(path)
                if text.strip():
                    return text
    tool_input = payload.get("tool_input")
    if isinstance(tool_input, str):
        return tool_input
    if isinstance(tool_input, dict):
        for key in ("plan", "content", "text"):
            candidate = tool_input.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate
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
    if not isinstance(payload, dict):
        print("plan_registry_hook: payload is not an object", file=sys.stderr)
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
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except BaseException as exc:  # noqa: BLE001 - a hook must never block the planner
        print(f"plan_registry_hook: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(0) from None
