#!/usr/bin/env python3
"""Claude Code PostToolUse hook: an ExitPlanMode plan is registered in the plan registry.

Wired by the operator in `~/.claude/settings.json` (the snippet lives in docs/ops/PLAN_REGISTRY.md;
the repository never edits that file). Claude Code posts one JSON document on stdin:

    {"session_id": "...", "tool_name": "ExitPlanMode", "tool_input": {"plan": "..."}}

The plan text is read from ``tool_input.plan`` (falling back to a plain string ``tool_input``), and
written with vendor ``claude`` and the session id as its author. The status is the registry default
(``registered``): the hook records that the plan exists, never that it was approved. The SAME plan
produces the same plan id, so a retried hook never duplicates a plan.

Never fails the tool: a registry problem is reported on stderr and the exit status is 0, because a
hook that blocks ExitPlanMode would stop the operator's own planning.
"""
from __future__ import annotations

import json
import os
import re
import stat
import sys
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
    """The only two places a client actually writes a plan: the plan store, and ``~/.claude/plans``.

    Deliberately NOT the whole state root, all of ``~/.claude`` (credential files live there) or the
    temp dir (review 2, B1). A path outside these roots is never plan input.
    """
    state = Path(os.environ.get("TRADEAI_STATE_ROOT")
                 or (Path.home() / "trade-ai-releases" / "persistent-state"))
    out = []
    for r in (state / "data" / "coordination" / "plans", Path.home() / ".claude" / "plans"):
        try:
            out.append(r.resolve())
        except OSError:
            continue
    return out


#: A plan file is a named Markdown/plain-text document. Anything credential-shaped, extension-less,
#: dot-named or binary is refused before a byte is read (review 2, B1).
_PLAN_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]*\.(md|markdown|txt)$", re.IGNORECASE)
_BAD_NAME_RE = re.compile(r"(credential|passwd|password|secret|token|apikey|api[_-]key|\.env|id_rsa|id_ed25519|\.pem|\.key)",
                          re.IGNORECASE)


def plan_name_ok(name: str) -> bool:
    return bool(_PLAN_NAME_RE.match(name or "")) and not _BAD_NAME_RE.search(name)


def _within(path: Path, roots: list[Path]) -> bool:
    return any(path == root or root in path.parents for root in roots)


def read_plan_file(raw: str) -> str:
    """The plan text at ``raw``, or ``""`` when it is not a bounded plan-shaped file in a plan root.

    One descriptor does the whole job (review 2, B2): ``O_NOFOLLOW`` refuses a symlinked final
    component, ``fstat`` on that descriptor decides regular/size, and containment is proven on
    ``/proc/self/fd/<fd>`` — the file actually opened — so a swap between a check and the read cannot
    redirect it. If the kernel cannot tell us where the descriptor points, nothing is read.
    """
    try:
        path = Path(raw)
    except (TypeError, ValueError):
        return ""
    if not plan_name_ok(path.name):
        return ""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        return ""
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size > MAX_PLAN_BYTES:
            return ""
        try:
            real = Path(os.readlink(f"/proc/self/fd/{fd}")).resolve()
        except OSError:
            return ""  # cannot prove where the descriptor points: fail closed
        if not _within(real, plan_file_roots()):
            return ""
        data = os.read(fd, MAX_PLAN_BYTES + 1)
    finally:
        os.close(fd)
    if len(data) > MAX_PLAN_BYTES:
        return ""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return ""
    return "" if "\x00" in text else text


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
        # No approved_at: the hook records that the plan exists, never when it was "approved".
        pid = pr.Registry().add(title=title_from_plan(text), body=text, author=session, vendor="claude")
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
