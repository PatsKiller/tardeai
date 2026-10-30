"""Deploy console P1 — the read-only "not live / in flight" open-PR board.

Backs ``GET /api/v2/ops/in-flight`` (mounted on System → Releases & schedules as the DeployInFlightBoard).
Design of record: ``docs/designs/DSN-20261029-deploy-console.md`` (P1). P1 is read-only: no label write, no
merge, no push, no promote, no schedule, no broker path. P2/P3 (buttons / push / force-promote) are separate PRs.

Each open (not-merged) PR to ``main`` is projected to one row: number, title, ``headRefOid`` short, mergeable
(MERGEABLE | CONFLICTING | UNKNOWN), ``mergeStateStatus``, and a short human ``why_held`` derived from labels
(held / broker / shared-infra / solo) and mergeability. The frontend renders a table with ⓘ hover tooltips
(no write path; the tooltip repeats title + head SHA + mergeable + why-held).

This view DOES call GitHub — it lists open PRs through ``gh pr list`` (the GitHub REST API via subprocess),
the same read-only path other read-only scripts use (``scripts/lib/pr_merge_digest.py``). That is why it is a
separate endpoint from ``releases-schedules``, whose request path never calls GitHub. It never writes, never
merges, never labels, never calls a broker. Cached 60 s; a gh failure is UNAVAILABLE with a reason, never an
empty list wearing "zero".

AUTHORITY: READ_ONLY_ADVISORY. MBI_BEHAVIOR = 0.
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Optional

SCHEMA = "DeployInFlight@v1"
ROUTE = "/api/v2/ops/in-flight"
AUTHORITY = "READ_ONLY_ADVISORY"
SOURCE = "gh pr list (GitHub REST API via subprocess, read-only; cached 60s)"
DEFAULT_REPO = os.environ.get("TRADEAI_GITHUB_REPO", "PatsKiller/tardeai")
CACHE_TTL_S = 60.0
PR_LIMIT = 100
DEFAULT_TIMEOUT_S = 30.0
PR_FIELDS = "number,title,url,headRefOid,headRefName,isDraft,labels,mergeable,mergeStateStatus"

# The label vocabulary the board reasons about (matches scripts/lib/pr_merge_digest.py / pr_merge_telegram.py).
HOLD_LABELS = frozenset({"held", "broker", "broker_active_trader"})
SHARED_INFRA_LABELS = frozenset({"shared-infra"})
SOLO_LABELS = frozenset({"solo"})
MERGE_LABEL = "operator-merge"

_CACHE: dict[str, tuple[float, dict]] = {}
_CACHE_LOCK = threading.Lock()


def _iso(dt: Optional[datetime] = None) -> str:
    return (dt or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()


# ── gh (read-only; stubbed in tests) ─────────────────────────────────────────────────────────────────────────


def _gh(args: list[str], *, timeout: int = DEFAULT_TIMEOUT_S) -> tuple[int, str]:
    proc = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=timeout, check=False)
    return proc.returncode, (proc.stdout or "") if proc.returncode == 0 else (proc.stderr or proc.stdout or "")


def list_open_prs(repo: str, limit: int = PR_LIMIT) -> list[dict[str, Any]]:
    """The open (not-merged) PRs to ``main``. Read-only; raises RuntimeError on any gh failure."""
    rc, out = _gh(["pr", "list", "--repo", repo, "--base", "main", "--state", "open",
                   "--limit", str(int(limit)), "--json", PR_FIELDS])
    if rc != 0:
        raise RuntimeError(f"gh pr list failed: {out.strip()[:240]}")
    try:
        rows = json.loads(out) if out.strip() else []
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"gh pr list returned non-JSON: {exc}") from exc
    return [r for r in rows if isinstance(r, dict)]


# ── pure projection (hermetic: fixture PR dicts only) ───────────────────────────────────────────────────────


def label_set(pr: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    for lab in pr.get("labels") or []:
        if isinstance(lab, dict):
            out.add(str(lab.get("name") or ""))
        else:
            out.add(str(lab))
    return out


def normalize_mergeable(v: Any) -> str:
    """``mergeable`` from gh is a JSON boolean or null → MERGEABLE | CONFLICTING | UNKNOWN."""
    if v is True:
        return "MERGEABLE"
    if v is False:
        return "CONFLICTING"
    return "UNKNOWN"


def why_held(pr: dict[str, Any]) -> Optional[str]:
    """A short human reason this PR is not auto-merging, from labels + mergeability. None = not held."""
    labels = label_set(pr)
    mergeable = normalize_mergeable(pr.get("mergeable"))
    merge_state = str(pr.get("mergeStateStatus") or "").upper()
    if pr.get("isDraft"):
        return "draft — needs the author to mark ready"
    if mergeable == "CONFLICTING":
        return "merge conflict — needs a coordinator"
    reasons: list[str] = []
    if labels & HOLD_LABELS:
        if "broker" in labels or "broker_active_trader" in labels:
            reasons.append("broker change — operator held")
        else:
            reasons.append("held — operator")
    if labels & SHARED_INFRA_LABELS:
        reasons.append("shared infra — coordinator merge only")
    if labels & SOLO_LABELS:
        reasons.append("solo — isolated change")
    if merge_state == "BLOCKED":
        reasons.append("merge blocked")
    if mergeable == "UNKNOWN":
        reasons.append("mergeability unknown")
    return "; ".join(dict.fromkeys(reasons)) or None


def next_action(pr: dict[str, Any]) -> str:
    """The board's "Next" column: one of auto-merge | coordinator | auto-rebase | blocked-shard-hints."""
    labels = label_set(pr)
    mergeable = normalize_mergeable(pr.get("mergeable"))
    merge_state = str(pr.get("mergeStateStatus") or "").upper()
    if pr.get("isDraft") or mergeable == "CONFLICTING" or labels & HOLD_LABELS:
        return "coordinator"
    if merge_state == "BLOCKED":
        return "blocked-shard-hints"
    if merge_state in ("DIRTY", "BEHIND", "UNSTABLE") or mergeable == "UNKNOWN":
        return "auto-rebase"
    if mergeable == "MERGEABLE":
        return "auto-merge"
    return "coordinator"


