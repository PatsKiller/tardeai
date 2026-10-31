"""Deploy console in-flight board — open PRs to main with operator-clarity fields.

Backs ``GET /api/v2/ops/in-flight`` (System → Releases & schedules → DeployInFlightBoard).
Design: ``docs/designs/DSN-20261029-deploy-console.md`` (P1 + Operator clarity).

Read-only: lists open PRs via ``gh pr list`` (no label/merge/push/promote). Cached 60 s;
a gh failure is UNAVAILABLE with a reason, never an empty list wearing "zero".

Operator-clarity fields (additive on DeployInFlight@v1) reuse the Telegram digest READY
classifier helpers: plain-English answers, the four required checks, digest_status /
digest_reason, relative ages, and next_plain. Approve in the UI should match digest READY.

AUTHORITY: READ_ONLY_ADVISORY. MBI_BEHAVIOR = 0.
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Optional

try:
    from scripts import check_pr_plain_english as plain
    from scripts.lib import pr_merge_telegram as pmt
except ImportError:  # pragma: no cover — run from scripts/
    import check_pr_plain_english as plain  # type: ignore
    from lib import pr_merge_telegram as pmt  # type: ignore

SCHEMA = "DeployInFlight@v1"
ROUTE = "/api/v2/ops/in-flight"
AUTHORITY = "READ_ONLY_ADVISORY"
SOURCE = "gh pr list (GitHub REST API via subprocess, read-only; cached 60s)"
DEFAULT_REPO = os.environ.get("TRADEAI_GITHUB_REPO", "PatsKiller/tardeai")
CACHE_TTL_S = 60.0
PR_LIMIT = 100
DEFAULT_TIMEOUT_S = 30.0
# body / rollup / timestamps for operator clarity (digest parity); merge fields for the board.
PR_FIELDS = (
    "number,title,url,headRefOid,headRefName,isDraft,labels,mergeable,mergeStateStatus,"
    "body,createdAt,updatedAt,statusCheckRollup,author"
)

HOLD_LABELS = frozenset({"held", "broker", "broker_active_trader"})
SHARED_INFRA_LABELS = frozenset({"shared-infra"})
SOLO_LABELS = frozenset({"solo"})
MERGE_LABEL = "operator-merge"
REQUIRED_CHECKS = pmt.REQUIRED_CHECKS

_CACHE: dict[str, tuple[float, dict]] = {}
_CACHE_LOCK = threading.Lock()


def _iso(dt: Optional[datetime] = None) -> str:
    return (dt or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()


def _parse_iso(value: Any) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def relative_age(iso_ts: Any, *, now: Optional[datetime] = None) -> Optional[str]:
    """Human age like '12m ago' / '3h ago' from an ISO timestamp. None if unparseable."""
    dt = _parse_iso(iso_ts)
    if dt is None:
        return None
    now = now or datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    secs = max(0, int((now - dt.astimezone(timezone.utc)).total_seconds()))
    if secs < 90:
        return f"{secs}s ago"
    if secs < 5400:
        return f"{secs // 60}m ago"
    if secs < 172_800:
        return f"{secs // 3600}h ago"
    return f"{secs // 86_400}d ago"


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


def plain_english_fields(pr: dict[str, Any]) -> dict[str, str]:
    """The six operator answers from the PR body (empty dict when the block is missing)."""
    return plain.fields(str(pr.get("body") or ""))


def checks_green(rollup: Iterable[dict[str, Any]] | None) -> tuple[bool, dict[str, str]]:
    """Same rule as ``pr_merge_digest.checks_green``: every required check present and SUCCESS."""
    seen: dict[str, set[str]] = {}
    for row in rollup or []:
        name = str(row.get("name") or row.get("context") or "")
        if name not in REQUIRED_CHECKS:
            continue
        concl = str(row.get("conclusion") or row.get("state") or row.get("status") or "").upper()
        seen.setdefault(name, set()).add(concl or "PENDING")
    statuses = {
        c: ("SUCCESS" if seen.get(c) == {"SUCCESS"} else ",".join(sorted(seen.get(c) or {"MISSING"})))
        for c in REQUIRED_CHECKS
    }
    return all(v == "SUCCESS" for v in statuses.values()), statuses


def check_statuses(pr: dict[str, Any]) -> dict[str, str]:
    """Map of the four required check names → SUCCESS / MISSING / other conclusions."""
    _green, statuses = checks_green(pr.get("statusCheckRollup"))
    return statuses


def _plain_ok(pr: dict[str, Any], answers: dict[str, str]) -> tuple[bool, list[str]]:
    errors = plain.check(str(pr.get("title") or ""), str(pr.get("body") or ""))
    if not errors and any(
        not answers.get(label)
        or (answers[label].startswith("<") and answers[label].endswith(">"))
        for label in plain.LABELS
    ):
        errors = ["plain-English answers are empty or still placeholders"]
    return (not errors), errors


def digest_classify_row(pr: dict[str, Any]) -> tuple[str, str, bool]:
    """Digest-parity status for the board: (digest_status, digest_reason, can_approve).

    Aligns with ``pr_merge_digest.classify_pr`` for the gates that do not need a full file list
    (draft, already approved, plain English, hold labels, four checks, conflict). Path-based
    held-class (files_unverified) is not recomputed here — labels cover the operator hold path.
    """
    labels = label_set(pr)
    mergeable = normalize_mergeable(pr.get("mergeable"))
    answers = plain_english_fields(pr)
    green, _statuses = checks_green(pr.get("statusCheckRollup"))

    if pr.get("isDraft"):
        return "draft", "draft", False
    if MERGE_LABEL in labels:
        return "approved", "already_approved", False
    if mergeable == "CONFLICTING":
        return "conflict", "merge_conflict", False
    ok_plain, _errs = _plain_ok(pr, answers)
    if not ok_plain:
        return "not_described", "plain_english_required", False
    if labels & HOLD_LABELS:
        return "needs_operator", "held", False
    if not green:
        return "waiting_ci", "checks_not_green", False
    merge_state = str(pr.get("mergeStateStatus") or "").upper()
    if merge_state == "BLOCKED":
        return "blocked", "merge_blocked", False
    return "ready", "ready", True


def next_plain(pr: dict[str, Any], *, digest_status: str, digest_reason: str) -> str:
    """One operator-facing sentence for the Status / Next column."""
    mergeable = normalize_mergeable(pr.get("mergeable"))
    merge_state = str(pr.get("mergeStateStatus") or "").upper()
    if digest_status == "draft":
        return "Author must mark this ready for review first."
    if digest_status == "approved":
        return "You already Approved — waiting for Mergify to merge into main (not on the site yet)."
    if digest_status == "conflict":
        return "Needs a coordinator — merge conflict."
    if digest_status == "not_described":
        return "Waiting for a plain-English description before you can Approve."
    if digest_status == "needs_operator":
        return "Operator held — do not Approve until this hold is released."
    if digest_status == "waiting_ci":
        return "Waiting for the four required checks to pass (same gates as Telegram)."
    if digest_status == "blocked":
        return "Blocked on GitHub — needs a coordinator or shard/CI hints refresh."
    if mergeable == "UNKNOWN":
        return (
            "GitHub has not finished computing mergeability yet — wait / refresh; "
            "this is not the same as a conflict."
        )
    if merge_state in ("DIRTY", "BEHIND", "UNSTABLE"):
        return "Branch is behind main — automation should update it (auto-rebase)."
    if digest_status == "ready":
        return "Safe to Approve — same READY rules as the Telegram digest."
    return digest_reason or "Waiting — see gates."


def project_pr(pr: dict[str, Any], *, now: Optional[datetime] = None) -> dict[str, Any]:
    """One raw gh PR dict → the wire row the board renders (legacy + operator-clarity fields)."""
    now = now or datetime.now(timezone.utc)
    head = str(pr.get("headRefOid") or "")
    answers = plain_english_fields(pr)
    checks = check_statuses(pr)
    d_status, d_reason, can_approve = digest_classify_row(pr)
    author = pr.get("author") or {}
    author_login = ""
    if isinstance(author, dict):
        author_login = str(author.get("login") or "")
    elif author:
        author_login = str(author)
    created = pr.get("createdAt")
    updated = pr.get("updatedAt")
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
        # Operator clarity (additive)
        "plain_english": answers or None,
        "plain_english_missing": not bool(answers) or not _plain_ok(pr, answers)[0],
        "checks": checks,
        "digest_status": d_status,
        "digest_reason": d_reason,
        "can_approve": can_approve,
        "created_at": str(created) if created else None,
        "updated_at": str(updated) if updated else None,
        "created_age": relative_age(created, now=now),
        "updated_age": relative_age(updated, now=now),
        "next_plain": next_plain(pr, digest_status=d_status, digest_reason=d_reason),
        "author": author_login or None,
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
    rows = [project_pr(p, now=now) for p in raw]
    ready_n = sum(1 for r in rows if r.get("can_approve"))
    return {
        **base,
        "prs": rows,
        "count": len(rows),
        "ready_count": ready_n,
        "status": "OK",
        "freshness": "OK",
        "reason": None,
    }


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
           "project_pr", "why_held", "next_action", "normalize_mergeable", "label_set", "DEFAULT_REPO",
           "digest_classify_row", "next_plain", "relative_age", "REQUIRED_CHECKS", "check_statuses"]
