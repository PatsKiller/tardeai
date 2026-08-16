#!/usr/bin/env python3
"""cio_topology_audit.py — read-only CDQ-25/26 production topology audit.

Enumerates live CIO-producing processes, scheduled jobs (user + system cron),
and systemd services/timers, resolves each to its checkout path and git
revision, and flags any that resolve to a deprecated tree or a content SHA
other than the approved current release.

CDQ-26 means "no deprecated-tree ownership" — a deprecated root is never
acceptable just because someone pointed it at the latest SHA. Deprecated roots
are flagged on their own, independent of SHA match.

READ-ONLY: reads /proc, crontab files, `git rev-parse`, and `systemctl`
read-only queries. Never restarts, kills, edits crontab, sends Telegram, or
touches broker/order/stop/2FA/risk state.

Exit 0 iff no violation is found (offline mode short-circuits NOT_RUN).
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

AUTHORITY = "READ_ONLY_ADVISORY"
TOPO_VERSION = "cio_topology_audit_1.1.0"

# The approved production release root. Deprecated development/worktree trees
# must NOT be here — only the deployed CURRENT release tree is an approved root.
APPROVED_ROOT_DEFAULT = "/home/johnclaw/trade-ai-releases/portfolio-server"

# Explicit deprecated roots. The old rebuild tree is deprecated ownership no
# matter what SHA it sits on (preflight found cio_governed_model_bridge.py
# running from here, 124 commits behind main).
DEPRECATED_ROOTS = (
    "/home/johnclaw/trade-ai-v12-rebuild",
)

# Path substrings that always indicate a throwaway / non-production checkout.
DEPRECATED_MARKERS = (
    "/tmp/", "agent-jobs/", "claude/worktrees/", "codex/", "/dev/shm/",
)

# CIO-producing entrypoints whose runtime provenance we audit. Covers the
# governed bridge, Telegram bot/converse, wake dispatch, outcome/reflection/
# learning/maturity workers, material scanner, notification delivery, defer/
# revisit workers, watch-review workers, and the portfolio server + watchdogs.
CIO_PROCESS_PATTERNS = (
    "cio_governed_model_bridge",
    "cio_telegram_bot",
    "cio_telegram_converse",
    "cio_wake_dispatch",
    "record_decision_outcome",
    "cio_event_detector",
    "cio_nightly_reflection",
    "cio_outcome_learning",
    "cio_production_case",
    "cio_material_scan",
    "cio_notification_delivery",
    "cio_defer",
    "cio_revisit",
    "run_watch_review_workers",
    "cio_watch_review",
    "portfolio_server",
    "telegram_poller_watchdog",
)

# Substrings identifying CIO-related scheduled jobs (cron / systemd units).
CIO_SCHEDULE_PATTERNS = (
    "cio_", "record_decision_outcome", "run_watch_review_workers",
    "portfolio_server", "telegram_poller", "cio_wake_dispatch",
    "cio_governed", "outcome", "reflection", "maturity", "material_scan",
    "notification_delivery", "defer", "revisit", "watch_review",
)

_ABS_PATH_RE = re.compile(r"(?:cd\s+)?(/[\w@+./~-]+)")


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


def _is_deprecated_path(
    path: str,
    deprecated_roots: tuple[str, ...],
    deprecated_markers: tuple[str, ...],
) -> bool:
    p = (path or "").rstrip("/")
    if not p:
        return False
    for m in deprecated_markers:
        if m in p:
            return True
    for r in deprecated_roots:
        rn = r.rstrip("/")
        if p == rn or p.startswith(rn + "/"):
            return True
    return False


def _under_approved(root: str, approved_roots: tuple[str, ...]) -> bool:
    if not root:
        return False
    for a in approved_roots:
        an = a.rstrip("/")
        if root == an or root.startswith(an + "/"):
            return True
    return False


def _classify(
    *,
    path: str,
    root: str,
    head: str,
    expected: str,
    approved_roots: tuple[str, ...],
    deprecated_roots: tuple[str, ...],
    deprecated_markers: tuple[str, ...],
    extra: Optional[dict[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    """Return a violation dict if this checkout violates CDQ-25/26, else None."""
    deprecated = _is_deprecated_path(path, deprecated_roots, deprecated_markers) or \
        _is_deprecated_path(root, deprecated_roots, deprecated_markers)
    sha_mismatch = bool(expected) and bool(head) and head != expected
    not_approved = bool(root) and not _under_approved(root, approved_roots)
    if not (deprecated or sha_mismatch or not_approved):
        return None
    v: dict[str, Any] = {
        "path": path,
        "git_root": root,
        "head_sha": head,
        "expected": expected,
        "deprecated": deprecated,
        "sha_mismatch": sha_mismatch,
        "root_not_approved": not_approved,
    }
    if extra:
        v.update(extra)
    return v


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


def _cron_lines() -> list[dict[str, str]]:
    """Collect CIO-relevant cron lines from user + system crontab files."""
    lines: list[dict[str, str]] = []
    user = _run(["crontab", "-l"], timeout=15)
    for s in user.splitlines():
        if s.strip() and not s.strip().startswith("#"):
            lines.append({"source": "user_crontab", "line": s.strip()})
    for path in ("/etc/crontab",):
        try:
            for s in Path(path).read_text().splitlines():
                if s.strip() and not s.strip().startswith("#"):
                    lines.append({"source": path, "line": s.strip()})
        except Exception:
            pass
    try:
        for f in Path("/etc/cron.d").glob("*"):
            try:
                for s in f.read_text().splitlines():
                    if s.strip() and not s.strip().startswith("#"):
                        lines.append({"source": f"/etc/cron.d/{f.name}", "line": s.strip()})
            except Exception:
                pass
    except Exception:
        pass
    return [
        l for l in lines
        if any(pat in l["line"] for pat in CIO_SCHEDULE_PATTERNS)
    ]


def enumerate_cron() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for entry in _cron_lines():
        s = entry["line"]
        paths = _ABS_PATH_RE.findall(s)
        # Prefer a directory checkout (cd target), else the parent of a script.
        checkout = next(
            (p for p in paths if not p.endswith((".py", ".sh", ".lock", ".log"))),
            next((str(Path(p).parent) for p in paths), ""),
        )
        out.append({
            "source": entry["source"],
            "line": s,
            "checkout": checkout,
            "paths": paths,
        })
    return out


def enumerate_systemd() -> list[dict[str, Any]]:
    """Collect CIO-relevant systemd services + timers with their exec/working dirs."""
    out: list[dict[str, Any]] = []
    for unit_type in ("service", "timer"):
        listing = _run(
            ["systemctl", "list-units", f"--type={unit_type}",
             "--no-pager", "--no-legend", "--all"],
            timeout=20,
        )
        for line in listing.splitlines():
            if not line.strip():
                continue
            fields = line.split()
            if not fields:
                continue
            unit = fields[0]
            if not any(pat in unit for pat in CIO_SCHEDULE_PATTERNS):
                continue
            show = _run(
                ["systemctl", "show", unit, "--no-pager",
                 "-p", "ExecStart", "-p", "WorkingDirectory",
                 "-p", "ActiveState", "-p", "LoadState"],
                timeout=20,
            )
            props: dict[str, str] = {}
            for s in show.splitlines():
                if "=" in s:
                    k, v = s.split("=", 1)
                    props[k] = v
            out.append({
                "unit": unit,
                "unit_type": unit_type,
                "active_state": props.get("ActiveState", ""),
                "load_state": props.get("LoadState", ""),
                "exec_start": props.get("ExecStart", ""),
                "working_directory": props.get("WorkingDirectory", ""),
            })
    return out


def _validate_scheduled_entries(
    entries: list[dict[str, Any]],
    *,
    expected: str,
    approved_roots: tuple[str, ...],
    deprecated_roots: tuple[str, ...],
    deprecated_markers: tuple[str, ...],
    key_fn,
) -> list[dict[str, Any]]:
    """Validate cron/systemd entries: resolve checkout, flag deprecated/SHA/root."""
    violations: list[dict[str, Any]] = []
    for e in entries:
        # Candidate paths to validate: cron checkout + all paths, or systemd
        # ExecStart / WorkingDirectory.
        candidates = key_fn(e)
        flagged = False
        for c in candidates:
            if not c:
                continue
            resolved = resolve_checkout(c)
            v = _classify(
                path=c,
                root=resolved.get("git_root", ""),
                head=resolved.get("head_sha", ""),
                expected=expected,
                approved_roots=approved_roots,
                deprecated_roots=deprecated_roots,
                deprecated_markers=deprecated_markers,
                extra={"source": e},
            )
            if v:
                violations.append(v)
                flagged = True
                break
        if not flagged:
            # Even without a resolvable git root, a deprecated path string is a
            # violation (CDQ-26 deprecated-tree ownership).
            raw = " ".join(str(x) for x in candidates)
            if _is_deprecated_path(raw, deprecated_roots, deprecated_markers):
                violations.append({
                    "path": raw,
                    "git_root": "",
                    "head_sha": "",
                    "expected": expected,
                    "deprecated": True,
                    "sha_mismatch": False,
                    "root_not_approved": False,
                    "source": e,
                })
    return violations


def audit_topology(
    expected_content_sha: str,
    *,
    offline: bool = False,
    approved_roots: Optional[list[str]] = None,
    deprecated_roots: Optional[list[str]] = None,
) -> dict[str, Any]:
    """CDQ-25/26 audit. offline=True short-circuits NOT_RUN (fail-closed)."""
    approved = tuple(approved_roots) if approved_roots else (APPROVED_ROOT_DEFAULT,)
    deprecated = tuple(deprecated_roots) if deprecated_roots else DEPRECATED_ROOTS
    markers = DEPRECATED_MARKERS

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
            "systemd": [],
            "violations": [],
            "deprecated_roots": list(deprecated),
        }

    processes = enumerate_processes()
    cron = enumerate_cron()
    systemd = enumerate_systemd()
    violations: list[dict[str, Any]] = []

    for p in processes:
        v = _classify(
            path=p.get("cwd") or p.get("path") or "",
            root=p.get("git_root") or "",
            head=p.get("head_sha") or "",
            expected=expected_content_sha,
            approved_roots=approved,
            deprecated_roots=deprecated,
            deprecated_markers=markers,
            extra={"kind": "process", "pid": p.get("pid"), "cmd": p.get("cmd")},
        )
        if v:
            violations.append(v)

    # Cron: validate scheduled-job paths, not merely return them.
    violations.extend(_validate_scheduled_entries(
        cron,
        expected=expected_content_sha,
        approved_roots=approved,
        deprecated_roots=deprecated,
        deprecated_markers=markers,
        key_fn=lambda e: [e.get("checkout", "")] + list(e.get("paths", [])),
    ))

    # systemd services/timers: validate ExecStart + WorkingDirectory.
    def _systemd_candidates(e: dict[str, Any]) -> list[str]:
        cands: list[str] = []
        for field in ("working_directory", "exec_start"):
            val = e.get(field) or ""
            cands.extend(_ABS_PATH_RE.findall(val))
        return [c for c in cands if c]

    violations.extend(_validate_scheduled_entries(
        systemd,
        expected=expected_content_sha,
        approved_roots=approved,
        deprecated_roots=deprecated,
        deprecated_markers=markers,
        key_fn=_systemd_candidates,
    ))

    ok = len(violations) == 0
    return {
        "version": TOPO_VERSION,
        "authority": AUTHORITY,
        "expected_content_sha": expected_content_sha,
        "offline": False,
        "status": "PASS" if ok else "FAIL",
        "ok": ok,
        "reason": (
            "no deprecated-tree or non-current checkout found among live CIO "
            "workers, scheduled jobs, or systemd units."
            if ok
            else f"{len(violations)} CIO worker(s)/job(s) resolve to a deprecated tree or non-current SHA"
        ),
        "process_count": len(processes),
        "cron_count": len(cron),
        "systemd_count": len(systemd),
        "approved_roots": list(approved),
        "deprecated_roots": list(deprecated),
        "processes": processes,
        "cron": cron,
        "systemd": systemd,
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