def project_pr(pr: dict[str, Any]) -> dict[str, Any]:
    """One raw gh PR dict → the wire row the board renders."""
    head = str(pr.get("headRefOid") or "")
    return {
        "number": int(pr.get("number") or 0),
        "title": str(pr.get("title") or ""),
        "url": str(pr.get("url") or ""),
        "head_sha": head,
        "head_sha_short": head[:9],
        "branch": str(pr.get("headRefName") or ""),
        "has_operator_merge": MERGE_LABEL in label_set(pr),
        "mergeable": normalize_mergeable(pr.get("mergeable")),
        "merge_state": str(pr.get("mergeStateStatus") or "").upper() or "UNKNOWN",
        "is_draft": bool(pr.get("isDraft")),
        "why_held": why_held(pr),
        "next": next_action(pr),
    }


# ── assembly and route ──────────────────────────────────────────────────────────────────────────────────────


def build(db_query: Any = None, *, now: Optional[datetime] = None, repo: Optional[str] = None,
          lister: Optional[Callable[[str, int], list[dict[str, Any]]]] = None) -> dict[str, Any]:
    """One read of the open PRs. ``lister`` is injected in tests (no network, no live gh)."""
    now = now or datetime.now(timezone.utc)
    repo = repo or DEFAULT_REPO
    lister = lister or list_open_prs
    base = {"schema": SCHEMA, "authority": AUTHORITY, "generated_at": _iso(now), "repo": repo,
            "source": SOURCE}
    try:
        raw = lister(repo, PR_LIMIT)
    except Exception as exc:  # noqa: BLE001 - the error is the evidence
        return {**base, "prs": None, "count": None, "status": "UNAVAILABLE", "freshness": "UNAVAILABLE",
                "reason": f"{type(exc).__name__}: {str(exc)[:240]}"}
    rows = [project_pr(p) for p in raw]
    return {**base, "prs": rows, "count": len(rows), "status": "OK", "freshness": "OK", "reason": None}


def handle(path: str, method: str, query: Optional[dict[str, Any]], db_query: Any) -> Optional[tuple[int, dict]]:
    """(status, body) for GET ROUTE; 405 for any other method on ROUTE; None for every other path."""
    base = path.split("?")[0].rstrip("/") or path
    if base != ROUTE:
        return None
    if (method or "GET").upper() != "GET":
        return 405, {"ok": False, "error": "read_only"}
    with _CACHE_LOCK:
        hit = _CACHE.get(base)
    if hit and time.monotonic() - hit[0] < CACHE_TTL_S:
        return 200, {"ok": True, "data": {**hit[1], "cache": "HIT"}}
    data = build(db_query)
    with _CACHE_LOCK:
        _CACHE[base] = (time.monotonic(), data)
    return 200, {"ok": True, "data": {**data, "cache": "MISS"}}


def clear_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()


__all__ = ["SCHEMA", "ROUTE", "AUTHORITY", "SOURCE", "build", "handle", "clear_cache", "list_open_prs",
           "project_pr", "why_held", "next_action", "normalize_mergeable", "label_set", "DEFAULT_REPO"]
