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
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

try:
    from scripts import check_pr_plain_english as plain
    from scripts.lib import merge_hold_paths as mhp
    from scripts.lib import pr_all_checks_green as pacg
    from scripts.lib import pr_merge_telegram as pmt
except ImportError:  # pragma: no cover — run from scripts/
    import check_pr_plain_english as plain  # type: ignore
    import merge_hold_paths as mhp  # type: ignore
    import pr_all_checks_green as pacg  # type: ignore
    from lib import pr_merge_telegram as pmt  # type: ignore

SCHEMA = "DeployInFlight@v1"
ROUTE = "/api/v2/ops/in-flight"
AUTHORITY = "READ_ONLY_ADVISORY"
SOURCE = "gh pr list (GitHub REST API via subprocess, read-only; cached 60s)"
DEFAULT_REPO = os.environ.get("TRADEAI_GITHUB_REPO", "PatsKiller/tardeai")
CACHE_TTL_S = 60.0
PR_LIMIT = 100
DEFAULT_TIMEOUT_S = 30.0
# The board's file views are fetched one PR at a time, and the browser aborts this endpoint after 30 s
# (useApi.ts). One aggregate deadline for the whole read keeps a stalled `gh pr view` from stacking up into a
# browser timeout: rows past the deadline stay files_unverified, so the list still renders.
FILE_VIEW_BUDGET_S = 12.0
MIN_FILE_VIEW_S = 1.0
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


def _bounded_file_views(fetch: Callable[..., dict[str, Any]], *,
                        budget_s: float = FILE_VIEW_BUDGET_S,
                        clock: Callable[[], float] = time.monotonic) -> Callable[[int], dict[str, Any]]:
    """Serve every PR's file view inside ONE aggregate deadline (codex review of 2307 at 78017a426).

    A per-call timeout alone is not a bound: five READY rows that each stall for the full timeout add up past
    the browser's 30 s abort, so a successful list becomes a blank board. Each call gets only what is left of
    the budget, and once it is spent the remaining rows raise and stay ``files_unverified`` — never approved.
    """

    deadline = clock() + float(budget_s)

    def _fetch(number: int) -> dict[str, Any]:
        remaining = deadline - clock()
        if remaining < MIN_FILE_VIEW_S:
            raise TimeoutError("file view budget exhausted")
        return fetch(number, timeout=min(remaining, DEFAULT_TIMEOUT_S))

    return _fetch


def pr_file_view(repo: str, number: int, *, timeout: Optional[float] = None) -> dict[str, Any]:
    """One PR's changed paths and changed-file count. Read-only; raises RuntimeError on any gh failure.

    The board cannot decide "may this be approved" without the file list: the digest's last gate before
    READY is the hold-rule match on changed paths (`merge_hold_paths.held_classes`) and the refusal to
    offer Approve on a partial view. Fetched per PR, and only for a row that would otherwise be READY, so
    the ordinary board read still costs one `gh pr list`.
    """
    rc, out = _gh(["pr", "view", str(int(number)), "--repo", repo, "--json", "files,changedFiles"],
                  timeout=int(timeout) if timeout is not None else int(DEFAULT_TIMEOUT_S))
    if rc != 0:
        raise RuntimeError(f"gh pr view failed: {out.strip()[:240]}")
    try:
        doc = json.loads(out) if out.strip() else {}
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"gh pr view returned non-JSON: {exc}") from exc
    return doc if isinstance(doc, dict) else {}


def _normalize_file_view(view: Any) -> Optional[tuple[list[str], int]]:
    """Validate a ``gh pr view --json files,changedFiles`` payload.

    Returns ``(paths, changedFiles)`` only when the envelope, the typed count and every path are usable.
    ``None`` means the view cannot prove anything, so the caller must keep the row ``files_unverified``.

    A successful-but-malformed response (``{}`` / ``null`` / ``[]``), a file object with no path, a
    non-string count and a count that disagrees with the paths all used to be read as ``files=[]`` /
    ``changedFiles=0`` and returned one step later as ``ready`` — a failed read wearing a verified empty
    scope (cx-openai-4 R4 at 8cd7fee69). Absence is not evidence that no path is held.
    """
    if not isinstance(view, dict):
        return None
    raw_files = view.get("files")
    changed = view.get("changedFiles")
    if not isinstance(raw_files, list):
        return None
    if isinstance(changed, bool) or not isinstance(changed, int) or changed < 0:
        return None
    paths: list[str] = []
    for item in raw_files:
        if not isinstance(item, dict):
            return None
        path = item.get("path")
        if not isinstance(path, str):
            return None
        path = path.strip()
        # ``str(f.get("path"))`` used to turn a missing path into the literal string "None" and let it pass.
        if not path or path.lower() == "none":
            return None
        paths.append(path)
    if changed != len(paths):
        return None
    return paths, changed


