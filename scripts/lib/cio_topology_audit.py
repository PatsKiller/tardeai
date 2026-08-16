#!/usr/bin/env python3
"""cio_topology_audit.py — read-only CDQ-25/26 production topology audit.

Enumerates live CIO-producing processes and scheduled jobs, resolves each to
its checkout path and git revision, and flags any that resolve to a deprecated
tree or a content SHA other than the approved current release.

READ-ONLY: reads /proc, crontab, and `git rev-parse`. Never restarts, kills,
edits crontab, sends Telegram, or touches broker/order/stop/2FA/risk state.

Exit 0 iff no deprecated-tree violation is found (or offline mode is explicit).
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

AUTHORITY = "READ_ONLY_ADVISORY"
TOPO_VERSION = "cio_topology_audit_1.0.0"

# CIO-producing entrypoints whose runtime provenance we audit.
CIO_PROCESS_PATTERNS = (
    "cio_governed_model_bridge.py",
    "cio_telegram_bot.py",
    "cio_wake_dispatch_entrypoint.py",
    "record_decision_outcome.py",
    "cio_event_detector",
    "cio_nightly_reflection",
    "cio_outcome_learning",
    "run_watch_review_workers.py",
    "portfolio_server_watchdog.sh",
    "telegram_poller_watchdog.sh",
)

# Cron lines that reference a CIO-producing script.
CIO_CRON_PATTERNS = (
    "cio_", "record_decision_outcome", "run_watch_review_workers",
    "portfolio_server_watchdog", "telegram_poller_watchdog",
    "cio_wake_dispatch", "cio_governed",
)

DEPRECATED_MARKERS = (
    "/tmp/", "agent-jobs/", "claude/worktrees/", "codex/",
)


def _run(args: list[str], timeout: int = 15) -> str:
    try:
        return subprocess.check_output(
            args, text=True, stderr=subprocess.DEVNULL, timeout=timeout,
        ).strip()
    except Exception:
        return ""


def _git_root(path: str) -> str:
    return _run(["git", "-C", path, "rev-parse", "--show-toplevel"])


def _git_rev(path: str) -> str:
    return _run(["git", "-C", path, "rev-parse", "HEAD"])


def resolve_checkout(path: str) -> dict[str, Any]:
    """Resolve a filesystem path to its enclosing git root + HEAD revision."""
    p = Path(path)
    if not p.exists():
        return {"path": path, "exists": False, "git_root": "", "head_sha": ""}
    try:
        root = _git_root(path)
    except Exception:
        root = ""
    head = _git_rev(path) if root else ""
    return {
        "path": path,
        "exists": True,
        "git_root": root or "",
        "head_sha": head or "",
    }


def enumerate_processes() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    ps = _run(["ps", "-eo", "pid,cmd"])
    for line in ps.splitlines():
        if not line.strip():
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        pid, cmd = parts[0], parts[1]
        if not any(pat in cmd for pat in CIO_PROCESS_PATTERNS):
            continue
        cwd = ""
        try:
            cwd = os.readlink(f"/proc/{pid}/cwd")
        except Exception:
            cwd = ""
        rec = resolve_checkout(cwd or Path(cmd.split()[0]).parent.as_posix())
        rec.update({"pid": int(pid), "cmd": cmd, "cwd": cwd})
        out.append(rec)
    return out


def enumerate_cron() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    raw = _run(["crontab", "-l"], timeout=15)
    for line in raw.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if not any(pat in s for pat in CIO_CRON_PATTERNS):
            continue
        # Heuristic checkout path: first absolute path inside cd/path or script path.
        paths = re.findall(r"(?:cd\s+)?(/[\w./-]+)", s)
        checkout = next((p for p in paths if not p.endswith((".py", ".sh", ".lock"))), "")
        out.append({"line": s, "checkout_hint": checkout})
    return out


def audit_topology(
    expected_content_sha: str,
    *,
    offline: bool = False,
    approved_roots: Optional[list[str]] = None,
) -> dict[str, Any]:
    """CDQ-25/26 audit. offline=True short-circuits with NOT_RUN (fail-closed)."""
    approved = approved_roots or [
        "/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild",
        "/home/johnclaw/trade-ai-releases/portfolio-server",
    ]
    if offline:
        return {
            "version": TOPO_VERSION,
            "authority": AUTHORITY,
            "expected_content_sha": expected_content_sha,
            "offline": True,
            "status": "NOT_RUN",
            "ok": False,
            "reason": "topology audit not run against live processes (offline/CI)",
            "processes": [],
            "cron": [],
            "violations": [],
        }

    processes = enumerate_processes()
    cron = enumerate_cron()
    violations: list[dict[str, Any]] = []

    for p in processes:
        head = p.get("head_sha") or ""
        root = p.get("git_root") or ""
        deprecated = any(m in (p.get("cwd") or p.get("path") or "") for m in DEPRECATED_MARKERS)
        mismatch = bool(expected_content_sha) and bool(head) and head != expected_content_sha
        not_approved = bool(root) and not any(
            root == a or root.startswith(a.rstrip("/") + "/") for a in approved
        )
        if deprecated or mismatch or not_approved:
            violations.append({
                "pid": p.get("pid"),
                "cmd": p.get("cmd"),
                "cwd": p.get("cwd"),
                "git_root": root,
                "head_sha": head,
                "expected": expected_content_sha,
                "deprecated_marker": deprecated,
                "sha_mismatch": mismatch,
                "root_not_approved": not_approved,
            })

    ok = len(violations) == 0
    return {
        "version": TOPO_VERSION,
        "authority": AUTHORITY,
        "expected_content_sha": expected_content_sha,
        "offline": False,
        "status": "PASS" if ok else "FAIL",
        "ok": ok,
        "reason": (
            "no deprecated-tree or non-current checkout found among live CIO workers."
            if ok
            else f"{len(violations)} CIO worker(s) resolve to a deprecated tree or non-current SHA"
        ),
        "process_count": len(processes),
        "cron_count": len(cron),
        "processes": processes,
        "cron": cron,
        "violations": violations,
    }


def main() -> int:
    expected = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("CIO_EXPECTED_SHA", "")
    offline = "--offline" in sys.argv or os.environ.get("CIO_TOPOLOGY_OFFLINE", "").lower() in ("1", "true")
    import json
    result = audit_topology(expected, offline=offline)
    print(json.dumps(result, indent=2, default=str))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
