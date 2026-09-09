"""Poller / release identity checks — fail closed when cwd ≠ CURRENT.

Lane A (maturity-gap-closure-20260909). No Telegram, no DB, no broker.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

log = logging.getLogger("tradeai.poller_release_identity")

DEFAULT_CURRENT_LINK = Path.home() / "trade-ai-releases" / "portfolio-server" / "CURRENT"


def resolve_current_release(link: Path | None = None) -> Path | None:
    target = Path(link or os.environ.get("TRADEAI_PORTFOLIO_CURRENT_LINK") or DEFAULT_CURRENT_LINK)
    try:
        if not target.exists():
            return None
        return target.resolve()
    except OSError:
        return None


def read_source_commit(release_dir: Path | None) -> str:
    if release_dir is None:
        return ""
    for name in ("SOURCE_COMMIT", "BUILD_SHA", "COMMIT"):
        p = release_dir / name
        try:
            if p.is_file():
                return p.read_text(encoding="utf-8").strip().splitlines()[0].strip()
        except OSError:
            continue
    # basename often encodes short sha: 845ce5d88-main-exact-...
    base = release_dir.name
    return base.split("-", 1)[0] if base else ""


def process_cwd() -> Path | None:
    try:
        return Path("/proc/self/cwd").resolve()
    except OSError:
        try:
            return Path.cwd().resolve()
        except OSError:
            return None


def identity_report(*, current_link: Path | None = None) -> dict[str, Any]:
    current = resolve_current_release(current_link)
    cwd = process_cwd()
    current_sha = read_source_commit(current)
    cwd_sha = read_source_commit(cwd) if cwd else ""
    match = bool(current and cwd and current == cwd)
    return {
        "current_release": str(current) if current else None,
        "current_basename": current.name if current else None,
        "current_source_commit": current_sha or None,
        "process_cwd": str(cwd) if cwd else None,
        "process_cwd_basename": cwd.name if cwd else None,
        "process_source_commit": cwd_sha or None,
        "matches_current": match,
        "mismatch_reason": None
        if match
        else (
            "current_link_missing"
            if current is None
            else ("cwd_unreadable" if cwd is None else "cwd_ne_current")
        ),
    }


def assert_running_from_current(
    *, current_link: Path | None = None, exit_on_mismatch: bool = True
) -> dict[str, Any]:
    """Compare process cwd to CURRENT. On mismatch: log and optionally SystemExit(0).

    Exit 0 (clean) so cron/flock wrappers relaunch from CURRENT without treating
    the self-exit as a crash loop.
    """
    report = identity_report(current_link=current_link)
    if report["matches_current"]:
        log.info(
            "poller_identity_ok current=%s sha=%s",
            report["current_basename"],
            (report["current_source_commit"] or "")[:12],
        )
        return report
    log.error(
        "poller_identity_mismatch reason=%s cwd=%s current=%s — self-exiting for relaunch",
        report["mismatch_reason"],
        report["process_cwd_basename"],
        report["current_basename"],
    )
    log.error("poller_identity_report %s", json.dumps(report, sort_keys=True))
    if exit_on_mismatch:
        raise SystemExit(0)
    return report