# ── pure projection (hermetic: fixture PR dicts only) ───────────────────────────────────────────────────────


def label_set(pr: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    for lab in pr.get("labels") or []:
        if isinstance(lab, dict):
            out.add(str(lab.get("name") or ""))
        else:
            out.add(str(lab))
    return out


#: The three states GitHub uses, as the GraphQL/API form spells them.
_MERGEABLE_TEXT = {"MERGEABLE": "MERGEABLE", "CONFLICTING": "CONFLICTING", "UNKNOWN": "UNKNOWN"}


def normalize_mergeable(v: Any) -> str:
    """``mergeable`` → MERGEABLE | CONFLICTING | UNKNOWN, from either form GitHub returns.

    ``gh pr list --json mergeable`` gives a JSON boolean or null; the GraphQL/API projection gives the
    enum strings. Only the boolean was handled, so a real ``"CONFLICTING"`` from the string form fell
    through to UNKNOWN and a genuinely conflicting PR lost its rebase hint, while ``"MERGEABLE"`` also
    read as unknown (2026-11-02, operator-requested Releases page fix). UNKNOWN stays UNKNOWN: it is
    GitHub saying "not computed yet", and it must never be read as either state.
    """
    if v is True:
        return "MERGEABLE"
    if v is False:
        return "CONFLICTING"
    if isinstance(v, str):
        return _MERGEABLE_TEXT.get(v.strip().upper(), "UNKNOWN")
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
    if mergeable == "UNKNOWN":
        # GitHub saying "not computed yet" is not evidence of a conflict. Treating it as one put
        # "auto-rebase" on a PR nobody had measured (2026-11-02). An unmeasured state is a coordinator
        # question, never an inference.
        return "coordinator"
    if merge_state in ("DIRTY", "BEHIND", "UNSTABLE"):
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


def _every_check_green(rollup: Iterable[dict[str, Any]] | None) -> dict[str, Any]:
    """The digest's own gate: the required four completed SUCCESS **and** no other check is red or pending."""
    return pacg.evaluate_merge_rollup(rollup, required=pmt.REQUIRED_CHECKS)


def _plain_ok(pr: dict[str, Any], answers: dict[str, str]) -> tuple[bool, list[str]]:
    errors = plain.check(str(pr.get("title") or ""), str(pr.get("body") or ""))
    if not errors and any(
        not answers.get(label)
        or (answers[label].startswith("<") and answers[label].endswith(">"))
        for label in plain.LABELS
    ):
        errors = ["plain-English answers are empty or still placeholders"]
    return (not errors), errors


def digest_classify_row(pr: dict[str, Any], *, files: Optional[list[str]] = None) -> tuple[str, str, bool]:
    """Digest-parity status for the board: (digest_status, digest_reason, can_approve).

    Aligns with ``pr_merge_digest.classify_pr``, including its LAST gate: a hold rule that covers one of
    the changed paths, and the refusal to offer Approve on a partial file view. ``files`` is the changed
    path list; when it is not supplied the row cannot be READY, because "every gate I could check passed"
    is not the digest's READY rule — it is a claim about a list nobody read (review finding F1 on PR 2307).
    """
    labels = label_set(pr)
    mergeable = normalize_mergeable(pr.get("mergeable"))
    answers = plain_english_fields(pr)
    # The digest's gate, not just its required four: `every_check_green` also refuses a failed or pending
    # check that is not one of the required names. `checks_green` (the display helper) cannot see those, so
    # using it here enabled Approve on a PR the digest would hold (codex-cloud F1 at 567486a98).
    every = _every_check_green(pr.get("statusCheckRollup"))
    green = bool(every.get("ok"))

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
    # Everything else passed; the digest's file gate is the only thing left between this row and READY.
    if files is None:
        return "files_unverified", "files_unverified", False
    # The view must be usable, not merely present: an empty list produced by a malformed payload is
    # indistinguishable from "no paths changed" and would turn a failed read into a verified empty scope
    # (cx-openai-4 R4 at 8cd7fee69). Every path must be a nonempty string.
    if not isinstance(files, (list, tuple)) or not all(
        isinstance(p, str) and p.strip() and p.strip().lower() != "none" for p in files
    ):
        return "files_unverified", "files_unverified", False
    clean = [p.strip() for p in files]
    changed_raw = pr.get("changedFiles")
    if changed_raw is None:
        if not clean:
            # An empty path list with no accompanying count is exactly the "successful but unusable view"
            # shape: there is nothing here that proves the PR changes no paths. Fail closed.
            return "files_unverified", "files_unverified", False
        changed = len(clean)
    elif isinstance(changed_raw, bool) or not isinstance(changed_raw, int) or changed_raw < 0:
        return "files_unverified", "files_unverified", False
    else:
        changed = changed_raw
    if changed != len(clean):
        # changed > len: a partial view (the digest's files_unverified). changed < len: an inconsistent
        # payload. Neither is a verified scope, so neither may offer Approve.
        return "files_unverified", "files_unverified", False
    try:
        held = mhp.held_classes(clean)
    except Exception:  # noqa: BLE001 - an unreadable hold config must not read as "no hold rule"
        return "files_unverified", "files_unverified", False
    if held:
        return "needs_operator", "held:" + ",".join(sorted(held)), False
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
        if str(digest_reason or "").startswith("held:"):
            return ("A hold rule covers a path this PR changes "
                    f"({str(digest_reason).split(':', 1)[1]}) — Approve stays off until the operator releases it.")
        return "Operator held — do not Approve until this hold is released."
    if digest_status == "waiting_ci":
        return "Waiting for the four required checks to pass (same gates as Telegram)."
    if digest_status == "blocked":
        return "Blocked on GitHub — needs a coordinator or shard/CI hints refresh."
    if digest_status == "files_unverified":
        return ("The changed-file list could not be checked here, so Approve stays off — that is the digest's "
                "own rule; open the PR to see why it is held.")
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


def project_pr(pr: dict[str, Any], *, now: Optional[datetime] = None,
               files_for: Optional[Callable[[int], dict[str, Any]]] = None) -> dict[str, Any]:
    """One raw gh PR dict → the wire row the board renders (legacy + operator-clarity fields).

    ``files_for`` reads one PR's changed paths. It is called at most once, and only for a row that has
    passed every other gate — the rest of the board never pays for a file view it cannot use.
    """
    now = now or datetime.now(timezone.utc)
    head = str(pr.get("headRefOid") or "")
    answers = plain_english_fields(pr)
    checks = check_statuses(pr)
    d_status, d_reason, can_approve = digest_classify_row(pr)
    if d_status == "files_unverified" and files_for is not None:
        number = int(pr.get("number") or 0)
        try:
            view = files_for(number)
        except Exception as exc:  # noqa: BLE001 - an unreadable file view is not a pass
            d_status, d_reason, can_approve = "files_unverified", f"files_unreadable:{type(exc).__name__}", False
        else:
            normalized = _normalize_file_view(view)
            if normalized is None:
                # A successful request whose body cannot prove the changed paths is not an empty scope.
                d_status, d_reason, can_approve = "files_unverified", "files_unverified", False
            else:
                files, changed = normalized
                merged = {**pr, "changedFiles": changed}
                d_status, d_reason, can_approve = digest_classify_row(merged, files=files)
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


def _state_root() -> Path:
    """Where persistent-state lives: ``$TRADEAI_STATE_ROOT``, else the house convention.

    This defaulted to ``Path(__file__).parents[3] / "trade-ai-releases" / "persistent-state"``, which exists in
    neither checkout layout (``…/portfolio-server/…`` in a release, ``…/trade-ai-v12-rebuild/…`` in the repo) and —
    because ``Path`` was never imported — raised NameError before it could look. Both faults together made every
    live read ``coordination_unavailable``: the served page showed no owner, task, review, CI or blockers for any
    PR (found on the served release 2026-11-03). Every other reader of the store (platform_health, jobs_health,
    n8n_coordination_projection) resolves it this way; follow them rather than inventing a path.
    """
    return Path(os.environ.get("TRADEAI_STATE_ROOT") or Path.home() / "trade-ai-releases" / "persistent-state")


def _default_coordination() -> Callable[..., dict[str, Any]]:
    from lib import releases_coordination  # noqa: E402

    root = _state_root()
    return lambda rows, now: releases_coordination.build(
        root / "data" / "coordination" / "coordinator" / "ledger.jsonl",
        root / "data" / "coordination" / "claims",
        rows,
        now=now,
    )


def build(db_query: Any = None, *, now: Optional[datetime] = None, repo: Optional[str] = None,
          lister: Optional[Callable[[str, int], list[dict[str, Any]]]] = None,
          coordination: Optional[Callable[..., dict[str, Any]]] = None,
          files_for: Optional[Callable[[int], dict[str, Any]]] = None) -> dict[str, Any]:
    """One read of the open PRs. ``lister`` is injected in tests (no network, no live gh).

    ``files_for`` defaults to one ``gh pr view --json files,changedFiles`` per PR that would otherwise be
    READY. It is read-only, and it is what makes ``can_approve`` mean the digest's READY rather than
    "everything I looked at passed" (review finding F1 on PR 2307).
    """
    now = now or datetime.now(timezone.utc)
    repo = repo or DEFAULT_REPO
    lister = lister or list_open_prs
    files_for = files_for or _bounded_file_views(
        lambda number, *, timeout: pr_file_view(repo, number, timeout=timeout))
    base = {"schema": SCHEMA, "authority": AUTHORITY, "generated_at": _iso(now), "repo": repo,
            "source": SOURCE}
    try:
        raw = lister(repo, PR_LIMIT)
    except Exception as exc:  # noqa: BLE001 - the error is the evidence
        return {**base, "prs": None, "count": None, "status": "UNAVAILABLE", "freshness": "UNAVAILABLE",
                "reason": f"{type(exc).__name__}: {str(exc)[:240]}"}
    rows = [project_pr(p, now=now, files_for=files_for) for p in raw]
    ready_n = sum(1 for r in rows if r.get("can_approve"))
    out = {**base, "prs": rows, "count": len(rows), "ready_count": ready_n, "status": "OK",
           "freshness": "OK", "reason": None}
    # 2026-11-02 (operator-requested Releases fix): an ADDITIVE coordination view. The PR list above is
    # unchanged - same keys, same values - and a failure to read the coordination sources degrades this
    # block alone rather than the board.
    try:
        view = (coordination or _default_coordination())(rows, now)
    except Exception as exc:  # noqa: BLE001 - the error is the evidence
        view = {"schema": "ReleasesCoordination@v1", "status": "UNAVAILABLE", "as_of": None,
                "captured_at": _iso(now), "source": "none", "gaps": [f"{type(exc).__name__}: {str(exc)[:160]}"],
                "agents": [], "work": {}, "authority": "READ_ONLY_ADVISORY"}
    out["coordination"] = {k: v for k, v in view.items() if k != "work"}
    by_number = view.get("work") or {}
    for row in rows:
        row["work"] = by_number.get(row["number"]) or {
            "owner": "UNKNOWN", "current_task": "UNKNOWN", "publication_state": "UNKNOWN",
            "local_head": None, "published_head": row.get("head_sha") or None,
            "review": {"state": "UNKNOWN", "head_sha": None, "as_of": None, "source": "none",
                       "gap": "coordination_unavailable"},
            "ci": {"state": "UNKNOWN", "head_sha": None, "as_of": None, "source": "none",
                   "gap": "coordination_unavailable"},
            "blockers": [], "next_action": "UNKNOWN", "as_of": None, "source": "none",
        }
    return out


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
           "pr_file_view", "project_pr", "why_held", "next_action", "normalize_mergeable", "label_set",
           "DEFAULT_REPO", "digest_classify_row", "next_plain", "relative_age", "REQUIRED_CHECKS",
           "check_statuses"]
